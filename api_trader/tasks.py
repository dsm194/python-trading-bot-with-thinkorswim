
# imports
import asyncio
import threading
import time
from dotenv import load_dotenv
from pathlib import Path
import os

from api_trader.order_builder import OrderBuilderWrapper
from assets.exception_handler import exception_handler
from assets.helper_functions import getUTCDatetime, selectSleep, modifiedAccountID
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")


class Tasks:

    # THE TASKS CLASS IS USED FOR HANDLING ADDITIONAL TASKS OUTSIDE OF THE LIVE TRADER.
    # YOU CAN ADD METHODS THAT STORE PROFIT LOSS DATA TO MONGO, SELL OUT POSITIONS AT END OF DAY, ETC.
    # YOU CAN CREATE WHATEVER TASKS YOU WANT FOR THE BOT.
    # YOU CAN USE THE DISCORD CHANNEL NAMED TASKS IF YOU ANY HELP.

    def __init__(self, quote_manager, position_updater):

        self.quote_manager = quote_manager
        self.position_updater = position_updater

        self.tasks_running = False
        self.positions_by_symbol = {}  # Class-level positions dictionary
        self.strategy_dict = {}  # Class-level strategy dictionary
        self.lock = threading.Lock()  # Lock for synchronizing access
        self._cached_market_hours = {}
        self._cached_market_hours_timestamp = 0

        super().__init__()

    async def run_tasks_with_exit_check(self):
        self.logger.info(
            f"STARTING TASKS FOR {self.user['Name']} ({modifiedAccountID(self.account_id)})", extra={'log': False})

        while not self.quote_manager.stop_event.is_set():
            await self.runTasks()

    
    @exception_handler
    async def checkOCOpapertriggers(self):
        # Are we during market hours?
        dtNow = getUTCDatetime()

        # Caching market hours for a certain period
        if not hasattr(self, '_cached_market_hours') or time.time() - self._cached_market_hours_timestamp > 300:  # Cache for 5 mins
            self._cached_market_hours = self.tdameritrade.getMarketHours(date=dtNow)
            self._cached_market_hours_timestamp = time.time()

        await self.quote_manager.add_callback(self.evaluate_paper_triggers)

        # Fetch all open positions for the trader and the paper account in one query
        open_positions = list(self.open_positions.find({
            "Trader": self.user["Name"], 
            "Account_ID": self.account_id, 
            "Account_Position": "Paper", 
            # "Strategy": {"$in": ["ATRTRAILINGSTOP_ATRFACTOR1_75_OPTIONS_DEBUG", "ATRHIGHSMABREAKOUTSFILTER_OPTIONS_DEBUG", "ATRHIGHSMABREAKOUTSFILTER_DEBUG", "MACD_XVER_8_17_9_EXP_DEBUG"]}
        }))

        # Fetch strategies from MongoDB and add any new strategies to the class-level dictionary
        strategies = self.strategies.find({"Account_ID": self.account_id})

        # Group positions by symbol to minimize the number of API calls
        with self.lock:  # Lock during modification
            # Create a mapping for new symbols with asset types
            new_symbols = []
            for position in open_positions:
                symbol = position["Symbol"] if position["Asset_Type"] == "EQUITY" else position["Pre_Symbol"]
                # Check if the symbol is not already subscribed
                if symbol not in self.positions_by_symbol:
                    self.positions_by_symbol[symbol] = []
                    new_symbols.append({"symbol": symbol, "asset_type": position["Asset_Type"]})
                # Ensure the position isn't already in the list
                if position not in self.positions_by_symbol[symbol]:
                    self.positions_by_symbol[symbol].append(position)

            # Optionally deduplicate new_symbols if necessary
            seen = set()
            new_symbols = [ns for ns in new_symbols if (ns["symbol"] not in seen and not seen.add(ns["symbol"]))]

            for strategy in strategies:
                strategy_name = strategy["Strategy"]
                if strategy_name not in self.strategy_dict:
                    strategy_object = OrderBuilderWrapper().load_strategy(strategy)
                    self.strategy_dict[strategy_name] = strategy
                    self.strategy_dict[strategy_name]["ExitStrategy"] = strategy_object

        # Pass the symbols to the QuoteManager
        if new_symbols:
            await self.quote_manager.add_quotes(new_symbols)

    @exception_handler
    async def evaluate_paper_triggers(self, symbol, quote_data):
            # Callback function invoked when quotes are updated
            # print(f"Evaluating paper triggers for {symbol}: {quote_data}")

            with self.lock:  # Lock during modification
                local_positions_by_symbol = self.positions_by_symbol.get(symbol, [])

            for position in local_positions_by_symbol:
                strategy_name = position["Strategy"]
                strategy_data = self.strategy_dict.get(strategy_name)

                if not strategy_data or "ExitStrategy" not in strategy_data:
                    self.logger.warning(f"Exit strategy not found for position: {position['_id']}")
                    continue

                exit_strategy = strategy_data["ExitStrategy"]

                # Check market hours from cached data
                marketHours = self._cached_market_hours or {}
                isMarketOpen = marketHours.get('isOpen', False)

                last_price = quote_data["last_price"] if isMarketOpen or position["Asset_Type"] == "OPTION" else quote_data["regular_market_last_price"]
                max_price = position.get("max_price", position["Entry_Price"])

                # Prepare additional params if needed
                additional_params = {
                    "entry_price": position["Entry_Price"],
                    "quantity": position["Qty"],
                    "last_price": last_price,
                    "max_price": max_price,
                }

                # Call the should_exit method to check for exit conditions
                exit_result = exit_strategy.should_exit(additional_params)
                should_exit = exit_result['exit']
                updated_max_price = exit_result["additional_params"]["max_price"]

                # Update max_price in MongoDB only if updated_max_price is greater than the existing max_price or if max_price is None
                current_max_price = position.get("max_price")

                if current_max_price is None or updated_max_price > current_max_price:
                    await self.position_updater.queue_max_price_update(position["_id"], updated_max_price)
                    self.logger.info(f"Updated max_price for {symbol} to {updated_max_price}")

                if should_exit:
                    # The exit conditions are met, so we need to close the position
                    position["Side"] = "SELL" if position["Position_Type"] == "LONG" and position["Qty"] > 0 else "BUY"
                    strategy_data["Order_Type"] = "STANDARD"
                    self.sendOrder(position, strategy_data, "CLOSE POSITION")

    def stop(self):
        self.quote_manager.stop_event.set()  # Signal the loop to stop
        self.position_updater.stop()
        self.thread.join()  # Wait for the thread to finish

    @exception_handler
    def checkOCOtriggers(self):
        """Checks OCO triggers (stop loss/ take profit) to see if either one has filled. 
        If so, closes the position in MongoDB accordingly.
        """

        open_positions = self.open_positions.find({
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Order_Type": "OCO"
        })

        bulk_updates = []
        rejected_inserts = []
        canceled_inserts = []

        for position in open_positions:
            # Handle the different formats of childOrderStrategies (list or dict)
            child_orders = position.get("childOrderStrategies")
            if not child_orders:
                self.logger.warning(f"No childOrderStrategies found for position {position['Symbol']}")
                continue
            
            # Convert to list if it's in a dict format
            if isinstance(child_orders, dict):
                child_orders = [child_orders]  # Convert to list for uniform processing

            # Process child orders whether they are single or OCO type
            for child_order in child_orders:
                # Check if childOrderStrategies contains nested orders (OCO format)
                if "childOrderStrategies" in child_order:
                    # Recursively process the OCO child orders
                    for nested_order in child_order["childOrderStrategies"]:
                        self.process_child_order(nested_order, position, bulk_updates, rejected_inserts, canceled_inserts)
                else:
                    # Process regular child order
                    self.process_child_order(child_order, position, bulk_updates, rejected_inserts, canceled_inserts)

        # Execute bulk updates and inserts
        self.apply_bulk_updates(bulk_updates, rejected_inserts, canceled_inserts)

    def process_child_order(self, child_order, position, bulk_updates, rejected_inserts, canceled_inserts):
        """Processes individual child orders and updates status."""
        order_id = child_order.get("Order_ID")
        if not order_id:
            self.logger.warning(f"Order ID missing in childOrder: {child_order}")
            return

        # Query the order status using the order_id
        spec_order = self.tdameritrade.getSpecificOrder(order_id)
        new_status = spec_order.get("status")

        if not new_status:
            if order_id > 0:
                self.logger.warning(f"No status found for order_id: {order_id}")
            return

        # If the order is filled, process the position and stop further checks
        if new_status == "FILLED":
            position["Direction"] = "CLOSE POSITION"
            position["Side"] = child_order.get("Side", "SELL")

            self.pushOrder(position, spec_order)
            self.logger.info(f"Order {order_id} for {position['Symbol']} filled")
            return

        # Handle rejected or canceled orders
        elif new_status in ["CANCELED", "REJECTED"]:
            other = {
                "Symbol": position["Symbol"],
                "Order_Type": position["Order_Type"],
                "Order_Status": new_status,
                "Strategy": position["Strategy"],
                "Trader": self.user["Name"],
                "Date": getUTCDatetime(),
                "Account_ID": self.account_id
            }

            if new_status == "REJECTED":
                rejected_inserts.append(other)
            else:
                canceled_inserts.append(other)

            self.logger.info(
                f"{new_status.upper()} ORDER for {position['Symbol']} - "
                f"TRADER: {self.user['Name']} - ACCOUNT ID: {modifiedAccountID(self.account_id)}"
            )
        else:
            # Use array filters to update the specific child order's status based on Order_ID
            updates = {
                "$set": {
                    "childOrderStrategies.$[orderElem].Order_Status": new_status
                }
            }

            # Use array filters to match the element with the correct Order_ID
            array_filters = [{"orderElem.Order_ID": order_id}]
            
            bulk_updates.append(
                UpdateOne(
                    {
                        "Trader": self.user["Name"],
                        "Account_ID": self.account_id,
                        "Symbol": position["Symbol"],
                        "Strategy": position["Strategy"]
                    },
                    updates,
                    upsert=False,
                    array_filters=array_filters
                )
            )

    def apply_bulk_updates(self, bulk_updates, rejected_inserts, canceled_inserts):
        """Applies bulk updates and inserts to MongoDB."""
        if bulk_updates:
            try:
                self.open_positions.bulk_write(bulk_updates)
            except BulkWriteError as e:
                self.logger.error(f"Bulk write error: {e.details}")

        if rejected_inserts:
            self.rejected.insert_many(rejected_inserts)
        if canceled_inserts:
            self.canceled.insert_many(canceled_inserts)



    @exception_handler
    def extractOCOchildren(self, spec_order):
        """This method extracts OCO children order ids and sends them to be stored in MongoDB open positions.
        Data will be used by checkOCOtriggers with order ids to see if stop loss or take profit has been triggered.
        """

        # Initialize an empty list to store the child orders
        oco_children = []

        # Retrieve the outer childOrderStrategies array, or an empty list if not present
        outer_child_order_strategies = spec_order.get("childOrderStrategies", [{}])

        # Check if there's a nested childOrderStrategies array in the first object
        nested_child_order_strategies = outer_child_order_strategies[0].get("childOrderStrategies", outer_child_order_strategies)

        # Iterate over the nested_child_order_strategies (either the nested array or the outer array itself)
        for child in nested_child_order_strategies:
            # Safely retrieve keys, default to None if missing
            exit_price = child.get("stopPrice", child.get("activationPrice", child.get("price")))
            exit_type = "STOP LOSS" if "stopPrice" in child else "TAKE PROFIT"

            order_id = child.get("Order_ID")

            # Check if Order_ID is present and numeric
            if order_id is None:
                self.logger.error(f"Missing Order_ID detected: {str(child)}")
            else:
                try:
                    order_id = int(order_id)  # Try to convert to integer
                except (ValueError, TypeError):
                    self.logger.error(f"Invalid or non-numeric Order_ID detected: {str(child)}")
                    order_id = None

            # Build the child order dictionary
            child_order = {
                "Side": child.get("orderLegCollection", [{}])[0].get("instruction"),
                "Exit_Price": exit_price,
                "Exit_Type": exit_type if exit_price is not None else None,
                "Order_Status": child.get("status"),
                "Order_ID": order_id
            }

            # Add the child order to the list
            oco_children.append(child_order)

        # Return the list of child orders within the expected structure
        return {"childOrderStrategies": oco_children}


    @exception_handler
    def addNewStrategy(self, strategy, asset_type):
        """ METHOD UPDATES STRATEGIES OBJECT IN MONGODB WITH NEW STRATEGIES.

        Args:
            strategy ([str]): STRATEGY NAME
        """

        obj = {"Active": False,
               "Order_Type": "STANDARD",
               "Asset_Type": asset_type,
               "Position_Size": 500,
               "Position_Type": "LONG",
               "Account_ID": self.account_id,
               "Strategy": strategy,
               "MaxPositionSize": 5000
               }

        # IF STRATEGY NOT IN STRATEGIES COLLECTION IN MONGO, THEN ADD IT

        self.strategies.update_one(
            {"Account_ID": self.account_id, "Strategy": strategy, "Asset_Type": asset_type},
            {"$setOnInsert": obj},
            upsert=True
        )

    async def runTasks(self):
        """ METHOD RUNS TASKS ON WHILE LOOP EVERY 5 - 60 SECONDS DEPENDING.
        """

        # RUN TASKS ####################################################
                
        # Run synchronous method in a separate thread
        await asyncio.to_thread(self.checkOCOtriggers)

        await self.checkOCOpapertriggers()

        ##############################################################
        
        await asyncio.sleep(selectSleep())  # Allows other tasks to run while waiting.
