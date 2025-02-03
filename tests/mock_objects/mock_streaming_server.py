import asyncio
import random
import traceback

class MockStreamingServer:
    """Simulates a real-time stock quote streaming service for testing."""

    def __init__(self):
        self.symbols = set()
        self.callbacks = []
        self.streaming = False
        self._prices = {}
        self.stop_event = None  # ✅ Will hold the stop_event from QuoteManager
        self.reset_event = None  # ✅ Will hold reset_event from QuoteManager
        self.is_logged_in = False

    async def login(self):
        """Mocks the login process for the streaming API, ensuring cancellation is logged."""
        try:
            await asyncio.sleep(0.5)  # ✅ Simulate API delay
            self.is_logged_in = True
            print("✅ [MOCK TDA] Logged into streaming API.")
        except asyncio.CancelledError:
            print("🚨 [MOCK TDA] Login was cancelled! Raising error... ")
            traceback.print_exc()  # ✅ Print the full traceback to see what caused it
            raise  # ✅ Ensure it propagates

    def add_level_one_equity_handler(self, callback):
        """Mocks adding a handler for Level 1 Equity quotes."""
        # print(f"✅ [MOCK TDA] Registered Level 1 Equity Handler: {callback}")
        self.callbacks.append(callback)  # ✅ Register the callback properly

    async def level_one_equity_add(self, symbols, fields):
        """Mocks adding symbols to the quote stream."""
        # print(f"🟢 [MOCK TDA] Adding {len(symbols)} symbols to the quote stream...")
        try:
            await asyncio.shield(asyncio.sleep(0.1))  # ✅ Debugging Step
            self.symbols.update(symbols)
            print(f"✅ [MOCK TDA] Subscribed to {len(symbols)} symbols.")
        except asyncio.CancelledError:
            print("❌ [MOCK TDA] Subscription was cancelled, but we completed `sleep` first!")
            raise

    async def level_one_equity_unsubs(self, symbols):
        """Mocks unsubscribing from equity symbols."""
        for symbol in symbols:
            self.symbols.discard(symbol)  # ✅ Remove symbol from tracking

        # print(f"🚫 [MOCK TDA] Unsubscribed from {len(symbols)} symbols: {symbols}")
        await asyncio.sleep(0.1)  # ✅ Simulate API delay

    async def start_stream(self, symbols, quote_handler, max_retries=5, stop_event=None, initialized_event=None, reset_event=None):
        """Mocks the behavior of `tdameritrade.start_stream()` to integrate with QuoteManager."""
        self.symbols.update(s["symbol"] for s in symbols)
        self.stop_event = stop_event
        self.reset_event = reset_event
        self.callbacks.append(quote_handler)

        # ✅ Simulate successful stream initialization
        if initialized_event:
            initialized_event.set()

        self.streaming = True
        print("✅ [MOCK STREAM] Started streaming quotes.")

        while self.streaming:
            await asyncio.sleep(random.uniform(0.5, 1.5))  # ✅ Simulate real-time quote updates

            # ✅ Generate quotes in the expected format
            updates = {"content": [
                {"key": symbol, "LAST_PRICE": random.uniform(50, 500)}
                for symbol in self.symbols
            ]}

            for callback in self.callbacks:
                await callback(updates)  # ✅ Send mock price updates

            if self.stop_event and self.stop_event.is_set():
                print("🚫 [MOCK STREAM] Stop event triggered. Ending stream.")
                self.streaming = False
                break

    async def handle_message(self):
        """Simulate handling messages by calling the registered callback."""
        while True:
            await asyncio.sleep(1)  # ✅ Simulate receiving messages periodically

            # Generate random price updates
            price_updates = {
                symbol_entry: {"LAST_PRICE": random.uniform(50, 500)}
                for symbol_entry in self.symbols
            }

            # print(f"🟢 [MOCK] Sending mock price updates: {price_updates}")

            # Call the registered quote handler with mock data
            for callback in self.callbacks:
                # print(f"🔵 [MOCK] Calling registered quote callback: {callback}")
                await callback(price_updates)

    async def stop(self):
        """Stops the mock streaming service."""
        self.streaming = False
        print("🚫 [MOCK STREAM] Stopped.")

    async def update_subscription(self, symbols):
        """Mocks subscribing to new stock symbols for streaming."""
        self.symbols.update(s["symbol"] for s in symbols)
        # print(f"✅ [MOCK STREAM] Subscribed to: {symbols}")

    async def unsubscribe_symbols(self, symbols):
        """Mocks unsubscribing from stock symbols."""
        self.symbols.difference_update(symbols)
        # print(f"🚫 [MOCK STREAM] Unsubscribed from: {symbols}")

    def add_callback(self, callback):
        """Registers a callback function to process updates."""
        self.callbacks.append(callback)
