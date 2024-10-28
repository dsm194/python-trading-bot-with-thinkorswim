# imports
import asyncio
from datetime import datetime, timedelta
import httpx
import websockets
from assets.helper_functions import getUTCDatetime, modifiedAccountID
from assets.exception_handler import exception_handler

from schwab.auth import client_from_manual_flow
from schwab.auth import client_from_token_file
from schwab.client.base import BaseClient as schwabBaseClient
from schwab.utils import Utils
from schwab.streaming import StreamClient

import os
from dotenv import load_dotenv

load_dotenv(dotenv_path="config.env")

API_KEY = os.getenv("API_KEY")
APP_SECRET = os.getenv("APP_SECRET")
CALLBACK_URL = os.getenv("CALLBACK_URL")

class TDAmeritrade:

    def __init__(self, mongo, user, account_id, logger, push_notification):

        self.user = user

        self.account_id = account_id

        self.logger = logger

        self.users = mongo.users

        self.push_notification = push_notification

        self.no_go_token_sent = False

        self.client_id = self.user["ClientID"]

        self.header = {}

        self.terminate = False

        self.invalid_count = 0

        self.client = {}

        self.stream_client = {}

        self.client_lock = asyncio.Lock()

    @exception_handler
    def initialConnect(self):

        self.logger.info(
            f"CONNECTING {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

        isValid = self.checkTokenValidity()

        if isValid:

            self.logger.info(
                f"CONNECTED {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

            return True

        else:

            self.logger.error(
                f"FAILED TO CONNECT {self.user['Name']} TO TDAMERITRADE ({self.account_id})", extra={'log': False})

            return False

    @exception_handler
    def checkTokenValidity(self):
        """ METHOD CHECKS IF ACCESS TOKEN IS VALID

        Returns:
            [boolean]: TRUE IF SUCCESSFUL, FALSE IF ERROR
        """

        # GET USER DATA
        user = self.users.find_one({"Name": self.user["Name"]})
        token_path = user["Accounts"][self.account_id]['token_path']
        if os.path.isfile(token_path):
            c = client_from_token_file(token_path, API_KEY, APP_SECRET)
        else:
            self.logger.warning('Failed to find token file \'%s\'', token_path)
            c = client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path)

        if c:
            self.client = c
            self.stream_client = StreamClient(client=self.client)

            # ADD NEW TOKEN DATA TO USER DATA IN DB
            self.users.update_one({"Name": self.user["Name"]}, {
                "$set": {f"{self.account_id}.refresh_exp_date": (datetime.now().replace(
                    microsecond=0) + timedelta(days=90)).strftime("%Y-%m-%d")}})

        else:

            return False

        return True

    def getAccount(self):
        """ METHOD GET ACCOUNT DATA

        Returns:
            [json]: ACCOUNT DATA
        """

        # fields = up.quote("positions,orders")

        # url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}?fields={fields}"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                return self.client.get_account(account_hash).json()
            else:
                return
        else:
            return

    def placeTDAOrder(self, data):
        """Method places order and retrieves full order details if necessary.

        Args:
            data (dict): Order data.

        Returns:
            dict: Full order details including order IDs or None if failed.
        """

        is_valid = self.checkTokenValidity()

        if not is_valid:
            return None

        resp = self.client.get_account_numbers()
        if resp.status_code == httpx.codes.OK:
            account_hash = resp.json()[0]['hashValue']
            # Place the order
            resp = self.client.place_order(account_hash, data)

        if resp.status_code not in [200, 201]:
            return resp  # Return the raw response to handle errors

        # Extract the main order ID
        main_order_id = Utils(client=self.client, account_hash=account_hash).extract_order_id(resp)

        if not main_order_id:
            return {"Order_ID": None}  # Return basic info if no order ID is available

        detailed_resp = self.getSpecificOrder(main_order_id)

        if detailed_resp:
            # Rename 'orderId' to 'Order_ID' in the detailed response
            detailed_resp = self.rename_order_ids(detailed_resp)
            return detailed_resp  # Return the full order details as a dictionary
        else:
            return {"Order_ID": main_order_id}  # Return basic info if full details are unavailable


    def rename_order_ids(self, order_data):
        """Recursively rename 'orderId' to 'Order_ID' in the order structure.

        Args:
            order_data (dict): The order data containing potential 'orderId' fields.

        Returns:
            dict: The updated order data with 'Order_ID' fields.
        """
        if isinstance(order_data, dict):
            if 'orderId' in order_data:
                order_data['Order_ID'] = order_data.pop('orderId')
            if 'childOrderStrategies' in order_data:
                for child_order in order_data['childOrderStrategies']:
                    self.rename_order_ids(child_order)
        elif isinstance(order_data, list):
            for item in order_data:
                self.rename_order_ids(item)
        
        return order_data


    def getBuyingPower(self):
        """ METHOD GETS BUYING POWER

        Returns:
            [json]: BUYING POWER
        """

        account = self.getAccount()

        # buying_power = account["securitiesAccount"]["initialBalances"]["cashAvailableForTrading"]
        buying_power = account["securitiesAccount"]["initialBalances"]["cashBalance"]

        return float(buying_power)

    def getQuote(self, symbol):
        """ METHOD GETS MOST RECENT QUOTE FOR STOCK

        Args:
            symbol ([str]): STOCK SYMBOL

        Returns:
            [json]: STOCK QUOTE
        """

        # url = f"https://api.tdameritrade.com/v1/marketdata/{symbol}/quotes"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if symbol == None or symbol == '':
            self.logger.warning('Symbol in getQuote was empty \'%s\'', symbol)
            isValid = False

        if isValid:
            try:
                if "/" in symbol:
                    response = self.client.get_quotes(symbol)
                else:
                    response = self.client.get_quote(symbol)

                # Check if the response status is not 200
                if response.status_code != 200:
                    self.logger.error(f"Failed to retrieve quote for symbol: {symbol}. HTTP Status: {response.status_code}")
                    return None
                
                # Parse the JSON only if it's a successful response
                return response.json()
                
            except Exception as e:
                self.logger.error(f"An error occurred while retrieving the quote for symbol: {symbol}. Error: {e}")
                return None
        else:
            return

    def getQuotes(self, symbols):
        """ METHOD GETS STOCK QUOTES FOR MULTIPLE STOCK IN ONE CALL.

        Args:
            symbols ([list]): LIST OF SYMBOLS

        Returns:
            [json]: ALL SYMBOLS STOCK DATA
        """

        # join_ = ",".join(symbols)

        # seperated_values = up.quote(join_)

        # url = f"https://api.tdameritrade.com/v1/marketdata/quotes?symbol={seperated_values}"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if isValid:
            try:
                response = self.client.get_quotes(symbols)

                # Check if the response status is not 200
                if response.status_code != 200:
                    self.logger.error(f"Failed to retrieve quote for symbols: {symbols}. HTTP Status: {response.status_code}")
                    return None
                
                # Parse the JSON only if it's a successful response
                return response.json()
                
            except Exception as e:
                self.logger.error(f"An error occurred while retrieving the quote for symbols: {symbols}. Error: {e}")
                return None
        else:
            return
    
    @exception_handler
    async def start_stream(self, symbols, quote_handler, max_retries=5):
        retries = 0
        while retries < max_retries:
            try:
                # Step 1: Login
                await self._safe_connect_to_streaming()

                # Step 2: Separate symbols by asset type
                equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
                option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]

                # Subscribe to equity symbols
                if equity_symbols:
                    self.stream_client.add_level_one_equity_handler(quote_handler)
                    await self.stream_client.level_one_equity_add(
                        symbols=equity_symbols,
                        fields=[
                            StreamClient.LevelOneEquityFields.SYMBOL,
                            StreamClient.LevelOneEquityFields.BID_PRICE,
                            StreamClient.LevelOneEquityFields.ASK_PRICE,
                            StreamClient.LevelOneEquityFields.LAST_PRICE,
                            StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE
                        ]
                    )

                # Subscribe to option symbols
                if option_symbols:
                    self.stream_client.add_level_one_option_handler(quote_handler)
                    await self.stream_client.level_one_option_add(
                        symbols=option_symbols,
                        fields=[
                            StreamClient.LevelOneOptionFields.SYMBOL,
                            StreamClient.LevelOneOptionFields.BID_PRICE,
                            StreamClient.LevelOneOptionFields.ASK_PRICE,
                            StreamClient.LevelOneOptionFields.LAST_PRICE,
                        ]
                    )

                # Step 3: Receive stream in a loop
                while True:
                    await self.receive_stream(quote_handler)

            except (websockets.exceptions.ConnectionClosedOK, websockets.ConnectionClosedError) as e:
                retries += 1
                self.logger.warning(f"Connection closed: {e}. Reconnecting attempt {retries}/{max_retries}")
                await asyncio.sleep(2 ** retries)  # Exponential backoff
            except ValueError as e:
                self.logger.warning(f"Value error encountered: {e}. Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                break

        if retries == max_retries:
            self.logger.error("Max retries reached. Failed to reconnect.")

    async def receive_stream(self, quote_handler):
        message = await self.stream_client.handle_message()
        if message:
            quote_handler(message)


    @exception_handler
    async def update_subscription(self, symbols):
        # Separate symbols by asset type
        equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
        option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]

        # Subscribe to equity symbols if any
        if equity_symbols:
            await self.stream_client.level_one_equity_add(
                symbols=equity_symbols,
                fields=[
                    StreamClient.LevelOneEquityFields.SYMBOL,
                    StreamClient.LevelOneEquityFields.BID_PRICE,
                    StreamClient.LevelOneEquityFields.ASK_PRICE,
                    StreamClient.LevelOneEquityFields.LAST_PRICE,
                    StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE
                ]
            )

        # Subscribe to option symbols if any
        if option_symbols:
            await self.stream_client.level_one_option_add(
                symbols=option_symbols,
                fields=[
                    StreamClient.LevelOneOptionFields.SYMBOL,
                    StreamClient.LevelOneOptionFields.BID_PRICE,
                    StreamClient.LevelOneOptionFields.ASK_PRICE,
                    StreamClient.LevelOneOptionFields.LAST_PRICE,
                ]
            )

    async def _safe_connect_to_streaming(self):
        try:
            # async with self.client_lock:
            await self.connect_to_streaming()  # Lock only during connection attempts
        except Exception as e:
            self.logger.error(f"Failed to connect to streaming: {e}")

    async def _safe_disconnect_streaming(self):
        try:
            async with self.client_lock:
                await self.disconnect_streaming()  # Lock only during connection attempts
        except Exception as e:
            self.logger.error(f"Failed to disconnect to streaming: {e}")

    async def connect_to_streaming(self):
        try:
            self.logger.info("Attempting to log in to the streaming service.")
            # await asyncio.wait_for(self.stream_client.login(), timeout=5)
            websocket_connect_args = {
                "ping_interval": 5,
            }
            await self.stream_client.login(websocket_connect_args)
            self.logger.info("Successfully logged in to the streaming service.")
        except asyncio.TimeoutError:
            self.logger.error("Login timed out.")
            raise  # Rethrow or handle appropriately
        except Exception as e:
            self.logger.error(f"Failed to connect to streaming: {e}")
            raise


    async def disconnect_streaming(self):
        await self.stream_client.logout()


    def getSpecificOrder(self, id):
        """ METHOD GETS A SPECIFIC ORDER INFO

        Args:
            id ([int]): ORDER ID FOR ORDER

        Returns:
            [json]: ORDER DATA
        """

        # Try to convert the order ID to an integer for the comparison
        try:
            numeric_id = int(id)
        except (ValueError, TypeError):
            numeric_id = None

        # If the order ID is an integer and less than 0, assume it's a paper trade
        if numeric_id is not None and numeric_id < 0:
            # self.logger.info(f"Order ID {id} is a paper trade, no need to check status.")
            return {'message': 'Order not found'}


        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            #resp.status_code == 404 breaks calling code
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
            
                try:
                    response = self.client.get_order(id, account_hash)

                    # Check if the response status is not 200
                    if response.status_code != 200:
                        self.logger.warning(f"Failed to get specific order: {id}. HTTP Status: {response.status_code}")
                        # return None
                    
                    # Parse the JSON only if it's a successful response
                    return self.rename_order_ids(response.json())
                    
                except Exception as e:
                    self.logger.error(f"An error occurred while attempting to get specific order: {id}. Error: {e}")
                    return
            else:
                return
        else:
            return

    def cancelOrder(self, id):
        """ METHOD CANCELS ORDER

        Args:
            id ([int]): ORDER ID FOR ORDER

        Returns:
            [json]: RESPONSE. LOOKING FOR STATUS CODE 200,201
        """

        url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}/orders/{id}"

        # return self.sendRequest(url, method="DELETE")

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
            
                try:
                    response = self.client.cancel_order(id, account_hash)

                    # Check if the response status is not 200
                    if response.status_code != 200:
                        self.logger.error(f"Failed to cancel order: {id}. HTTP Status: {response.status_code}")
                        return None
                    
                    # Parse the JSON only if it's a successful response
                    return response.json()
                    
                except Exception as e:
                    self.logger.error(f"An error occurred while attempting to cancel order: {id}. Error: {e}")
                    return None
            else:
                return
        else:
            return
        
    def getMarketHours(self, markets=None, *, date=None):
        isValid = self.checkTokenValidity()

        if isValid:
            try:
                # If no market is provided, get all the enum values as a list
                if markets is None:
                    markets = [market for market in schwabBaseClient.MarketHours.Market]

                # Use the current UTC datetime if no date is provided
                if date is None:
                    date = getUTCDatetime()

                response = self.client.get_market_hours(markets=markets, date=date)

                # Check if the response status is not 200
                if response.status_code != 200:
                    self.logger.error(f"Failed to retrieve market hours for markets: {markets}. HTTP Status: {response.status_code}")
                    return None
                
                # Parse the JSON only if it's a successful response
                return response.json()
                
            except Exception as e:
                self.logger.error(f"An error occurred while retrieving market hours for markets: {markets}. Error: {e}")
                return None
        else:
            return
