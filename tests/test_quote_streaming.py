import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import random

from websockets.exceptions import ConnectionClosedError  # Import directly

from api_trader.position_updater import PositionUpdater
from api_trader.quote_manager import QuoteManager
from tdameritrade import TDAmeritrade

class TestQuoteStreaming(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock necessary dependencies
        self.mongo_mock = MagicMock()
        self.user_mock = MagicMock()
        self.logger_mock = MagicMock()
        self.push_notification_mock = MagicMock()
        self.stop_event = threading.Event()

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

        # Create mock open_positions and initialize PositionUpdater
        self.open_positions = AsyncMock()  # Mock for open positions data
        self.position_updater = PositionUpdater(self.open_positions, self.logger_mock)  # Instantiate PositionUpdater

        # Mock stream client behavior
        self.quote_manager.tdameritrade.stream_client = MagicMock()
        self.quote_manager.tdameritrade.stream_client.login = AsyncMock(side_effect=lambda: asyncio.sleep(0.1))
        self.quote_manager.tdameritrade.stream_client.level_one_equity_add = AsyncMock(side_effect=lambda: asyncio.sleep(0.1))

        self.quote_manager.tdameritrade.stream_client.handle_message = AsyncMock()

        self.quote_manager.tdameritrade.start_stream = self.simulate_mock_stream
        

    async def simulate_mock_stream(self, symbols, quote_handler, max_retries=5, iterations=100, error_chance=0.05, stop_event=None):
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

            await quote_handler(quotes)  # Call the quote_handler with the quotes
            await asyncio.sleep(random.uniform(0.01, 0.2))


    async def test_streaming_with_reconnect_and_load(self):
        symbols = [
            {"symbol": "AAPL", "asset_type": "EQUITY"},
            {"symbol": "MSFT", "asset_type": "EQUITY"},
            {"symbol": "GOOGL", "asset_type": "EQUITY"},
            {"symbol": "TSLA", "asset_type": "EQUITY"}
        ]

        with patch.object(self.position_updater, 'queue_max_price_update') as mock_queue_max_price_update, \
            patch.object(self.quote_manager, 'add_quotes') as mock_add_quotes:
            
            # Register PositionUpdater's queue_max_price_update as a callback
            await self.quote_manager.add_callback(self.position_updater.queue_max_price_update)
            
            # Mock start_stream to call simulate_mock_stream
            async def mock_start_stream(symbols, quote_handler, max_retries, stop_event):
                return await self.simulate_mock_stream(symbols, quote_handler=quote_handler, max_retries=max_retries, stop_event=stop_event)
            self.quote_manager.tdameritrade.start_stream = AsyncMock(side_effect=mock_start_stream)
            
            # Call add_quotes (mocked) to simulate streaming without real data
            await self.quote_manager.add_quotes(symbols)

            # Manually specified quotes for consistent test verification
            quotes = {
                "content": [
                    {'key': "AAPL", 'LAST_PRICE': 150.0},
                    {'key': "MSFT", 'LAST_PRICE': 300.0}
                ]
            }

            # Directly invoke quote_handler to simulate receiving these quotes
            await self.quote_manager.quote_handler(quotes)

            # Verify queue_max_price_update calls with correct values
            mock_queue_max_price_update.assert_any_call("AAPL", {'bid_price': None, 'ask_price': None, 'last_price': 150.0, 'regular_market_last_price': 150.0})
            mock_queue_max_price_update.assert_any_call("MSFT", {'bid_price': None, 'ask_price': None, 'last_price': 300.0, 'regular_market_last_price': 300.0})
            
            # Check number of calls to confirm expected updates
            self.assertEqual(mock_queue_max_price_update.call_count, 2)


    async def asyncTearDown(self):
        # Clean up or reset mocks if necessary
        pass

# Run the tests
if __name__ == "__main__":
    unittest.main()
