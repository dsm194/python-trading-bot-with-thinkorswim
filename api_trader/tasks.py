
# imports
import time
from dotenv import load_dotenv
from pathlib import Path
import os

import httpcore
from assets.exception_handler import exception_handler
from assets.helper_functions import getDatetime, selectSleep, modifiedAccountID
from pymongo import UpdateOne

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")

TAKE_PROFIT_PERCENTAGE = float(os.getenv('TAKE_PROFIT_PERCENTAGE'))
STOP_LOSS_PERCENTAGE = float(os.getenv('STOP_LOSS_PERCENTAGE'))

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
            {"Trader": self.user["Name"], "Account_Position": "Paper", "Strategy":"MACD_XVER_8_17_9_EXP_DEBUG"}))
            # {"Trader": self.user["Name"], "Account_Position": "Paper"}))

        # Fetch all relevant strategies for the account in one query and store them in a dictionary
        strategies = self.mongo.strategies.find({"Account_ID": self.account_id})
        strategy_dict = {strategy["Strategy"]: strategy for strategy in strategies}

        positions_by_symbol = {}
        for position in open_positions:
            symbol = position["Symbol"] if position["Asset_Type"] == "EQUITY" else position["Pre_Symbol"]
            if symbol not in positions_by_symbol:
                positions_by_symbol[symbol] = []
            positions_by_symbol[symbol].append(position)

        # Process symbols in chunks of 500
        symbols = list(positions_by_symbol.keys())
        batch_size = 500
        quotes = {}
        for i in range(0, len(symbols), batch_size):
            # Batch the symbols for API call
            batch_symbols = symbols[i:i + batch_size]

            success = False
            retries = 3  # Number of retries if a timeout occurs
            while not success and retries > 0:
                try:
                    batch_quotes = self.tdameritrade.getQuotes(batch_symbols)
                    quotes.update(batch_quotes)
                    success = True
                except httpcore.ConnectTimeout as e:
                    retries -= 1
                    self.logger.warning(f"Timeout occurred for batch {i//batch_size + 1}, retries left: {retries}")
                    if retries > 0:
                        time.sleep(2)  # Wait for 2 seconds before retrying
                    else:
                        self.logger.error(f"Failed to retrieve quotes for batch {i//batch_size + 1} after multiple attempts.")
                except Exception as e:
                    self.logger.error(f"An unexpected error occurred: {e}")
                    break  # If another type of exception occurs, break the loop and stop retrying

            for symbol in batch_symbols:
                
                # Reset the price at the start of each loop iteration
                price = None

                for position in positions_by_symbol[symbol]:
                    strategy_object = strategy_dict.get(position["Strategy"])

                    if not strategy_object:
                        self.logger.warning(f"Strategy not found for position: {position['_id']}")
                        continue

                    quote = quotes.get(symbol)

                    if not quote or "askPrice" not in quote["quote"]:
                        self.logger.error(f"Quote not found or invalid for symbol: {symbol}")
                        continue

                    # Safely check if 'EQ' exists in the marketHours structure and if the market is open
                    equity_data = marketHours.get(position["Asset_Type"].lower(), marketHours)
                    equity_data = equity_data.get('EQ', equity_data)
                    equity_data = equity_data.get(position["Asset_Type"].lower(), equity_data)
                    isMarketOpen = equity_data.get('isOpen', False)

                    price = float(quote["quote"]["askPrice"] if isMarketOpen else quote["regular"]["regularMarketLastPrice"] )

                    # Check for stop-loss or take-profit conditions
                    if price and price <= (position["Entry_Price"] * STOP_LOSS_PERCENTAGE) or price >= (position["Entry_Price"] * TAKE_PROFIT_PERCENTAGE):
                        # Determine side of the order to close the position
                        position["Side"] = "SELL" if position["Position_Type"] == "LONG" and position["Qty"] > 0 else "BUY"
                        # If we are going to close the position, make sure we send just a single closing order by setting the strategy_object["Order_Type"] to "STANDARD"
                        strategy_object["Order_Type"] = "STANDARD"
                        self.sendOrder(position, strategy_object, "CLOSE POSITION")

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

            oco_children["childOrderStrategies"][child["orderId"]] = {
                "Side": child["orderLegCollection"][0]["instruction"],
                "Exit_Price": child["stopPrice"] if "stopPrice" in child else child["price"],
                "Exit_Type": "STOP LOSS" if "stopPrice" in child else "TAKE PROFIT",
                "Order_Status": child["status"]
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
