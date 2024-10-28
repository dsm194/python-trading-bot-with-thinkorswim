import unittest
from unittest.mock import AsyncMock, MagicMock
import asyncio
import random

from websockets.exceptions import ConnectionClosedError  # Import directly

from api_trader.quote_manager import QuoteManager
from tdameritrade import TDAmeritrade

class TestQuoteStreaming(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock necessary dependencies
        self.mongo_mock = MagicMock()
        self.user_mock = MagicMock()
        self.logger_mock = MagicMock()
        self.push_notification_mock = MagicMock()

        # Mock TDAmeritrade object as required
        self.td_ameritrade = TDAmeritrade(
            mongo=self.mongo_mock,
            user=self.user_mock,
            account_id='test_account',
            logger=self.logger_mock,
            push_notification=self.push_notification_mock
        )
        
        # Set up the QuoteManager with mock methods
        self.quote_manager = QuoteManager(self.td_ameritrade, self.logger_mock)
        self.quote_manager._trigger_callbacks = AsyncMock()
        # self.quote_manager.add_callback(self.evaluate_paper_triggers)

        # Mock stream client behavior
        self.quote_manager.tdameritrade.stream_client = MagicMock()
        self.quote_manager.tdameritrade.stream_client.login = AsyncMock(side_effect=lambda: asyncio.sleep(0.1))
        self.quote_manager.tdameritrade.stream_client.level_one_equity_add = AsyncMock(side_effect=lambda: asyncio.sleep(0.1))

        self.quote_manager.tdameritrade.stream_client.handle_message = AsyncMock()

        # Mock start_stream to call simulate_mock_stream
        # self.quote_manager.tdameritrade.start_stream = AsyncMock(
        #     side_effect=lambda symbols, quote_handler, max_retries: self.simulate_mock_stream(symbols, quote_handler=quote_handler, max_retries=max_retries)
        # )
        self.quote_manager.tdameritrade.start_stream = self.simulate_mock_stream
        

    async def simulate_mock_stream(self, symbols, quote_handler, max_retries=5, iterations=100, error_chance=0.05):
        """Simulate streaming quotes and randomly raise disconnection errors."""
        for _ in range(iterations):

            # Randomly simulate a WebSocket disconnection
            if random.random() < error_chance:
                # Simulate a disconnect
                try:
                    raise ConnectionClosedError(1006, 1006, "Simulated disconnection")
                except ConnectionClosedError as e:
                    # self.quote_manager.logger.warning(f"WebSocket connection closed: {e}. Reconnecting...")
                    self.quote_manager.logger.warning(f"Connection closed: {e}. Reconnecting attempt 1/5")
                    await asyncio.sleep(0.5)  # Simulate reconnect delay
                    continue  # Reconnect and resume streaming

            # Create quotes wrapped in a 'content' key
            quotes = {
                "content": [
                    {
                        'key': entry['symbol'],  # Access symbol within each dictionary entry
                        'BID_PRICE': random.uniform(10, 50) if random.choice([True, False]) else None,
                        'ASK_PRICE': random.uniform(10, 50) if random.choice([True, False]) else None,
                        'LAST_PRICE': random.uniform(10, 50) if random.choice([True, False]) else None,
                        'REGULAR_MARKET_LAST_PRICE': random.uniform(10, 50) if random.choice([True, False]) else None
                    }
                    for entry in symbols
                ]
            }


            # await self.quote_manager.add_quotes(quotes)  # Call add_quotes once with the list of quotes
            await quote_handler(quotes)  # Call the quote_handler with the quotes

            await asyncio.sleep(random.uniform(0.01, 0.2))

    async def test_streaming_with_reconnect_and_load(self):
        symbols = [
            {"symbol": "AAPL", "asset_type": "EQUITY"},
            {"symbol": "MSFT", "asset_type": "EQUITY"},
            {"symbol": "GOOGL", "asset_type": "EQUITY"},
            {"symbol": "TSLA", "asset_type": "EQUITY"}
        ]

        # Start the stream
        await self.quote_manager._start_quotes_stream(symbols)
        
        # Verify that callbacks were triggered
        self.assertTrue(self.quote_manager._trigger_callbacks.called)
        self.assertGreaterEqual(self.quote_manager._trigger_callbacks.call_count, 1)

    async def asyncTearDown(self):
        # Clean up or reset mocks if necessary
        pass

# Run the tests
if __name__ == "__main__":
    unittest.main()
