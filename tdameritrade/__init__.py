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
                f"FAILED TO CONNECT {self.user['Name']} TO TDAMERITRADE ({self.account_id})", extra={'log': False})

            return False

    @exception_handler
    def checkTokenValidity(self):
        """
        Ensures the authentication token is valid.

        Returns:
            bool: True if the token is valid or successfully refreshed, False otherwise.
        """
        # Check if client is initialized and token expiration is valid
        if self.client:
            current_time = time.time()
            expires_at = self.client.token_metadata.token.get("expires_at", 0)

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
            self.client = client_from_token_file(token_path, API_KEY, APP_SECRET)
        else:
            self.logger.warning("Failed to find token file '%s'", token_path)
            self.client = client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path)

        if not self.client:
            self.logger.error("Failed to initialize client.")
            return False

        # Update token expiration and async/stream clients
        self.token_expiration = datetime.now() + timedelta(seconds=self.client.token_metadata.token.get("expires_in", 3600))
        self.async_client = self.async_client or client_from_token_file(token_path, API_KEY, APP_SECRET, asyncio=True)
        self.stream_client = self.stream_client or StreamClient(client=self.async_client)

        self.logger.info("Token refreshed successfully.")
        return True
    
    @exception_handler
    async def checkTokenValidityAsync(self):
        """
        Ensures the authentication token is valid.

        Returns:
            bool: True if the token is valid or successfully refreshed, False otherwise.
        """
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
            self.logger.error("Failed to initialize client.")
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

        detailed_resp = self.getSpecificOrderUnified(main_order_id, use_async=False)

        if detailed_resp:
            # Rename 'orderId' to 'Order_ID' in the detailed response
            detailed_resp = self.rename_order_ids(detailed_resp)
            return detailed_resp  # Return the full order details as a dictionary
        else:
            return {"Order_ID": main_order_id}  # Return basic info if full details are unavailable

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

        detailed_resp = await self.getSpecificOrderUnified(main_order_id, use_async=True)

        if detailed_resp:
            # Rename 'orderId' to 'Order_ID' in the detailed response
            detailed_resp = self.rename_order_ids(detailed_resp)
            return detailed_resp  # Return the full order details as a dictionary
        else:
            return {"Order_ID": main_order_id}  # Return basic info if full details are unavailable
        
    def placeTDAOrderUnified(self, data, use_async=False):
        """
        Unified method to place order, decides between sync and async based on use_async.
        """
        if use_async:
            if asyncio.get_event_loop().is_running():
                # If an event loop is already running, await the async function
                return asyncio.run_coroutine_threadsafe(self.placeTDAOrderAsync(data), asyncio.get_event_loop()).result()
            else:
                # If no event loop is running, execute the async function
                return asyncio.run(self.placeTDAOrderAsync(data))
        else:
            return self.placeTDAOrder(data)

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
        
    async def getQuoteAsync(self, symbol):
        """
        Retrieves the most recent quote for a stock asynchronously.

        Args:
            symbol (str): Stock symbol.

        Returns:
            dict: Stock quote in JSON format, or None if an error occurs.
        """
        if not symbol:
            self.logger.warning("Symbol in getQuote was empty '%s'", symbol)
            return None

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            try:
                if "/" in symbol:
                    response = await self.async_client.get_quotes(symbol)
                else:
                    response = await self.async_client.get_quote(symbol)

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
            return None

    def getQuoteUnified(self, symbol, use_async=False):
        """
        Unified method to fetch quote, decides between sync and async based on use_async.
        """
        if use_async:
            if asyncio.get_event_loop().is_running():
                # If an event loop is already running, await the async function
                return asyncio.run_coroutine_threadsafe(self.getQuoteAsync(symbol), asyncio.get_event_loop()).result()
            else:
                # If no event loop is running, execute the async function
                return asyncio.run(self.getQuoteAsync(symbol))
        else:
            return self.getQuote(symbol)


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
    async def start_stream(self, symbols, quote_handler, max_retries=5, stop_event=None):
        retries = 0
        last_handler_activity = datetime.now()

        async def update_activity(*args, **kwargs):
            nonlocal last_handler_activity
            last_handler_activity = datetime.now()
            self.logger.debug(f"Activity updated at {last_handler_activity} ({modifiedAccountID(self.account_id)})")

            try:
                # Check if quote_handler is a coroutine function
                if asyncio.iscoroutinefunction(quote_handler):
                    await quote_handler(*args, **kwargs)  # Await if it's asynchronous
                else:
                    quote_handler(*args, **kwargs)  # Call directly if it's synchronous
            except Exception as e:
                self.logger.error(f"Error in callback {quote_handler}: {e}")

        while not (stop_event and stop_event.is_set()):
            try:
                # Step 1: Login and Reset Retries
                await self._safe_connect_to_streaming()
                retries = 0  # Reset retries on successful connection

                # Step 2: Separate symbols by asset type
                equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
                option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]

                # Step 3: Register `quote_handler` with callback update
                if equity_symbols:
                    async with self.lock:
                        if quote_handler not in self.registered_handlers["equity"]:
                            self.stream_client.add_level_one_equity_handler(update_activity)
                            self.registered_handlers["equity"].add(quote_handler)

                    await self.stream_client.level_one_equity_add(
                    # await self.stream_client.level_one_equity_subs(
                        symbols=equity_symbols,
                        fields=[
                            StreamClient.LevelOneEquityFields.SYMBOL,
                            StreamClient.LevelOneEquityFields.BID_PRICE,
                            StreamClient.LevelOneEquityFields.ASK_PRICE,
                            StreamClient.LevelOneEquityFields.LAST_PRICE,
                            StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE
                        ]
                    )

                # Step 4: Register option symbols and callback
                if option_symbols:
                    async with self.lock:
                        if quote_handler not in self.registered_handlers["option"]:
                            self.stream_client.add_level_one_option_handler(update_activity)
                            self.registered_handlers["option"].add(quote_handler)

                    await self.stream_client.level_one_option_add(
                    # await self.stream_client.level_one_option_subs(
                        symbols=option_symbols,
                        fields=[
                            StreamClient.LevelOneOptionFields.SYMBOL,
                            StreamClient.LevelOneOptionFields.BID_PRICE,
                            StreamClient.LevelOneOptionFields.ASK_PRICE,
                            StreamClient.LevelOneOptionFields.LAST_PRICE,
                        ]
                    )

                # Step 5: Stream and check for inactivity timeout
                try:
                    while not (stop_event and stop_event.is_set()):
                        self.logger.debug(f"Calling handle_message ({modifiedAccountID(self.account_id)})")

                        # await asyncio.wait_for(self.stream_client.handle_message(), timeout=5)
                        await self.stream_client.handle_message()

                        self.logger.debug(f"handle_message returned, sleeping ({modifiedAccountID(self.account_id)})")
                        await asyncio.sleep(0.1)  # Yield control to event loop
                        self.logger.debug(f"Woke up from sleep ({modifiedAccountID(self.account_id)})")

                        # If handler not updated, reset the connection
                        if datetime.now() - last_handler_activity > timedelta(minutes=5):
                            self.logger.warning(f"Handler timeout detected. Last activity: {last_handler_activity} ({modifiedAccountID(self.account_id)})")
                            await self._clean_up_handler(quote_handler)
                            await self._safe_disconnect_streaming()
                            break  # Break out to reconnect
                finally:
                    self.logger.debug(f"Exiting inner loop. Cleaning up... ({modifiedAccountID(self.account_id)})")

            except (websockets.exceptions.ConnectionClosedOK, websockets.ConnectionClosedError) as e:
                retries += 1
                if retries >= max_retries:
                    self.logger.error("Max retries reached. Extending cooldown...")
                    retries = max_retries
                self.logger.warning(f"ConnectionClosed error encountered: {e}. Retrying... ({modifiedAccountID(self.account_id)})")
                await asyncio.sleep(1)
            except ValueError as e:
                self.logger.warning(f"Value error encountered: {e}. Reconnecting... ({modifiedAccountID(self.account_id)})")
                await self._clean_up_handler(quote_handler)
                await asyncio.sleep(1)
            except Exception as e:
                self.logger.error(f"Unexpected error: {e} - {traceback.format_exc()}")
                await self._clean_up_handler(quote_handler)
                await asyncio.sleep(min(2 ** retries, 60))  # Exponential backoff
            except asyncio.TimeoutError:
                self.logger.warning(f"handle_message timed out; resetting connection. ({modifiedAccountID(self.account_id)})")
                # Handle cleanup or reconnect logic here
                await self._clean_up_handler(quote_handler)
                await asyncio.sleep(min(2 ** retries, 60))  # Exponential backoff

        self.logger.info("Streaming canceled.")


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


    async def _safe_connect_to_streaming(self):
        try:
            # async with self.client_lock:
            await self.connect_to_streaming()  # Lock only during connection attempts
        except Exception as e:
            self.logger.error(f"Failed to connect to streaming: {e}")

    async def _safe_disconnect_streaming(self):
        try:
            # async with self.client_lock:
            await self.disconnect_streaming()  # Lock only during connection attempts
        except Exception as e:
            self.logger.error(f"Failed to disconnect to streaming: {e}")

    async def connect_to_streaming(self):
        try:
            self.logger.debug(f"Attempting to log in to the streaming service. ({modifiedAccountID(self.account_id)})")
            # await self.stream_client.login({"ping_interval": 13, "ping_timeout":30, "max_queue":10000})
            await self.stream_client.login()
            self.logger.debug(f"Successfully logged in to the streaming service. ({modifiedAccountID(self.account_id)})")
        except asyncio.TimeoutError:
            self.logger.error("Login timed out.")
            raise
        except Exception as e:
            self.logger.error(f"Failed to connect to streaming: {e}")
            raise

    async def disconnect_streaming(self):
        try:
            self.logger.debug(f"Attempting to log out of the streaming service. ({modifiedAccountID(self.account_id)})")
            await self.stream_client.logout()
            self.logger.debug(f"Successfully logged out of the streaming service. ({modifiedAccountID(self.account_id)})")
        except Exception as e:
            self.logger.warning(f"Suppressed exception during logout: {e}")



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
                    self.logger.error(f"An error occurred while attempting to get specific order: {id}. Error: {e}")
                    return
            else:
                return
        else:
            return
        
    def getSpecificOrderUnified(self, id, use_async=False):
        """
        Unified method to fetch market hours, decides between sync and async based on use_async.
        """
        if use_async:
            # Raise an error if called in a synchronous context to enforce correct usage
            if not asyncio.get_event_loop().is_running():
                raise RuntimeError("getSpecificOrderUnified was called with use_async=True in a non-async context.")
            
            # Directly call the async method (to be awaited by the caller)
            return self.getSpecificOrderAsync(id)
        else:
            return self.getSpecificOrder(id)

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
        
    def getMarketHoursUnified(self, markets=None, *, date=None, use_async=False):
        """
        Unified method to fetch market hours, decides between sync and async based on use_async.
        """
        if use_async:
            # Raise an error if called in a synchronous context to enforce correct usage
            if not asyncio.get_event_loop().is_running():
                raise RuntimeError("getMarketHoursUnified was called with use_async=True in a non-async context.")
            
            # Directly call the async method (to be awaited by the caller)
            return self.getMarketHoursAsync(markets, date=date)
        else:
            return self.getMarketHours(markets, date=date)

