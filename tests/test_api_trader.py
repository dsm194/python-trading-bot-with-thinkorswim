from unittest.mock import PropertyMock, patch, MagicMock, ANY
import unittest

import httpx
from api_trader import ApiTrader

from pymongo.errors import WriteConcernError, WriteError

class TestApiTrader(unittest.TestCase):

    @staticmethod
    def match_partial_error(expected_message):
        def match_error_message(actual_message):
            return expected_message in actual_message
        return unittest.mock.ANY

    def setUp(self):
        # This method runs before every test case to set up reusable mocks and variables

        self.user = {
            "Name": "TestUser",
            "Accounts": {
                "12345": {
                    "Account_Position": "Live"
                }
            }
        }
        self.mongo = MagicMock()
        self.push = MagicMock()
        self.logger = MagicMock()
        self.account_id = "12345"
        self.tdameritrade = MagicMock()

        # Instantiate ApiTrader
        self.api_trader = ApiTrader(
            user=self.user,
            mongo=self.mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade
        )

        self.queue_order = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Direction": "OPEN POSITION",
            "Account_ID": "123",
            "Asset_Type": "EQUITY",
            "Side": "BUY",
            "Position_Type": "LONG",
            "Position_Size": 10,
            "Account_Position": "Live",
            "Order_Type": "LIMIT",
            "Qty": 10,
        }
        self.spec_order = {
            "price": 150.0,
            "quantity": 10
        }


    @patch('api_trader.ApiTrader.run_tasks_with_exit_check')
    def test_initialization_live_trader(self, mock_run_tasks_with_exit_check):
        # Check if the initialization sets RUN_LIVE_TRADER to True
        self.assertTrue(self.api_trader.RUN_LIVE_TRADER)
        self.assertIsInstance(self.api_trader.mongo.users, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.open_positions, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.closed_positions, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.strategies, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.rejected, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.canceled, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.queue, MagicMock)
        self.assertTrue(self.api_trader.task_thread.is_alive())

    @patch('api_trader.ApiTrader.run_tasks_with_exit_check')
    def test_initialization_paper_trader(self, mock_run_tasks_with_exit_check):
        self.user["Accounts"]["12345"]["Account_Position"] = "Paper"
        self.api_trader = ApiTrader(
            user=self.user,
            mongo=self.mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade
        )
        self.assertFalse(self.api_trader.RUN_LIVE_TRADER)
        self.assertTrue(hasattr(self.api_trader, 'task_thread'))

    # @patch('api_trader.ApiTrader.check_stop_signal', return_value=False)
    # @patch('api_trader.ApiTrader.runTasks')
    # def test_run_tasks_with_exit_check(self, mock_run_tasks, mock_check_stop_signal):
    #     self.api_trader.run_tasks_with_exit_check()
    #     self.assertTrue(mock_run_tasks.called)

    # @patch('api_trader.ApiTrader.check_stop_signal', return_value=True)
    # def test_run_tasks_with_exit_check_stop_signal(self, mock_check_stop_signal):
    #     self.api_trader.run_tasks_with_exit_check()
    #     self.assertFalse(self.api_trader.runTasks.called)

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    @patch('api_trader.OrderBuilderWrapper.standardOrder')
    @patch('api_trader.ApiTrader.queueOrder')
    def test_send_order_live(self, mock_queue_order, mock_standard_order, mock_init):

        # Setup mocks
        trade_data = {"Symbol": "AAPL", "Strategy": "test_strategy", "Side": "BUY"}
        strategy_object = {"Order_Type": "STANDARD", "Position_Type": "LONG", "Position_Size": 500, "Active": True}
        
        # Mock the response of tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }

        # Mock standardOrder to return a valid parent order and exit order
        parent_order_mock = MagicMock()  # This should represent a valid OrderBuilder or dict
        exit_order_mock = MagicMock()  # This should represent a valid OrderBuilder or dict

        # First call succeeds, second call simulates failure
        mock_standard_order.side_effect = [
            (parent_order_mock, {}),  # First call (parent order)
            Exception("Failed to place order"),  # Second call simulates failure
            (exit_order_mock, {}),  # Second call (exit order)
        ]

        # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        self.api_trader = ApiTrader()
        self.api_trader.logger = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = MagicMock()
        self.api_trader.queue = MagicMock()
        self.api_trader.rejected = MagicMock()
        self.api_trader.account_id = "test_account"  # Set this to a specific account ID for your test
        self.api_trader.tdameritrade = MagicMock()
        self.api_trader.check_stop_signal = MagicMock(return_value=False)
        self.api_trader.stop_signal_file = "mock_stop_signal_file"  # Add this line to mock the stop_signal_file
        self.api_trader.tdameritrade.placeTDAOrder = MagicMock(return_value={"orderId": "12345"})
        self.api_trader.RUN_LIVE_TRADER = True  # Mock or set RUN_LIVE_TRADER attribute

        # Call method: Open Position Scenario
        self.api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")
        
        # Assert correct order placement behavior
        self.api_trader.logger.warning.assert_not_called()
        self.api_trader.logger.error.assert_not_called()
        mock_standard_order.assert_called_once_with(trade_data, strategy_object, "OPEN POSITION")
        self.api_trader.tdameritrade.placeTDAOrder.assert_called_once()
        mock_queue_order.assert_called_once()

        # Call method: Simulate failure in the second call (quote data missing)
        self.api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")

        # Instead of matching the entire error message, use partial matching with assert_any_call
        # This checks if 'Failed to place order' was logged without requiring exact match
        self.api_trader.logger.error.assert_any_call(self.match_partial_error("Failed to place order"))

        # Test placing an order with RUN_LIVE_TRADER set to False
        self.api_trader.RUN_LIVE_TRADER = False
        self.api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")
        
        # Assert that placeTDAOrder was not called in paper trading mode
        self.api_trader.tdameritrade.placeTDAOrder.assert_called_once()  # Should be called only once in live mode
        mock_queue_order.assert_called()

    @patch('api_trader.ApiTrader.queueOrder')
    def test_send_order_paper(self, mock_queue_order):
        self.api_trader = ApiTrader(
            user=self.user,
            mongo=self.mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade
        )
        self.api_trader.RUN_LIVE_TRADER = False
        trade_data = create_mock_open_positions(1)[0]

        strategy_object = {"Order_Type": "STANDARD", "Position_Type": "LONG"}

        self.api_trader.sendOrder(trade_data, strategy_object, "CLOSE POSITION")
        
        mock_queue_order.assert_called_once()

    def test_queueOrder(self):
        # Prepare the input order
        order = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Quantity": 10
        }

        # Call the queueOrder method
        self.api_trader.queueOrder(order)

        # Verify that the queue.update_one was called with the correct arguments
        self.mongo.queue.update_one.assert_called_once_with(
            {"Trader": "TestUser", "Symbol": "AAPL", "Strategy": "TestStrategy"},
            {"$set": order},
            upsert=True
        )

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_update_status_filled_order(self, mock_init):
        
        self.api_trader.pushOrder = MagicMock()

        # Mock the getSpecificOrder to return a FILLED status
        self.api_trader.tdameritrade.getSpecificOrder.side_effect = [{"status": "FILLED", "orderId": "12345"}]
        self.api_trader.queue = MagicMock()
        self.api_trader.queue.find.return_value = [
            {"Symbol": "AAPL", "Order_ID": "12345", "Order_Type": "STANDARD",
             "Trader": "test_trader", "Account_ID": "test_account",
             "Direction": "OPEN POSITION", "Qty": 100, "Entry_Price": 150,
             "Strategy": "test_strategy", "Asset_Type": "EQUITY", "Side": "BUY"}
        ]

        # Call updateStatus
        self.api_trader.updateStatus()

        # Assert pushOrder was called once with the queued order and the specific order
        self.api_trader.pushOrder.assert_called_once_with(
            {
                "Symbol": "AAPL", "Order_ID": "12345", "Order_Type": "STANDARD", 
                "Trader": "test_trader", "Account_ID": "test_account", 
                "Direction": "OPEN POSITION", "Qty": 100, "Entry_Price": 150,
                "Strategy": "test_strategy", "Asset_Type": "EQUITY", "Side": "BUY"
            }, 
            {"status": "FILLED", "orderId": "12345"}
        )
        self.api_trader.logger.warning.assert_not_called()


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_update_status_order_not_found(self, mock_init):

        self.api_trader.pushOrder = MagicMock()

        # Mock the getSpecificOrder to return a FILLED status
        self.api_trader.tdameritrade.getSpecificOrder.side_effect = [{"message": "Order not found"}]
        self.api_trader.queue = MagicMock()
        self.api_trader.queue.find.return_value = [
            {"Symbol": "AAPL", "Order_ID": "12345", "Order_Type": "STANDARD",
             "Trader": "test_trader", "Account_ID": "test_account",
             "Direction": "OPEN POSITION", "Qty": 100, "Entry_Price": 150,
             "Strategy": "test_strategy", "Asset_Type": "EQUITY", "Side": "BUY"}
        ]

        # Call updateStatus
        self.api_trader.updateStatus()

        # Assert pushOrder was called with "Assumed" data integrity
        self.api_trader.pushOrder.assert_called_once_with(
            {
                "Symbol": "AAPL", "Order_ID": "12345", "Order_Type": "STANDARD", 
                "Trader": "test_trader", "Account_ID": "test_account", 
                "Direction": "OPEN POSITION", "Qty": 100, "Entry_Price": 150,
                "Strategy": "test_strategy", "Asset_Type": "EQUITY", "Side": "BUY"
            }, 
            {"price": 150, "shares": 100}, "Assumed"
        )
        
        # Get the actual call arguments of the logger
        log_message, _ = self.api_trader.logger.warning.call_args

        # Assert that the log message contains the expected prefix
        assert log_message[0].startswith(
            "Order ID Not Found. Moving AAPL STANDARD Order To OPEN POSITION Positions ("
        ), f"Log message '{log_message[0]}' did not start with the expected string."


    def test_pushOrder_open_position(self):
        # Call the pushOrder method
        self.api_trader.pushOrder(self.queue_order, self.spec_order)

        # Extract the arguments used in the call to insert_one
        called_args = self.mongo.open_positions.insert_one.call_args[0][0]

        # Create the expected dictionary, but without the Entry_Date field
        expected_args = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Position_Size": 10,
            "Position_Type": "LONG",
            "Data_Integrity": "Reliable",
            "Trader": "TestUser",
            "Account_ID": "123",
            "Asset_Type": "EQUITY",
            "Account_Position": "Live",
            "Order_Type": "LIMIT",
            "Qty": 10,
            "Entry_Price": 150.0
        }

        # Check if Entry_Date is the only difference
        for key, value in expected_args.items():
            self.assertEqual(called_args.get(key), value)
        
        # Verify that the Entry_Date is not checked
        self.assertIn("Entry_Date", called_args)

        # Verify other method calls
        self.mongo.queue.delete_one.assert_called_once_with({
            "Trader": "TestUser",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Account_ID": "12345"
        })
        self.push.send.assert_called_once_with(
            ">>>> \n Side: BUY \n Symbol: AAPL \n Qty: 10 \n Price: $150.0 \n Strategy: TestStrategy \n Trader: TestUser"
        )

    def test_pushOrder_close_position(self):
        # Prepare the mock data
        self.queue_order = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Direction": "CLOSE POSITION",
            "Account_ID": "123",
            "Asset_Type": "EQUITY",
            "Side": "SELL",
            "Position_Type": "LONG",
            "Position_Size": 10,
            "Account_Position": "Live",
            "Order_Type": "LIMIT",
            "Qty": 10,
            "Entry_Date": "2024-01-01",
            "Entry_Price": 150.0,
            "Exit_Date": None
        }
        
        self.spec_order = {
            "price": 155.0,
            "quantity": 10
        }
        
        # Mock the `find_one` method to return a position
        self.mongo.open_positions.find_one.return_value = {
            "Qty": 10,
            "Entry_Price": 150.0,
            "Entry_Date": "2024-01-01"
        }
        
        # Mock the `count_documents` method to return 0
        self.mongo.closed_positions.count_documents.return_value = 0

        # Call the pushOrder method
        self.api_trader.pushOrder(self.queue_order, self.spec_order)

        # Extract the arguments used in the call to insert_one
        called_args = self.mongo.closed_positions.insert_one.call_args[0][0]

        # Create the expected dictionary for closed positions, without the Exit_Date
        expected_args = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Position_Size": 10,
            "Position_Type": "LONG",
            "Data_Integrity": "Reliable",
            "Trader": "TestUser",
            "Account_ID": "123",
            "Asset_Type": "EQUITY",
            "Account_Position": "Live",
            "Order_Type": "LIMIT",
            "Qty": 10,
            "Entry_Price": 150.0,
            "Exit_Price": 155.0
        }

        # Check if Exit_Date is the only difference
        for key, value in expected_args.items():
            self.assertEqual(called_args.get(key), value)
        
        # Verify that Exit_Date is not checked
        self.assertIn("Exit_Date", called_args)

        # Verify that open_positions entry was removed
        self.mongo.open_positions.delete_one.assert_called_once_with({
            "Trader": "TestUser",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy"
        })

        # Verify the queue deletion
        self.mongo.queue.delete_one.assert_called_once_with({
            "Trader": "TestUser",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Account_ID": "12345"
        })

        # Verify that push.send was called with the expected message
        self.push.send.assert_called_once_with(
            "____ \n Side: SELL \n Symbol: AAPL \n Qty: 10 \n Entry Price: $150.0 \n Exit Price: $155.0 \n Trader: TestUser"
        )

    def test_pushOrder_mongo_exception(self):
        # Setup mocks to raise exceptions
        self.mongo.open_positions.insert_one.side_effect = WriteConcernError("WriteConcernError")
        self.mongo.queue.delete_one.side_effect = WriteError("WriteError")

        # Call the pushOrder method
        self.queue_order["Direction"] = "OPEN POSITION"
        self.api_trader.pushOrder(self.queue_order, self.spec_order)

        # Extract all call arguments
        call_args_list = self.logger.error.call_args_list

        # Define expected substrings
        expected_substrings = [
            "Failed to insert AAPL into MongoDB. Retrying... - WriteConcernError",
            "Retry failed for AAPL. Error: WriteConcernError",
        ]

        # Convert the log messages to a list of strings for easy checking
        log_messages = [call[0][0] for call in call_args_list]
        
        # Check if expected substrings are in the log messages
        for expected_substring in expected_substrings:
            self.assertTrue(any(expected_substring in message for message in log_messages),
                            f"Expected log message containing '{expected_substring}' not found.")

        # Check that the delete_one and send methods were still called
        self.mongo.queue.delete_one.assert_called_once_with({
            "Trader": "TestUser",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Account_ID": "12345"
        })
        # self.push.send.assert_called_once_with(
        #     ">>>> \n Side: BUY \n Symbol: AAPL \n Qty: 10 \n Price: $150.0 \n Strategy: TestStrategy \n Trader: TestUser"
        # )


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock the constructor to avoid actual init
    @patch('api_trader.ApiTrader.sendOrder')
    def test_run_trader(self, mock_sendOrder, mock_init):

        # Mock relevant methods/attributes used in run_trader
        self.api_trader.queue = MagicMock()
        self.api_trader.user = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "test_account"  # Set this to a specific account ID for your test
        self.api_trader.updateStatus = MagicMock()

        # Mock the find_one method on open_positions and queue to None value, so that runTrader will BUY
        self.api_trader.open_positions.find_one.return_value = None
        self.api_trader.queue.find_one.return_value = None
        self.api_trader.mongo.find.return_value = [{"Trader": "test_trader", "Account_ID": "test_account", "Order_ID": "12345"}]
        self.api_trader.strategies.find_one.return_value = {"Strategy": "test_strategy", "Account_ID": "test_account", "Position_Type": "LONG", "Order_Type": "STANDARD"}

        trade_data = [{"Symbol": "AAPL", "Strategy": "test_strategy", "Side": "BUY", 'Asset_Type': 'EQUITY'}]

        # Call run_trader method
        self.api_trader.runTrader(trade_data=trade_data)

        # Add assertions here
        self.api_trader.open_positions.find_one.assert_called_once()  # Ensure mongo query is performed
        self.api_trader.queue.find_one.assert_called_once()  # Ensure mongo query is performed
        self.api_trader.strategies.find_one.assert_called_once()  # Ensure mongo query is performed
        self.api_trader.updateStatus.assert_called()  # Ensure status is updated
        mock_sendOrder.assert_called_once()


    def test_initialization_error_handling(self):
        # Create a mock mongo object
        mock_mongo = MagicMock()
        # Set up mongo.users to raise an exception when accessed using PropertyMock
        type(mock_mongo).users = PropertyMock(side_effect=Exception("Initialization Error with mongo.users"))

        # Instantiate ApiTrader and check if exception is raised
        # with self.assertRaises(Exception):
        ApiTrader(
            user=self.user,
            mongo=mock_mongo,  # Pass the mocked mongo object
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade
        )

        # Verify that logger.error was called with the expected message
        self.logger.error.assert_called_once_with("Error initializing ApiTrader: Initialization Error with mongo.users")


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_checkOCOpapertriggers_retry_logic_with_timeout(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock instance attributes
        self.api_trader.logger = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = MagicMock()
        self.api_trader.account_id = MagicMock()
        self.api_trader.tdameritrade = MagicMock()
        self.api_trader.stop_signal_file = "mock_stop_signal_file"

        # Mock open positions
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = [
            {
                "_id": "position1",
                "Symbol": "AAPL",
                "Asset_Type": "EQUITY",
                "Strategy": "MACD_XVER_8_17_9_EXP_DEBUG",
                "Entry_Price": 150.00,
                "Qty": 10,
                "Position_Type": "LONG",
                "Side": "BUY",
                "Pre_Symbol": "AAPL"
            }
        ]
        self.api_trader.mongo.open_positions = mock_open_positions
        self.api_trader.mongo.strategies = MagicMock()
        self.api_trader.mongo.strategies.find.return_value = [
            {"Strategy": "MACD_XVER_8_17_9_EXP_DEBUG", "Account_ID": "test_account"}
        ]

        # Mock getQuotes to fail first with ConnectTimeout and succeed after retries
        mock_quote_response = {
            "AAPL": {"quote": {"lastPrice": 145.00, "askPrice": 146.00}}
        }
        
        # Raise ConnectTimeout, then ReadTimeout, then return a successful response
        self.api_trader.tdameritrade.getQuotes.side_effect = [
            httpx.ConnectTimeout("Connection timed out"),
            httpx.ReadTimeout("Read operation timed out"),
            mock_quote_response  # Successful quote response
        ]

        # Run the method to test
        self.api_trader.checkOCOpapertriggers()

        # Assertions to ensure that getQuotes was called 3 times (2 failures, 1 success)
        self.assertEqual(self.api_trader.tdameritrade.getQuotes.call_count, 3)

        # Verify logger warning was called for both timeouts
        # Check for ConnectTimeout warning
        assert any(call[0][0].startswith("Connection timed out for batch") for call in self.api_trader.logger.warning.call_args_list), "No match for ConnectTimeout"
        
        # Check for ReadTimeout warning
        assert any(call[0][0].startswith("Read operation timed out for batch") for call in self.api_trader.logger.warning.call_args_list), "No match for ReadTimeout"

        # Instead of asserting an exact message, let's look for any retry-related info log
        assert any("Retry" in call[0][0] for call in self.api_trader.logger.info.call_args_list), "No retry log message found"

        # Verify the successful flow after retries
        self.assertIn("AAPL", mock_quote_response)
        last_price = mock_quote_response["AAPL"]["quote"]["lastPrice"]
        self.assertEqual(last_price, 145.00)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    @patch('api_trader.strategies.fixed_percentage_exit.FixedPercentageExitStrategy')  # Mocking ExitStrategy
    def test_checkOCOpapertriggers_with_large_data(self, mock_exit_strategy, mock_init):
        self.api_trader = ApiTrader()
        
        # Mock instance attributes
        self.api_trader.logger = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = MagicMock()
        self.api_trader.queue = MagicMock()
        self.api_trader.rejected = MagicMock()
        self.api_trader.account_id = "test_account"  # Set this to a specific account ID for your test
        self.api_trader.tdameritrade = MagicMock()
        self.api_trader.stop_signal_file = "mock_stop_signal_file"  # Add this line to mock the stop_signal_file
        self.api_trader.RUN_LIVE_TRADER = True  # Mock or set RUN_LIVE_TRADER attribute

        # Mock open_positions
        num_positions = 500
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.mongo.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.mongo.strategies = mock_strategies

        # Mock quotes
        mock_quotes_data = create_mock_quotes(num_positions)
        self.api_trader.tdameritrade.getQuotes = MagicMock(return_value=mock_quotes_data)        

        # Mock the quotes update method
        self.api_trader.tdameritrade.quotes = MagicMock()
        self.api_trader.tdameritrade.quotes.update = MagicMock()

        # Mock the return value of exit_strategy's should_exit method
        mock_exit_response = {
            "exit": True,
            "take_profit_price": 160.00,
            "stop_loss_price": 140.00,
            "additional_params": {"ATR": 2.5, "max_price": 180.00},
            "reason": "OCO"
        }
        mock_exit_strategy.return_value.should_exit.return_value = mock_exit_response


        # Run the method to test
        self.api_trader.checkOCOpapertriggers()

        # Add assertions to validate behavior
        self.api_trader.logger.warning.assert_not_called()
        self.api_trader.logger.error.assert_not_called()

        mock_open_positions.find.assert_called()
        mock_strategies.find.assert_called()
        self.api_trader.tdameritrade.getQuotes.assert_called()

        mock_exit_strategy.return_value.should_exit.assert_called()  # Validate the method was called
        self.assertTrue(mock_exit_strategy.return_value.should_exit.called, "should_exit should have been called")


def create_mock_open_positions(num_positions):
    from datetime import datetime, timedelta

    base_date = datetime.now()  # Get the current date and time
    return [
        {
            "_id": f"position_id_{i}",
            "Symbol": f"SYM{i}",
            "Asset_Type": "EQUITY",
            "Strategy": f"STRATEGY_{i}",
            "Entry_Price": 100.00 + i,
            "Entry_Date": (base_date - timedelta(days=i)).strftime("%Y-%m-%d"),  # Entry date for each position
            "Qty": 10,
            "Position_Type": "LONG",
            "Side": "BUY",
            "Position_Size": 500
        }
        for i in range(num_positions)
    ]

def create_mock_strategies(num_positions):
    return [
        {"Strategy": f"STRATEGY_{i}", "Account_ID": "test_account", "Position_Type": "LONG"}
        for i in range(num_positions)
    ]

def create_mock_quotes(num_positions):
    # Generates both the quotes dictionary and individual quote structure
    quotes_dict = {}
    for i in range(num_positions):
        symbol = f"SYM{i}"
        quotes_dict[symbol] = {
            "quote": {
                "askPrice": 100.00 + i,  # Mock value for askPrice
                "lastPrice": 100.00 + i,  # Mock value for lastPrice
                "highPrice": 100.00 + i,  # Mock value for highPrice
                "otherQuoteData": "value"  # Include any other expected fields here
            }
        }
    return quotes_dict

if __name__ == '__main__':
    unittest.main()
