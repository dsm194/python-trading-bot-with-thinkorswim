# imports
import asyncio
from datetime import datetime, timedelta
import time
import httpx
from prompt_toolkit import PromptSession
import websockets
from assets.helper_functions import getUTCDatetime, modifiedAccountID
from assets.exception_handler import exception_handler

from schwab.auth import client_from_manual_flow
from schwab.auth import client_from_token_file, __make_update_token_func as make_update_token_func, client_from_received_url, get_auth_context
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

    def __init__(self, async_mongo, user, account_id, logger, push_notification):

        self.user = user

        self.account_id = account_id

        self.logger = logger

        self.async_mongo = async_mongo

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

        self._streaming_lock = asyncio.Lock()

        self.is_streaming_connected = False  # Default to not connected


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
                self.logger.debug(f"Token is valid. Time remaining: {time_remaining} seconds.")
                return True
            else:
                self.logger.warning("Token has expired or is about to expire.")

        # Retrieve user data and refresh or generate a new token
        user = await self.async_mongo.users.find_one({"Name": self.user["Name"]})
        token_path = user["Accounts"][self.account_id]["token_path"]

        if os.path.isfile(token_path):
            self.async_client = client_from_token_file(token_path, API_KEY, APP_SECRET, asyncio=True)
        else:
            self.logger.warning("Failed to find token file '%s'", token_path)
            self.async_client = await self.async_client_from_manual_flow(token_path)

        if not self.async_client:
            self.logger.error(f"Failed to initialize clients. ({modifiedAccountID(self.account_id)})")
            return False

        # Update token expiration and async/stream clients
        tokenSeconds = self.async_client.token_metadata.token.get("expires_in", 3600)
        self.token_expiration = datetime.now() + timedelta(seconds=tokenSeconds)

        if not self.stream_client:
            self.stream_client = StreamClient(client=self.async_client)

        # ADD NEW TOKEN DATA TO USER DATA IN DB
        await self.async_mongo.users.update_one({"Name": self.user["Name"]}, {
            "$set": {f"{self.account_id}.refresh_exp_date": (self.token_expiration).strftime("%Y-%m-%d")}})

        self.logger.info("Token refreshed successfully.")
        return True

    async def async_client_from_manual_flow(self, token_path):

        auth_context = get_auth_context(API_KEY, CALLBACK_URL)

        print('\n**************************************************************\n')
        print('This is the manual login and token creation flow for schwab-py.')
        print('Please follow these instructions exactly:')
        print()
        print(' 1. Open the following link by copy-pasting it into the browser')
        print('    of your choice:')
        print()
        print('        ' + auth_context.authorization_url)
        print()
        print(' 2. Log in with your account credentials. You may be asked to')
        print('    perform two-factor authentication using text messaging or')
        print('    another method, as well as whether to trust the browser.')
        print()
        print(' 3. When asked whether to allow your app access to your account,')
        print('    select "Allow".')
        print()
        print(' 4. Your browser should be redirected to your callback URI. Copy')
        print('    the ENTIRE address, paste it into the following prompt, and press')
        print('    Enter/Return.')
        print()
        print('If you encounter any issues, see here for troubleshooting:')
        print('https://schwab-py.readthedocs.io/en/latest/auth.html#troubleshooting')
        print('\n**************************************************************\n')

        if CALLBACK_URL.startswith('http://'):
            print(('WARNING: Your callback URL ({}) will transmit data over HTTP, ' +
                'which is a potentially severe security vulnerability. ' +
                'Please go to your app\'s configuration with Schwab ' +
                'and update your callback URL to begin with \'https\' ' +
                'to stop seeing this message.').format(CALLBACK_URL))

        token_write_func = None

        # Use asynchronous prompt for user input
        session = PromptSession()
        received_url = await session.prompt_async("Redirect URL> ")

        token_write_func = (
            make_update_token_func(token_path) if token_write_func is None
            else token_write_func)

        return client_from_received_url(
                API_KEY, APP_SECRET, auth_context, received_url, token_write_func, 
                asyncio, True)

    async def getAccount(self):
        """ METHOD GET ACCOUNT DATA

        Returns:
            [json]: ACCOUNT DATA
        """

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            resp = await self.async_client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                account_resp = await self.async_client.get_account(account_hash)
                return account_resp.json()  # Ensure this is the final awaited object
            else:
                return None
        else:
            return None


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

        account = await self.getAccount()

        # buying_power = account["securitiesAccount"]["initialBalances"]["cashAvailableForTrading"]
        buying_power = account["securitiesAccount"]["initialBalances"]["cashBalance"]

        return float(buying_power)

    @exception_handler
    async def getQuoteAsync(self, symbol, fields=schwabBaseClient.Quote.Fields.QUOTE):
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
                    response = await self.async_client.get_quotes(symbol, fields=fields)
                else:
                    response = await self.async_client.get_quote(symbol, fields=fields)

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
    async def start_stream(self, symbols, quote_handler, max_retries=5, stop_event=None, initialized_event=None, message_rate_limit=10):
        retries = 0
        self.logger.info(f"Starting stream for symbols: {symbols} ({modifiedAccountID(self.account_id)})")

        async def reconnect():
            """Reconnect logic with exponential backoff."""
            nonlocal retries
            retries += 1
            if retries > max_retries:
                self.logger.error("Max retries reached. Stopping reconnection attempts.")
                return False
            sleep_time = min(2 ** retries, 60)
            self.logger.warning(f"Reconnecting in {sleep_time}s (retry {retries}/{max_retries})...")
            await asyncio.sleep(sleep_time)
            return True

        async def stream_messages():
            """Stream messages continuously with rate limiting."""
            last_received_time = time.time()
            while not (stop_event and stop_event.is_set()):
                try:
                    # Wrap handle_message in a task
                    message_task = asyncio.create_task(self.stream_client.handle_message())
                    stop_event_task = asyncio.create_task(stop_event.wait())

                    # Wait for either the message task or stop_event
                    done, pending = await asyncio.wait(
                        [message_task, stop_event_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Cancel remaining tasks
                    for task in pending:
                        task.cancel()

                    # If stop_event is set, exit gracefully
                    if stop_event.is_set():
                        self.logger.info("Stop event triggered during streaming.")
                        break

                    # Check if handle_message raised an exception
                    for task in done:
                        if task is message_task and task.exception():
                            raise task.exception()

                    # Throttle message handling by waiting for the defined rate limit
                    time_elapsed = time.time() - last_received_time
                    if time_elapsed < message_rate_limit:
                        await asyncio.sleep(message_rate_limit - time_elapsed)  # Wait for the next slot
                    last_received_time = time.time()

                except asyncio.TimeoutError:
                    self.logger.warning("Timeout waiting for messages.")
                except websockets.exceptions.ConnectionClosedError as e:
                    self.logger.warning(f"WebSocket connection closed: {e}")
                    break
                except asyncio.CancelledError:
                    self.logger.info("Stream messages task was cancelled.")
                    break
                except Exception as e:
                    self.logger.error(f"Unexpected error during message handling: {e}")
                    break


        while not (stop_event and stop_event.is_set()):
            try:
                # Step 1: Establish connection
                await self._safe_connect_to_streaming()
                retries = 0  # Reset retries on successful connection

                # Step 2: Register handlers and subscribe
                await self._register_and_subscribe(symbols, quote_handler)

                # Signal that the stream has been initialized
                if initialized_event and not initialized_event.is_set():
                    initialized_event.set()

                # Step 3: Stream messages in the background with rate limiting
                await stream_messages()

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

    async def _register_and_subscribe(self, symbols, quote_handler):
        """Register handlers and subscribe to symbols."""
        equity_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "EQUITY"]
        option_symbols = [entry["symbol"] for entry in symbols if entry["asset_type"] == "OPTION"]

        async with self.lock:
            if equity_symbols:
                if quote_handler not in self.registered_handlers["equity"]:
                    self.stream_client.add_level_one_equity_handler(quote_handler)
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
                    self.stream_client.add_level_one_option_handler(quote_handler)
                    self.registered_handlers["option"].add(quote_handler)
                await self.stream_client.level_one_option_add(option_symbols, fields=[
                    StreamClient.LevelOneOptionFields.SYMBOL,
                    StreamClient.LevelOneOptionFields.BID_PRICE,
                    StreamClient.LevelOneOptionFields.ASK_PRICE,
                    StreamClient.LevelOneOptionFields.LAST_PRICE,
                ])

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
        
        async with self.lock:  # Ensure thread-safety
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
                self.is_streaming_connected = True
                return
            except Exception as e:
                self.logger.error(f"Reconnect attempt {attempt + 1} failed: {e} ({modifiedAccountID(self.account_id)})")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(f"Failed to reconnect after retries. ({modifiedAccountID(self.account_id)})")

    async def _safe_disconnect_streaming(self):
        if not self.is_streaming_connected:
            self.logger.info("Streaming already disconnected. Skipping disconnect call.")
            return

        async with self._streaming_lock:
            if not self.is_streaming_connected:  # Recheck after acquiring the lock
                self.logger.info("Streaming already disconnected. Skipping disconnect call.")
                return

            try:
                self.logger.debug("Disconnecting streaming...")
                await self.disconnect_streaming()
                self.is_streaming_connected = False  # Update the flag after disconnection
                self.logger.debug("Streaming disconnected successfully.")
            except asyncio.CancelledError:
                self.logger.warning(f"Task was cancelled during disconnect_streaming ({modifiedAccountID(self.account_id)})")
                raise  # Re-raise to propagate cancellation
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
            try:
                # Timeout on the logout process
                await asyncio.wait_for(self.stream_client.logout(), timeout=3)
                self.logger.debug(f"Successfully logged out of the streaming service. ({modifiedAccountID(self.account_id)})")
            except asyncio.TimeoutError:
                self.logger.warning("Timeout during logout. Forcing WebSocket closure.")
                if hasattr(self.stream_client, "_socket") and self.stream_client._socket:
                    self.logger.debug("Forcing WebSocket close.")
                    await self.stream_client._socket.close()
        except asyncio.CancelledError:
            self.logger.warning(f"Task cancellation acknowledged during logout. ({modifiedAccountID(self.account_id)})")
            raise  # Re-raise the cancellation
        except Exception as e:
            self.logger.warning(f"Suppressed exception during logout: {e}")
        finally:
            self.logger.debug("Finished disconnect_streaming.")
        
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
                        self.logger.warning(f"Failed to get specific order: {id}. HTTP Status: {response.status_code} ({modifiedAccountID(self.account_id)})")
                        # return None

                    return self.rename_order_ids(response.json())

                except Exception as e:
                    self.logger.error(f"An error occurred while attempting to get specific order: {id}. Error: {e} ({modifiedAccountID(self.account_id)})")
                    return
            else:
                return
        else:
            return

    async def cancelOrder(self, id):
        """ METHOD CANCELS ORDER

        Args:
            id ([int]): ORDER ID FOR ORDER

        Returns:
            [json]: RESPONSE. LOOKING FOR STATUS CODE 200,201
        """

        url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}/orders/{id}"

        # return self.sendRequest(url, method="DELETE")

        isValid = await self.checkTokenValidityAsync()

        if isValid:
            resp = await self.async_client.get_account_numbers()
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
                    response = await self.async_client.cancel_order(id, account_hash)

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