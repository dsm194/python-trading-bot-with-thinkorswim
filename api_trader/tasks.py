
# imports
import random
import time
from dotenv import load_dotenv
from pathlib import Path
import os

import httpx
from api_trader.order_builder import OrderBuilderWrapper
from assets.exception_handler import exception_handler
from assets.helper_functions import getDatetime, selectSleep, modifiedAccountID
from pymongo import UpdateOne

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")


class Tasks:

    # THE TASKS CLASS IS USED FOR HANDLING ADDITIONAL TASKS OUTSIDE OF THE LIVE TRADER.
    # YOU CAN ADD METHODS THAT STORE PROFIT LOSS DATA TO MONGO, SELL OUT POSITIONS AT END OF DAY, ECT.
    # YOU CAN CREATE WHATEVER TASKS YOU WANT FOR THE BOT.
    # YOU CAN USE THE DISCORD CHANNEL NAMED TASKS IF YOU ANY HELP.

    def __init__(self):

        self.isAlive = True


    @exception_handler
    def checkOCOpapertriggers(self):

        # Are we during market hours?
        dtNow = getDatetime()
        marketHours = self.tdameritrade.getMarketHours(date=dtNow)

        # Fetch all open positions for the trader and the paper account in one query
        open_positions = list(self.mongo.open_positions.find(
            # {"Trader": self.user["Name"], "Account_ID": self.account_id, "Account_Position": "Paper", "Strategy":"MACD_XVER_8_17_9_EXP_DEBUG"}))
            {"Trader": self.user["Name"], "Account_ID": self.account_id, "Account_Position": "Paper"}))

        # Fetch all relevant strategies for the account in one query and store them in a dictionary
        strategies = self.mongo.strategies.find({"Account_ID": self.account_id})
        strategy_dict = {strategy["Strategy"]: strategy for strategy in strategies}

        # Load exit strategies and store them in strategy_dict
        for strategy_name, strategy_data in strategy_dict.items():
            strategy_object = OrderBuilderWrapper().load_strategy(strategy_data) # self.load_exit_strategy(strategy_data)
            strategy_dict[strategy_name]["ExitStrategy"] = strategy_object

        positions_by_symbol = {}
        for position in open_positions:
            symbol = position["Symbol"] if position["Asset_Type"] == "EQUITY" else position["Pre_Symbol"]
            if symbol not in positions_by_symbol:
                positions_by_symbol[symbol] = []
            positions_by_symbol[symbol].append(position)

        # Process symbols in chunks of 250 (reduced batch size)
        symbols = list(positions_by_symbol.keys())
        batch_size = 250
        quotes = {}
        for i in range(0, len(symbols), batch_size):
            # Batch the symbols for API call
            batch_symbols = symbols[i:i + batch_size]

            success = False
            retries = 3  # Number of retries if a timeout occurs
            backoff_time = 2  # Start with a 2-second delay

            while not success and retries > 0:
                try:
                    batch_quotes = self.tdameritrade.getQuotes(batch_symbols)
                    quotes.update(batch_quotes)
                    success = True
                except httpx.ReadTimeout as e:
                    retries -= 1
                    self.logger.warning(f"Read operation timed out for batch {i//batch_size + 1}, retries left: {retries}, exception: {e}")
                    if retries > 0:
                        backoff_time *= 2  # Exponential backoff
                        time.sleep(backoff_time + random.uniform(0, 1))  # Add a small random delay
                        self.logger.info(f"Retrying after timeout with backoff of {backoff_time} seconds...")
                    else:
                        self.logger.error(f"Failed to retrieve quotes for batch {i//batch_size + 1} after multiple attempts due to ReadTimeout. Exception: {e}")
                except httpx.ConnectTimeout as e:
                    retries -= 1
                    self.logger.warning(f"Connection timed out for batch {i//batch_size + 1}, retries left: {retries}, exception: {e}")
                    if retries > 0:
                        backoff_time *= 2  # Exponential backoff
                        time.sleep(backoff_time + random.uniform(0, 1))
                        self.logger.info(f"Retrying after connection timeout with backoff of {backoff_time} seconds...")
                    else:
                        self.logger.error(f"Failed to retrieve quotes for batch {i//batch_size + 1} after multiple attempts due to ConnectTimeout. Exception: {e}")
                except Exception as e:
                    self.logger.error(f"An unexpected error occurred: {e}")
                    break  # If another type of exception occurs, break the loop and stop retrying

            # Skip processing if quotes retrieval fails for the current batch
            if not success:
                continue  # Skip this batch and move on to the next one if any

            for symbol in batch_symbols:
                
                quote = quotes.get(symbol)

                if not quote or "askPrice" not in quote["quote"]:
                    self.logger.error(f"Quote not found or invalid for symbol: {symbol}")
                    continue

                for position in positions_by_symbol[symbol]:
                    strategy_name = position["Strategy"]
                    strategy_data = strategy_dict.get(strategy_name)

                    if not strategy_data or "ExitStrategy" not in strategy_data:
                        self.logger.warning(f"Exit strategy not found for position: {position['_id']}")
                        continue

                    exit_strategy = strategy_data["ExitStrategy"]

                    # Safely check if 'EQ' exists in the marketHours structure and if the market is open
                    equity_data = marketHours.get(position["Asset_Type"].lower(), marketHours)
                    equity_data = equity_data.get('EQ', equity_data)
                    equity_data = equity_data.get(position["Asset_Type"].lower(), equity_data)
                    isMarketOpen = equity_data.get('isOpen', False)

                    # price = float(quote["quote"]["askPrice"] if isMarketOpen else quote["regular"]["regularMarketLastPrice"])
                    last_price = quote["quote"]["lastPrice"]
                    max_price = position.get("max_price", position["Entry_Price"])

                    # Prepare additional params if needed
                    additional_params = {
                        "entry_price": position["Entry_Price"],
                        "quantity": position["Qty"],
                        # Add any other necessary params here
                        "last_price": last_price,
                        "max_price": max_price,
                    }

                    # Call the should_exit method to check for exit conditions
                    exit_result = exit_strategy.should_exit(additional_params)
                    should_exit = exit_result['exit']
                    
                    # Update max_price in MongoDB before sending any order
                    updated_max_price = exit_result["additional_params"]["max_price"]
                    if updated_max_price != position.get("max_price"):
                        self.mongo.open_positions.update_one(
                            {"_id": position["_id"]},
                            {"$set": {"max_price": updated_max_price}}
                        )
                        self.logger.info(f"Updated max_price for {symbol} to {updated_max_price}")

                    if should_exit:
                        # The exit conditions are met, so we need to close the position
                        position["Side"] = "SELL" if position["Position_Type"] == "LONG" and position["Qty"] > 0 else "BUY"
                        strategy_data["Order_Type"] = "STANDARD"
                        self.sendOrder(position, strategy_data, "CLOSE POSITION")

                    # Check for stop_signal.txt in each iteration
                    if os.path.isfile(self.stop_signal_file):
                        self.logger.info("Stop signal detected. Exiting checkOCOpapertriggers.")
                        return


    @exception_handler
    def checkOCOtriggers(self):
        """Checks OCO triggers (stop loss/ take profit) to see if either one has filled. 
        If so, closes the position in MongoDB accordingly.
        """

        # Fetch open OCO positions
        open_positions = self.open_positions.find(
            {"Trader": self.user["Name"], "Order_Type": "OCO"}
        )

        bulk_updates = []
        rejected_inserts = []
        canceled_inserts = []

        for position in open_positions:
            childOrderStrategies = position["childOrderStrategies"]
            updates = {}

            for strategy in childOrderStrategies:
                # Ensure 'childOrderStrategies' is in the strategy dictionary
                if 'childOrderStrategies' in strategy:
                    child_orders = strategy['childOrderStrategies']

                    for order_data in child_orders:
                        # Since 'order_id' is not shown in your structure, assume it needs to be derived or is not directly available
                        # You'll likely need a method to map each order to its ID, so modify this section accordingly
                        order_id = order_data.get("order_id")  # Replace with correct method to retrieve the order ID
                        
                        # If order_id is None, you might need to log or handle this case
                        if not order_id:
                            # self.logger.warning(f"Order ID missing for strategy: {strategy}")
                            continue

                        updates = {}

                        # Query the order status using the order_id
                        spec_order = self.tdameritrade.getSpecificOrder(order_id)
                        new_status = spec_order["status"]

                        # If the order is filled, handle it and stop processing further orders in this OCO group
                        if new_status == "FILLED":
                            self.pushOrder(position, spec_order)

                        # Handle rejected or canceled orders
                        elif new_status in ["CANCELED", "REJECTED"]:
                            other = {
                                "Symbol": position["Symbol"],
                                "Order_Type": position["Order_Type"],
                                "Order_Status": new_status,
                                "Strategy": position["Strategy"],
                                "Trader": self.user["Name"],
                                "Date": getDatetime(),
                                "Account_ID": self.account_id
                            }
                            
                            # Append to the appropriate list based on the status
                            if new_status == "REJECTED":
                                rejected_inserts.append(other)
                            else:
                                canceled_inserts.append(other)

                            # Log the status change
                            self.logger.info(
                                f"{new_status.upper()} ORDER For {position['Symbol']} - "
                                f"TRADER: {self.user['Name']} - ACCOUNT ID: {modifiedAccountID(self.account_id)}"
                            )
                        else:
                            # If the status is not terminal, prepare the update for MongoDB
                            updates[f"childOrderStrategies.{order_id}.Order_Status"] = new_status

                        # Queue the updates for bulk execution
                        if updates:
                            bulk_updates.append(
                                UpdateOne(
                                    {"Trader": self.user["Name"], "Symbol": position["Symbol"], "Strategy": position["Strategy"]},
                                    {"$set": updates}
                                )
                            )


        # Perform bulk updates in MongoDB
        if bulk_updates:
            self.open_positions.bulk_write(bulk_updates)

        # Perform bulk inserts for rejected/canceled orders
        if rejected_inserts:
            self.rejected.insert_many(rejected_inserts)

        if canceled_inserts:
            self.canceled.insert_many(canceled_inserts)


    @exception_handler
    def extractOCOchildren(self, spec_order):
        """This method extracts oco children order ids and then sends it to be stored in mongo open positions. 
        Data will be used by checkOCOtriggers with order ids to see if stop loss or take profit has been triggered.

        """

        oco_children = {
            "childOrderStrategies": {}
        }

        childOrderStrategies = spec_order["childOrderStrategies"][0]["childOrderStrategies"]

        for child in childOrderStrategies:

            # Use .get() to safely retrieve keys, and provide None as a default if keys are missing
            exit_price = child.get("stopPrice", child.get("price"))
            exit_type = "STOP LOSS" if "stopPrice" in child else "TAKE PROFIT"

            # Ensure that exit_price exists, otherwise handle missing values
            oco_children["childOrderStrategies"][child.get("Order_ID")] = {
                "Side": child.get("orderLegCollection", [{}])[0].get("instruction"),
                "Exit_Price": exit_price,
                "Exit_Type": exit_type if exit_price is not None else None,
                "Order_Status": child.get("status")
            }

        return oco_children

    @exception_handler
    def addNewStrategy(self, strategy, asset_type):
        """ METHOD UPDATES STRATEGIES OBJECT IN MONGODB WITH NEW STRATEGIES.

        Args:
            strategy ([str]): STRATEGY NAME
        """

        obj = {"Active": True,
               "Order_Type": "STANDARD",
               "Asset_Type": asset_type,
               "Position_Size": 500,
               "Position_Type": "LONG",
               "Account_ID": self.account_id,
               "Strategy": strategy,
               }

        # IF STRATEGY NOT IN STRATEGIES COLLECTION IN MONGO, THEN ADD IT

        self.strategies.update_one(
            {"Strategy": strategy},
            {"$setOnInsert": obj},
            upsert=True
        )

    def runTasks(self):
        """ METHOD RUNS TASKS ON WHILE LOOP EVERY 5 - 60 SECONDS DEPENDING.
        """

        self.logger.info(
            f"STARTING TASKS FOR {self.user['Name']} ({modifiedAccountID(self.account_id)})", extra={'log': False})

        while self.isAlive:

            try:

                # RUN TASKS ####################################################
                
                self.checkOCOtriggers()

                self.checkOCOpapertriggers()

                ##############################################################

            except KeyError:

                self.isAlive = False

            except Exception as e:

                self.logger.error(
                    f"ACCOUNT ID: {modifiedAccountID(self.account_id)} - TRADER: {self.user['Name']} - {e}")

            finally:

                time.sleep(selectSleep())

        self.logger.warning(
            f"TASK STOPPED FOR ACCOUNT ID {modifiedAccountID(self.account_id)}")
