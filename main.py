# imports
import asyncio
import logging
import os
import sys

from api_trader import ApiTrader
from api_trader.quote_manager_pool import QuoteManagerPool
from async_mongo import AsyncMongoDB
from tdameritrade import TDAmeritrade
from gmail import Gmail

from assets.pushsafer import PushNotification
from assets.exception_handler import exception_handler
from assets.helper_functions import modifiedAccountID, selectSleep
from assets.timeformatter import Formatter
from assets.multifilehandler import MultiFileHandler

class Main:

    def __init__(self):
        self.running = True
        self.stop_event = asyncio.Event()  # NEW: Added asyncio.Event for graceful stop signaling
       # Set the stop_signal_file path to the directory of the current script
        self.stop_signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp', 'stop_signal.txt')

         # Clean up leftover stop signal file from previous runs
        if os.path.isfile(self.stop_signal_file):
            try:
                os.remove(self.stop_signal_file)
                print(f"Removed leftover stop signal file: {self.stop_signal_file}")
            except Exception as e:
                print(f"Failed to remove stop signal file: {e}")
                
        self.traders = {}  # Initialize traders dictionary here
        self.tasks = set()


    async def connectAll(self):
        """ METHOD INITIALIZES LOGGER, MONGO, GMAIL, PAPERTRADER.
        """

        # INSTANTIATE LOGGER
        file_handler = MultiFileHandler(
            filename=f'{os.path.abspath(os.path.dirname(__file__))}/logs/error.log', mode='a')

        formatter = Formatter('%(asctime)s [%(levelname)s] %(message)s')

        file_handler.setFormatter(formatter)

        ch = logging.StreamHandler()

        ch.setLevel(level="INFO")

        ch.setFormatter(formatter)

        self.logger = logging.getLogger(__name__)

        self.logger.setLevel(level="INFO")

        self.logger.addHandler(file_handler)

        self.logger.addHandler(ch)

        # CONNECT TO MONGO
        self.async_mongo = AsyncMongoDB(self.logger)
        
        mongo_connected = await self.async_mongo.connect()

        # CONNECT TO GMAIL API
        self.gmail = Gmail(self.logger)

        gmail_connected = self.gmail.connect()

        self.loop = asyncio.get_event_loop()
        self.quote_manager_pool = QuoteManagerPool(loop=self.loop)

        if mongo_connected and gmail_connected:
            self.traders = {}
            self.accounts = []
            self.not_connected = []
            return True

        return False

    @exception_handler
    async def setupTraders(self):
        """ METHOD GETS ALL USERS ACCOUNTS FROM MONGO AND CREATES LIVE TRADER INSTANCES FOR THOSE ACCOUNTS.
            IF ACCOUNT INSTANCE ALREADY IN SELF.TRADERS DICT, THEN ACCOUNT INSTANCE WILL NOT BE CREATED AGAIN.
        """
        # Example test data
        # self.not_connected.append("1112")
        # self.not_connected.append("1113")

        tasks = []
        async for user in self.async_mongo.users.find({}):  # Iterate asynchronously over users
            for account_id in user["Accounts"].keys():
                if account_id not in self.traders and account_id not in self.not_connected:
                    tasks.append(self._setup_trader(user, account_id))
        await asyncio.gather(*tasks)


    async def _setup_trader(self, user, account_id):
        push_notification = PushNotification(user["deviceID"], self.logger)
        tdameritrade = TDAmeritrade(self.async_mongo, user, account_id, self.logger, push_notification)
        if await tdameritrade.initialConnect():
            self.traders[account_id] = ApiTrader(user, self.async_mongo, push_notification, self.logger, int(account_id), tdameritrade, self.quote_manager_pool)
        else:
            self.logger.warning(f"Failed to connect to account ({modifiedAccountID(account_id)}). Adding to not_connected list.")
            self.not_connected.append(account_id)

    @exception_handler
    async def run(self):
        """ Runs the two methods above and then runs live trader method for each instance. """
        if not self.traders:  # Avoid re-instantiating traders
            await self.setupTraders()

        # Now get emails asynchronously
        # !!!!!!!!!!!!!!!!!!!!
        # trade_data = []
        trade_data = await self.gmail.getEmails()  # This now works asynchronously

        if trade_data is not None:
            # ✅ Remove tasks that are already done
            self.tasks = {task for task in self.tasks if not task.done()}

            # ✅ Prevent new tasks from running if old ones are still pending
            if any(not task.done() for task in self.tasks):
                self.logger.warning("Previous tasks are still running! Skipping new task creation.")
            else:
                new_tasks = {asyncio.create_task(trader.runTrader(trade_data)) for trader in self.traders.values()}
                self.tasks.update(new_tasks)

            self.logger.debug(f"Waiting for {len(self.tasks)} trader tasks to complete...")

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*self.tasks, return_exceptions=True),
                    timeout=30
                )

                # ✅ Explicitly remove completed tasks
                completed_tasks = {task for task, result in zip(self.tasks, results) if task.done()}
                self.tasks.difference_update(completed_tasks)

            except asyncio.TimeoutError:
                self.logger.error("Timeout while waiting for trader tasks.")

                # ✅ Cancel ONLY "trader" tasks that are still running
                running_tasks = {task for task in self.tasks if not task.done()}
                
                if running_tasks:
                    self.logger.warning(f"Cancelling {len(running_tasks)} stuck trader tasks...")
                    for task in running_tasks:
                        task.cancel()

                    # ✅ Give them a short grace period to cancel cleanly
                    try:
                        await asyncio.wait(running_tasks, timeout=5)
                    except asyncio.TimeoutError:
                        self.logger.error("Some trader tasks did not cancel in time.")

                    # ✅ Remove cancelled tasks from self.tasks
                    self.tasks.difference_update(running_tasks)

            finally:
                self.logger.debug(f"Finished processing trader tasks. {len(self.tasks)} remaining.")

        else:
            self.logger.error("Failed to retrieve trade data from emails.")

    async def watch_stop_signal(self):
        """Monitor the stop signal file and trigger stop_event."""
        while self.running:
            if os.path.isfile(self.stop_signal_file):
                self.logger.info("Stop signal detected. Stopping...")
                await self.stop()
                return
            await asyncio.sleep(0.1)  # Check every 0.1 seconds

    async def stop(self):
        """Gracefully stop all tasks and shutdown."""
        self.logger.info("Initiating graceful shutdown...")
        self.running = False
        self.stop_event.set()  # Notify all tasks to stop

        try:
            # Step 1: Stop all traders
            stop_tasks = [
                asyncio.wait_for(api_trader.stop_trader(), timeout=5)
                for api_trader in self.traders.values()
            ]
            results = await asyncio.gather(*stop_tasks, return_exceptions=True)
            for result, trader in zip(results, self.traders.values()):
                if isinstance(result, asyncio.TimeoutError):
                    self.logger.warning(f"Trader {trader} took too long to stop.")

            # Step 2: Cancel remaining tasks
            self.logger.info("Cancelling remaining tasks...")
            remaining_tasks = [
                task for task in asyncio.all_tasks() if task is not asyncio.current_task()
            ]
            for task in remaining_tasks:
                task.cancel()

            # Wait for tasks to finish, explicitly ignoring CancelledError
            await asyncio.gather(*remaining_tasks, return_exceptions=True)

        except asyncio.CancelledError:
            self.logger.info("Task cancellation acknowledged during shutdown.")
        except Exception as e:
            self.logger.error(f"Error while cancelling tasks: {e}")
        finally:
            # Close MongoDB connection
            try:
                await self.async_mongo.close()
                self.logger.info("Closed AsyncMongoDB connection.")
            except Exception as close_error:
                self.logger.error(f"Error while closing AsyncMongoDB: {close_error}")

            # Remove the stop signal file
            try:
                if os.path.isfile(self.stop_signal_file):
                    os.remove(self.stop_signal_file)
                    self.logger.info(f"Removed stop signal file: {self.stop_signal_file}")
            except Exception as file_error:
                self.logger.error(f"Error while removing stop signal file: {file_error}")

            self.logger.info("Shutdown process completed.")

async def main_async():
    """Main async function to execute logic."""
    main = Main()

    connected = await main.connectAll()

    if connected:
        try:
            # Run the watcher for the stop signal in the background
            asyncio.create_task(main.watch_stop_signal())

            while not main.stop_event.is_set():
                await main.run()  # Execute main logic
                await asyncio.sleep(selectSleep())
        except asyncio.CancelledError:
            main.logger.info("Main loop canceled.")
        finally:
            main.logger.info("Exited loop. Cleaning up...")
    else:
        main.logger.error("Failed to connect. Exiting...")

    sys.exit(0)

if __name__ == "__main__":
    # Call the main async function within the event loop
    asyncio.run(main_async())
