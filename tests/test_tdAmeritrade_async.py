import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tdameritrade import TDAmeritrade

class TestTDAmeritrade(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock dependencies
        self.mongo_mock = MagicMock()
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
            mongo=self.mongo_mock, 
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
    async def test_safe_connect_to_streaming_failure(self, mock_connect_to_streaming):
        # Verify exception handling and logging in case of connection error
        await self.td._safe_connect_to_streaming()
        mock_connect_to_streaming.assert_called_once()
        self.td.logger.error.assert_called_once_with("Failed to connect to streaming: Connection error")

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
        self.td.logger.error.assert_called_once_with("Failed to disconnect to streaming: Disconnection error")

if __name__ == "__main__":
    unittest.main()
