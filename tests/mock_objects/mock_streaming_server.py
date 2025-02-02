import asyncio
import random

class MockStreamingServer:
    """Simulates a real-time stock quote streaming service for testing."""

    def __init__(self):
        self.symbols = set()
        self.callbacks = []
        self.streaming = False
        self._prices = {}
        self.stop_event = None  # ✅ Will hold the stop_event from QuoteManager
        self.reset_event = None  # ✅ Will hold reset_event from QuoteManager

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

    async def stop(self):
        """Stops the mock streaming service."""
        self.streaming = False
        print("🚫 [MOCK STREAM] Stopped.")

    async def update_subscription(self, symbols):
        """Mocks subscribing to new stock symbols for streaming."""
        self.symbols.update(s["symbol"] for s in symbols)
        print(f"✅ [MOCK STREAM] Subscribed to: {symbols}")

    async def unsubscribe_symbols(self, symbols):
        """Mocks unsubscribing from stock symbols."""
        self.symbols.difference_update(symbols)
        print(f"🚫 [MOCK STREAM] Unsubscribed from: {symbols}")

    def add_callback(self, callback):
        """Registers a callback function to process updates."""
        self.callbacks.append(callback)
