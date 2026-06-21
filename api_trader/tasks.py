
# imports
import asyncio
import datetime as dt
import os
import time
from typing import TYPE_CHECKING

import httpx
from pymongo import UpdateOne

from assets.exception_handler import exception_handler
from assets.helper_functions import (getUTCDatetime, modifiedAccountID,
                                     selectSleep)

if TYPE_CHECKING:
    from api_trader import ApiTrader  # Forward declaration to avoid circular import


_EXPIRED_PAPER_OPTION_DRY_RUN_LOGGED_IDS = set()


class Tasks:
    """
    The Tasks class is used for handling additional tasks outside of the live trader.
    You can add methods that store profit/loss data to Mongo, sell out positions at the end of the day, etc.
    You can create whatever tasks you want for the bot.
    You can use the Discord channel named "Tasks" if you need any help.
    """

    def __init__(self, api_trader: "ApiTrader"):

        self.api_trader = api_trader
        self.quote_manager = api_trader.quote_manager
        self.position_updater = api_trader.position_updater
        self.logger = api_trader.logger
        self.user = api_trader.user
        self.account_id = api_trader.account_id
        self.async_mongo = api_trader.async_mongo
        self.tdameritrade = api_trader.tdameritrade

        self.tasks_running = False
        self.positions_by_symbol = {}  # Class-level positions dictionary
        self.symbol_evaluation_locks = {}
        self.strategy_dict = {}  # Class-level strategy dictionary
        self.lock = asyncio.Lock()
        self._cached_market_hours = {}
        self._cached_market_hours_timestamp = 0

        self.task_queue = asyncio.Queue()
        self.task_status = {
            'checkOCOtriggers': False,
            'checkOCOpapertriggers': False
        }
        self.last_checkOCOtriggers_time = time.time()  # Track the last time checkOCOtriggers was run
        self.checkOCO_interval = 10  # Run checkOCOtriggers once every 10 seconds (adjustable)
        self.last_checkOCOpapertriggers_time = time.time()  # Track the last time checkOCOtriggers was run
        self.checkOCOpaper_interval = 10  # Run checkOCOtriggers once every 10 seconds (adjustable)

        self.bulk_updates_queue = asyncio.Queue()
        self.rejected_inserts_queue = asyncio.Queue()
        self.canceled_inserts_queue = asyncio.Queue()
        self.auto_close_expired_paper_options = os.getenv("AUTO_CLOSE_EXPIRED_PAPER_OPTIONS") == "True"
        self.expired_paper_option_dry_run_logged_ids = _EXPIRED_PAPER_OPTION_DRY_RUN_LOGGED_IDS

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
            current_time = time.time()  # Get the current timestamp once at the beginning

            if task == 'checkOCOtriggers':
                # Check if enough time has passed since the last checkOCOtriggers
                if current_time - self.last_checkOCOtriggers_time >= self.checkOCO_interval:
                    await self.checkOCOtriggers()
                    self.last_checkOCOtriggers_time = current_time  # Update the last run time
            elif task == 'checkOCOpapertriggers':
                # Check if enough time has passed since the last checkOCOpapertriggers
                if current_time - self.last_checkOCOpapertriggers_time >= self.checkOCOpaper_interval:
                    await self.checkOCOpapertriggers()
                    self.last_checkOCOpapertriggers_time = current_time  # Update the last run time
            # Add more task conditions as needed
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

        position_projection = {
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
            "Side": 1,
            "Position_Size": 1,
            "Position_Type": 1,
            "Account_Position": 1,
            "childOrderStrategies": 1,
            "Pre_Symbol": 1,
            "Exp_Date": 1,
            "Option_Type": 1
        }

        today = dtNow.date()
        today_iso = today.isoformat()
        today_start = dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc)

        # Keep this cleanup targeted so the frequent task loop does not scan every
        # fake paper position just to find a few expired option contracts.
        expired_options_cursor = self.async_mongo.open_positions.find({
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Account_Position": "Paper",
            "Asset_Type": "OPTION",
            "$or": [
                {"Exp_Date": {"$lt": today_iso}},
                {"Exp_Date": {"$lt": today_start}},
            ]
        }, position_projection)

        expired_options = await expired_options_cursor.to_list(None)
        for position in expired_options:
            if self._is_expired_paper_option(position, today):
                await self._close_expired_paper_option(position, dtNow)

        # Collect all symbols from the open positions that haven't been subscribed yet
        # Check which symbols are already subscribed and filter them out from the query
        subscribed_symbols = set(self.quote_manager.subscribed_symbols)

        # Fetch open positions but only those that haven't been subscribed to yet
        open_positions_cursor = self.async_mongo.open_positions.find({
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Account_Position": "Paper",
            # "Strategy": {
            #     "$in": [
            #         "ATRTRAILINGSTOP_ATRFACTOR1_75_OPTIONS_DEBUG",
            #         "ATRHIGHSMABREAKOUTSFILTER_OPTIONS_DEBUG",
            #         "ATRHIGHSMABREAKOUTSFILTER_DEBUG",
            #         "MACD_XVER_8_17_9_EXP_DEBUG",
            #     ]
            # },
            "$and": [
                {"Symbol": {"$nin": list(subscribed_symbols)}},  # Symbol is NOT in subscribed symbols
                {"Pre_Symbol": {"$nin": list(subscribed_symbols)}}  # Pre_Symbol is NOT in subscribed symbols
            ]
        }, position_projection)

        open_positions = await open_positions_cursor.to_list(None)
        active_open_positions = []

        for position in open_positions:
            if self._is_expired_paper_option(position, today):
                await self._close_expired_paper_option(position, dtNow)
            else:
                active_open_positions.append(position)

        # Fetch strategies from MongoDB (only load the strategies needed based on open positions)
        strategy_names = {position["Strategy"] for position in active_open_positions}
        # Only query if there are new strategies to load
        if strategy_names:
            strategies = await self.async_mongo.strategies.find({
                "Account_ID": self.account_id,
                "Strategy": {"$in": list(strategy_names)}
            }).to_list(None)
        else:
            strategies = []

        # Group positions by symbol and minimize API calls
        async with self.lock:
            new_symbols = []
            for position in active_open_positions:
                # Determine the appropriate symbol key (Equity or Pre_Symbol)
                symbol = position["Symbol"] if position["Asset_Type"] == "EQUITY" else position["Pre_Symbol"]

                # Use subscribed_symbols exclusively to determine if the symbol is new
                if symbol not in self.quote_manager.subscribed_symbols:
                    # Add to new_symbols only if not already subscribed
                    new_symbols.append({"symbol": symbol, "asset_type": position["Asset_Type"]})

                # Always update positions_by_symbol for grouping purposes
                if symbol not in self.positions_by_symbol:
                    self.positions_by_symbol[symbol] = []

                if position not in self.positions_by_symbol[symbol]:
                    self.positions_by_symbol[symbol].append(position)

            # Deduplicate new symbols
            seen = set()
            new_symbols = [ns for ns in new_symbols if (ns["symbol"] not in seen and not seen.add(ns["symbol"]))]

            # Add new strategies to strategy_dict
            for strategy in strategies:
                strategy_name = strategy["Strategy"]
                if strategy_name not in self.strategy_dict:
                    strategy_object = self.api_trader.load_strategy(strategy)
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

    @staticmethod
    def _parse_expiration_date(expiration_date):
        if not expiration_date:
            return None

        if isinstance(expiration_date, dt.datetime):
            return expiration_date.date()

        if isinstance(expiration_date, dt.date):
            return expiration_date

        if isinstance(expiration_date, str):
            for date_format in ("%Y-%m-%d", "%Y%m%d", "%y%m%d"):
                try:
                    return dt.datetime.strptime(expiration_date[:10], date_format).date()
                except ValueError:
                    continue

        return None

    def _is_expired_paper_option(self, position, today):
        if position.get("Asset_Type") != "OPTION":
            return False

        expiration_date = self._parse_expiration_date(position.get("Exp_Date"))
        if expiration_date is None:
            self.logger.warning(f"Paper option {position.get('Pre_Symbol')} has no valid Exp_Date; leaving open.")
            return False

        return expiration_date < today

    async def _close_expired_paper_option(self, position, close_datetime):
        symbol = position.get("Pre_Symbol")

        if not self.auto_close_expired_paper_options:
            position_id = position.get("_id")
            dry_run_key = (str(position.get("Account_ID")), str(position_id))
            if dry_run_key in self.expired_paper_option_dry_run_logged_ids:
                return

            self.expired_paper_option_dry_run_logged_ids.add(dry_run_key)
            self.logger.info(
                f"[DRY RUN] Would close expired paper option {symbol} at 0 "
                f"(position_id={position_id}, account_id={position.get('Account_ID')}, "
                f"strategy={position.get('Strategy')}). "
                "Set AUTO_CLOSE_EXPIRED_PAPER_OPTIONS=True to enable."
            )
            return

        closed_position = {
            "Symbol": position["Symbol"],
            "Strategy": position["Strategy"],
            "Position_Size": position.get("Position_Size"),
            "Position_Type": position.get("Position_Type"),
            "Data_Integrity": "Expired Paper Option",
            "Trader": self.user["Name"],
            "Account_ID": self.account_id,
            "Asset_Type": "OPTION",
            "Account_Position": "Paper",
            "Order_Type": position.get("Order_Type"),
            "Pre_Symbol": position.get("Pre_Symbol"),
            "Exp_Date": position.get("Exp_Date"),
            "Option_Type": position.get("Option_Type"),
            "Qty": position.get("Qty"),
            "Entry_Price": position.get("Entry_Price"),
            "Entry_Date": position.get("Entry_Date"),
            "Exit_Price": 0,
            "Exit_Date": close_datetime,
        }

        await self.async_mongo.closed_positions.insert_one(closed_position)
        delete_result = await self.async_mongo.open_positions.delete_one({"_id": position["_id"]})

        if delete_result.deleted_count == 0:
            self.logger.error(f"Failed to delete expired paper option {position.get('Pre_Symbol')} from open positions.")
            return

        async with self.lock:
            if symbol in self.positions_by_symbol:
                self.positions_by_symbol[symbol] = [
                    pos for pos in self.positions_by_symbol[symbol] if pos.get("_id") != position["_id"]
                ]
                if not self.positions_by_symbol[symbol]:
                    del self.positions_by_symbol[symbol]

        if symbol in self.quote_manager.subscribed_symbols:
            await self.quote_manager.unsubscribe([symbol])

        self.logger.info(f"Closed expired paper option {symbol} at 0.")

    @exception_handler
    async def evaluate_paper_triggers(self, symbol, quote_data):
        """ Evaluates whether a position should be exited based on updated quote data. """

        async with self.lock:
            symbol_lock = self.symbol_evaluation_locks.setdefault(symbol, asyncio.Lock())

        async with symbol_lock:
            await self._evaluate_paper_triggers_for_symbol(symbol, quote_data)

    async def _evaluate_paper_triggers_for_symbol(self, symbol, quote_data):
        async with self.lock:  # Lock during modification
            local_positions_by_symbol = list(self.positions_by_symbol.get(symbol, []))

        # List to track positions that should be removed
        positions_to_remove = []

        for position in local_positions_by_symbol:
            strategy_name = position["Strategy"]
            strategy_data = self.strategy_dict.get(strategy_name)

            if not strategy_data or "ExitStrategy" not in strategy_data:
                self.logger.warning(f"Exit strategy not found for position: {position['_id']}")
                continue

            exit_strategy = strategy_data["ExitStrategy"]

            # Determine whether the market is open (use REGULAR_MARKET_LAST_PRICE if closed)
            marketHours = self._cached_market_hours or {}
            isMarketOpen = marketHours.get('isOpen', False)

            last_price = quote_data["last_price"] if isMarketOpen or position["Asset_Type"] == "OPTION" else quote_data["regular_market_last_price"]
            max_price = position.get("Max_Price", position["Entry_Price"])

            # Prepare additional params for exit strategy
            additional_params = {
                "entry_price": position["Entry_Price"],
                "quantity": position["Qty"],
                "last_price": last_price,
                "max_price": max_price,
            }

            # Check if the exit conditions are met
            exit_result = exit_strategy.should_exit(additional_params)
            should_exit = exit_result['exit']
            updated_max_price = exit_result["additional_params"]["max_price"]

            # Update max_price in MongoDB only if updated_max_price is greater than the existing max_price or if max_price is None
            current_max_price = position.get("Max_Price")
            if current_max_price is None or updated_max_price > current_max_price:
                await self.position_updater.queue_max_price_update(position["_id"], updated_max_price)
                self.logger.info(f"Updated max_price for {symbol} ({position["_id"]}) to {updated_max_price}")
                position["Max_Price"] = updated_max_price

            if should_exit:
                # The exit conditions are met, so we need to close the position
                position["Side"] = "SELL" if position["Position_Type"] == "LONG" and position["Qty"] > 0 else "BUY"
                strategy_data["Order_Type"] = "STANDARD"
                close_order_queued = await self.api_trader.sendOrder(position, strategy_data, "CLOSE POSITION")

                # Mark this position for removal
                if close_order_queued:
                    positions_to_remove.append(position)
                else:
                    self.logger.warning(f"Close order was not queued for {symbol}; keeping position active.")

        # 🔍 **NEW: Remove closed positions from `self.positions_by_symbol`**
        should_unsubscribe = False

        async with self.lock:
            if positions_to_remove:
                current_positions = self.positions_by_symbol.get(symbol, [])
                self.positions_by_symbol[symbol] = [
                    pos for pos in current_positions if pos not in positions_to_remove
                ]
                # If no more positions remain, clean up and prepare to unsubscribe
                should_unsubscribe = not self.positions_by_symbol[symbol]
                if should_unsubscribe:
                    del self.positions_by_symbol[symbol]  # Clean up empty entries
                    self.logger.info(f"No remaining positions for {symbol}. Unsubscribing.")

        # ✅ Release the lock first, then unsubscribe
        if should_unsubscribe:
            await self.quote_manager.unsubscribe([symbol])

    def stop(self):
        self.quote_manager.stop_event.set()  # Signal the loop to stop
        self.position_updater.stop()

    @exception_handler
    async def checkOCOtriggers(self):
        """Checks OCO triggers (stop loss/take profit) to see if either one has filled.
        If so, closes the position in MongoDB accordingly.
        """
        batch_size = 100  # Number of positions to process per batch

        try:
            # Limit the fields and use cursor iteration to avoid loading everything into memory at once
            cursor = self.async_mongo.open_positions.find(
                {
                    "Trader": self.user["Name"],
                    "Account_ID": self.account_id,
                    "Order_Type": "OCO",
                    "Account_Position": "Live",
                },
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
                    "Side": 1,
                    "Position_Size": 1,
                    "Position_Type": 1,
                    "Account_Position": 1,
                    "childOrderStrategies": 1,
                    "Pre_Symbol": 1,
                    "Exp_Date": 1,
                    "Option_Type": 1,
                    "Needs_Reconciliation": 1,
                    "Reconciliation_Reason": 1,
                    "Reconciliation_Detected_At": 1,
                }
            )  # Only fetch necessary fields

            while True:
                positions = await cursor.to_list(length=batch_size)  # Fetch batch
                if not positions:  # Stop when there are no more documents
                    break

                results = await asyncio.gather(
                    *(self._process_position(position) for position in positions),
                    return_exceptions=True
                )
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        self.logger.error(f"Error processing position {positions[i]['Symbol']}: {result}")

            # Apply bulk updates at the end for efficiency
            try:
                await self._apply_bulk_updates()
            except Exception as e:
                self.logger.error(f"Error applying bulk updates: {e}")

        except Exception as e:
            self.logger.error(f"Failed to fetch open positions: {e}")

    async def _process_position(self, position):
        """Processes a single position and its child orders."""
        try:
            child_orders = position.get("childOrderStrategies")
            if not child_orders:
                self.logger.warning(f"No childOrderStrategies found for position {position['Symbol']}")
                return

            if isinstance(child_orders, dict):  # Ensure list format
                child_orders = [child_orders]

            status_changed = False
            processed_order_ids = set()

            for child_order in child_orders:
                try:
                    if "childOrderStrategies" in child_order:  # Handle nested OCO orders
                        for nested_order in child_order["childOrderStrategies"]:
                            order_id = nested_order.get("Order_ID")
                            if order_id in processed_order_ids:
                                continue
                            processed_order_ids.add(order_id)
                            status_changed |= await self._process_child_order(
                                nested_order, position
                            )
                    else:
                        order_id = child_order.get("Order_ID")
                        if order_id in processed_order_ids:
                            continue
                        processed_order_ids.add(order_id)
                        status_changed |= await self._process_child_order(
                            child_order, position
                        )
                except Exception as e:
                    self.logger.error(f"Error processing child order: {child_order} - {e}")

            if status_changed:
                filter_query = (
                    {"_id": position["_id"]}
                    if position.get("_id") is not None
                    else {
                        "Trader": self.user["Name"],
                        "Account_ID": self.account_id,
                        "Symbol": position["Symbol"],
                        "Strategy": position["Strategy"],
                    }
                )
                await self.bulk_updates_queue.put(
                    UpdateOne(
                        filter_query,
                        {
                            "$set": {
                                "childOrderStrategies": position[
                                    "childOrderStrategies"
                                ]
                            }
                        },
                        upsert=False,
                    )
                )

            await self._flag_terminal_oco_for_reconciliation(position)
        except Exception as e:
            self.logger.error(f"Error processing position: {position} - {e}")

    @staticmethod
    def _flatten_child_orders(child_orders):
        flattened = []
        for child_order in child_orders:
            nested_orders = child_order.get("childOrderStrategies")
            if nested_orders:
                flattened.extend(nested_orders)
            else:
                flattened.append(child_order)
        return flattened

    async def _flag_terminal_oco_for_reconciliation(self, position):
        if position.get("Needs_Reconciliation"):
            return False

        child_orders = position.get("childOrderStrategies") or []
        if isinstance(child_orders, dict):
            child_orders = [child_orders]

        flattened_orders = self._flatten_child_orders(child_orders)
        statuses = [order.get("Order_Status") for order in flattened_orders]
        terminal_without_fill = {"CANCELED", "REJECTED"}

        if not statuses or not all(status in terminal_without_fill for status in statuses):
            return False

        detected_at = getUTCDatetime()
        reason = "All OCO child orders are terminal without a fill"
        reconciliation_fields = {
            "Needs_Reconciliation": True,
            "Reconciliation_Reason": reason,
            "Reconciliation_Detected_At": detected_at,
        }

        if position.get("_id") is not None:
            position_filter = {"_id": position["_id"]}
        else:
            position_filter = {
                "Trader": self.user["Name"],
                "Account_ID": self.account_id,
                "Symbol": position["Symbol"],
                "Strategy": position["Strategy"],
            }
        position_filter["Needs_Reconciliation"] = {"$ne": True}

        result = await self.async_mongo.open_positions.update_one(
            position_filter,
            {"$set": reconciliation_fields},
        )
        if result.modified_count == 0:
            return False

        position.update(reconciliation_fields)
        message = (
            f"Live OCO position requires reconciliation: {position['Symbol']} / "
            f"{position['Strategy']} / account {modifiedAccountID(self.account_id)}. "
            f"{reason}."
        )
        self.logger.critical(message)
        await asyncio.to_thread(self.api_trader.push.send, message)
        return True

    async def _process_child_order(self, child_order, position):
        """Processes individual child orders and updates status."""
        order_id = child_order.get("Order_ID")
        if not order_id:
            self.logger.warning(f"Order ID missing in childOrder: {child_order}")
            return

        # Query the order status using the order_id
        try:
            spec_order = await self.tdameritrade.getSpecificOrderAsync(order_id)
            if not spec_order:
                self.logger.error(f"Failed to retrieve order details for Order_ID: {order_id}")
                return
        except Exception as e:
            self.logger.error(f"An error occurred while attempting to get specific order: {order_id}. Error: {e}")
            return

        new_status = spec_order.get("status")
        if not new_status:
            if order_id > 0:
                self.logger.warning(f"No status found for order_id: {order_id}")
            return False

        current_status = child_order.get("Order_Status")
        if new_status == current_status:
            self.logger.debug(
                f"Skipping update for Order_ID {order_id} "
                f"(Status unchanged: {new_status})"
            )
            return False

        # Handle FILLED status
        if new_status == "FILLED":
            position["Direction"] = "CLOSE POSITION"
            position["Side"] = child_order.get("Side", "SELL")

            await self.api_trader.pushOrder(position, spec_order)
            self.logger.info(f"Order {order_id} for {position['Symbol']} filled")
            return False

        # Handle REJECTED or CANCELED status
        elif new_status in ["CANCELED", "REJECTED"]:
            child_order["Order_Status"] = new_status
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
                await self.rejected_inserts_queue.put(other)
            else:
                await self.canceled_inserts_queue.put(other)

            self.logger.info(
                f"{new_status.upper()} ORDER for {position['Symbol']} - "
                f"TRADER: {self.user['Name']} - ACCOUNT ID: {modifiedAccountID(self.account_id)}"
            )
            return True
        else:
            self.logger.debug(f"Updating Order_ID {order_id} from {current_status} to {new_status}")
            child_order["Order_Status"] = new_status
            return True

    async def _apply_bulk_updates(self):
        """Processes bulk updates, rejected orders, and canceled orders from queues with error handling."""

        try:
            # Process bulk updates
            bulk_updates = []
            while not self.bulk_updates_queue.empty():
                bulk_updates.append(await self.bulk_updates_queue.get())

            if bulk_updates:
                try:
                    await self.async_mongo.open_positions.bulk_write(bulk_updates)
                except Exception as e:
                    self.logger.error(f"Failed to execute bulk_write: {e}")

            # Process rejected orders
            rejected_orders = []
            while not self.rejected_inserts_queue.empty():
                rejected_orders.append(await self.rejected_inserts_queue.get())

            if rejected_orders:
                try:
                    await self.async_mongo.rejected.insert_many(rejected_orders)
                except Exception as e:
                    self.logger.error(f"Failed to insert rejected orders: {e}")

            # Process canceled orders
            canceled_orders = []
            while not self.canceled_inserts_queue.empty():
                canceled_orders.append(await self.canceled_inserts_queue.get())

            if canceled_orders:
                try:
                    await self.async_mongo.canceled.insert_many(canceled_orders)
                except Exception as e:
                    self.logger.error(f"Failed to insert canceled orders: {e}")

        except Exception as e:
            self.logger.error(f"Unexpected error in _apply_bulk_updates: {e}")

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

        # Retrieve and return the newly created (or existing) strategy
        strategy_object = await self.async_mongo.strategies.find_one(
            {"Account_ID": self.account_id, "Strategy": strategy, "Asset_Type": asset_type}
        )
        return strategy_object
