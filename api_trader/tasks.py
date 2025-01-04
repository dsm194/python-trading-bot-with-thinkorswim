
# imports
import asyncio
import time
from dotenv import load_dotenv
from pathlib import Path
import os
import httpx

from assets.exception_handler import exception_handler
from assets.helper_functions import getUTCDatetime, selectSleep, modifiedAccountID
from pymongo import UpdateOne

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
        self.lock = asyncio.Lock()
        self._cached_market_hours = {}
        self._cached_market_hours_timestamp = 0

        self.task_queue = asyncio.Queue()
        self.task_status = {
            'checkOCOtriggers': False,
            'checkOCOpapertriggers': False
        }

        super().__init__()

    async def run_tasks_with_exit_check(self):
        self.logger.info(
            f"STARTING TASKS FOR {self.user['Name']} ({modifiedAccountID(self.account_id)})", extra={'log': False})

        while not self.quote_manager.stop_event.is_set():
            task = await self.task_queue.get()  # Get a task from the queue
            await self.process_task(task)  # Process the task asynchronously
            self.task_queue.task_done()  # Mark the task as done

    async def process_task(self, task):
        """ Process the task in an async manner, simulating the original loop iteration. """
        print(f"Processing task: {task} ({modifiedAccountID(self.account_id)})")

        try:
            # Task-specific processing
            if task == 'checkOCOtriggers':
                await self.checkOCOtriggers()
            elif task == 'checkOCOpapertriggers':
                # Run blocking call in a separate thread
                await self.checkOCOpapertriggers()
        finally:
            # Mark task as complete
            self.task_status[task] = False

    async def trader_thread_function(self):
        """ Each trader will submit tasks to the queue for processing by the main event loop. """
        while not self.quote_manager.stop_event.is_set():
            # Submit tasks only if they aren't already in progress
            for task_name in ['checkOCOtriggers', 'checkOCOpapertriggers']:
                if not self.task_status.get(task_name, False):  # Only submit if not running
                    self.task_status[task_name] = True
                    await self.task_queue.put(task_name)
                    
            await asyncio.sleep(selectSleep())
    
    @exception_handler
    async def checkOCOpapertriggers(self):

        dtNow = getUTCDatetime()

        # Protect cached market hours access
        async with self.lock:
            if not hasattr(self, '_cached_market_hours') or time.time() - self._cached_market_hours_timestamp > 300:
                self._cached_market_hours = await self.tdameritrade.getMarketHoursAsync(date=dtNow)
                self._cached_market_hours_timestamp = time.time()

        await self.quote_manager.add_callback(self.evaluate_paper_triggers)

        # Fetch all open positions for the trader and the paper account in one query
        open_positions = await self.async_mongo.open_positions.find({
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Account_Position": "Paper",
            # "Strategy": {
            #     "$in": [
            #         "ATRTRAILINGSTOP_ATRFACTOR1_75_OPTIONS_DEBUG",
            #         "ATRHIGHSMABREAKOUTSFILTER_OPTIONS_DEBUG",
            #         "ATRHIGHSMABREAKOUTSFILTER_DEBUG",
            #         "MACD_XVER_8_17_9_EXP_DEBUG"
            #     ]
            # }
        }).to_list(None)  # Convert cursor to a list

        # Fetch strategies from MongoDB and add any new strategies to the class-level dictionary
        strategies = await self.async_mongo.strategies.find({"Account_ID": self.account_id}).to_list(None)

        # Group positions by symbol and minimize API calls
        async with self.lock:
            new_symbols = []
            for position in open_positions:
                symbol = position["Symbol"] if position["Asset_Type"] == "EQUITY" else position["Pre_Symbol"]
                if symbol not in self.positions_by_symbol:
                    self.positions_by_symbol[symbol] = []
                    new_symbols.append({"symbol": symbol, "asset_type": position["Asset_Type"]})
                if position not in self.positions_by_symbol[symbol]:
                    self.positions_by_symbol[symbol].append(position)

            # Deduplicate new symbols
            seen = set()
            new_symbols = [ns for ns in new_symbols if (ns["symbol"] not in seen and not seen.add(ns["symbol"]))]

            for strategy in strategies:
                strategy_name = strategy["Strategy"]
                if strategy_name not in self.strategy_dict:
                    strategy_object = self.load_strategy(strategy)
                    self.strategy_dict[strategy_name] = strategy
                    self.strategy_dict[strategy_name]["ExitStrategy"] = strategy_object

        # Pass symbols to the QuoteManager
        if new_symbols:
            try:
                await self.quote_manager.add_quotes(new_symbols)
            except httpx.ReadTimeout as e:
                self.logger.error(f"ReadTimeout occurred while adding quotes: {e}")
            except httpx.ConnectTimeout as e:
                self.logger.error(f"ConnectTimeout occurred while adding quotes: {e}")
            except Exception as e:
                self.logger.error(f"An unexpected error occurred in add_quotes: {e}")

    async def evaluate_paper_triggers(self, symbol, quote_data):
            # Callback function invoked when quotes are updated
            # print(f"Evaluating paper triggers for {symbol}: {quote_data}")

            async with self.lock:  # Lock during modification
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
                max_price = position.get("Max_Price", position["Entry_Price"])

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
                current_max_price = position.get("Max_Price")

                if current_max_price is None or updated_max_price > current_max_price:
                    await self.position_updater.queue_max_price_update(position["_id"], updated_max_price)
                    self.logger.info(f"Updated max_price for {symbol} to {updated_max_price}")
                    position["Max_Price"] = updated_max_price

                if should_exit:
                    # The exit conditions are met, so we need to close the position
                    position["Side"] = "SELL" if position["Position_Type"] == "LONG" and position["Qty"] > 0 else "BUY"
                    strategy_data["Order_Type"] = "STANDARD"
                    await self.sendOrder(position, strategy_data, "CLOSE POSITION")

    def stop(self):
        self.quote_manager.stop_event.set()  # Signal the loop to stop
        self.position_updater.stop()
        self.thread.join()  # Wait for the thread to finish

    @exception_handler
    async def checkOCOtriggers(self):
        """Checks OCO triggers (stop loss/ take profit) to see if either one has filled. 
        If so, closes the position in MongoDB accordingly.
        """
        bulk_updates = []
        rejected_inserts = []
        canceled_inserts = []

        open_positions = await self.async_mongo.open_positions.find({
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Order_Type": "OCO"
        }).to_list(None)  # Convert cursor to a list

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
                        await self._process_child_order(nested_order, position, bulk_updates, rejected_inserts, canceled_inserts)
                else:
                    # Process regular child order
                    await self._process_child_order(child_order, position, bulk_updates, rejected_inserts, canceled_inserts)

        # Execute bulk updates and inserts asynchronously
        await self._apply_bulk_updates(bulk_updates, rejected_inserts, canceled_inserts)

    async def _process_child_order(self, child_order, position, bulk_updates, rejected_inserts, canceled_inserts):
        """Processes individual child orders and updates status."""
        order_id = child_order.get("Order_ID")
        if not order_id:
            self.logger.warning(f"Order ID missing in childOrder: {child_order}")
            return

        # Query the order status using the order_id
        spec_order = await self.tdameritrade.getSpecificOrderAsync(order_id)
        new_status = spec_order.get("status")

        if not new_status:
            if order_id > 0:
                self.logger.warning(f"No status found for order_id: {order_id}")
            return

        # Handle FILLED status
        if new_status == "FILLED":
            position["Direction"] = "CLOSE POSITION"
            position["Side"] = child_order.get("Side", "SELL")

            await self.pushOrder(position, spec_order)
            self.logger.info(f"Order {order_id} for {position['Symbol']} filled")
            return

        # Handle REJECTED or CANCELED status
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
            filter_query = {
                "Trader": self.user["Name"],
                "Account_ID": self.account_id,
                "Symbol": position["Symbol"],
                "Strategy": position["Strategy"]
            }

            update_query = {
                "$set": {
                    "childOrderStrategies.$[orderElem].Order_Status": new_status
                }
            }

            array_filters = [{"orderElem.Order_ID": order_id}]

            # Append to bulk_updates for later execution via bulk_write
            bulk_updates.append(
                UpdateOne(
                    filter_query,
                    update_query,
                    upsert=False,
                    array_filters=array_filters
                )
            )

    async def _apply_bulk_updates(self, bulk_updates, rejected_inserts, canceled_inserts):
        """Executes bulk updates and inserts asynchronously."""
        if bulk_updates:
            try:
                result = await self.async_mongo.open_positions.bulk_write(bulk_updates)
                self.logger.info(f"Bulk update complete: {result.modified_count} documents modified.")
            except Exception as e:
                self.logger.error(f"Error during bulk update: {e}")

        if rejected_inserts:
            try:
                await self.async_mongo.rejected.insert_many(rejected_inserts)
                self.logger.info(f"Inserted {len(rejected_inserts)} rejected orders.")
            except Exception as e:
                self.logger.error(f"Error inserting rejected orders: {e}")

        if canceled_inserts:
            try:
                await self.async_mongo.canceled.insert_many(canceled_inserts)
                self.logger.info(f"Inserted {len(canceled_inserts)} canceled orders.")
            except Exception as e:
                self.logger.error(f"Error inserting canceled orders: {e}")

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
    async def addNewStrategy(self, strategy, asset_type):
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

        await self.async_mongo.strategies.update_one(
            {"Account_ID": self.account_id, "Strategy": strategy, "Asset_Type": asset_type},
            {"$setOnInsert": obj},
            upsert=True
        )