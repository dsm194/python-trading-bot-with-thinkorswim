# imports
import asyncio
from datetime import datetime, timedelta
import time
import traceback
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

        self.async_client = {}

        self.stream_client = {}

        self.lock = asyncio.Lock()

        self.registered_handlers = {"equity": set(), "option": set()}

        self.loop = asyncio.get_running_loop()

    @exception_handler
    async def initialConnect(self):

        self.logger.info(
            f"CONNECTING {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

        isValid = await self.checkTokenValidityAsync()

        if isValid:

            self.logger.info(
                f"CONNECTED {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

            return True

        else:

            self.logger.error(
                f"FAILED TO CONNECT {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

            return False

    @exception_handler
    async def checkTokenValidityAsync(self):
        """
        Ensures the authentication token is valid.

        Returns:
            bool: True if the token is valid or successfully refreshed, False otherwise.
        """
        # self.logger.debug(f"Current event loop in checkTokenValidityAsync: {asyncio.get_event_loop()} ({modifiedAccountID(self.account_id)})")

        # Check if client is initialized and token expiration is valid
        if self.async_client:
            current_time = time.time()
            expires_at = self.async_client.token_metadata.token.get("expires_at", 0)

            # Calculate time remaining on the token
            time_remaining = expires_at - current_time

            if time_remaining > 0:
                # self.logger.info(f"Token is valid. Time remaining: {time_remaining} seconds.")
                return True
            else:
                self.logger.warning("Token has expired or is about to expire.")

        # Retrieve user data and refresh or generate a new token
        user = self.users.find_one({"Name": self.user["Name"]})
        token_path = user["Accounts"][self.account_id]["token_path"]

        if os.path.isfile(token_path):
            self.async_client = client_from_token_file(token_path, API_KEY, APP_SECRET, asyncio=True)
        else:
            self.logger.warning("Failed to find token file '%s'", token_path)
            self.async_client = client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path, asyncio=True)

        if not self.async_client:
            self.logger.error(f"Failed to initialize client. ({modifiedAccountID(self.account_id)})")
            return False

        # Update token expiration and async/stream clients
        tokenSeconds = self.async_client.token_metadata.token.get("expires_in", 3600)
        self.token_expiration = datetime.now() + timedelta(seconds=tokenSeconds)
        self.stream_client = self.stream_client or StreamClient(client=self.async_client)

        # ADD NEW TOKEN DATA TO USER DATA IN DB
        self.users.update_one({"Name": self.user["Name"]}, {
            "$set": {f"{self.account_id}.refresh_exp_date": (self.token_expiration).strftime("%Y-%m-%d")}})

        self.logger.info("Token refreshed successfully.")
        return True

    def refresh_token(self, token_path):
        """
        Refreshes the token using the file or manual flow.

        Args:
            token_path (str): Path to the token file.

        Returns:
            client: The refreshed client object.
        """
        if os.path.isfile(token_path):
            return client_from_token_file(token_path, API_KEY, APP_SECRET)
        else:
            self.logger.warning("Token file missing: '%s'. Initiating manual flow.", token_path)
            return client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path)

    async def getAccount(self):
        """ METHOD GET ACCOUNT DATA

        Returns:
            [json]: ACCOUNT DATA
        """

        # fields = up.quote("positions,orders")

        # url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}?fields={fields}"

        # return self.sendRequest(url)

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            resp = self.async_client.get_account_numbers()
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
                return self.async_client.get_account(account_hash).json()
            else:
                return
        else:
            return

    async def placeTDAOrderAsync(self, data):
        """Method places order and retrieves full order details if necessary.

        Args:
            data (dict): Order data.

        Returns:
            dict: Full order details including order IDs or None if failed.
        """

        is_valid = await self.checkTokenValidityAsync()

        if not is_valid:
            return None

        resp = await self.async_client.get_account_numbers()
        if resp.status_code == httpx.codes.OK:
            account_hash = resp.json()[0]['hashValue']
            # Place the order
            resp = await self.async_client.place_order(account_hash, data)

        if resp.status_code not in [200, 201]:
            return resp  # Return the raw response to handle errors

        # Extract the main order ID
        # TODO: why do we have to pass client here?
        main_order_id = Utils(client=self.async_client, account_hash=account_hash).extract_order_id(resp)

        if not main_order_id:
            return {"Order_ID": None}  # Return basic info if no order ID is available

        detailed_resp = await self.getSpecificOrderAsync(main_order_id)

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


    async def getBuyingPower(self):
        """ METHOD GETS BUYING POWER

        Returns:
            [json]: BUYING POWER
        """

        account = self.getAccount()

        # buying_power = account["securitiesAccount"]["initialBalances"]["cashAvailableForTrading"]
        buying_power = account["securitiesAccount"]["initialBalances"]["cashBalance"]

        return float(buying_power)

    async def getQuoteAsync(self, symbol):
        """
        Retrieves the most recent quote for a stock asynchronously.

        Args:
            symbol (str): Stock symbol.

        Returns:
            dict: Stock quote in JSON format, or None if an error occurs.
        """
        if not symbol:
            self.logger.warning("Symbol in getQuoteAsync was empty '%s'", symbol)
            return None

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            try:
                if "/" in symbol:
                    response = await self.async_client.get_quotes(symbol)
                else:
                    # self.logger.debug(f"Current event loop in getQuoteAsync: {asyncio.get_event_loop()} ({modifiedAccountID(self.account_id)})")
                    # response = await self.async_client.get_quote(symbol)
                    self.logger.debug(f"Calling get_quote for symbol: {symbol} ({modifiedAccountID(self.account_id)})")
                    try:
                        response = await self.async_client.get_quote(symbol)
                    except Exception as e:
                        self.logger.error(f"Error in get_quote: {e} ({modifiedAccountID(self.account_id)})")
                        raise


                # Check if the response status is not 200
                if response.status_code != 200:
                    self.logger.error(f"Failed to retrieve quote for symbol: {symbol}. HTTP Status: {response.status_code} ({modifiedAccountID(self.account_id)})")
                    return None

                # Parse the JSON only if it's a successful response
                return response.json()

            except Exception as e:
                self.logger.error(f"An error occurred while retrieving the quote for symbol: {symbol}. Error: {e} ({modifiedAccountID(self.account_id)})")
                return None
        else:
            return None

    @exception_handler
    async def start_stream(self, symbols, quote_handler, max_retries=5, stop_event=None):
        retries = 0
        last_handler_activity = datetime.now()

        async def call_quote_handler(*args, **kwargs):
            """Handle quote callback logic."""
            nonlocal last_handler_activity
            last_handler_activity = datetime.now()
            self.logger.debug(f"Activity updated at {last_handler_activity} ({modifiedAccountID(self.account_id)})")
            try:
                if asyncio.iscoroutinefunction(quote_handler):
                    loop = asyncio.get_running_loop()  # Ensure running loop
                    await asyncio.wrap_future(
                        asyncio.run_coroutine_threadsafe(quote_handler(*args, **kwargs), loop)
                    )
                else:
                    quote_handler(*args, **kwargs)  # Sync handler
            except Exception as e:
                self.logger.error(f"Error in quote_handler: {e} ({modifiedAccountID(self.account_id)})")

        async def reconnect():
            """Reconnect logic with exponential backoff."""
            nonlocal retries
            retries += 1
            if retries > max_retries:
                self.logger.error("Max retries reached. Stopping reconnection attempts.")
                return False  # Signal to stop retries
            sleep_time = min(2 ** retries, 60)
            self.logger.warning(f"Reconnecting in {sleep_time}s (retry {retries}/{max_retries})...")
            await asyncio.sleep(sleep_time)
            return True  # Continue retries

        while not (stop_event and stop_event.is_set()):
            try:
                # Step 1: Establish connection
                await self._safe_connect_to_streaming()
                retries = 0  # Reset retries on successful connection

                # Step 2: Prepare symbols and register handlers
                equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
                option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]

                async with self.lock:
                    if equity_symbols:
                        if quote_handler not in self.registered_handlers["equity"]:
                            self.stream_client.add_level_one_equity_handler(call_quote_handler)
                            self.registered_handlers["equity"].add(quote_handler)
                        await self.stream_client.level_one_equity_add(equity_symbols, fields=[
                            StreamClient.LevelOneEquityFields.SYMBOL,
                            StreamClient.LevelOneEquityFields.BID_PRICE,
                            StreamClient.LevelOneEquityFields.ASK_PRICE,
                            StreamClient.LevelOneEquityFields.LAST_PRICE,
                            StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE
                        ])

                    if option_symbols:
                        if quote_handler not in self.registered_handlers["option"]:
                            self.stream_client.add_level_one_option_handler(call_quote_handler)
                            self.registered_handlers["option"].add(quote_handler)
                        await self.stream_client.level_one_option_add(option_symbols, fields=[
                            StreamClient.LevelOneOptionFields.SYMBOL,
                            StreamClient.LevelOneOptionFields.BID_PRICE,
                            StreamClient.LevelOneOptionFields.ASK_PRICE,
                            StreamClient.LevelOneOptionFields.LAST_PRICE,
                        ])

                # Step 3: Stream messages
                while not (stop_event and stop_event.is_set()):
                    self.logger.debug(f"Waiting for messages... ({modifiedAccountID(self.account_id)})")
                    try:
                        await asyncio.wait_for(self.stream_client.handle_message(), timeout=15)
                    except asyncio.TimeoutError:
                        self.logger.warning(f"Timeout waiting for messages. Checking activity... ({modifiedAccountID(self.account_id)})")
                    except Exception as e:
                        self.logger.error(f"Error during message handling: {e} ({modifiedAccountID(self.account_id)})")
                        break

                    # Check for handler inactivity
                    if datetime.now() - last_handler_activity > timedelta(minutes=5):   #TODO - change back to 5 mins, or increase to 10??
                        self.logger.warning(f"Handler timeout detected. Last activity: {last_handler_activity} ({modifiedAccountID(self.account_id)})")
                        last_handler_activity = datetime.now()
                        break

            except websockets.ConnectionClosedError as e:
                self.logger.warning(f"Connection closed: {e} ({modifiedAccountID(self.account_id)})")
                if not await reconnect():
                    break
            except Exception as e:
                self.logger.error(f"Unexpected error: {e} ({modifiedAccountID(self.account_id)})")
                if not await reconnect():
                    break

            finally:
                await self._safe_disconnect_streaming()
                self.logger.debug(f"Disconnected. Cleaning up handlers... ({modifiedAccountID(self.account_id)})")
                await self._clean_up_handler(quote_handler)
                self.stream_client = StreamClient(client=self.async_client)

        self.logger.info("Streaming stopped.")


    async def _clean_up_handler(self, quote_handler):
        async with self.lock:
            self.logger.debug(f"Cleaning up handler: {quote_handler} ({modifiedAccountID(self.account_id)})")
            self.logger.debug(f"Before cleanup: {self.registered_handlers} ({modifiedAccountID(self.account_id)})")
            self.registered_handlers["equity"].discard(quote_handler)
            self.registered_handlers["option"].discard(quote_handler)
            self.logger.debug(f"After cleanup: {self.registered_handlers} ({modifiedAccountID(self.account_id)})")
            self.logger.info(f"Handler {quote_handler} removed from registered_handlers. ({modifiedAccountID(self.account_id)})")


    @exception_handler
    async def update_subscription(self, symbols):
        self.logger.debug(f"Updating subscription with symbols: {symbols}")
        
        equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
        option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]
        
        if equity_symbols:
            self.logger.debug(f"Subscribing to equity symbols: {equity_symbols}")
            await self.stream_client.level_one_equity_add(
                symbols=equity_symbols,
                fields=[
                    StreamClient.LevelOneEquityFields.SYMBOL,
                    StreamClient.LevelOneEquityFields.BID_PRICE,
                    StreamClient.LevelOneEquityFields.ASK_PRICE,
                    StreamClient.LevelOneEquityFields.LAST_PRICE,
                    StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE,
                ],
            )
            self.logger.debug(f"Successfully subscribed to equity symbols: {equity_symbols}")
        
        if option_symbols:
            self.logger.debug(f"Subscribing to option symbols: {option_symbols}")
            await self.stream_client.level_one_option_add(
                symbols=option_symbols,
                fields=[
                    StreamClient.LevelOneOptionFields.SYMBOL,
                    StreamClient.LevelOneOptionFields.BID_PRICE,
                    StreamClient.LevelOneOptionFields.ASK_PRICE,
                    StreamClient.LevelOneOptionFields.LAST_PRICE,
                ],
            )
            self.logger.debug(f"Successfully subscribed to option symbols: {option_symbols}")


    async def _safe_connect_to_streaming(self, retries=3, delay=5):
        for attempt in range(retries):
            try:
                await self.connect_to_streaming()
                return
            except Exception as e:
                self.logger.error(f"Reconnect attempt {attempt + 1} failed: {e} ({modifiedAccountID(self.account_id)})")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError("Failed to reconnect after retries. ({modifiedAccountID(self.account_id)})")


    async def _safe_disconnect_streaming(self):
        try:
            # async with self.client_lock:
            await self.disconnect_streaming()  # Lock only during connection attempts
        except Exception as e:
            self.logger.error(f"Failed to disconnect to streaming: {e} ({modifiedAccountID(self.account_id)})")

    async def connect_to_streaming(self):
        try:
            self.logger.debug(f"Attempting to log in to the streaming service. ({modifiedAccountID(self.account_id)})")
            # await self.stream_client.login({"ping_interval": 13, "ping_timeout":30, "max_queue":10000})
            await self.stream_client.login()
            self.logger.debug(f"Successfully logged in to the streaming service. ({modifiedAccountID(self.account_id)})")
        except asyncio.TimeoutError:
            self.logger.error(f"Login timed out. ({modifiedAccountID(self.account_id)})")
            raise
        except Exception as e:
            self.logger.error(f"Failed to connect to streaming: {e} ({modifiedAccountID(self.account_id)})")
            raise

    async def disconnect_streaming(self):
        try:
            self.logger.debug(f"Attempting to log out of the streaming service. ({modifiedAccountID(self.account_id)})")
            await self.stream_client.logout()
            self.logger.debug(f"Successfully logged out of the streaming service. ({modifiedAccountID(self.account_id)})")
        except Exception as e:
            self.logger.warning(f"Suppressed exception during logout: {e}")
        
    async def getSpecificOrderAsync(self, id):
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
            return {'message': 'Order not found'}

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            resp = await self.async_client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                account_hash = resp.json()[0]['hashValue']
            
                try:
                    response = await self.async_client.get_order(id, account_hash)

                    if response.status_code != 200:
                        self.logger.warning(f"Failed to get specific order: {id}. HTTP Status: {response.status_code}")
                        # return None

                    return self.rename_order_ids(response.json())

                except Exception as e:
                    self.logger.error(f"An error occurred while attempting to get specific order: {id}. Error: {e} ({modifiedAccountID(self.account_id)})")
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
    
    async def getMarketHoursAsync(self, markets=None, *, date=None):
        isValid = await self.checkTokenValidityAsync()

        if isValid:
            try:
                # If no market is provided, get all the enum values as a list
                if markets is None:
                    markets = [market for market in schwabBaseClient.MarketHours.Market]

                # Use the current UTC datetime if no date is provided
                if date is None:
                    date = getUTCDatetime()

                response = await self.async_client.get_market_hours(markets=markets, date=date)

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