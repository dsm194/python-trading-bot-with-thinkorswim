import asyncio
import random
import string
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from mock_objects.mock_streaming_server import MockStreamingServer

from api_trader.quote_manager import QuoteManager


class TestQuoteManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock necessary dependencies
        self.logger_mock = MagicMock()
        self.tdameritrade_mock = AsyncMock()
        self.tdameritrade_mock.async_client.token_metadata.token = {"id_token": "mocked_token"}
        self.quote_manager = QuoteManager(tdameritrade=self.tdameritrade_mock, logger=self.logger_mock)

    async def test_extract_underlying_account_id_success(self):
        """Test successful extraction of underlying account ID."""
        token_metadata = {"id_token": jwt.encode({"sub": "account123"}, "secret", algorithm="HS256")}
        account_id = QuoteManager._extract_underlying_account_id(token_metadata, self.logger_mock)
        self.assertEqual(account_id, "account123")

    async def test_extract_underlying_account_id_failure(self):
        """Test failure to extract underlying account ID."""
        token_metadata = {"id_token": "invalid_token"}
        account_id = QuoteManager._extract_underlying_account_id(token_metadata, self.logger_mock)
        self.assertIsNone(account_id)
        self.logger_mock.error.assert_called_with("Failed to extract underlying account ID: Not enough segments")

    async def test_add_callback(self):
        """Test adding a callback function."""
        async def mock_callback(symbol, quote):
            pass

        await self.quote_manager.add_callback(mock_callback)
        self.assertIn(mock_callback, self.quote_manager.callbacks)

    async def test_add_quotes_start_stream(self):
        """Test adding quotes when streaming has not started."""
        symbols = [{"symbol": "AAPL", "asset_type": "EQUITY"}]

        with patch.object(self.quote_manager, '_start_quotes_stream') as mock_start_stream:
            await self.quote_manager.add_quotes(symbols)
            mock_start_stream.assert_called_once_with(symbols)

    async def test_add_quotes_update_subscription(self):
        """Test adding quotes when streaming has already started."""
        symbols = [{"symbol": "AAPL", "asset_type": "EQUITY"}]
        self.quote_manager.is_streaming = True

        with patch.object(self.quote_manager, '_update_stream_subscription') as mock_update_subscription:
            await self.quote_manager.add_quotes(symbols)
            mock_update_subscription.assert_called_once_with(symbols)

    async def test_quote_handler_updates_quotes(self):
        """Test the quote_handler updates quotes and debounce cache."""
        quotes = {
            "content": [
                {'key': "AAPL", 'BID_PRICE': 150.0, 'ASK_PRICE': 155.0, 'LAST_PRICE': 152.0, 'REGULAR_MARKET_LAST_PRICE': 152.0},
                {'key': "MSFT", 'BID_PRICE': None, 'ASK_PRICE': 250.0, 'LAST_PRICE': 245.0, 'REGULAR_MARKET_LAST_PRICE': None}
            ]
        }

        await self.quote_manager.quote_handler(quotes)

        # Verify updates in quotes and debounce_cache
        self.assertIn("AAPL", self.quote_manager.quotes)
        self.assertEqual(self.quote_manager.quotes["AAPL"], {
            'bid_price': 150.0,
            'ask_price': 155.0,
            'last_price': 152.0,
            'regular_market_last_price': 152.0,
        })

        self.assertIn("MSFT", self.quote_manager.quotes)
        self.assertEqual(self.quote_manager.quotes["MSFT"], {
            'bid_price': None,
            'ask_price': 250.0,
            'last_price': 245.0,
            'regular_market_last_price': 245.0,
        })

    async def test_trigger_callbacks(self):
        """Test triggering callbacks for a given symbol."""
        async def mock_callback(symbol, quote):
            self.logger_mock.info(f"Callback triggered for {symbol} with quote {quote}")

        await self.quote_manager.add_callback(mock_callback)

        quote = {'bid_price': 150.0, 'ask_price': 155.0, 'last_price': 152.0, 'regular_market_last_price': 152.0}
        await self.quote_manager._trigger_callbacks("AAPL", quote)

        self.logger_mock.info.assert_called_with("Callback triggered for AAPL with quote {'bid_price': 150.0, 'ask_price': 155.0, 'last_price': 152.0, 'regular_market_last_price': 152.0}")

    async def test_stop_streaming(self):
        """Test stopping the streaming process and resource cleanup."""
        self.quote_manager.is_streaming = True

        with patch.object(self.quote_manager.executor, 'shutdown') as mock_shutdown:
            await self.quote_manager.stop_streaming()

            self.assertFalse(self.quote_manager.is_streaming)
            mock_shutdown.assert_called_once()

    async def test_start_quotes_stream(self):
        """Test starting the quotes stream."""
        symbols = [{"symbol": "AAPL", "asset_type": "EQUITY"}]

        with patch.object(self.tdameritrade_mock, 'start_stream', AsyncMock()) as mock_start_stream:
            await self.quote_manager._start_quotes_stream(symbols)
            mock_start_stream.assert_called_once_with(
                symbols,
                quote_handler=self.quote_manager.quote_handler,
                max_retries=5,
                stop_event=self.quote_manager.stop_event,
                initialized_event=self.quote_manager.stream_initialized,
                reset_event=self.quote_manager.reset_event
            )

    async def test_update_stream_subscription(self):
        """Test updating the stream subscription."""
        symbols = [{"symbol": "AAPL", "asset_type": "EQUITY"}]
        self.quote_manager.stream_initialized.set()  # Simulate stream initialization

        with patch.object(self.tdameritrade_mock, 'update_subscription', AsyncMock()) as mock_update_subscription:
            await self.quote_manager._update_stream_subscription(symbols)
            mock_update_subscription.assert_called_once_with(symbols)

    async def test_quote_streaming_and_unsubscribe(self):
        """Tests subscribing, receiving price updates, and unsubscribing using a mock stream."""
        
        mock_stream_server = MockStreamingServer()

        # ✅ Mock `tdameritrade` to behave like `MockStreamingServer`
        self.tdameritrade_mock.update_subscription = AsyncMock(side_effect=mock_stream_server.update_subscription)
        self.tdameritrade_mock.unsubscribe_symbols = AsyncMock(side_effect=mock_stream_server.unsubscribe_symbols)
        self.tdameritrade_mock.start_stream = AsyncMock(side_effect=mock_stream_server.start_stream)

        # ✅ Generate 1000 random stock tickers
        def generate_random_ticker():
            return ''.join(random.choices(string.ascii_uppercase, k=random.randint(2, 5)))

        symbols = [{"symbol": generate_random_ticker(), "asset_type": "EQUITY"} for _ in range(1000)]

        # ✅ Track received price updates
        received_quotes = {}

        async def quote_callback(updates):
            """Receives price updates and stores them."""
            received_quotes.update(updates)

        mock_stream_server.add_callback(quote_callback)

        # ✅ Start the streaming service in the background
        # ✅ Start the streaming service properly using `start_stream()` instead of `start()`
        stream_task = asyncio.create_task(mock_stream_server.start_stream(
            symbols,
            quote_handler=quote_callback,
            max_retries=5,
            stop_event=asyncio.Event(),
            initialized_event=asyncio.Event(),
            reset_event=asyncio.Event(),
        ))

        # ✅ Subscribe to symbols
        await self.quote_manager.add_quotes(symbols)

        # ✅ Allow some time for updates to arrive
        await asyncio.sleep(5)

        # ✅ Verify that updates have been received
        assert len(received_quotes) > 0, "No price updates received!"

        # ✅ Unsubscribe from half the symbols
        to_unsubscribe = [s["symbol"] for s in symbols[:500]]
        await self.quote_manager.unsubscribe(to_unsubscribe)

        # ✅ Ensure the unsubscribed symbols stop receiving updates
        received_quotes.clear()
        await asyncio.sleep(5)  # ✅ Wait for another round of updates

        for symbol in to_unsubscribe:
            assert symbol not in received_quotes, f"Unsubscribed symbol {symbol} still receiving updates!"

        # ✅ Stop the streaming service
        await mock_stream_server.stop()
        stream_task.cancel()

        print("✅ Streaming and unsubscribe test passed!")

    async def asyncTearDown(self):
        await self.quote_manager.stop_streaming()

# Run the tests
if __name__ == "__main__":
    unittest.main()
