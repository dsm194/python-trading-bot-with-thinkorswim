import asyncio
from concurrent.futures import ThreadPoolExecutor
import jwt  # PyJWT library for decoding tokens

class QuoteManager:
    def __init__(self, tdameritrade, logger, callback=None):
        self.tdameritrade = tdameritrade
        self.logger = logger
        self.quotes = {}  # Store quotes
        self.is_streaming = False
        self.callbacks = []  # Callback functions for updates
        self.subscribed_symbols = set()  # Track subscribed symbols
        self.executor = ThreadPoolExecutor(max_workers=10)  # Limit thread pool size
        self.debounce_cache = {}  # Store the latest quote for each symbol
        self.underlying_account_id = self._extract_underlying_account_id(self.tdameritrade.async_client.token_metadata.token, self.logger)

        self.loop = asyncio.get_event_loop()  # Obtain the event loop first

        # Now it's safe to create asyncio objects
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.new_data_event = asyncio.Event()
        self.stream_initialized = asyncio.Event()
        self.stream_lock = asyncio.Lock()

        # Start the debounce cache processor in the background
        self.debounce_task = asyncio.create_task(self._process_debounce_cache())

        assert asyncio.get_event_loop() == self.loop, "QuoteManager is not created with the expected event loop"

    @staticmethod
    def _extract_underlying_account_id(token_metadata, logger):
        """
        Extracts the underlying account ID from the id_token.

        Args:
            token_metadata (dict): Token metadata containing access_token, refresh_token, and id_token.

        Returns:
            str: The extracted account ID, or None if extraction fails.
        """
        try:
            # Fetch the id_token from the token metadata
            id_token = token_metadata.get("id_token")
            if not id_token:
                raise ValueError("id_token is missing in token_metadata.")

            # Decode the id_token without verifying the signature
            payload = jwt.decode(id_token, options={"verify_signature": False})

            # Extract the account ID (or equivalent field) from the payload
            account_id = payload.get("sub")  # Replace 'sub' with the correct key if needed
            if not account_id:
                raise KeyError("Account ID ('sub') not found in token payload.")

            return account_id

        except (jwt.exceptions.DecodeError, ValueError, KeyError) as e:
            logger.error(f"Failed to extract underlying account ID: {e}")
            return None

    # Define a handler for updating quotes as they stream
    async def quote_handler(self, quotes):
        self.logger.debug(f"Received quote: {quotes}")

        # Extract the content property directly as a list of quotes
        quote_list = quotes['content']

        for quote in quote_list:
            symbol = quote.get('key')
            bid_price = quote.get('BID_PRICE')
            ask_price = quote.get('ASK_PRICE')
            last_price = quote.get('LAST_PRICE')
            regular_market_last_price = quote.get('REGULAR_MARKET_LAST_PRICE') or quote.get('LAST_PRICE')

            # Log or handle each quote as needed
            self.logger.debug(f"Received quote for {symbol}: Bid Price: {bid_price}, Ask Price: {ask_price}, Last Price: {last_price}, Regular Market Last Price: {regular_market_last_price}")

            # Store the quotes in a dictionary
            async with self.lock:
                cached_quote = self.quotes.get(symbol, {})
                self.quotes[symbol] = {
                    'bid_price': bid_price or cached_quote.get('bid_price'),
                    'ask_price': ask_price or cached_quote.get('ask_price'),
                    'last_price': last_price or cached_quote.get('last_price'),
                    'regular_market_last_price': regular_market_last_price or cached_quote.get('regular_market_last_price'),
                }
                self.debounce_cache[symbol] = self.quotes[symbol]

        # Signal that new data is available safely
        self.loop.call_soon_threadsafe(self.new_data_event.set)

    async def _process_debounce_cache(self):
        """Processes debounced quotes when new data is signaled."""
        while not self.stop_event.is_set():
            # Wait for the event to be set
            await self.new_data_event.wait()

            async with self.lock:
                debounce_cache_copy = self.debounce_cache.copy()
                self.debounce_cache.clear()  # Clear cache after copying

            for symbol, quote in debounce_cache_copy.items():
                await self._trigger_callbacks(symbol, quote)

            # Reset the event after processing
            self.new_data_event.clear()

    async def _trigger_callbacks(self, symbol, quote):
        """Triggers all registered callbacks for a given quote."""

        self.logger.debug(f"Triggering callbacks for {symbol}")
        tasks = []
        for callback in self.callbacks:
            if callback:
                tasks.append(asyncio.create_task(self._invoke_callback(callback, symbol, quote)))
        
        # Gather results and handle exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Callback error for {symbol}: {result}")

    
    async def _invoke_callback(self, callback, symbol, quote):
        """Invoke a callback, handling both async and sync functions."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(symbol, quote)
            else:
                # await asyncio.to_thread(callback, symbol, quote)
                await asyncio.get_event_loop().run_in_executor(self.executor, callback, symbol, quote)
        except Exception as e:
            self.logger.error(f"Callback error for {symbol}: {e}")

    async def _start_quotes_stream(self, symbols):
        async with self.stream_lock:  # Prevent overlapping calls
            if self.is_streaming:
                return  # Already streaming, no action needed

            self.is_streaming = True

            try:
                async with self.lock:
                    # Update subscribed symbols with the new structure
                    self.subscribed_symbols.update(entry["symbol"] for entry in symbols)

                # Pass stream_initialized to TdAmeritrade.start_stream and run as a background task
                self.stream_task = asyncio.create_task(
                    self.tdameritrade.start_stream(
                        symbols,
                        quote_handler=self.quote_handler,
                        max_retries=5,
                        stop_event=self.stop_event,
                        initialized_event=self.stream_initialized  # Pass the event here
                    )
                )
            except Exception as e:
                self.logger.error(f"Failed to start stream: {e}")
                self.is_streaming = False  # Reset state on failure
                raise



    async def _update_stream_subscription(self, new_symbols):
        """Update the stream with new symbols."""
        async with self.stream_lock:  # Prevent concurrent stream operations
            await self.stream_initialized.wait()

            async with self.lock:
                try:
                    self.subscribed_symbols.update(s["symbol"] for s in new_symbols)

                    # Call the update_subscription method with the new structure
                    await self.tdameritrade.update_subscription(new_symbols)
                except Exception as e:
                    self.logger.error(f"Failed to update stream subscription: {e}")
                    # Rollback the added symbols on failure
                    self.subscribed_symbols.difference_update(s["symbol"] for s in new_symbols)
                    raise

    async def add_quotes(self, symbols):
        async with self.lock:
            # Extract symbols and filter out already subscribed ones
            new_symbols = [s for s in symbols if s["symbol"] not in self.subscribed_symbols]

        if new_symbols:
            if self.is_streaming:
                try:
                    # Pass the new structure to the update function
                    await self._update_stream_subscription(new_symbols)
                except Exception as e:
                    self.logger.error(f"Failed to update subscription: {e}")
            else:
                try:
                    # Pass the new structure to start the stream
                    await self._start_quotes_stream(new_symbols)
                except Exception as e:
                    self.logger.error(f"Failed to start stream for new quotes: {e}")
                    raise

    async def add_callback(self, callback):
        """Add a new callback."""
        async with self.lock:
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        """Stops streaming and performs cleanup."""
        if not self.is_streaming:
            return  # Stream is already stopped

        self.is_streaming = False
        self.stop_event.set()  # Signal all waiting tasks to stop
        self.new_data_event.set()  # Ensure any waiting tasks are woken up

        # Wait for debounce task to finish and clean up resources
        if self.debounce_task:
            await self.debounce_task  # Wait for the debounce task to finish

        # Attempt to disconnect the streaming service
        try:
            self.logger.debug("Disconnecting streaming...")
            if hasattr(self, 'tdameritrade') and self.tdameritrade:
                await asyncio.wait_for(self.tdameritrade.disconnect_streaming(), timeout=2)
                self.logger.debug("Streaming disconnected successfully.")
        except asyncio.TimeoutError:
            self.logger.warning("Streaming logout timed out.")
        except Exception as e:
            self.logger.error(f"Error during streaming disconnect: {e}")

        # Properly shut down the executor
        self.executor.shutdown(wait=True)
        self.logger.info("Streaming stopped and resources cleaned up.")
