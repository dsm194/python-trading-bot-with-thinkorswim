import asyncio
from concurrent.futures import ThreadPoolExecutor
import jwt  # PyJWT library for decoding tokens

from tdameritrade import TDAmeritrade

class QuoteManager:
    """Manages stock price subscriptions & streaming."""

    def __init__(self, tdameritrade: TDAmeritrade, logger):
        self.tdameritrade = tdameritrade
        self.logger = logger
        self.quotes = {}  # Store quotes
        self.is_streaming = False
        self.callbacks = []  # Callback functions for updates
        self.subscribed_symbols = {}  # Track subscribed symbols with their full structure
        self.executor = ThreadPoolExecutor(max_workers=10)  # Limit thread pool size
        self.debounce_cache = {}  # Store the latest quote for each symbol
        self.underlying_account_id = self._extract_underlying_account_id(self.tdameritrade.async_client.token_metadata.token, self.logger)

        self.loop = asyncio.get_event_loop()  # Obtain the event loop first

        # Now it's safe to create asyncio objects
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.new_data_event = asyncio.Event()
        self.stream_initialized = asyncio.Event()
        self.reset_event = asyncio.Event()
        self.stream_lock = asyncio.Lock()

        # Start the debounce cache processor in the background
        self.debounce_task = asyncio.create_task(self._process_debounce_cache())
        self.reset_task = asyncio.create_task(self._listen_for_resets())
        self.stop_lock = asyncio.Lock()

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
                raise RuntimeError(f"Callback errors for {symbol}: {result}")
    
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

    async def _listen_for_resets(self):
        """Listen for stream reset events and clean up subscribed symbols."""
        while not self.stop_event.is_set():
            # Wait for the reset_event to be triggered
            await self.reset_event.wait()
            self.reset_event.clear()  # Reset the event for future use

            async with self.lock:
                if self.subscribed_symbols:
                    self.logger.info(f"Stream reset detected. Clearing {len(self.subscribed_symbols)} subscribed symbols.")
                    self.subscribed_symbols.clear()
                else:
                    self.logger.warning("Stream reset detected, but no subscribed symbols to clear.")

            async with self.stream_lock:
                self.stream_initialized.clear()

    async def _start_quotes_stream(self, symbols):
        try:
            async with self.lock:
                # Update subscribed symbols with the new structure
                for entry in symbols:
                    self.subscribed_symbols[entry["symbol"]] = entry

            # Pass stream_initialized to TdAmeritrade.start_stream and run as a background task
            self.stream_task = asyncio.create_task(
                self.tdameritrade.start_stream(
                    symbols,
                    quote_handler=self.quote_handler,
                    max_retries=5,
                    stop_event=self.stop_event,
                    initialized_event=self.stream_initialized,  # Pass the event here
                    reset_event=self.reset_event,
                )
            )
        except Exception as e:
            self.logger.error(f"Failed to start stream: {e}")
            raise

    async def _update_stream_subscription(self, symbols_to_update):
        """Update the stream with new symbols while preventing deadlocks."""
        self.logger.debug(f"[QUOTE MANAGER] Starting stream update for {len(symbols_to_update)} symbols: {symbols_to_update}")

        if not self.stream_initialized.is_set():
            self.logger.warning("[QUOTE MANAGER] Stream not initialized yet. Waiting...")

        await self.stream_initialized.wait()
        self.logger.debug(f"[QUOTE MANAGER] Stream initialized. Proceeding with subscription update.")


        # Call update_subscription() *after* releasing all locks
        try:
            self.logger.debug(f"[QUOTE MANAGER] Calling update_subscription() with {symbols_to_update}")

            # Add a forced timeout to catch any hanging issue
            await asyncio.wait_for(self.tdameritrade.update_subscription(symbols_to_update), timeout=15)

            self.logger.debug(f"[QUOTE MANAGER] Returned from update_subscription()")  # 🚨 This will tell us if execution continues
            self.logger.debug(f"[QUOTE MANAGER] Successfully updated subscription for {len(symbols_to_update)} symbols.")
        except asyncio.TimeoutError:
            self.logger.error(f"[QUOTE MANAGER] Timeout waiting for update_subscription() to return!")
        except Exception as e:
            self.logger.error(f"[QUOTE MANAGER] Failed to update stream subscription: {e}")
            
            raise

    async def add_quotes(self, symbols, batch_size=10):
        async with self.lock:
            # Extract only new symbols that are NOT in `self.subscribed_symbols`
            new_symbols = [s for s in symbols if s["symbol"] not in self.subscribed_symbols]

            if not new_symbols:
                self.logger.debug("[QUOTE MANAGER] No new symbols to process. Skipping update.")
                return  # Nothing new to process

            self.logger.debug(f"[QUOTE MANAGER] New symbols detected: {new_symbols}")

            # Reserve all new symbols *before* releasing the lock to prevent race conditions
            for s in new_symbols:
                self.subscribed_symbols[s["symbol"]] = s

            start_stream = not self.is_streaming
            if start_stream:
                self.is_streaming = True  # Mark as streaming before starting

            # Split into batches
            first_batch = new_symbols[:batch_size]
            remaining_batches = new_symbols[batch_size:]

        try:
            if start_stream:
                self.logger.debug(f"Calling `_start_quotes_stream` with: {first_batch}")
                await self._start_quotes_stream(first_batch)  # Start streaming with the first batch
            else:
                self.logger.debug(f"Streaming is already active. Calling `_update_stream_subscription` with: {first_batch}")
                await self._update_stream_subscription(first_batch)  # Ensure first batch is processed

            # Process remaining batches using `_update_stream_subscription`
            for i in range(0, len(remaining_batches), batch_size):
                batch = remaining_batches[i:i + batch_size]
                self.logger.debug(f"Calling `_update_stream_subscription` with: {batch}")
                await self._update_stream_subscription(batch)

            self.logger.info(f"Successfully updated stream subscription with {len(new_symbols)} symbols.")
        except Exception as e:
            self.logger.error(f"Failed to process batch: {e}")

            # Rollback `is_streaming` if we had set it to `True` but the stream failed
            if start_stream:
                self.is_streaming = False

            # Rollback failed symbols
            async with self.lock:
                for s in new_symbols:
                    self.subscribed_symbols.pop(s["symbol"], None)

            raise

    async def unsubscribe(self, symbols):
        """Unsubscribes a list of symbols from streaming and removes them from subscribed_symbols."""

        symbols_to_unsubscribe = []

        async with self.lock:
            # First, copy the structures BEFORE removing from self.subscribed_symbols
            symbols_to_unsubscribe = [
                self.subscribed_symbols[symbol]
                for symbol in symbols if symbol in self.subscribed_symbols
            ]

        if symbols_to_unsubscribe:
            self.logger.info(f"[QUOTE MANAGER] Unsubscribing from {symbols_to_unsubscribe}.")

            # Call API first before removing from tracking list
            await self._unsubscribe_from_stream(symbols_to_unsubscribe)

            # Only remove AFTER successful API call
            async with self.lock:
                for entry in symbols_to_unsubscribe:
                    self.subscribed_symbols.pop(entry["symbol"], None)

        else:
            self.logger.warning(f"[QUOTE MANAGER] No matching symbols found in subscribed_symbols for unsubscribe.")

    async def _unsubscribe_from_stream(self, structured_symbols):
        """Sends an unsubscribe request for a batch of symbols to the streaming API."""
        try:
            if structured_symbols:
                await self.tdameritrade.unsubscribe_symbols(structured_symbols)  # Call API with correct format
                self.logger.info(f"[QUOTE MANAGER] Sent batch unsubscribe request for {structured_symbols}.")
            else:
                self.logger.warning(f"[QUOTE MANAGER] No valid structures found for unsubscribe.")

        except Exception as e:
            self.logger.error(f"[QUOTE MANAGER] Failed to unsubscribe symbols: {structured_symbols}, Error: {e}")

    async def add_callback(self, callback):
        """Add a new callback."""
        async with self.lock:
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        """Stops streaming and performs cleanup."""
        async with self.stop_lock:  # Ensure only one task enters this block
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
