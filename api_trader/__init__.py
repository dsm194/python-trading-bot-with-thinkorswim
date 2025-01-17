import asyncio
from api_trader.position_updater import PositionUpdater
from assets.helper_functions import assign_order_ids, convertStringToDatetime, getUTCDatetime, modifiedAccountID
from api_trader.tasks import Tasks
from assets.exception_handler import exception_handler
from api_trader.order_builder import OrderBuilderWrapper
from dotenv import load_dotenv
from pathlib import Path
import os

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")


class ApiTrader(Tasks, OrderBuilderWrapper):

    def __init__(self, user, async_mongo, push, logger, account_id, tdameritrade, quote_manager_pool):
        """
        Args:
            user ([dict]): [USER DATA FOR CURRENT INSTANCE]
            mongo ([object]): [MONGO OBJECT CONNECTING TO DB]
            push ([object]): [PUSH OBJECT FOR PUSH NOTIFICATIONS]
            logger ([object]): [LOGGER OBJECT FOR LOGGING]
            account_id ([str]): [USER ACCOUNT ID FOR TDAMERITRADE]
            asset_type ([str]): [ACCOUNT ASSET TYPE (EQUITY, OPTIONS)]
        """
        
        try:

            self.RUN_TASKS = os.getenv('RUN_TASKS') == "True"
            self.RUN_LIVE_TRADER = user["Accounts"].get(str(account_id), {}).get("Account_Position") == "Live"

            # Instance variables
            self.user = user
            self.async_mongo = async_mongo
            self.push = push
            self.logger = logger
            self.account_id = account_id
            self.tdameritrade = tdameritrade

            self.no_ids_list = []
            
            self.quote_manager = quote_manager_pool.get_or_create_manager(tdameritrade, logger)
            self.position_updater = PositionUpdater(self.async_mongo.open_positions, self.logger)

            # Initialize parent classes
            Tasks.__init__(self, self.quote_manager, self.position_updater)
            OrderBuilderWrapper.__init__(self, async_mongo)

            # Path to the stop signal file
            self.stop_signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp', 'stop_signal.txt')

            if self.RUN_TASKS:
                # Start the event loop in the main thread and process tasks
                asyncio.create_task(self.run_tasks_with_exit_check())
                asyncio.create_task(self.trader_thread_function())
                asyncio.create_task(self.position_updater.start_workers())
                asyncio.create_task(self.position_updater.monitor_queue())
            else:
                self.logger.info(
                    f"NOT RUNNING TASKS FOR {self.user['Name']} ({modifiedAccountID(self.account_id)})\n",
                    extra={'log': False}
                )

            self.logger.info(
                f"RUNNING {self.user['Accounts'][str(self.account_id)]['Account_Position'].upper()} TRADER ({modifiedAccountID(self.account_id)})\n"
            )
        
        except Exception as e:
            self.logger.error(f"Error initializing ApiTrader: {str(e)}")

    async def stop_trader(self):
        await self.quote_manager.stop_streaming()
        await self.position_updater.stop()

    # STEP ONE
    @exception_handler
    async def sendOrder(self, trade_data, strategy_object, direction):
        """Processes and sends an order based on trade data, strategy, and direction.

        Args:
            trade_data (dict): Trade data for the order.
            strategy_object (dict): Strategy configuration.
            direction (str): "OPEN POSITION" or "CLOSE POSITION".
        """
        from schwab.utils import Utils

        symbol = trade_data["Symbol"]
        strategy = trade_data["Strategy"]
        side = trade_data["Side"]
        order_type = strategy_object["Order_Type"]

        # Generate the order and object based on the order type
        if order_type == "STANDARD":
            order, obj = await self.standardOrder(
                trade_data, strategy_object, direction, self.user, self.account_id
            )
        elif order_type == "OCO":
            order, obj = await self.OCOorder(
                trade_data, strategy_object, direction, self.user, self.account_id
            )
        else:
            self.logger.error(f"Unsupported order type: {order_type}")
            return

        if order is None or obj is None:
            self.logger.warning(f"Order creation failed for {symbol}.")
            return

        # Place live trade orders
        if self.RUN_LIVE_TRADER:
            try:
                order_details = await self.tdameritrade.placeTDAOrderAsync(order)

                if not order_details or "Order_ID" not in order_details:
                    # Handle failed order placement
                    error_message = order_details.get("error", "Unknown error") if order_details else "No response"
                    other = {
                        "Symbol": symbol,
                        "Order_Type": side,
                        "Order_Status": "REJECTED",
                        "Strategy": strategy,
                        "Trader": self.user["Name"],
                        "Date": getUTCDatetime(),
                        "Account_ID": self.account_id,
                    }
                    await self.async_mongo.rejected.insert_one(other)

                    self.logger.error(
                        f"Order rejected for {symbol} ({modifiedAccountID(self.account_id)}) - Reason: {error_message}"
                    )
                    return

                # Update order object with live trade details
                obj.update(order_details)
                obj["Account_Position"] = "Live"

            except Exception as e:
                self.logger.error(
                    f"Exception while placing live order for {symbol}: {e}"
                )
                return
        else:
            # Simulate a paper trade
            assign_order_ids(obj)  # Ensure this function handles async or thread-safe behavior if needed
            obj["Account_Position"] = "Paper"

        # Mark order as queued and add to the queue collection
        obj["Order_Status"] = "QUEUED"
        await self.queueOrder(obj)

        # Log the outcome
        trade_type = "Live Trade" if self.RUN_LIVE_TRADER else "Paper Trade"
        self.logger.info(
            f"{trade_type}: {side} order for symbol {symbol} ({modifiedAccountID(self.account_id)})"
        )


    # STEP TWO
    @exception_handler
    async def queueOrder(self, order):
        """Asynchronous method for queuing an order to the queue collection in MongoDB.

        Args:
            order (dict): Order data to be placed in the queue collection.
        """
        # Asynchronously update or insert into the queue
        await self.async_mongo.queue.update_one(
            {
                "Trader": self.user["Name"],
                "Account_ID": order["Account_ID"],
                "Symbol": order["Symbol"],
                "Strategy": order["Strategy"]
            },
            {"$set": order},
            upsert=True
        )
        self.logger.debug(f"Order queued successfully: {order}")

    # STEP THREE
    @exception_handler
    async def updateStatus(self):
        """Asynchronous method to update the status of queued orders."""
        # Semaphore to limit concurrent tasks (e.g., max 10 concurrent tasks)
        semaphore = asyncio.Semaphore(10)

        queued_orders_cursor = self.async_mongo.queue.find(
            {"Trader": self.user["Name"], "Order_ID": {"$ne": None}, "Account_ID": self.account_id},
            {
                "_id": 1,
                "Order_ID": 1,
                "Symbol": 1,
                "Strategy": 1,
                "Direction": 1,
                "Account_ID": 1,
                "Asset_Type": 1,
                "Order_Type": 1,
                "Qty": 1,
                "Entry_Price": 1,
                "Entry_Date": 1,
                "Exit_Price": 1,
                "Exit_Date": 1,
                "Position_Size": 1,
                "Position_Type": 1,
                "Account_Position": 1,
                "childOrderStrategies": 1,
                "Pre_Symbol": 1,
                "Exp_Date": 1,
                "Option_Type": 1
            }
        )

        queued_orders = await queued_orders_cursor.to_list(None)

        async def process_order(queue_order):
            async with semaphore:
                try:
                    spec_order = await self.tdameritrade.getSpecificOrderAsync(queue_order["Order_ID"])
                    orderMessage = "Order not found or API is down." if spec_order is None else spec_order.get('message', '')

                    if "error" in orderMessage.lower() or "Order not found" in orderMessage:
                        custom = {
                            "price": queue_order["Entry_Price"] if queue_order["Direction"] == "OPEN POSITION" else queue_order["Exit_Price"],
                            "shares": queue_order["Qty"]
                        }
                        data_integrity = "Assumed" if self.RUN_LIVE_TRADER else "Reliable"

                        self.logger.warning(f"Order ID not found. Moving {queue_order['Symbol']} to positions.")
                        await self.pushOrder(queue_order, custom, data_integrity)
                        return

                    new_status = spec_order.get("status")
                    if new_status == "FILLED":
                        if queue_order["Order_Type"] == "OCO":
                            queue_order = {**queue_order, **self.extractOCOchildren(spec_order)}
                        await self.pushOrder(queue_order, spec_order)
                    elif new_status in {"CANCELED", "REJECTED"}:
                        await self._handle_cancel_reject(queue_order, new_status)
                    else:
                        await self.async_mongo.queue.update_one(
                            {"_id": queue_order["_id"]},
                            {"$set": {"Order_Status": new_status}}
                        )
                except Exception as e:
                    self.logger.error(f"Error processing order for {queue_order['Symbol']}: {e}")

        # Process orders concurrently with semaphore to limit parallelism
        # Using asyncio.gather but ensuring context is correct
        tasks = [asyncio.create_task(process_order(order)) for order in queued_orders]
        await asyncio.gather(*tasks)

    async def _handle_cancel_reject(self, queue_order, new_status):
        """Handles the logic for CANCELED or REJECTED orders"""
        # Use _id to delete the specific queued order
        await self.async_mongo.queue.delete_one(
            {"_id": queue_order["_id"]}
        )
        other = {
            "Symbol": queue_order["Symbol"],
            "Order_Type": queue_order["Order_Type"],
            "Order_Status": new_status,
            "Strategy": queue_order["Strategy"],
            "Trader": self.user["Name"],
            "Date": getUTCDatetime(),
            "Account_ID": self.account_id
        }
        collection = self.async_mongo.rejected if new_status == "REJECTED" else self.async_mongo.canceled
        await collection.insert_one(other)
        self.logger.info(f"{new_status.upper()} order for {queue_order['Symbol']} ({modifiedAccountID(self.account_id)})")


    # STEP FOUR
    @exception_handler
    async def pushOrder(self, queue_order, spec_order, data_integrity="Reliable"):
        """Pushes order to open or closed positions collection in MongoDB."""
        symbol = queue_order["Symbol"]
        strategy = queue_order["Strategy"]
        direction = queue_order["Direction"]
        account_id = queue_order["Account_ID"]
        asset_type = queue_order["Asset_Type"]
        order_type = queue_order["Order_Type"]

        # Retrieve price and shares from spec_order
        price = spec_order["orderActivityCollection"][0]["executionLegs"][0]["price"] if "orderActivityCollection" in spec_order else spec_order.get("price")
        shares = int(spec_order["quantity"]) if "orderActivityCollection" in spec_order else int(queue_order.get("Qty"))
        price = round(price, 2) if price >= 1 else round(price, 4)

        entered_time_str = spec_order.get("enteredTime")
        entry_date = convertStringToDatetime(entered_time_str) if entered_time_str else queue_order.get("Entry_Date", getUTCDatetime())

        obj = {
            "Symbol": symbol,
            "Strategy": strategy,
            "Position_Size": queue_order["Position_Size"],
            "Position_Type": queue_order["Position_Type"],
            "Data_Integrity": data_integrity,
            "Trader": self.user["Name"],
            "Account_ID": account_id,
            "Asset_Type": asset_type,
            "Account_Position": queue_order["Account_Position"],
            "Order_Type": order_type
        }

        if order_type == "OCO":
            obj["childOrderStrategies"] = queue_order.get("childOrderStrategies")

        if asset_type == "OPTION":
            obj.update({
                "Pre_Symbol": queue_order["Pre_Symbol"],
                "Exp_Date": queue_order["Exp_Date"],
                "Option_Type": queue_order["Option_Type"]
            })

        collection_insert = None

        # Handle open and close positions
        if direction == "OPEN POSITION":
            obj.update({"Qty": shares, "Entry_Price": price, "Entry_Date": entry_date})
            collection_insert = self.async_mongo.open_positions.insert_one
        elif direction == "CLOSE POSITION":
            obj.update({
                "Qty": queue_order.get("Qty"),
                "Entry_Price": queue_order.get("Entry_Price"),
                "Entry_Date": queue_order.get("Entry_Date"),
                "Exit_Price": price,
                "Exit_Date": getUTCDatetime() if not queue_order.get("Exit_Date") else queue_order["Exit_Date"]
            })
            
            position = await self.async_mongo.open_positions.find_one(
                {"Trader": self.user["Name"], "Symbol": symbol, "Strategy": strategy, "Account_ID": account_id}
            )
            if position:
                obj.update({
                    "Qty": position["Qty"],
                    "Entry_Price": position["Entry_Price"],
                    "Entry_Date": position["Entry_Date"]
                })

            collection_insert = self.async_mongo.closed_positions.insert_one

            is_removed = await self.async_mongo.open_positions.delete_one(
                {"Trader": self.user["Name"], "Account_ID": account_id, "Symbol": symbol, "Strategy": strategy}
            )

            if is_removed.deleted_count == 0:
                self.logger.error(f"Failed to delete open position for {symbol}")

        # Push to MongoDB
        if collection_insert:
            try:
                await collection_insert(obj)
            except Exception as e:
                self.logger.error(f"Insert failed for {symbol}: {e}")
                await self.retry_insert(collection_insert, obj)

        # Remove from Queue
        await self.async_mongo.queue.delete_one({"_id": queue_order["_id"]})

    async def retry_insert(self, collection_insert, obj, max_retries=3):
        for attempt in range(max_retries):
            try:
                await collection_insert(obj)
                break
            except Exception as e:
                self.logger.error(f"Retry {attempt + 1} failed for {obj['Symbol']}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

    # RUN TRADER
    @exception_handler
    async def runTrader(self, trade_data):
        try:
            self.logger.debug(f"runTrader started with trade_data ({modifiedAccountID(self.account_id)}): {trade_data}")

            # Update all order statuses
            await self.updateStatus()

            # Update user attribute
            self.user = await self.async_mongo.users.find_one({"Name": self.user["Name"]})

            user_name = self.user["Name"]
            account_id = self.account_id

            # Set the cursor first
            forbidden_cursor = self.async_mongo.forbidden.find({"Account_ID": account_id})

            # Await the result of to_list()
            forbidden_symbols = await forbidden_cursor.to_list(None)
            forbidden_symbols = {doc['Symbol'] for doc in forbidden_symbols}

            # Collect all symbols from the trade data
            trade_data_strategies = [row["Strategy"] for row in trade_data]
            trade_data_symbols = [row["Symbol"] for row in trade_data]

            # Batch the queries into one for each collection
            queued_orders_cursor = self.async_mongo.queue.find(
                {"Trader": self.user["Name"], "Account_ID": self.account_id, "Symbol": {"$in": trade_data_symbols}, "Strategy": {"$in": trade_data_strategies}}
            )
            queued_orders = await queued_orders_cursor.to_list(None)

            open_positions_cursor = self.async_mongo.open_positions.find(
                {"Trader": self.user["Name"], "Account_ID": self.account_id, "Symbol": {"$in": trade_data_symbols}, "Strategy": {"$in": trade_data_strategies}}
            )
            open_positions = await open_positions_cursor.to_list(None)

            strategies_cursor = self.async_mongo.strategies.find(
                {"Account_ID": self.account_id, "Strategy": {"$in": trade_data_strategies}}
            )
            strategies = await strategies_cursor.to_list(None)

            # Convert lists to dictionaries for faster lookup
            queued_orders_dict = {f"{order['Symbol']}_{order['Strategy']}": order for order in queued_orders}
            open_positions_dict = {f"{position['Symbol']}_{position['Strategy']}": position for position in open_positions}
            strategies_dict = {strategy['Strategy']: strategy for strategy in strategies}

            # Now, iterate over each row in trade_data and process the corresponding order
            for row in trade_data:
                strategy = row["Strategy"]
                symbol = row["Symbol"]
                
                # Lookup strategy, queued order, and open position directly by symbol and strategy
                queued_order = queued_orders_dict.get(f"{symbol}_{strategy}")
                open_position = open_positions_dict.get(f"{symbol}_{strategy}")
                strategy_object = strategies_dict.get(strategy)

                # Add new strategy if it doesn't exist
                if not strategy_object:
                    strategy_object = await self.addNewStrategy(strategy, row["Asset_Type"])

                position_type = strategy_object["Position_Type"]
                row["Position_Type"] = position_type

                # Skip processing if the order is already queued
                if queued_order:
                    continue

                # Determine trade direction
                direction = None
                if open_position:
                    # Closing existing positions
                    if row["Side"] == "BUY" and position_type == "SHORT":
                        direction = "CLOSE POSITION"  # Covering a short
                    elif row["Side"] == "SELL" and position_type == "LONG":
                        direction = "CLOSE POSITION"  # Selling a long
                    elif row["Side"] == "SELL_TO_CLOSE" and position_type == "LONG":
                        direction = "CLOSE POSITION"  # Selling long option
                    elif row["Side"] == "BUY_TO_CLOSE" and position_type == "SHORT":
                        direction = "CLOSE POSITION"  # Covering short option
                    else:
                        continue  # Skip if none of the above conditions match
                elif symbol not in forbidden_symbols:
                    # Opening new positions
                    if row["Side"] == "BUY" and position_type == "LONG":
                        direction = "OPEN POSITION"  # Going long
                    elif row["Side"] == "SELL" and position_type == "SHORT":
                        direction = "OPEN POSITION"  # Shorting
                    elif row["Side"] == "SELL_TO_OPEN" and position_type == "SHORT":
                        direction = "OPEN POSITION"  # Opening short option
                    elif row["Side"] == "BUY_TO_OPEN" and position_type == "LONG":
                        direction = "OPEN POSITION"  # Opening long option
                    else:
                        continue  # Skip if none of the above conditions match

                # Process the order if a direction is determined
                if direction:
                    order_data = {**row, **open_position} if open_position else row
                    await self.sendOrder(order_data, strategy_object, direction)

        except asyncio.CancelledError:
            self.logger.warning("runTrader was cancelled.")
            raise  # Re-raise to let the task know it's cancelled