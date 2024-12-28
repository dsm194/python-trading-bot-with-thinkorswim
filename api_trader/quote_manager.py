
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
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()  # Use asyncio.Event to manage streaming state
        self.new_data_event = asyncio.Event()  # Event to signal new data
        self.executor = ThreadPoolExecutor(max_workers=10)  # Limit thread pool size
        self.debounce_cache = {}  # Store the latest quote for each symbol
        self.loop = asyncio.get_event_loop()  # Save the current event loop
        self.underlying_account_id = self._extract_underlying_account_id(self.tdameritrade.async_client.token_metadata.token, self.logger)
        self.stream_initialized = asyncio.Event()

        # Start the debounce cache processor in the background
        self.debounce_task = asyncio.create_task(self._process_debounce_cache())

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
        await asyncio.gather(*tasks)
    
    async def _invoke_callback(self, callback, symbol, quote):
        """Invoke a callback, handling both async and sync functions."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(symbol, quote)
            else:
                await asyncio.get_event_loop().run_in_executor(self.executor, callback, symbol, quote)
        except Exception as e:
            self.logger.error(f"Callback error for {symbol}: {e}")

    async def _start_quotes_stream(self, symbols):
        async with self.lock:
            # Update subscribed symbols with the new structure
            self.subscribed_symbols.update(entry["symbol"] for entry in symbols)
            
        if not self.is_streaming:
            self.is_streaming = True

            try:
                await self.tdameritrade.start_stream(
                    symbols,
                    quote_handler=self.quote_handler, 
                    max_retries=5,
                    stop_event = self.stop_event
                )
            finally:
                # Signal that the stream is fully initialized
                self.stream_initialized.set()

    async def _update_stream_subscription(self, new_symbols):
        """Update the stream with new symbols."""
        # Wait for the stream to be initialized
        await self.stream_initialized.wait()
        
        async with self.lock:
            self.subscribed_symbols.update(s["symbol"] for s in new_symbols)

        # Call the update_subscription method with the new structure
        await self.tdameritrade.update_subscription(new_symbols)

    async def add_quotes(self, symbols):
        async with self.lock:
            # Extract symbols and filter out already subscribed ones
            new_symbols = [s for s in symbols if s["symbol"] not in self.subscribed_symbols]

        if new_symbols:
            if self.is_streaming:
                # Pass the new structure to the update function
                await self._update_stream_subscription(new_symbols)
            else:
                # Pass the new structure to start the stream
                await self._start_quotes_stream(new_symbols)

    async def add_callback(self, callback):
        """Add a new callback."""
        async with self.lock:
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        """Stop streaming quotes."""
        if self.is_streaming:
            self.is_streaming = False
            self.stop_event.set()   # Signal stop to the background task    
            self.new_data_event.set()  # Wake up the task if waiting
            await self.debounce_task  # Wait for the task to finish
