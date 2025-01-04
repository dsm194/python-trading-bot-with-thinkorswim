import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from assets.helper_functions import modifiedAccountID
from tdameritrade import TDAmeritrade

class TestTDAmeritrade(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock dependencies
        self.mongo_mock = AsyncMock()
        self.logger_mock = MagicMock()
        self.push_notification_mock = MagicMock()

        # Mock user dictionary
        self.user_mock = {
            "Name": "TestUser",
            "ClientID": "TestClientID",
            "Accounts": {
                "test_account_id": {
                    "token_path": "test_token_path"
                }
            }
        }

        # Mock account_id
        self.account_id = "test_account_id"
        
        # Instantiate TDAmeritrade with mock objects
        self.td = TDAmeritrade(
            async_mongo=self.mongo_mock, 
            user=self.user_mock, 
            account_id=self.account_id, 
            logger=self.logger_mock, 
            push_notification=self.push_notification_mock
        )
        # Mock the stream_client and logger
        self.td.stream_client = AsyncMock()
        self.td.logger = MagicMock()

    @patch.object(TDAmeritrade, 'connect_to_streaming', new_callable=AsyncMock)
    async def test_safe_connect_to_streaming_success(self, mock_connect_to_streaming):
        # Ensure connect_to_streaming runs without exception
        await self.td._safe_connect_to_streaming()
        mock_connect_to_streaming.assert_called_once()

    @patch.object(TDAmeritrade, 'connect_to_streaming', side_effect=Exception("Connection error"))
    @patch('asyncio.sleep', return_value=None)  # Prevent actual delays during the test
    async def test_safe_connect_to_streaming_failure(self, mock_sleep, mock_connect_to_streaming):
        # Mock the logger
        self.td.logger = MagicMock()

        # Call the method and expect it to raise a RuntimeError
        with self.assertRaises(RuntimeError) as context:
            await self.td._safe_connect_to_streaming()

        # Verify the exception message
        self.assertEqual(str(context.exception), f"Failed to reconnect after retries. ({modifiedAccountID(self.td.account_id)})")

        # Ensure the connect_to_streaming method was called the correct number of times
        self.assertEqual(mock_connect_to_streaming.call_count, 3)

        # Ensure the logger.error was called for each failed attempt
        expected_error_calls = [
            (f"Reconnect attempt 1 failed: Connection error ({modifiedAccountID(self.td.account_id)})",),
            (f"Reconnect attempt 2 failed: Connection error ({modifiedAccountID(self.td.account_id)})",),
            (f"Reconnect attempt 3 failed: Connection error ({modifiedAccountID(self.td.account_id)})",)
        ]
        self.td.logger.error.assert_has_calls([unittest.mock.call(msg[0]) for msg in expected_error_calls])

        # Verify no additional calls to sleep beyond the retry limit
        self.assertEqual(mock_sleep.call_count, 2)  # Retries are 3, so sleeps are 2


    @patch.object(TDAmeritrade, 'disconnect_streaming', new_callable=AsyncMock)
    async def test_safe_disconnect_streaming_success(self, mock_disconnect_streaming):
        # Ensure disconnect_streaming runs without exception
        await self.td._safe_disconnect_streaming()
        mock_disconnect_streaming.assert_called_once()

    @patch.object(TDAmeritrade, 'disconnect_streaming', side_effect=Exception("Disconnection error"))
    async def test_safe_disconnect_streaming_failure(self, mock_disconnect_streaming):
        # Verify exception handling and logging in case of disconnection error
        await self.td._safe_disconnect_streaming()
        mock_disconnect_streaming.assert_called_once()
        self.td.logger.error.assert_called_once_with(f"Failed to disconnect to streaming: Disconnection error ({modifiedAccountID(self.td.account_id)})")

if __name__ == "__main__":
    unittest.main()
