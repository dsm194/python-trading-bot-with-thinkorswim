import asyncio
import random
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest

from mock_objects.mock_streaming_server import MockStreamingServer
from schwab.streaming import StreamClient

from tdameritrade import TDAmeritrade


class TestStreamIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_stream_full_workflow(self):
        """Tests starting and stopping the streaming service with mocked interactions."""

        # Mock necessary dependencies
        mongo_mock = AsyncMock()
        user_mock = MagicMock()
        logger_mock = MagicMock()
        push_notification_mock = MagicMock()

        # Mock TDAmeritrade object as required
        obj = TDAmeritrade(
            async_mongo=mongo_mock,
            user=user_mock,
            account_id='test_account',
            logger=logger_mock,
            push_notification=push_notification_mock
        )

        # Mock stream client
        mock_stream_client = MagicMock()
        mock_stream_client.login = AsyncMock(return_value=None)
        mock_stream_client.logout = AsyncMock(return_value=None)
        mock_stream_client.level_one_equity_add = AsyncMock(return_value=True)
        mock_stream_client.handle_message = AsyncMock(return_value=None)

        obj.stream_client = mock_stream_client
        obj.logger = MagicMock()

        symbols = [
            {"symbol": "AAPL", "asset_type": "EQUITY"},
            {"symbol": "TSLA", "asset_type": "EQUITY"},
        ]
        stop_event = asyncio.Event()
        
        # Start the `start_stream` method in a background task
        stream_task = asyncio.create_task(obj.start_stream(symbols, lambda *args: None, stop_event=stop_event))

        # Stop the stream after a short delay
        async def set_stop_event():
            await asyncio.sleep(1)  # Let the stream run briefly
            stop_event.set()  # Signal the `start_stream` method to stop

        # Run the stop event setter in parallel
        stop_task = asyncio.create_task(set_stop_event())

        # Wait for both tasks to complete
        await asyncio.gather(stream_task, stop_task)
        
        # Validate interactions
        mock_stream_client.login.assert_called_once()
        mock_stream_client.level_one_equity_add.assert_called_once_with(
            ["AAPL", "TSLA"],
            fields=[
                StreamClient.LevelOneEquityFields.SYMBOL,
                StreamClient.LevelOneEquityFields.BID_PRICE,
                StreamClient.LevelOneEquityFields.ASK_PRICE,
                StreamClient.LevelOneEquityFields.LAST_PRICE,
                StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE,
            ],
        )

        # Check that the stream client handled messages
        mock_stream_client.handle_message.assert_called()

    async def test_tdameritrade_streaming_with_dynamic_subscription(self):
        """Tests starting a stream, adding symbols dynamically, and unsubscribing."""

        tracked_tasks = set()
        user_mock = MagicMock()
        logger_mock = MagicMock()
        mongo_mock = AsyncMock()
        push_notification_mock = MagicMock()
        mock_stream_server = MockStreamingServer()  # ✅ Reuse the existing mock server

        # ✅ Use an `AsyncMock` wrapper around the mock server
        mock_stream_client = AsyncMock(wraps=mock_stream_server)

        # ✅ Properly mock the login and streaming methods
        mock_stream_client.login = AsyncMock(side_effect=mock_stream_server.login)
        mock_stream_client.update_subscription = AsyncMock(side_effect=mock_stream_server.update_subscription)
        mock_stream_client.unsubscribe_symbols = AsyncMock(side_effect=mock_stream_server.unsubscribe_symbols)
        mock_stream_client.handle_message = AsyncMock(side_effect=mock_stream_server.handle_message)
        mock_stream_client.add_level_one_equity_handler = MagicMock()

        tdameritrade = TDAmeritrade(
            async_mongo=mongo_mock,
            user=user_mock,
            account_id='test_account',
            logger=logger_mock,
            push_notification=push_notification_mock
        )

        tdameritrade.stream_client = mock_stream_client  # ✅ Ensure correct mock assignment

        # ✅ Generate initial symbols and additional symbols
        def generate_random_ticker():
            return ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=random.randint(2, 5)))

        initial_symbols = [{"symbol": generate_random_ticker(), "asset_type": "EQUITY"} for _ in range(250)]
        new_symbols = [{"symbol": generate_random_ticker(), "asset_type": "EQUITY"} for _ in range(100)]

        # ✅ Track received price updates
        received_quotes = {}

        async def quote_callback(updates):
            """Receives price updates and stores them."""
            # print(f"📩 [TEST] Received quote update: {updates}")  # ✅ Debug
            received_quotes.update(updates)

        mock_stream_server.add_callback(quote_callback)

        test_stop_event = asyncio.Event()

        print(f"🟢 [TEST] Starting stream_task for {len(initial_symbols)} symbols...")
        # ✅ Step 1: Start the streaming service using `start_stream()` instead of `update_subscription()`
        stream_task = asyncio.create_task(tdameritrade.start_stream(
            initial_symbols,
            quote_handler=quote_callback,
            max_retries=5,
            stop_event=test_stop_event,
            initialized_event=asyncio.Event(),
            reset_event=asyncio.Event(),
        ))
        print(f"🔵 [TEST] stream_task created: {stream_task}")

        # ✅ Step 2: Track the task in a set to prevent unittest cleanup
        tracked_tasks.add(stream_task)

        try:
            # ✅ Wait for the stream to fully initialize before checking updates
            await asyncio.sleep(5)  # Give time for the streaming service to start

            print("🟡 [TEST] Waiting for first price update...")
            await asyncio.sleep(5)  # Give more time for quotes to be received

            print(f"🟡 [TEST] stream_task status: {stream_task.done()}")

            # ✅ Log received quotes
            # print(f"📊 [TEST] received_quotes before assertion: {received_quotes}")

            assert len(received_quotes) > 0, "No price updates received for initial symbols!"

            # ✅ Step 2: Add new symbols dynamically using `update_subscription()`
            await tdameritrade.update_subscription(new_symbols)
            await asyncio.sleep(5)  # ✅ Allow time for updates

            # ✅ Ensure new symbols are receiving updates
            for symbol_entry in new_symbols:
                assert symbol_entry["symbol"] in received_quotes, f"New symbol {symbol_entry['symbol']} did not receive updates!"

            # ✅ Step 3: Unsubscribe from half the symbols
            to_unsubscribe = initial_symbols[:125] + new_symbols[:50]  # Keep full dicts!
            await tdameritrade.unsubscribe_symbols(to_unsubscribe)

            # ✅ Ensure the unsubscribed symbols stop receiving updates
            received_quotes.clear()
            await asyncio.sleep(5)

            for symbol_entry in to_unsubscribe:
                assert symbol_entry["symbol"] not in received_quotes, f"Unsubscribed symbol {symbol_entry['symbol']} still receiving updates!"

            # ✅ Stop the streaming service properly
            await mock_stream_server.stop()
        finally:
            print("🛑 [TEST] Stopping stream...")

            # ✅ Trigger stop event to break the loop in start_stream()
            test_stop_event.set()

            # ✅ Allow a moment for the stream task to complete
            await asyncio.sleep(2)

            # ✅ Ensure stream_task is awaited before cleanup
            if not stream_task.done():
                stream_task.cancel()

            await asyncio.gather(stream_task, return_exceptions=True)
            tracked_tasks.discard(stream_task)  # Cleanup task reference

            print("✅ Stream stopped successfully.")


        print("✅ Dynamic subscription test passed!")

