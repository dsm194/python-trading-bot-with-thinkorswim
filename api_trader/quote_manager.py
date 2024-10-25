
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
            callbacks = self.callbacks[:]  # Copy to avoid race conditions
        for callback in callbacks:
            if callback is not None:
                if asyncio.iscoroutinefunction(callback):
                    await callback(symbol, quote)
                else:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, callback, symbol, quote)

    @exception_handler
    async def get_streaming_quotes(self, batch_symbols, add_handler=True):
        # Subscription step, possibly setting up the connection
        await self.tdameritrade.subscribe_to_stream(batch_symbols, self.quote_handler, add_handler)
        
        # Background task for continuously receiving the stream
        asyncio.create_task(self.stream_quotes())

    @exception_handler        
    async def stream_quotes(self):
        while self.running:
            # Receiving and processing the stream
            await self.tdameritrade.receive_stream(self.quote_handler)


    async def add_quotes(self, symbols):
        if self.running:
            async with self.lock:
                # Streaming is already running, just add the new symbols to the existing list
                new_symbols = [s for s in symbols if s not in self.quotes and s not in self.subscribed_symbols]
            
            if new_symbols:
                await self.get_streaming_quotes(new_symbols, False)
                # Update the subscribed symbols set
                async with self.lock:
                    self.subscribed_symbols.update(new_symbols)
        else:
            # First time starting, subscribe to the initial batch
            self.running = True
            await self.get_streaming_quotes(symbols)
            async with self.lock:
                self.subscribed_symbols.update(symbols)  # Mark all initial symbols as subscribed

    async def add_callback(self, callback):
        async with self.lock:
            # Logic to add a new callback
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    async def stop_streaming(self):
        if self.running:
            await self.tdameritrade.disconnect_streaming()  # Disconnect WebSocket
            self.running = False
