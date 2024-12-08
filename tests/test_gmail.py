import asyncio
import unittest
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime
from gmail import Gmail  # Assuming your class is in a file named gmail.py

class TestGmail(unittest.TestCase):

    def setUp(self):
        """Set up an instance of Gmail for testing."""
        
        # Mock the logger
        self.mock_logger = MagicMock()

        # Create an instance of Gmail with the mock logger
        self.gmail = Gmail(logger=self.mock_logger)

        # Mock any additional attributes if necessary (creds, service, etc.)
        self.gmail.creds = MagicMock()
        self.mock_service = MagicMock()
        self.gmail.service = self.mock_service



    @patch("gmail.os.path.exists")
    @patch("gmail.open", new_callable=mock_open)
    @patch("gmail.Credentials.from_authorized_user_file")
    @patch("gmail.InstalledAppFlow.from_client_secrets_file")
    @patch("gmail.build")
    def test_connect_with_valid_token(self, mock_build, mock_installed_flow, mock_from_authorized_file, mock_open_func, mock_path_exists):
        """Test connect method when the token file is present and valid."""
        
        # Simulate the token file existing
        mock_path_exists.return_value = True

        # Mock the credentials returned from the token file
        mock_creds = MagicMock()
        mock_from_authorized_file.return_value = mock_creds

        # Simulate valid, non-expired credentials
        mock_creds.expired = False
        mock_creds.refresh_token = False

        # Call the connect method
        result = self.gmail.connect()

        # Assert the method was successful
        self.assertTrue(result)

        # Assert the logger was called to log success
        self.mock_logger.info.assert_called_with("CONNECTED TO GMAIL!\n", extra={'log': False})

        # Ensure the service was built using the credentials
        mock_build.assert_called_with('gmail', 'v1', credentials=mock_creds)


    @patch("gmail.os.path.exists")
    @patch("gmail.open", new_callable=mock_open)
    @patch("gmail.Credentials.from_authorized_user_file")
    @patch("gmail.InstalledAppFlow.from_client_secrets_file")
    @patch("gmail.build")
    def test_connect_without_token_file(self, mock_build, mock_installed_flow, mock_from_authorized_file, mock_open_func, mock_path_exists):
        """Test connect method when the token file is not present, triggering authentication flow."""
        
        # Simulate the token file not existing
        mock_path_exists.return_value = False

        # Mock the flow and credentials
        mock_flow = MagicMock()
        mock_installed_flow.return_value = mock_flow

        # Mock the credentials that will be returned from run_local_server
        mock_creds = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds  # Ensures the returned credentials are consistent

        # Should force us to call InstalledAppFlow...
        self.gmail.creds = None

        # Call the connect method
        result = self.gmail.connect()

        # Assert the method was successful
        self.assertTrue(result)

        # Assert the logger was called to log success
        self.mock_logger.info.assert_called_with("CONNECTED TO GMAIL!\n", extra={'log': False})

        # Ensure the service was built using the credentials returned by run_local_server()
        mock_build.assert_called_with('gmail', 'v1', credentials=mock_creds)

        # Ensure the flow was called
        mock_installed_flow.assert_called_with(self.gmail.creds_file, self.gmail.SCOPES)


    @patch("gmail.os.path.exists")
    @patch("gmail.open", new_callable=mock_open)
    @patch("gmail.Credentials.from_authorized_user_file")
    @patch("gmail.InstalledAppFlow.from_client_secrets_file")
    @patch("gmail.Request")
    @patch("gmail.build")
    def test_connect_with_expired_creds(self, mock_build, mock_request, mock_installed_flow, mock_from_authorized_file, mock_open_func, mock_path_exists):
        """Test connect method when the credentials are expired and need to be refreshed."""
        
        # Simulate the token file existing
        mock_path_exists.return_value = True

        # Mock the credentials returned from the token file
        mock_creds = MagicMock()
        mock_from_authorized_file.return_value = mock_creds

        # Simulate expired credentials with a refresh token
        mock_creds.expired = True
        mock_creds.refresh_token = True

        # Mock the refresh method
        mock_creds.refresh = MagicMock()

        # Call the connect method
        result = self.gmail.connect()

        # Assert the method was successful
        self.assertTrue(result)

        # Assert the refresh method was called
        mock_creds.refresh.assert_called_once_with(mock_request())

        # Ensure the service was built using the refreshed credentials
        mock_build.assert_called_with('gmail', 'v1', credentials=mock_creds)


    @patch("gmail.os.path.exists")
    @patch("gmail.open", new_callable=mock_open)
    @patch("gmail.Credentials.from_authorized_user_file")
    @patch("gmail.InstalledAppFlow.from_client_secrets_file")
    @patch("gmail.build")
    def test_connect_fail(self, mock_build, mock_installed_flow, mock_from_authorized_file, mock_open_func, mock_path_exists):
        """Test connect method when an exception occurs."""
        
        # Simulate an exception being raised in the credentials retrieval
        mock_path_exists.side_effect = Exception("Token file access error")

        # Call the connect method
        result = self.gmail.connect()

        # Assert the method failed
        self.assertFalse(result)

        # Assert the logger was called to log the error
        self.mock_logger.error.assert_called_with("FAILED TO CONNECT TO GMAIL! - Token file access error\n", extra={'log': False})


    @patch("gmail.os.path.exists")
    @patch("gmail.open", new_callable=mock_open)
    @patch("gmail.Credentials.from_authorized_user_file")
    @patch("gmail.InstalledAppFlow.from_client_secrets_file")
    @patch("gmail.build")
    def test_connect_creds_not_found_exception(self, mock_build, mock_installed_flow, mock_from_authorized_file, mock_open_func, mock_path_exists):
        """Test connect method when creds are not found, raising an exception."""
        
        # Simulate the token file not existing
        mock_path_exists.return_value = False

        # Simulate creds being None after trying to retrieve them
        self.gmail.creds = None  # Simulate that credentials are never set

        # Simulate the flow returning None for credentials (fail authentication)
        mock_installed_flow.return_value.run_local_server.return_value = None

        # Call the connect method
        result = self.gmail.connect()

        # Assert the method failed due to the exception
        self.assertFalse(result)

        # Assert the logger was called to log the exception with "Creds Not Found!"
        self.mock_logger.error.assert_called_with(
            "FAILED TO CONNECT TO GMAIL! - Creds Not Found!\n", extra={'log': False}
        )


    def test_getEmails_no_emails(self):
        asyncio.run(self.async_test_getEmails_no_emails())

    @patch("gmail.Gmail.extractSymbolsFromEmails")
    async def async_test_getEmails_no_emails(self, mock_extract):
        """Test getEmails when there are no emails (resultSizeEstimate = 0)."""
        
        # Mock the response to simulate no emails in the inbox
        self.mock_service.users().messages().list().execute.return_value = {"resultSizeEstimate": 0}

        # Call the getEmails method
        result = await self.gmail.getEmails()

        # Assert extractSymbolsFromEmails was called with an empty list
        mock_extract.assert_called_once_with([])

        # Assert the result is what extractSymbolsFromEmails returned (empty in this case)
        self.assertEqual(result, mock_extract.return_value)


    def test_getEmails_with_emails(self):
        asyncio.run(self.async_test_getEmails_with_emails())

    @patch("gmail.Gmail.extractSymbolsFromEmails")
    async def async_test_getEmails_with_emails(self, mock_extract):
        """Test getEmails when emails are retrieved and processed."""
        
        # Mock the list of emails returned by the API
        self.mock_service.users().messages().list().execute.return_value = {
            "resultSizeEstimate": 2,
            "messages": [
                {"id": "123abc", "threadId": "thread1"},
                {"id": "456def", "threadId": "thread2"},
            ],
        }

        # Mock individual email details
        self.mock_service.users().messages().get().execute.side_effect = [
            {"payload": {"headers": [{"name": "Subject", "value": "Email 1 Subject"}]}},
            {"payload": {"headers": [{"name": "Subject", "value": "Email 2 Subject"}]}},
        ]

        # Call the getEmails method
        result = await self.gmail.getEmails()

        # Assert that the subjects were extracted
        mock_extract.assert_called_once_with(["Email 1 Subject", "Email 2 Subject"])

        # Assert that emails were moved to the trash
        self.mock_service.users().messages().trash.assert_any_call(userId='me', id='123abc')
        self.mock_service.users().messages().trash.assert_any_call(userId='me', id='456def')

        # Assert the result is what extractSymbolsFromEmails returned
        self.assertEqual(result, mock_extract.return_value)


    def test_getEmails_exception_handling(self):
        asyncio.run(self.async_test_getEmails_exception_handling())

    @patch("gmail.Gmail.extractSymbolsFromEmails")
    async def async_test_getEmails_exception_handling(self, mock_extract):
        """Test getEmails when an exception occurs."""
        
        # Simulate an exception being raised during the API call
        self.mock_service.users().messages().list().execute.side_effect = Exception("API Error")

        # Call the getEmails method
        result = await self.gmail.getEmails()

        # Assert the logger recorded the error
        self.mock_logger.error.assert_called_with(f"Error fetching email list: API Error")

        # Assert that extractSymbolsFromEmails was called with an empty list
        mock_extract.assert_called_once_with([])

        # Assert the result is what extractSymbolsFromEmails returned
        self.assertEqual(result, mock_extract.return_value)


    @patch("gmail.Gmail.translate_option_symbol")
    def test_extractSymbolsFromEmails_valid(self, mock_translate):
        """Test extractSymbolsFromEmails with valid email payloads."""
        payloads = [
            "Alert: New Symbol: ABC was added to LinRegEMA_v2, BUY",
            "Alert: New Symbol: XYZ were added to LinRegEMA_v2, SELL"
        ]
        mock_translate.return_value = ("ABC", "ABC", None, None)  # Mock the translate function output

        result = self.gmail.extractSymbolsFromEmails(payloads)

        expected = [
            {"Symbol": "ABC", "Side": "BUY", "Strategy": "LINREGEMA_V2", "Asset_Type": "EQUITY"},
            {"Symbol": "XYZ", "Side": "SELL", "Strategy": "LINREGEMA_V2", "Asset_Type": "EQUITY"},
        ]
        self.assertEqual(result, expected)


    @patch("gmail.Gmail.translate_option_symbol")
    def test_extractSymbolsFromEmails_option_symbol(self, mock_translate):
        """Test extractSymbolsFromEmails with an option symbol."""
        payloads = [
            "Alert: New Symbol: AAPL.1234 was added to LinRegEMA_v2, BUY"
        ]
        mock_translate.return_value = ("AAPL", "AAPL", "2024-10-01", "CALL")

        result = self.gmail.extractSymbolsFromEmails(payloads)

        expected = [
            {"Symbol": "AAPL", "Pre_Symbol": "AAPL", "Exp_Date": "2024-10-01", "Option_Type": "CALL", "Side": "BUY", "Strategy": "LINREGEMA_V2", "Asset_Type": "OPTION"},
        ]
        self.assertEqual(result, expected)


    def test_extractSymbolsFromEmails_invalid_format(self):
        """Test extractSymbolsFromEmails with an invalid email format."""
        payloads = [
            "Invalid format string"
        ]
        
        result = self.gmail.extractSymbolsFromEmails(payloads)

        self.assertEqual(result, [])
        self.gmail.logger.warning.assert_called_once()  # Ensure warning was logged


    def test_extractSymbolsFromEmails_missing_fields(self):
        """Test extractSymbolsFromEmails with missing fields."""
        payloads = [
            "Alert: New Symbol: ABC was added to LinRegEMA_v2,"
        ]

        result = self.gmail.extractSymbolsFromEmails(payloads)

        self.assertEqual(result, [])
        self.gmail.logger.warning.assert_called_once()  # Ensure warning was logged


    def test_extractSymbolsFromEmails_logical_match_failure(self):
        """Test extractSymbolsFromEmails with a logical match failure."""
        payloads = [
            "Alert: New Symbol: ABC was added to LinRegEMA_v2, UNKNOWN"
        ]

        result = self.gmail.extractSymbolsFromEmails(payloads)

        self.assertEqual(result, [])
        self.gmail.logger.warning.assert_called_once()  # Ensure warning was logged


    def test_extractSymbolsFromEmails_empty_payloads(self):
        """Test extractSymbolsFromEmails with empty payloads."""
        payloads = []

        result = self.gmail.extractSymbolsFromEmails(payloads)

        self.assertEqual(result, [])


    @patch("gmail.Gmail.translate_option_symbol")
    def test_extractSymbolsFromEmails_index_error(self, mock_translate):
        """Test extractSymbolsFromEmails for handling IndexError gracefully."""
        
        # Simulate a valid payload and an invalid payload
        payloads = [
            "Alert: New Symbol: .ABC was added to LinRegEMA_v2, BUY",
        ]

        mock_translate.side_effect = IndexError("Generic error")

        result = self.gmail.extractSymbolsFromEmails(payloads)

        self.assertEqual(result, [])
        
        # Ensure no warnings were logged for the invalid payload
        self.gmail.logger.warning.assert_not_called()


    @patch("gmail.Gmail.translate_option_symbol")
    def test_extractSymbolsFromEmails_value_error(self, mock_translate):
        """Test extractSymbolsFromEmails for handling ValueError."""
        
        # Simulate a valid payload and a malformed payload
        payloads = [
            "Alert: New Symbol: ABC was added to LinRegEMA_v2, BUY", 
            "Alert: New Symbol: XYZ was added to LinRegEMA_v2,,"  # Double comma leading to ValueError
        ]

        mock_translate.return_value = ("ABC", "ABC", "2024-12-31", "CALL")  # Mock return value for translate_option_symbol

        result = self.gmail.extractSymbolsFromEmails(payloads)

        # Ensure the valid payload was processed correctly
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['Symbol'], 'ABC')
        self.assertEqual(result[0]['Side'], 'BUY')
        self.assertEqual(result[0]['Strategy'], 'LINREGEMA_V2')
        self.assertEqual(result[0]['Asset_Type'], 'EQUITY')
        
        # Ensure the ValueError triggers a warning log
        self.gmail.logger.warning.assert_called_with(
            f"{Gmail.__name__} - Email Format Issue: {payloads[1]}"
        )


    @patch("gmail.Gmail.translate_option_symbol")
    def test_extractSymbolsFromEmails_generic_exception(self, mock_translate):
        """Test extractSymbolsFromEmails for handling a generic exception."""

        payloads = [
            "Alert: New Symbol: .ABC was added to LinRegEMA_v2, BUY"
        ]

        # Mock translate_option_symbol to raise a generic exception
        mock_translate.side_effect = Exception("Generic error")

        result = self.gmail.extractSymbolsFromEmails(payloads)

        # Ensure the result is empty since the valid payload doesn't produce trade data
        self.assertEqual(result, [])
        # Ensure the error was logged correctly
        self.gmail.logger.error.assert_called_once_with(f"{Gmail.__name__} - Generic error")


    def test_translate_option_symbol(self):
        """Test the translate_option_symbol method with a valid symbol."""
        
        # Input symbol
        input_symbol = ".WM241011C210"
        
        # Expected values
        expected_underlying = "WM"
        expected_pre_symbol = "WM    241011C00210000"
        expected_expiration_date = datetime.strptime("2024-10-11", "%Y-%m-%d")
        expected_option_type = "CALL"
        
        # Call the method
        underlying, pre_symbol, expiration_date, option_type = self.gmail.translate_option_symbol(input_symbol)
        
        # Assertions
        self.assertEqual(underlying, expected_underlying)
        self.assertEqual(pre_symbol, expected_pre_symbol)
        self.assertEqual(expiration_date, expected_expiration_date)
        self.assertEqual(option_type, expected_option_type)


    def test_translate_option_symbol_invalid_format(self):
        """Test the translate_option_symbol method with an invalid symbol format."""
        
        # Invalid symbol
        invalid_symbol = ".INVALID123"
        
        # Assert that a ValueError is raised
        with self.assertRaises(ValueError):
            self.gmail.translate_option_symbol(invalid_symbol)


# If you're running this directly
if __name__ == '__main__':
    unittest.main()
