import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from requests import HTTPError
from tdameritrade import TDAmeritrade  # Replace with actual module

class TestTDAmeritrade(unittest.TestCase):

    def setUp(self):
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
        self.td_ameritrade = TDAmeritrade(
            mongo=self.mongo_mock, 
            user=self.user_mock, 
            account_id=self.account_id, 
            logger=self.logger_mock, 
            push_notification=self.push_notification_mock
        )

    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_initialConnect_success(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True (successful connection)
        mock_checkTokenValidity.return_value = True

        # Call the method
        result = self.td_ameritrade.initialConnect()

        # Verify the connection succeeds
        self.assertTrue(result)

        # Adjust expected log message to match actual log
        self.logger_mock.info.assert_called_with(
            f"CONNECTED {self.user_mock['Name']} TO TDAMERITRADE (***********t_id)",  # Adjust this part
            extra={'log': False}
        )


    # Patching in the correct order
    @patch('tdameritrade.client_from_token_file')  # First argument in test function
    @patch('tdameritrade.client_from_manual_flow')  # Second argument in test function
    @patch('tdameritrade.os.path.isfile')  # Third argument in test function
    @patch('tdameritrade.API_KEY', 'mock_api_key')  # Mock API_KEY globally
    @patch('tdameritrade.APP_SECRET', 'mock_app_secret')  # Mock APP_SECRET globally
    def test_checkTokenValidity_token_exists(self, mock_isfile, mock_client_from_manual_flow, mock_client_from_token_file):
        # Simulate that the token file exists
        mock_isfile.return_value = True
        
        # Simulate return value for client_from_token_file
        mock_client_from_token_file.return_value = "client_token_mock"
        
        # Simulate MongoDB user data
        self.mongo_mock.users.find_one.return_value = self.user_mock

        # Call the method
        result = self.td_ameritrade.checkTokenValidity()
        
        # Assert the method returns True
        self.assertTrue(result)
        
        # Assert client_from_token_file was called with expected arguments
        mock_client_from_token_file.assert_called_once_with("test_token_path", 'mock_api_key', 'mock_app_secret')
        
        # Assert MongoDB update was called
        self.mongo_mock.users.update_one.assert_called_once()


    @patch('tdameritrade.client_from_token_file')  # First argument in test function
    @patch('tdameritrade.client_from_manual_flow')  # Second argument in test function
    @patch('tdameritrade.os.path.isfile')  # Third argument in test function
    @patch('tdameritrade.API_KEY', 'mock_api_key')  # Mock API_KEY globally
    @patch('tdameritrade.APP_SECRET', 'mock_app_secret')  # Mock APP_SECRET globally
    @patch('tdameritrade.CALLBACK_URL', 'mock_callback_url')  # Mock APP_SECRET globally
    def test_checkTokenValidity_token_does_not_exist(self, mock_isfile, mock_client_from_manual_flow, mock_client_from_token_file):
        # Simulate the token file does not exist
        mock_isfile.return_value = False

        # Simulate return value for client_from_token_file
        mock_client_from_token_file.return_value = "client_token_mock"
        
        # Simulate MongoDB user data
        self.mongo_mock.users.find_one.return_value = self.user_mock

        # Call the method
        result = self.td_ameritrade.checkTokenValidity()

        # Assertions
        self.assertTrue(result)
        # c = client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path)
        mock_client_from_manual_flow.assert_called_once_with('mock_api_key', 'mock_app_secret', 'mock_callback_url', 'test_token_path')
        self.mongo_mock.users.update_one.assert_called_once()


    @patch('tdameritrade.client_from_token_file')  # First argument in test function
    @patch('tdameritrade.client_from_manual_flow')  # Second argument in test function
    @patch('tdameritrade.os.path.isfile')  # Third argument in test function
    @patch('tdameritrade.API_KEY', 'mock_api_key')  # Mock API_KEY globally
    @patch('tdameritrade.APP_SECRET', 'mock_app_secret')  # Mock APP_SECRET globally
    @patch('tdameritrade.CALLBACK_URL', 'mock_callback_url')  # Mock CALLBACK_URL globally
    def test_checkTokenValidity_fails(self, mock_isfile, mock_client_from_manual_flow, mock_client_from_token_file):
        # Simulate the token file does not exist
        mock_isfile.return_value = False
        
        # Simulate `client_from_manual_flow` failing to return a valid client
        mock_client_from_manual_flow.return_value = None
        
        # Simulate MongoDB user data
        self.mongo_mock.users.find_one.return_value = self.user_mock

        # Call the method
        result = self.td_ameritrade.checkTokenValidity()

        # Assertions
        self.assertFalse(result)
        # Ensure that client_from_manual_flow was called with the expected arguments
        mock_client_from_manual_flow.assert_called_once_with('mock_api_key', 'mock_app_secret', 'mock_callback_url', 'test_token_path')
        self.mongo_mock.users.update_one.assert_not_called()  # Ensure update_one was not called


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_quote_non_existent_symbol(self, mock_check_token_validity):
        # Create a mock client with a mocked get_quote method
        mock_client = MagicMock()
        mock_client.get_quote.return_value = MagicMock(status_code=404, json=lambda: {})

        # Mock token validity
        mock_check_token_validity.return_value = True

        # Set the mock client directly on the TDAmeritrade instance
        self.td_ameritrade.client = mock_client

        # Call the method under test
        result = self.td_ameritrade.getQuote("INVALID_SYMBOL")

        # Assertions
        self.logger_mock.error.assert_called_once()
        self.assertIsNone(result, "Expected None for non-existent symbol")
        mock_client.get_quote.assert_called_once_with("INVALID_SYMBOL")

    
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getAccount_successful(self, mock_checkTokenValidity):
        # Mock token validity check to return True
        mock_checkTokenValidity.return_value = True

        # Create a mock client with necessary methods
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = MagicMock(status_code=200, json=lambda: [{'hashValue': 'mock_account_hash'}])
        mock_client.get_account.return_value = MagicMock(json=lambda: {'accountNumber': 'mock_account_number', 'balance': 1000})
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        result = self.td_ameritrade.getAccount()
        
        # Assertions
        self.assertEqual(result, {'accountNumber': 'mock_account_number', 'balance': 1000})
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_called_once()
        mock_client.get_account.assert_called_once_with('mock_account_hash')


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getAccount_token_invalid(self, mock_checkTokenValidity):
        # Mock token validity check to return False
        mock_checkTokenValidity.return_value = False
        
        # Call the method
        result = self.td_ameritrade.getAccount()
        
        # Assertions
        self.assertIsNone(result)
        mock_checkTokenValidity.assert_called_once()


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getAccount_account_retrieval_fails(self, mock_checkTokenValidity):
        # Mock token validity check to return True
        mock_checkTokenValidity.return_value = True

        # Create a mock client with get_account_numbers failing
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = MagicMock(status_code=500)  # Simulate failure
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        result = self.td_ameritrade.getAccount()
        
        # Assertions
        self.assertIsNone(result)
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_called_once()


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_successful(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and set its behavior for get_quote
        mock_client = MagicMock()
        mock_client.get_quote.return_value = MagicMock(status_code=200, json=lambda: {'symbol': 'AAPL', 'price': 150})
        
        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client
        
        # Call the method with a valid symbol
        result = self.td_ameritrade.getQuote('AAPL')
        
        # Assert the expected result
        self.assertEqual(result, {'symbol': 'AAPL', 'price': 150})
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quote.assert_called_once_with('AAPL')
    

    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_empty_symbol(self, mock_checkTokenValidity):
        # Mock token validity to return True (which is irrelevant since symbol is empty)
        mock_checkTokenValidity.return_value = True
        
        # Call the method with an empty symbol
        result = self.td_ameritrade.getQuote('')  # Empty symbol
        
        # Assert that None is returned for an empty symbol
        self.assertIsNone(result)
        
        # Check if the logger warning was called once with the expected message
        self.logger_mock.warning.assert_called_once_with('Symbol in getQuote was empty \'%s\'', '')

        # Ensure that checkTokenValidity was still called
        mock_checkTokenValidity.assert_called_once()


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_http_error(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and simulate an HTTP error response
        mock_client = MagicMock()
        mock_client.get_quote.return_value = MagicMock(status_code=404)

        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client

        # Call the method with a valid symbol
        result = self.td_ameritrade.getQuote('AAPL')

        # Assert that None is returned
        self.assertIsNone(result)

        # Ensure the logger logs the error
        self.logger_mock.error.assert_called_once_with("Failed to retrieve quote for symbol: AAPL. HTTP Status: 404")

        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quote.assert_called_once_with('AAPL')


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_exception(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and simulate an exception being raised
        mock_client = MagicMock()
        mock_client.get_quote.side_effect = Exception("Network error")

        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client

        # Call the method with a valid symbol
        result = self.td_ameritrade.getQuote('AAPL')

        # Assert that None is returned
        self.assertIsNone(result)

        # Ensure the logger logs the error
        self.logger_mock.error.assert_called_once_with("An error occurred while retrieving the quote for symbol: AAPL. Error: Network error")

        mock_checkTokenValidity.assert_called_once()


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_invalid_token(self, mock_checkTokenValidity):
        # Mock token validity to be False
        mock_checkTokenValidity.return_value = False

        # Call the method with a valid symbol
        result = self.td_ameritrade.getQuote('AAPL')

        # Assert that None is returned when the token is invalid
        self.assertIsNone(result)

        mock_checkTokenValidity.assert_called_once()

        # Ensure no further calls are made after token check
        self.logger_mock.error.assert_not_called()


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuote_with_slash_symbol(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and set its behavior for get_quotes
        mock_client = MagicMock()
        mock_client.get_quotes.return_value = MagicMock(status_code=200, json=lambda: {'AAPL/MSFT': {'symbol': 'AAPL/MSFT', 'price': 200}})
        
        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client
        
        # Call the method with a symbol containing "/"
        result = self.td_ameritrade.getQuote('AAPL/MSFT')
        
        # Assert the expected result
        self.assertEqual(result, {'AAPL/MSFT': {'symbol': 'AAPL/MSFT', 'price': 200}})
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quotes.assert_called_once_with('AAPL/MSFT')


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuotes_successful(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and set its behavior
        mock_client = MagicMock()
        mock_client.get_quotes.return_value = MagicMock(status_code=200, json=lambda: {'AAPL': {'symbol': 'AAPL', 'price': 150}})
        
        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client
        
        # Call the method
        symbols = ['AAPL']
        result = self.td_ameritrade.getQuotes(symbols)
        
        # Assert the expected result
        self.assertEqual(result, {'AAPL': {'symbol': 'AAPL', 'price': 150}})
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quotes.assert_called_once_with(symbols)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuotes_failed_status_code(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and simulate a non-200 response
        mock_client = MagicMock()
        mock_client.get_quotes.return_value = MagicMock(status_code=404)  # Simulate a failed response
        
        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client
        
        # Call the method
        symbols = ['AAPL']
        result = self.td_ameritrade.getQuotes(symbols)
        
        # Assert that None is returned for a non-200 response
        self.assertIsNone(result)
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quotes.assert_called_once_with(symbols)
    

    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuotes_token_invalid(self, mock_checkTokenValidity):
        # Mock token validity to be False
        mock_checkTokenValidity.return_value = False
        
        # Call the method
        symbols = ['AAPL']
        result = self.td_ameritrade.getQuotes(symbols)
        
        # Assert that None is returned when token is invalid
        self.assertIsNone(result)
        mock_checkTokenValidity.assert_called_once()

    
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_getQuotes_exception_during_retrieval(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Create a mock client and simulate an exception during the request
        mock_client = MagicMock()
        mock_client.get_quotes.side_effect = Exception('Some error occurred')  # Simulate an exception
        
        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client
        
        # Call the method
        symbols = ['AAPL']
        result = self.td_ameritrade.getQuotes(symbols)
        
        # Assert that None is returned when an exception is raised
        self.assertIsNone(result)
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_quotes.assert_called_once_with(symbols)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_invalid_token(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return False
        mock_checkTokenValidity.return_value = False

        # Call the method
        result = self.td_ameritrade.getSpecificOrder(id=12345)

        # Ensure that the method returns None when the token is invalid
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_account_numbers_error(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Mock the response for get_account_numbers to simulate an error
        mock_account_response = MagicMock()
        mock_account_response.status_code = 500  # Simulating a server error
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = mock_account_response
        self.td_ameritrade.client = mock_client

        order_id = '12345'

        # Call the method
        order = self.td_ameritrade.getSpecificOrder(order_id)

        # Assert that the method returns None since the account numbers request failed
        self.assertIsNone(order)  # Since the else block returns None

    
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_success(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        # Sample response data for a successful order retrieval
        mock_client = MagicMock()
        order_id = '12345'

        mock_order_response = MagicMock()
        mock_order_response.status_code = 200
        mock_order_response.json.return_value = {
            'Order_ID': order_id,
            'status': 'FILLED',
            'symbol': 'AAPL',
            'quantity': 10
        }
        mock_client.get_order.return_value = mock_order_response

        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        # Set up the mock to return a specific value
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue":"123ABCXYZ"
            },
            {
                "accountNumber": "789012",
                "hashValue":"789ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        order = self.td_ameritrade.getSpecificOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_order.assert_called_once_with(order_id, mock_get_account_numbers_response.json.return_value[0]["hashValue"])

        # Assert the order details
        self.assertEqual(order['Order_ID'], order_id)
        self.assertEqual(order['status'], 'FILLED')
        self.assertEqual(order['symbol'], 'AAPL')
        self.assertEqual(order['quantity'], 10)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_order_failure(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Mock the response from get_account_numbers
        mock_client = MagicMock()
        mock_resp_account = MagicMock()
        mock_resp_account.status_code = 200
        mock_resp_account.json.return_value = [{"accountNumber": "123456789", "hashValue": "123ABCXYZ"}]
        mock_client.get_account_numbers.return_value = mock_resp_account

        # Mock the response from get_order with a non-200 status code
        mock_resp_order = MagicMock()
        mock_resp_order.status_code = 404  # Simulate an HTTP error
        mock_resp_order.json.return_value = {"error": "Order not found"}
        mock_client.get_order.return_value = mock_resp_order

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.getSpecificOrder(id=12345)

        # Ensure that the method logs the error and returns None
        self.td_ameritrade.logger.warning.assert_called_once_with("Failed to get specific order: 12345. HTTP Status: 404")
        self.assertEqual(result, {"error": "Order not found"})


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_exception(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Mock the response from get_account_numbers
        mock_client = MagicMock()
        mock_resp_account = MagicMock()
        mock_resp_account.status_code = 200
        mock_resp_account.json.return_value = [{"accountNumber": "123456789", "hashValue": "123ABCXYZ"}]
        mock_client.get_account_numbers.return_value = mock_resp_account

        # Mock the client to raise an exception during get_order
        mock_client.get_order.side_effect = Exception("API error")

        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client

        # Call the method and mock the response for the exception case
        result = self.td_ameritrade.getSpecificOrder(id=12345)

        # Ensure that the method logs the exception and returns None
        self.td_ameritrade.logger.error.assert_called_once_with("An error occurred while attempting to get specific order: 12345. Error: API error")
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_paper_trade(self, mock_checkTokenValidity):
        # Test case where the order is a paper trade (ID < 0)
        result = self.td_ameritrade.getSpecificOrder(id=-1)

        # Assert that the method returns the 'Order not found' message
        self.assertEqual(result, {'message': 'Order not found'})

    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_real_order(self, mock_checkTokenValidity):
        # This test case would remain similar to the one you had for real orders
        mock_checkTokenValidity.return_value = True

        # Mock the response from get_account_numbers
        mock_client = MagicMock()
        mock_resp_account = MagicMock()
        mock_resp_account.status_code = 200
        mock_resp_account.json.return_value = [{"accountNumber": "123456789", "hashValue": "123ABCXYZ"}]
        mock_client.get_account_numbers.return_value = mock_resp_account

        # Mock the response from get_order
        mock_resp_order = MagicMock()
        mock_resp_order.status_code = 200
        mock_resp_order.json.return_value = {"orderId": 12345}
        mock_client.get_order.return_value = mock_resp_order

        # Set the mock client to the TDAmeritrade instance
        self.td_ameritrade.client = mock_client

        # Call the method
        result = self.td_ameritrade.getSpecificOrder(id=12345)

        # Ensure that the method returns the correct result
        self.assertEqual(result, {"Order_ID": 12345})


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_specific_order_handles_404(self, mock_checkTokenValidity):
        mock_checkTokenValidity.return_value = True

        # Mock the get_account_numbers method to return a response with a 404 status code
        mock_response = MagicMock()
        mock_response.status_code = 404  # Simulating a 404 response

        # Create a mock client with necessary methods
        mock_client = MagicMock()    
        mock_client.get_account_numbers.return_value = mock_response
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client

        # Create a dummy queue_order
        queue_order = {"Order_ID": "invalid_order_id"}

        # Call the method that uses getSpecificOrder
        spec_order = self.td_ameritrade.getSpecificOrder(queue_order["Order_ID"])

        # Handle the response as expected in the code
        orderMessage = "Order not found or API is down." if spec_order is None else spec_order.get('message', '')

        # Assert the correct message is set for the 404 case
        self.assertEqual(orderMessage, "Order not found or API is down.")


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_success(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue": "123ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response
        order_id = '12345'

        mock_cancel_response = MagicMock()
        mock_cancel_response.status_code = 200
        mock_cancel_response.json.return_value = {'success': True}
        mock_client.cancel_order.return_value = mock_cancel_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        mock_client.cancel_order.assert_called_once_with(order_id, mock_get_account_numbers_response.json.return_value[0]["hashValue"])
        self.assertEqual(result, {'success': True})  # Adjust based on your implementation


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_not_found(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue": "123ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response
        order_id = '12345'

        mock_cancel_response = MagicMock()
        mock_cancel_response.status_code = 404  # Simulate not found
        mock_cancel_response.json.return_value = {'error': 'Order not found'}
        mock_client.cancel_order.return_value = mock_cancel_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        mock_client.cancel_order.assert_called_once_with(order_id, mock_get_account_numbers_response.json.return_value[0]["hashValue"])
        self.td_ameritrade.logger.error.assert_called_once()  # Ensure logging of the error
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_api_error(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue": "123ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response
        order_id = '12345'

        # Mock the response for an unexpected API error
        mock_cancel_response = MagicMock()
        mock_cancel_response.status_code = 500  # Simulate server error
        mock_cancel_response.json.return_value = {'error': 'Internal Server Error'}
        mock_client.cancel_order.return_value = mock_cancel_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        mock_client.cancel_order.assert_called_once_with(order_id, mock_get_account_numbers_response.json.return_value[0]["hashValue"])
        self.td_ameritrade.logger.error.assert_called_once()  # Ensure logging of the error
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_token_invalid(self, mock_checkTokenValidity):
        # Mock token validity to be False
        mock_checkTokenValidity.return_value = False

        # Call the method
        order_id = '12345'
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assert that the method returns None
        self.assertIsNone(result)  # Since the else block returns None


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_invalid_api_response(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue": "123ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response

        # Mock the response for an unexpected status code (neither success nor not found)
        mock_cancel_response = MagicMock()
        mock_cancel_response.status_code = 400  # Simulate a bad request
        mock_cancel_response.json.return_value = {'error': 'Bad Request'}
        mock_client.cancel_order.return_value = mock_cancel_response

        # Set the mock client to the TDAmeritrade instance and call the method
        order_id = '12345'
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assert that the method returns None
        self.assertIsNone(result)  # Since the else block returns None


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_account_numbers_error(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 400  # Simulate an error response
        mock_get_account_numbers_response.json.return_value = {'error': 'Bad Request'}
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response
        order_id = '12345'

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        self.assertIsNone(result)  # Since the else block returns None


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_cancel_order_exception_handling(self, mock_checkTokenValidity):
        # Mock token validity to be True
        mock_checkTokenValidity.return_value = True

        mock_client = MagicMock()
        mock_get_account_numbers_response = MagicMock()
        mock_get_account_numbers_response.status_code = 200
        mock_get_account_numbers_response.json.return_value = [
            {
                "accountNumber": "123456",
                "hashValue": "123ABCXYZ"
            }
        ]
        mock_client.get_account_numbers.return_value = mock_get_account_numbers_response
        order_id = '12345'

        # Simulate an exception when attempting to cancel the order
        mock_client.cancel_order.side_effect = Exception("Network Error")

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.cancelOrder(order_id)

        # Assertions
        mock_checkTokenValidity.assert_called_once()
        mock_client.cancel_order.assert_called_once_with(order_id, mock_get_account_numbers_response.json.return_value[0]["hashValue"])
        self.td_ameritrade.logger.error.assert_called_once_with(
            f"An error occurred while attempting to cancel order: {order_id}. Error: Network Error"
        )
        self.assertIsNone(result)  # Since the exception is caught, it should return None


    @patch('tdameritrade.Utils')  # Mock Utils if used in the method
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_placeTDAOrder_successful(self, mock_checkTokenValidity, MockUtils):
        
        mock_checkTokenValidity.return_value = True

        # Create a mock client with necessary methods
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = MagicMock(status_code=200, json=lambda: [{'hashValue': 'mock_account_hash'}])
        mock_client.place_order.return_value = MagicMock(status_code=200)
        
        # Mock Utils methods
        mock_utils_instance = MockUtils.return_value
        mock_utils_instance.extract_order_id.return_value = 'mock_order_id'
        
        # Mock getSpecificOrder and rename_order_ids methods
        self.td_ameritrade.getSpecificOrder = MagicMock(return_value={'orderId': 'mock_order_id'})
        self.td_ameritrade.rename_order_ids = MagicMock(return_value={'Order_ID': 'mock_order_id'})
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        order_data = {'symbol': 'AAPL', 'quantity': 1, 'price': 150}
        result = self.td_ameritrade.placeTDAOrder(order_data)
        
        # Assertions
        self.assertEqual(result, {'Order_ID': 'mock_order_id'})
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_called_once()
        mock_client.place_order.assert_called_once_with('mock_account_hash', order_data)
        mock_utils_instance.extract_order_id.assert_called_once()
        self.td_ameritrade.getSpecificOrder.assert_called_once_with('mock_order_id')


    @patch('tdameritrade.Utils')  # Mock Utils if used in the method
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_placeTDAOrder_token_invalid(self, mock_checkTokenValidity, MockUtils):
        
        mock_checkTokenValidity.return_value = False
        
        # Create a mock client (though it won't be used since token validity fails)
        mock_client = MagicMock()
        
        # Mock Utils methods
        mock_utils_instance = MockUtils.return_value
        mock_utils_instance.extract_order_id.return_value = 'mock_order_id'
        
        # Mock getSpecificOrder and rename_order_ids methods
        self.td_ameritrade.getSpecificOrder = MagicMock(return_value={'orderId': 'mock_order_id'})
        self.td_ameritrade.rename_order_ids = MagicMock(return_value={'Order_ID': 'mock_order_id'})
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        order_data = {'symbol': 'AAPL', 'quantity': 1, 'price': 150}
        result = self.td_ameritrade.placeTDAOrder(order_data)
        
        # Assertions
        self.assertIsNone(result)  # Should return None if the token is invalid
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_not_called()  # Client methods should not be called
        mock_client.place_order.assert_not_called()
        mock_utils_instance.extract_order_id.assert_not_called()
        self.td_ameritrade.getSpecificOrder.assert_not_called()

    
    @patch('tdameritrade.Utils')  # Mock Utils if used in the method
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_placeTDAOrder_order_placement_fails(self, mock_checkTokenValidity, MockUtils):
        
        mock_checkTokenValidity.return_value = True

        # Create a mock client with necessary methods
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = MagicMock(status_code=200, json=lambda: [{'hashValue': 'mock_account_hash'}])
        mock_client.place_order.return_value = MagicMock(status_code=500)  # Simulate order placement failure
        
        # Mock Utils methods
        mock_utils_instance = MockUtils.return_value
        mock_utils_instance.extract_order_id.return_value = 'mock_order_id'
        
        # Mock getSpecificOrder and rename_order_ids methods
        self.td_ameritrade.getSpecificOrder = MagicMock(return_value={'orderId': 'mock_order_id'})
        self.td_ameritrade.rename_order_ids = MagicMock(return_value={'Order_ID': 'mock_order_id'})
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        order_data = {'symbol': 'AAPL', 'quantity': 1, 'price': 150}
        result = self.td_ameritrade.placeTDAOrder(order_data)
        
        # Assertions
        self.assertEqual(result.status_code, 500)  # Should return the raw response if placement fails
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_called_once()
        mock_client.place_order.assert_called_once_with('mock_account_hash', order_data)
        mock_utils_instance.extract_order_id.assert_not_called()
        self.td_ameritrade.getSpecificOrder.assert_not_called()

    
    @patch('tdameritrade.Utils')  # Mock Utils if used in the method
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_placeTDAOrder_no_order_id(self, mock_checkTokenValidity, MockUtils):
        
        mock_checkTokenValidity.return_value = True

        # Create a mock client with necessary methods
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = MagicMock(status_code=200, json=lambda: [{'hashValue': 'mock_account_hash'}])
        mock_client.place_order.return_value = MagicMock(status_code=200)
        
        # Mock Utils methods
        mock_utils_instance = MockUtils.return_value
        mock_utils_instance.extract_order_id.return_value = None  # No order ID
        
        # Mock getSpecificOrder and rename_order_ids methods
        self.td_ameritrade.getSpecificOrder = MagicMock(return_value={})
        self.td_ameritrade.rename_order_ids = MagicMock(return_value={})
        
        # Set the mock client as the client attribute
        self.td_ameritrade.client = mock_client
        
        # Call the method
        order_data = {'symbol': 'AAPL', 'quantity': 1, 'price': 150}
        result = self.td_ameritrade.placeTDAOrder(order_data)
        
        # Assertions
        self.assertEqual(result, {"Order_ID": None})  # Should return basic info with None as the order ID
        mock_checkTokenValidity.assert_called_once()
        mock_client.get_account_numbers.assert_called_once()
        mock_client.place_order.assert_called_once_with('mock_account_hash', order_data)
        mock_utils_instance.extract_order_id.assert_called_once()
        self.td_ameritrade.getSpecificOrder.assert_not_called()
        

    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_market_hours_invalid_token(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return False
        mock_checkTokenValidity.return_value = False

        # Call the method
        result = self.td_ameritrade.getMarketHours(markets=['EQUITY'])

        # Ensure that the method returns None when the token is invalid
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_market_hours_success(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Mock the response from get_market_hours with a successful status code
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"market": "EQUITY", "hours": "9:30 AM - 4:00 PM"}
        mock_client.get_market_hours.return_value = mock_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.getMarketHours(markets=['EQUITY'])

        # Verify that the call was made with a datetime object (since now we default to current datetime)
        mock_client.get_market_hours.assert_called_once()
        called_args, called_kwargs = mock_client.get_market_hours.call_args
        self.assertEqual(result, {"market": "EQUITY", "hours": "9:30 AM - 4:00 PM"})
        self.assertEqual(called_kwargs['markets'], ['EQUITY'])
        self.assertIsInstance(called_kwargs['date'], datetime)  # Ensure 'date' is a datetime object


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_market_hours_http_error(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Mock the response from get_market_hours with a non-200 status code
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 400  # Simulate an HTTP error
        mock_client.get_market_hours.return_value = mock_response

        # Set the mock client to the TDAmeritrade instance and call the method
        self.td_ameritrade.client = mock_client
        result = self.td_ameritrade.getMarketHours(markets=['EQUITY'])

        # Ensure that the method logs the error and returns None
        self.td_ameritrade.logger.error.assert_called_once_with("Failed to retrieve market hours for markets: ['EQUITY']. HTTP Status: 400")
        self.assertIsNone(result)


    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_market_hours_exception(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Mock the client to raise an exception during get_market_hours
        mock_client = MagicMock()
        mock_client.get_market_hours.side_effect = Exception("API error")
        self.td_ameritrade.client = mock_client

        # Call the method
        result = self.td_ameritrade.getMarketHours(markets=['EQUITY'])

        # Ensure that the method logs the exception and returns None
        self.td_ameritrade.logger.error.assert_called_once_with("An error occurred while retrieving market hours for markets: ['EQUITY']. Error: API error")
        self.assertIsNone(result)

    
    @patch('tdameritrade.TDAmeritrade.checkTokenValidity')
    def test_get_account_numbers_handles_404(self, mock_checkTokenValidity):
        # Mock checkTokenValidity to return True
        mock_checkTokenValidity.return_value = True

        # Set up the mock to raise a 404 HTTPError
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {}  # Assuming the API returns an empty dict on 404

        # Mock the client to raise an exception during get_market_hours
        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = mock_response
        self.td_ameritrade.client = mock_client
        
        # Call the method and assert it handles the 404 gracefully
        account_numbers = self.td_ameritrade.getAccount()
        
        # Assert that account_numbers is None (or empty) when 404 occurs
        self.assertIsNone(account_numbers)
        

if __name__ == '__main__':
    unittest.main()
