import os
import unittest
from unittest.mock import MagicMock, patch

from assets.pushsafer import PushNotification


class TestPushNotification(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    @patch("assets.pushsafer.requests.post")
    def test_send_skips_request_when_not_configured(self, mock_post):
        logger = MagicMock()
        notification = PushNotification(device_id="", logger=logger)

        sent = notification.send("test")

        self.assertFalse(sent)
        mock_post.assert_not_called()
        logger.warning.assert_called_once_with(
            "Pushsafer is not configured; notification was not sent."
        )

    @patch.dict(os.environ, {"PUSH_API_KEY": "private-key"}, clear=True)
    @patch("assets.pushsafer.requests.post")
    def test_send_uses_timeout_and_returns_success(self, mock_post):
        logger = MagicMock()
        response = MagicMock()
        response.json.return_value = {"success": "message transmitted"}
        mock_post.return_value = response
        notification = PushNotification(device_id="42", logger=logger)

        sent = notification.send("test message")

        self.assertTrue(sent)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["data"]["k"], "private-key")
        self.assertEqual(kwargs["data"]["d"], "42")
        self.assertEqual(kwargs["data"]["m"], "test message")
