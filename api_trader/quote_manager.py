
import asyncio
from assets.exception_handler import exception_handler

class QuoteManager:
    def __init__(self, tdameritrade, logger, callback = None):
        self.tdameritrade = tdameritrade
        self.quotes = {}  # Store quotes here
        self.logger = logger
        self.running = False
        self.callbacks = []  # Store callback functions for when quotes update
        self.subscribed_symbols = set()  # Track subscribed symbols
        # Use a dictionary to track running callbacks per symbol
        self.running_callbacks = {}
        self.lock = asyncio.Lock()

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
            regular_market_last_price = quote.get('REGULAR_MARKET_LAST_PRICE')
    
            # Log or handle each quote as needed
            self.logger.info(f"Received quote for {symbol}: Bid Price: {bid_price}, Ask Price: {ask_price}")

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
            await self.trigger_callbacks(symbol, merged_quote)

    async def trigger_callbacks(self, symbol, quote):
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
                

    async def start_quotes_stream(self, symbols):
        if not self.running:
            async with self.lock:
                self.subscribed_symbols.update(symbols)  # Ensure subscribed symbols are set initially
            self.running = True
            await self.tdameritrade.start_stream(
                self.subscribed_symbols, 
                quote_handler=self.quote_handler, 
                max_retries=5
            )


    async def update_stream_subscription(self, new_symbols):
        # Add new symbols to the active stream
        async with self.lock:
            self.subscribed_symbols.update(new_symbols)  # Update subscribed symbols with new symbols
        await self.tdameritrade.update_subscription(new_symbols)  # Adjust stream subscription


    async def add_quotes(self, symbols):
        async with self.lock:
            new_symbols = [s for s in symbols if s not in self.subscribed_symbols]

        if new_symbols:
            if self.running:
                # Update the subscription if the stream is running
                await self.update_stream_subscription(new_symbols)
            else:
                # Start the stream with all subscribed symbols
                await self.start_quotes_stream(symbols)


    async def add_callback(self, callback):
        async with self.lock:
            # Logic to add a new callback
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        if self.running:
            await self.tdameritrade.disconnect_streaming()  # Disconnect WebSocket
            self.running = False
