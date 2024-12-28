# imports
import asyncio
import time
import logging
import os
import sys

from api_trader import ApiTrader
from api_trader.quote_manager_pool import QuoteManagerPool
from tdameritrade import TDAmeritrade
from gmail import Gmail
from mongo import MongoDB

from assets.pushsafer import PushNotification
from assets.exception_handler import exception_handler
from assets.helper_functions import selectSleep
from assets.timeformatter import Formatter
from assets.multifilehandler import MultiFileHandler

class Main:

    def __init__(self):
        self.running = True
       # Set the stop_signal_file path to the directory of the current script
        self.stop_signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp', 'stop_signal.txt')


    def connectAll(self):
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
        self.mongo = MongoDB(self.logger)

        mongo_connected = self.mongo.connect()

        # CONNECT TO GMAIL API
        self.gmail = Gmail(self.logger)

        gmail_connected = self.gmail.connect()

        self.quote_manager_pool = QuoteManagerPool()

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
        # GET ALL USERS ACCOUNTS
        users = self.mongo.users.find({})

        for user in users:
            try:
                for account_id in user["Accounts"].keys():
                    if account_id not in self.traders and account_id not in self.not_connected:
                        push_notification = PushNotification(
                            user["deviceID"], self.logger)

                        tdameritrade = TDAmeritrade(
                            self.mongo, user, account_id, self.logger, push_notification)

                        connected = await tdameritrade.initialConnect()

                        if connected:
                            obj = ApiTrader(user, self.mongo, push_notification, self.logger, int(account_id), tdameritrade, self.quote_manager_pool)
                            self.traders[account_id] = obj
                            await asyncio.sleep(0.1)
                        else:
                            self.not_connected.append(account_id)

                    self.accounts.append(account_id)

            except Exception as e:
                logging.error(e)

    @exception_handler
    async def run(self):
        """ Runs the two methods above and then runs live trader method for each instance. """
        await self.setupTraders()  # Ensure setupTraders is awaited before continuing

        # Now get emails asynchronously
        # !!!!!!!!!!!!!!!!!!!!
        # trade_data = []
        trade_data = await self.gmail.getEmails()  # This now works asynchronously

        if trade_data is not None:
            for api_trader in self.traders.values():
                await api_trader.runTrader(trade_data)  # Each trader's runTrader is awaited
        else:
            self.logger.error("Failed to retrieve trade data from emails.")


    async def stop(self):
        """ Checks for the stop signal file to stop the running loop gracefully. """
        if os.path.isfile(self.stop_signal_file):
            self.logger.info("Stopping...")
            self.running = False

            for api_trader in self.traders.values():
                await api_trader.stop_trader()

            os.remove(self.stop_signal_file)  # Remove stop signal file
        else:
            await asyncio.sleep(selectSleep())


async def main_async():
    """Main async function to execute logic."""
    main = Main()

    connected = main.connectAll()

    if connected:
        # Run the main async logic in an event loop
        while main.running:
            await main.run()  # Await the run method to ensure setupTraders and runTrader are executed properly
            await main.stop()  # Check if we need to stop the loop

        main.logger.info("Exited loop. Cleaning up...")
    else:
        main.logger.error("Failed to connect. Exiting...")

    sys.exit(0)

if __name__ == "__main__":
    # Call the main async function within the event loop
    asyncio.run(main_async())
