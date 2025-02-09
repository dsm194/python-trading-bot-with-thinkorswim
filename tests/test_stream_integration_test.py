import asyncio
import random
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets

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
        mock_stream_client.level_one_option_add = AsyncMock(return_value=True)
        mock_stream_client.handle_message = AsyncMock(return_value=None)

        obj.stream_client = mock_stream_client
        obj.logger = MagicMock()

        symbols = [
            {"symbol": "AAPL", "asset_type": "EQUITY"},
            {"symbol": "TSLA", "asset_type": "EQUITY"},
            {"symbol": ".LRCX250131C71", "asset_type": "OPTION"},
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
        mock_stream_client.level_one_option_add.assert_called_once_with(
            [".LRCX250131C71"],
            fields=[
                StreamClient.LevelOneOptionFields.SYMBOL,
                StreamClient.LevelOneOptionFields.BID_PRICE,
                StreamClient.LevelOneOptionFields.ASK_PRICE,
                StreamClient.LevelOneOptionFields.LAST_PRICE,
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
        mock_stream_client.add_level_one_option_handler = MagicMock()
        mock_stream_client._socket = MagicMock()

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
        test_stream_initialized_event = asyncio.Event()

        print(f"🟢 [TEST] Starting stream_task for {len(initial_symbols)} symbols...")
        # ✅ Step 1: Start the streaming service using `start_stream()` instead of `update_subscription()`
        stream_task = asyncio.create_task(tdameritrade.start_stream(
            initial_symbols,
            quote_handler=quote_callback,
            max_retries=5,
            stop_event=test_stop_event,
            initialized_event=test_stream_initialized_event,
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

            # ✅ Step 2a: Add new stock symbols dynamically using `update_subscription()`
            await tdameritrade.update_subscription(new_symbols)
            await asyncio.sleep(5)  # ✅ Allow time for updates

            # ✅ Ensure new symbols are receiving updates
            for symbol_entry in new_symbols:
                assert symbol_entry["symbol"] in received_quotes, f"New symbol {symbol_entry['symbol']} did not receive updates!"

            # ✅ Step 2b: Add new options symbols dynamically using `update_subscription()`
            new_options = [{"symbol": generate_random_ticker(), "asset_type": "OPTION"} for _ in range(10)]
            await tdameritrade.update_subscription(new_options)
            await asyncio.sleep(5)  # ✅ Allow time for updates

            # ✅ Ensure new symbols are receiving updates
            for symbol_entry in new_options:
                assert symbol_entry["symbol"] in received_quotes, f"New symbol {symbol_entry['symbol']} did not receive updates!"

            # ✅ Step 3: Simulate WebSocket Failure Mid-Unsubscribe

            async def failing_unsubscribe(symbols):
                try:
                    await asyncio.sleep(2)  # ✅ Ensure enough time for cancellation
                    raise websockets.exceptions.ConnectionClosedError(1011, 1011, False)
                except asyncio.CancelledError:
                    print("🚨 [TEST] Task was actually canceled!")
                    raise  # ✅ Allow proper cancellation

            mock_stream_client._socket.state = 3
            # mock_stream_client.level_one_equity_unsubs.side_effect = failing_unsubscribe

            print(f"🟡 [TEST] Running multiple simultaneous unsubscribe requests...")

            unsubscribe_tasks = []

            # 🔥 Create multiple concurrent unsubscribe calls for the same symbol
            for _ in range(5):
                task = asyncio.create_task(tdameritrade.unsubscribe_symbols([initial_symbols[5]]))
                unsubscribe_tasks.append(task)

            task = asyncio.create_task(tdameritrade.unsubscribe_symbols([new_options[5]]))
            unsubscribe_tasks.append(task)

            # ✅ Allow all tasks to start running
            await asyncio.sleep(0.1)  # 🔥 Reduce sleep to force concurrency
            test_stream_initialized_event.set()

            # # ✅ Actively cancel 3 of them
            # print(f"⚠️ [TEST] Randomly canceling some unsubscribe tasks now...")
            # for task in unsubscribe_tasks[:3]:  # 🔥 Cancel first 3
            #     task.cancel()

            # ✅ Wait for all tasks and **DO NOT use return_exceptions=True** (we WANT exceptions!)
            try:
                results = await asyncio.gather(*unsubscribe_tasks)
            except Exception as e:
                print(f"🚨 [TEST] Caught unexpected failure: {e}")
                raise  # 🔥 Force the test to fail if we hit an unknown state

            print("✅ [TEST] If we get here, the system didn't break.")

            # ✅ Ensure that we recovered from the failure
            mock_stream_client._socket.state = 1
            mock_stream_client.level_one_equity_unsubs.side_effect = mock_stream_server.level_one_equity_unsubs
            await tdameritrade.unsubscribe_symbols([initial_symbols[5]])

            print(f"✅ [TEST] Successfully recovered from failed unsubscribe.")

            # ✅ Step 4: Unsubscribe from half the symbols
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