import asyncio
from api_trader.position_updater import PositionUpdater
from api_trader.quote_manager import QuoteManager
from assets.helper_functions import assign_order_ids, convertStringToDatetime, getUTCDatetime, modifiedAccountID
from api_trader.tasks import Tasks
from assets.exception_handler import exception_handler
from api_trader.order_builder import OrderBuilderWrapper
from dotenv import load_dotenv
from pathlib import Path
import os
from pymongo.errors import WriteError, WriteConcernError

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
        """Asynchronous method to update the status of queued orders.

        Queries queued orders and checks their current status via the TDAmeritrade API.
        Handles outcomes for filled, canceled, and rejected orders.
        """
        # Fetch queued orders asynchronously
        queued_orders = await self.async_mongo.queue.find(
            {"Trader": self.user["Name"], "Order_ID": {"$ne": None}, "Account_ID": self.account_id}
        ).to_list(None)

        for queue_order in queued_orders:

            spec_order = await self.tdameritrade.getSpecificOrderAsync(queue_order["Order_ID"])

            # Check if spec_order is None before attempting to access it
            if spec_order is None:
                orderMessage = "Order not found or API is down."
            else:
                orderMessage = spec_order.get('message', '')

            # Handle cases where the order is not found or contains an error
            if "error" in orderMessage.lower() or "Order not found" in orderMessage:
                custom = {
                    "price": queue_order["Entry_Price"] if queue_order["Direction"] == "OPEN POSITION" else queue_order["Exit_Price"],
                    "shares": queue_order["Qty"]
                }

                if self.RUN_LIVE_TRADER:
                    data_integrity = "Assumed"
                    self.logger.warning(
                        f"Order ID not found. Moving {queue_order['Symbol']} {queue_order['Order_Type']} order to {queue_order['Direction']} positions ({modifiedAccountID(self.account_id)})"
                    )
                else:
                    data_integrity = "Reliable"
                    self.logger.info(
                        f"Paper Trader - Sending queue order to PushOrder ({modifiedAccountID(self.account_id)})"
                    )

                await self.pushOrder(queue_order, custom, data_integrity)
                continue

            # Extract the new status
            new_status = spec_order.get("status")

            if new_status == "FILLED":
                if queue_order["Order_Type"] == "OCO":
                    queue_order = {**queue_order, **self.extractOCOchildren(spec_order)}

                await self.pushOrder(queue_order, spec_order)

            elif new_status in {"CANCELED", "REJECTED"}:
                await self.async_mongo.queue.delete_one(
                    {"Trader": self.user["Name"], "Symbol": queue_order["Symbol"], "Strategy": queue_order["Strategy"], "Account_ID": self.account_id}
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

                self.logger.info(
                    f"{new_status.upper()} order for {queue_order['Symbol']} ({modifiedAccountID(self.account_id)})"
                )

            else:
                await self.async_mongo.queue.update_one(
                    {"Trader": self.user["Name"], "Account_ID": queue_order["Account_ID"], "Symbol": queue_order["Symbol"], "Strategy": queue_order["Strategy"]},
                    {"$set": {"Order_Status": new_status}}
                )

    # STEP FOUR
    @exception_handler
    async def pushOrder(self, queue_order, spec_order, data_integrity="Reliable"):
        """ METHOD PUSHES ORDER TO EITHER OPEN POSITIONS OR CLOSED POSITIONS COLLECTION IN MONGODB.
            IF BUY ORDER, THEN PUSHES TO OPEN POSITIONS.
            IF SELL ORDER, THEN PUSHES TO CLOSED POSITIONS.
        """

        symbol = queue_order["Symbol"]
        strategy = queue_order["Strategy"]
        direction = queue_order["Direction"]
        account_id = queue_order["Account_ID"]
        asset_type = queue_order["Asset_Type"]
        side = queue_order["Side"]
        position_type = queue_order["Position_Type"]
        position_size = queue_order["Position_Size"]
        account_position = queue_order["Account_Position"]
        order_type = queue_order["Order_Type"]

        if "orderActivityCollection" in spec_order:
            price = spec_order["orderActivityCollection"][0]["executionLegs"][0]["price"]
            shares = int(spec_order["quantity"])
        else:
            price = spec_order.get("price")
            shares = int(queue_order.get("Qty"))

        price = round(price, 2) if price >= 1 else round(price, 4)

        # Extract the entered time from the spec_order if available
        entered_time_str = spec_order.get("enteredTime")
        entry_date = convertStringToDatetime(entered_time_str) if entered_time_str else queue_order.get("Entry_Date", getUTCDatetime())

        obj = {
            "Symbol": symbol,
            "Strategy": strategy,
            "Position_Size": position_size,
            "Position_Type": position_type,
            "Data_Integrity": data_integrity,
            "Trader": self.user["Name"],
            "Account_ID": account_id,
            "Asset_Type": asset_type,
            "Account_Position": account_position,
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
        message_to_push = None

        if direction == "OPEN POSITION":
            obj.update({
                "Qty": shares,
                "Entry_Price": price,
                "Entry_Date": entry_date  # Use the more accurate entry date
            })
            collection_insert = self.async_mongo.open_positions.insert_one
            message_to_push = f">>>> \n Side: {side} \n Symbol: {symbol} \n Qty: {shares} \n Price: ${price} \n Strategy: {strategy} \n Trader: {self.user['Name']}"

        elif direction == "CLOSE POSITION":
            try:
                position = await self.async_mongo.open_positions.find_one(
                    {"Trader": self.user["Name"], "Symbol": symbol, "Strategy": strategy, "Account_ID": account_id}
                )
                self.logger.debug(f"Query result for {symbol}: {position}")
            except asyncio.CancelledError:
                self.logger.warning(f"Task for {symbol} in pushOrder was cancelled.")
                raise  # Reraise the cancellation to propagate it
            except Exception as e:
                self.logger.error(f"Query failed for {symbol}: {e}")
                position = None

            if position is not None:
                obj.update({
                    "Qty": position["Qty"],
                    "Entry_Price": position["Entry_Price"],
                    "Entry_Date": position["Entry_Date"],  # Use the entry date from open position
                    "Exit_Price": price,
                    "Exit_Date": getUTCDatetime() if position.get("Exit_Date") is None else position["Exit_Date"]
                })

                # Check if the position is already in closed_positions
                already_closed = await self.async_mongo.closed_positions.count_documents({
                    "Trader": self.user["Name"],
                    "Account_ID": account_id,
                    "Symbol": symbol,
                    "Strategy": strategy, 
                    "Entry_Date": position["Entry_Date"],
                    "Entry_Price": position["Entry_Price"],
                    "Exit_Price": price,
                    "Qty": position["Qty"]
                })

                if already_closed == 0:
                    collection_insert = self.async_mongo.closed_positions.insert_one
                    message_to_push = f"____ \n Side: {side} \n Symbol: {symbol} \n Qty: {position['Qty']} \n Entry Price: ${position['Entry_Price']} \n Exit Price: ${price} \n Trader: {self.user['Name']}"

                is_removed = await self.async_mongo.open_positions.delete_one(
                    {"Trader": self.user["Name"], "Account_ID": account_id, "Symbol": symbol, "Strategy": strategy}
                )

                if is_removed.deleted_count == 0:
                    self.logger.error(f"Failed to delete open position for {symbol}")

        # Push to MongoDB with retry logic
        if collection_insert:
            try:
                await collection_insert(obj)
            except Exception as e:
                self.logger.error(f"Failed to insert {symbol} into MongoDB. Retrying... - {e}")
                try:
                    await collection_insert(obj)
                except Exception as e:
                    self.logger.error(f"Retry failed for {symbol}. Error: {e}")

        # Remove from Queue
        await self.async_mongo.queue.delete_one(
            {"Trader": self.user["Name"], "Symbol": symbol, "Strategy": strategy, "Account_ID": account_id}
        )

        # Send notification
        # if message_to_push:
        #     await self.push.send(message_to_push)

    # RUN TRADER
    @exception_handler
    async def runTrader(self, trade_data):
        self.logger.debug(f"runTrader started with trade_data ({modifiedAccountID(self.account_id)}): {trade_data}")

        # Update all order statuses
        await self.updateStatus()

        # Update user attribute
        self.user = await self.async_mongo.users.find_one({"Name": self.user["Name"]})

        user_name = self.user["Name"]
        account_id = self.account_id

        forbidden_symbols = {
            doc['Symbol'] for doc in await self.async_mongo.forbidden.find({"Account_ID": account_id}).to_list(None)
        }

        for row in trade_data:
            strategy = row["Strategy"]
            symbol = row["Symbol"]
            side = row["Side"]

            # Fetch open position, queued order, and strategy for the current row
            open_position = await self.async_mongo.open_positions.find_one(
                {"Trader": user_name, "Symbol": symbol, "Strategy": strategy, "Account_ID": account_id}
            )
            queued_order = await self.async_mongo.queue.find_one(
                {"Trader": user_name, "Symbol": symbol, "Strategy": strategy, "Account_ID": account_id}
            )
            strategy_object = await self.async_mongo.strategies.find_one(
                {"Strategy": strategy, "Account_ID": account_id}
            )

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
                if side == "BUY" and position_type == "SHORT":
                    direction = "CLOSE POSITION"  # Covering a short
                elif side == "SELL" and position_type == "LONG":
                    direction = "CLOSE POSITION"  # Selling a long
                elif side == "SELL_TO_CLOSE" and position_type == "LONG":
                    direction = "CLOSE POSITION"  # Selling long option
                elif side == "BUY_TO_CLOSE" and position_type == "SHORT":
                    direction = "CLOSE POSITION"  # Covering short option
                else:
                    continue  # Skip if none of the above conditions match
            elif symbol not in forbidden_symbols:
                # Opening new positions
                if side == "BUY" and position_type == "LONG":
                    direction = "OPEN POSITION"  # Going long
                elif side == "SELL" and position_type == "SHORT":
                    direction = "OPEN POSITION"  # Shorting
                elif side == "SELL_TO_OPEN" and position_type == "SHORT":
                    direction = "OPEN POSITION"  # Opening short option
                elif side == "BUY_TO_OPEN" and position_type == "LONG":
                    direction = "OPEN POSITION"  # Opening long option
                else:
                    continue  # Skip if none of the above conditions match

            # Process the order if a direction is determined
            if direction:
                order_data = {**row, **open_position} if open_position else row
                await self.sendOrder(order_data, strategy_object, direction)
