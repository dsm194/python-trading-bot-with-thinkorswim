
import asyncio
import threading
from assets.exception_handler import exception_handler

class QuoteManager:
    def __init__(self, tdameritrade, logger, callback = None):
        self.tdameritrade = tdameritrade
        self.quotes = {}  # Store quotes here
        self.logger = logger
        self.is_streaming = False
        self.callbacks = []  # Store callback functions for when quotes update
        self.subscribed_symbols = set()  # Track subscribed symbols
        # Use a dictionary to track running callbacks per symbol
        self.running_callbacks = {}
        self.lock = asyncio.Lock()
        self.stop_event = threading.Event()

    # Define a handler for updating quotes as they stream
    async def quote_handler(self, quotes):
        self.logger.info(f"Received quote: {quotes}")

        # Extract the content property directly as a list of quotes
        quote_list = quotes['content']

        for quote in quote_list:
            symbol = quote.get('key')
            bid_price = quote.get('BID_PRICE')
            ask_price = quote.get('ASK_PRICE')
            last_price = quote.get('LAST_PRICE')
            regular_market_last_price = quote.get('REGULAR_MARKET_LAST_PRICE') or quote.get('LAST_PRICE')

    
            # Log or handle each quote as needed
            self.logger.info(f"Received quote for {symbol}: Bid Price: {bid_price}, Ask Price: {ask_price}, Last Price: {last_price}, Regular Market Last Price: {regular_market_last_price}")

            # Store the quotes in a dictionary
            async with self.lock:
                cached_quote = self.quotes.get(symbol, {})
                merged_quote = {
                    'bid_price': bid_price if bid_price is not None else cached_quote.get('bid_price'),
                    'ask_price': ask_price if ask_price is not None else cached_quote.get('ask_price'),
                    'last_price': last_price if last_price is not None else cached_quote.get('last_price'),
                    'regular_market_last_price': regular_market_last_price if regular_market_last_price is not None else cached_quote.get('regular_market_last_price')
                }

                # Update the cache
                self.quotes[symbol] = merged_quote

            # Trigger all registered callbacks
            await self._trigger_callbacks(symbol, merged_quote)

    async def _trigger_callbacks(self, symbol, quote):
        async with self.lock:
            # Skip if callback for this symbol is already running
            if self.running_callbacks.get(symbol):
                return
            self.running_callbacks[symbol] = True  # Mark as running

            callbacks = self.callbacks[:]  # Copy to avoid race conditions

        try:
            for callback in callbacks:
                if callback is not None:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(symbol, quote)
                    else:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, callback, symbol, quote)
        finally:
            async with self.lock:
                # Remove the symbol from running callbacks after execution completes
                self.running_callbacks.pop(symbol, None)
                
    async def _start_quotes_stream(self, symbols):
        if not self.is_streaming:
            async with self.lock:
                # Update subscribed symbols with the new structure
                self.subscribed_symbols.update(entry["symbol"] for entry in symbols)
                # self.subscribed_symbols.update(entry["symbol"] for entry in symbols if isinstance(entry, dict))

            self.is_streaming = True
            await self.tdameritrade.start_stream(
                symbols,
                quote_handler=self.quote_handler, 
                max_retries=5,
                stop_event = self.stop_event
            )

    async def _update_stream_subscription(self, new_symbols):
        # Add new symbols to the active stream
        async with self.lock:
            # Update subscribed symbols with the new structure
            for entry in new_symbols:
                symbol = entry["symbol"]
                self.subscribed_symbols.add(symbol)  # Assuming subscribed_symbols is a set

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
        async with self.lock:
            # Logic to add a new callback
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        if self.is_streaming:
            # await self.tdameritrade.disconnect_streaming()  # Disconnect WebSocket
            self.is_streaming = False
            self.stop_event.set()
