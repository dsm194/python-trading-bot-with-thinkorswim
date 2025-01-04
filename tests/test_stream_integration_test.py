import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from tdameritrade import TDAmeritrade
from schwab.streaming import StreamClient


class TestStreamIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_stream_full_workflow(self):
        # Mock necessary dependencies
        self.mongo_mock = AsyncMock()
        self.user_mock = MagicMock()
        self.logger_mock = MagicMock()
        self.push_notification_mock = MagicMock()

        # Mock TDAmeritrade object as required
        obj = TDAmeritrade(
            async_mongo=self.mongo_mock,
            user=self.user_mock,
            account_id='test_account',
            logger=self.logger_mock,
            push_notification=self.push_notification_mock
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
