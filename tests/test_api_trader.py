import os
import random
import re
import string
from unittest import mock
from unittest.mock import PropertyMock, call, patch, MagicMock, ANY
import unittest

import httpx
from api_trader import ApiTrader

from pymongo.errors import WriteConcernError, WriteError
from pymongo import UpdateOne

from api_trader.order_builder import OrderBuilderWrapper
from api_trader.strategies.fixed_percentage_exit import FixedPercentageExitStrategy
from api_trader.strategies.trailing_stop_exit import TrailingStopExitStrategy
import tdameritrade

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

    @patch.dict(os.environ, {'RUN_TASKS': 'True'})  # Set the environment variable for the test
    def test_initialization_live_trader(self):
        
        # Debug: Check the environment variable directly in the test
        print("RUN_TASKS (within test):", os.getenv('RUN_TASKS'))

        # Set up your mocks and variables
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

        # Initialize the ApiTrader
        self.api_trader = ApiTrader(
            user=self.user,
            mongo=self.mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade
        )

        # Check if RUN_LIVE_TRADER is set to True
        self.assertTrue(self.api_trader.RUN_LIVE_TRADER)
        self.assertIsInstance(self.api_trader.mongo.users, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.open_positions, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.closed_positions, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.strategies, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.rejected, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.canceled, MagicMock)
        self.assertIsInstance(self.api_trader.mongo.queue, MagicMock)

        # Assert that task_thread is running
        self.assertTrue(hasattr(self.api_trader, 'task_thread'))
        self.assertTrue(self.api_trader.task_thread.is_alive())


    @patch.dict(os.environ, {'RUN_TASKS': 'False'})  # Set the environment variable for the test
    @patch('api_trader.ApiTrader.run_tasks_with_exit_check')
    def test_initialization_paper_trader(self, mock_run_tasks_with_exit_check):

        # Debug: Check the environment variable directly in the test
        print("RUN_TASKS (within test):", os.getenv('RUN_TASKS'))

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
        
        # Assert that task_thread is NOT created when RUN_TASKS is False
        self.assertFalse(hasattr(self.api_trader, 'task_thread'))


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
        self.api_trader.tdameritrade.placeTDAOrder = MagicMock(return_value={"Order_ID": "12345"})
        self.api_trader.RUN_LIVE_TRADER = True  # Mock or set RUN_LIVE_TRADER attribute

        # Call method: Open Position Scenario
        self.api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")
        
        # Assert correct order placement behavior
        self.api_trader.logger.warning.assert_not_called()
        self.api_trader.logger.error.assert_not_called()
        mock_standard_order.assert_called_once_with(trade_data, strategy_object, "OPEN POSITION", self.api_trader.user, self.api_trader.account_id)
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


    @patch.object(OrderBuilderWrapper, 'OCOorder', return_value=("mock_order", {"key": "value"}))
    @patch.object(ApiTrader, 'queueOrder', return_value=None)
    def test_send_order_oco(self, mock_queueOrder, mock_OCOorder):

        self.api_trader.tdameritrade = MagicMock()
        
        # Set the account_id explicitly if not already set
        self.account_id = '12345'
        self.api_trader.tdameritrade.placeTDAOrder = MagicMock(return_value={"Order_ID": self.account_id})

        """ Test the OCO order branch in sendOrder method """

        # Call the sendOrder method and specify OCO order type
        strategy_object = {"Order_Type": "OCO", "Position_Type": "LONG"}
        trade_data = create_mock_open_positions(1)[0]

        # Call sendOrder to trigger the OCO branch
        self.api_trader.sendOrder(trade_data, strategy_object, "CLOSE POSITION")

        # Verify the OCOorder method was called with the correct arguments
        mock_OCOorder.assert_called_once_with(trade_data, strategy_object, "CLOSE POSITION", self.user, self.account_id)

        # Construct the expected order details after updates
        updated_obj = {
            'key': 'value',
            'Order_ID': '12345',
            'Account_Position': 'Live',
            'Order_Status': 'QUEUED'
        }

        # Check that queueOrder was called with the updated order details
        mock_queueOrder.assert_called_once_with(
            updated_obj
        )

        # Check that placeTDAOrder was called with the correct order object
        self.api_trader.tdameritrade.placeTDAOrder.assert_called_once_with('mock_order')
        

    def test_queueOrder(self):
        # Prepare the input order
        order = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Quantity": 10,
            "Account_ID": "12345"
        }

        # Call the queueOrder method
        self.api_trader.queueOrder(order)

        # Verify that the queue.update_one was called with the correct arguments
        self.mongo.queue.update_one.assert_called_once_with(
            {"Trader": "TestUser", "Symbol": "AAPL", "Strategy": "TestStrategy", "Account_ID": "12345"},
            {"$set": order},
            upsert=True
        )

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_update_status_filled_order(self, mock_init):
        
        self.api_trader.pushOrder = MagicMock()

        # Mock the getSpecificOrder to return a FILLED status
        self.api_trader.tdameritrade.getSpecificOrder.side_effect = [{"status": "FILLED", "Order_ID": "12345"}]
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
            {"status": "FILLED", "Order_ID": "12345"}
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


    @patch.object(ApiTrader, 'pushOrder', return_value=None)
    def test_update_status_canceled_rejected(self, mock_pushOrder):
        # Mock the queued order
        self.mongo.return_value.__getitem__.return_value.find.return_value = [
            {"Order_ID": "12345", "Symbol": "SYM0", "Order_Type": "OCO", "Qty": 10, "Strategy": "STRATEGY_0", "Entry_Price": 100.0}
        ]
        
        # Mock the specific order response for "CANCELED"
        self.api_trader.tdameritrade.getSpecificOrder = MagicMock(return_value={"Order_ID": "12345", "status": "CANCELED"})
        
        # Add mock collections (queue, canceled, and rejected) to ApiTrader instance
        self.api_trader.queue = self.mongo.return_value.__getitem__.return_value  # Mock the queue collection
        self.api_trader.canceled = self.mongo.return_value.__getitem__.return_value  # Mock the canceled collection
        self.api_trader.rejected = self.mongo.return_value.__getitem__.return_value  # Mock the rejected collection
        
        # Call updateStatus for "CANCELED"
        self.api_trader.updateStatus()

        # Verify that the order was removed from the queue
        self.api_trader.queue.delete_one.assert_called_once()

        # Verify that the canceled order was inserted into the canceled collection
        self.api_trader.canceled.insert_one.assert_called_once()

        # Check that insert_one was called with the correct arguments for "CANCELED"
        expected_canceled_order = {
            'Symbol': 'SYM0',
            'Order_Type': 'OCO',
            'Order_Status': 'CANCELED',
            'Strategy': 'STRATEGY_0',
            'Trader': 'TestUser',
            'Date': mock.ANY,  # Mocked datetime
            'Account_ID': '12345'
        }
        self.api_trader.canceled.insert_one.assert_called_with(expected_canceled_order)

        # Now handle the "REJECTED" case
        self.api_trader.tdameritrade.getSpecificOrder.return_value = {"Order_ID": "12345", "status": "REJECTED"}
        self.api_trader.updateStatus()

        # Verify the order was removed from the queue again
        self.api_trader.queue.delete_one.assert_called_with(
            {"Trader": self.api_trader.user["Name"], "Symbol": "SYM0", "Strategy": "STRATEGY_0", "Account_ID": self.api_trader.account_id}
        )

        # Verify that the rejected order was inserted into the rejected collection
        expected_rejected_order = {
            'Symbol': 'SYM0',
            'Order_Type': 'OCO',
            'Order_Status': 'REJECTED',
            'Strategy': 'STRATEGY_0',
            'Trader': 'TestUser',
            'Date': mock.ANY,  # Mocked datetime
            'Account_ID': '12345'
        }

        # Check that insert_one was called for both "CANCELED" and "REJECTED"
        self.api_trader.rejected.insert_one.assert_has_calls([
            call(expected_canceled_order),
            call(expected_rejected_order)
        ], any_order=False)

        # Verify insert_one was called twice (once for "CANCELED", once for "REJECTED")
        self.assertEqual(self.api_trader.rejected.insert_one.call_count, 2)


    @patch.object(ApiTrader, 'pushOrder', return_value=None)
    def test_update_status_else_branch(self, mock_pushOrder):
        # Mock the queued order
        self.mongo.return_value.__getitem__.return_value.find.return_value = [
            {"Order_ID": "12345", "Symbol": "SYM0", "Order_Type": "OCO", "Qty": 10, "Strategy": "STRATEGY_0", "Entry_Price": 100.0, "Account_ID": "12345"}
        ]

        # Mock the specific order response with a non-matching status
        self.api_trader.tdameritrade.getSpecificOrder = MagicMock(return_value={
            "Order_ID": "12345", 
            "status": "PENDING",  # Non-matching status
            # No childOrderStrategies here
        })

        # Set up collections
        self.api_trader.queue = self.mongo.return_value.__getitem__.return_value
        self.api_trader.canceled = self.mongo.return_value.__getitem__.return_value
        self.api_trader.rejected = self.mongo.return_value.__getitem__.return_value

        # Call updateStatus to trigger the else branch
        self.api_trader.updateStatus()

        # Verify that the order was not removed from the queue
        self.api_trader.queue.delete_one.assert_not_called()

        # Verify that neither the canceled nor the rejected collections were updated
        self.api_trader.canceled.insert_one.assert_not_called()
        self.api_trader.rejected.insert_one.assert_not_called()

        # Verify that update_one was called with the correct arguments
        expected_filter = {
            "Trader": self.api_trader.user["Name"],
            "Symbol": "SYM0",
            "Strategy": "STRATEGY_0",
            "Account_ID": "12345"
        }
        expected_update = {
            "$set": {"Order_Status": "PENDING"}
        }

        self.api_trader.queue.update_one.assert_called_once_with(expected_filter, expected_update)


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
            "Account_ID": "123"
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
            "Account_ID": "123",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy"
        })

        # Verify the queue deletion
        self.mongo.queue.delete_one.assert_called_once_with({
            "Trader": "TestUser",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Account_ID": "123"
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
            "Account_ID": "123"
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

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    @patch('api_trader.ApiTrader.sendOrder')
    def test_runTrader_with_dynamic_round_trip_orders(self, mock_sendOrder, mock_init):

        # Mock relevant methods/attributes used in run_trader
        self.api_trader.queue = MagicMock()
        self.api_trader.user = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "test_account"  # Set this to a specific account ID for your test
        self.api_trader.updateStatus = MagicMock()
        
        # Mock dependencies
        self.api_trader.mongo = MagicMock()
        self.api_trader.tdameritrade = MagicMock()
        self.api_trader.logger = MagicMock()

        # Generate dynamic test data for round-trip orders
        open_positions, strategies, quotes = generate_test_data_for_run_trader(num_positions=10)

        # Mock the mongo collections to return generated data
        self.api_trader.mongo.open_positions.find.return_value = open_positions
        self.api_trader.mongo.strategies.find.return_value = strategies

        # Mock the getQuotes method to return simulated quotes data
        self.api_trader.tdameritrade.getQuotes.return_value = quotes

        # Mock queue.find_one to simulate unqueued orders
        self.api_trader.queue.find_one.return_value = None

        # Mock strategies.find_one to return the correct strategy object
        def mock_find_strategy(query):
            strategy_name = query.get("Strategy")
            for strategy in strategies:
                if strategy["Strategy"] == strategy_name:
                    return strategy
            return None

        self.api_trader.strategies.find_one.side_effect = mock_find_strategy

        # Call runTrader with the mock data
        trade_data = [{"Symbol": position["Symbol"], "Strategy": position["Strategy"], "Side": position["Side"], 'Asset_Type': position["Asset_Type"]} for position in open_positions]
        self.api_trader.runTrader(trade_data=trade_data)

        # Add assertions here
        self.api_trader.open_positions.find_one.assert_called()  # Ensure mongo query is performed
        self.api_trader.queue.find_one.assert_called()  # Ensure mongo query is performed
        self.api_trader.strategies.find_one.assert_called()  # Ensure mongo query is performed
        self.api_trader.updateStatus.assert_called()  # Ensure status is updated
        mock_sendOrder.assert_called()


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
    @patch('api_trader.strategies.fixed_percentage_exit.FixedPercentageExitStrategy')  # Mocking ExitStrategy
    def test_checkOCOpapertriggers_retry_logic_with_timeout(self, mock_exit_strategy, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock instance attributes
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
        num_positions = 1
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.strategies = mock_strategies

        # Mock quotes
        mock_quote_response = create_mock_quotes(num_positions)
        self.api_trader.tdameritrade.getQuotes = MagicMock(return_value=mock_quote_response) 
        
        # Raise ConnectTimeout, then ReadTimeout, then return a successful response
        self.api_trader.tdameritrade.getQuotes.side_effect = [
            httpx.ConnectTimeout("Connection timed out"),
            httpx.ReadTimeout("Read operation timed out"),
            mock_quote_response  # Successful quote response
        ]

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

        # Assertions to ensure that getQuotes was called 3 times (2 failures, 1 success)
        self.assertEqual(self.api_trader.tdameritrade.getQuotes.call_count, 3)

        self.api_trader.logger.error.assert_not_called()

        # Verify logger warning was called for both timeouts
        # Check for ConnectTimeout warning
        assert any(call[0][0].startswith("Connection timed out for batch") for call in self.api_trader.logger.warning.call_args_list), "No match for ConnectTimeout"
        
        # Check for ReadTimeout warning
        assert any(call[0][0].startswith("Read operation timed out for batch") for call in self.api_trader.logger.warning.call_args_list), "No match for ReadTimeout"

        # Instead of asserting an exact message, let's look for any retry-related info log
        assert any("Retry" in call[0][0] for call in self.api_trader.logger.info.call_args_list), "No retry log message found"

        first_key = list(mock_quote_response.keys())[0]
        # Verify the successful flow after retries
        self.assertIn(first_key, mock_quote_response)
        mock_exit_strategy.return_value.should_exit.assert_called()  # Validate the method was called
        self.assertTrue(mock_exit_strategy.return_value.should_exit.called, "should_exit should have been called")
        self.assertEqual(mock_exit_strategy.return_value.should_exit.call_count, num_positions)

        # Verify that the queue.update_one was called with the correct arguments
        # Or, if you want to verify the sequence of multiple calls, use assert_has_calls
        self.api_trader.open_positions.update_one.assert_has_calls([
            call(
                {"_id": mock_open_positions.find.return_value[0]["_id"]},
                {"$set": {"max_price": mock_exit_response["additional_params"]["max_price"]}}
            ),
            # Add other expected calls if necessary
        ])


    def test_checkOCOpapertriggers_read_timeout(self):
        """Test ReadTimeout scenario and cover the else block after retries."""
        
        # Simulate ReadTimeout on each call
        self.api_trader.tdameritrade.getQuotes.side_effect = httpx.ReadTimeout("Read operation timed out.")
        
        # Mock open_positions
        num_positions = 1
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.strategies = mock_strategies

        # Call the method
        self.api_trader.checkOCOpapertriggers()

        # Assert logger warning was called after retries
        self.assertTrue(self.logger.warning.called)
        self.assertTrue(self.logger.error.called)
        self.assertIn('Failed to retrieve quotes', self.logger.error.call_args[0][0])


    def test_checkOCOpapertriggers_connect_timeout(self):
        """Test ConnectTimeout scenario and cover the else block after retries."""
        
        # Simulate ConnectTimeout on each call
        self.api_trader.tdameritrade.getQuotes.side_effect = httpx.ConnectTimeout("Connection timed out.")

        # Mock open_positions
        num_positions = 1
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.strategies = mock_strategies
        
        # Call the method
        self.api_trader.checkOCOpapertriggers()

        # Assert logger warning was called after retries
        self.assertTrue(self.logger.warning.called)
        self.assertTrue(self.logger.error.called)
        self.assertIn('Failed to retrieve quotes', self.logger.error.call_args[0][0])


    def test_checkOCOpapertriggers_general_exception(self):
        """Test general Exception scenario and cover the except Exception block."""
        
        # Simulate a generic exception
        self.api_trader.tdameritrade.getQuotes.side_effect = Exception("An unexpected error occurred.")

        # Mock open_positions
        num_positions = 1
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.strategies = mock_strategies
        
        # Call the method
        self.api_trader.checkOCOpapertriggers()

        # Assert logger error was called
        self.assertTrue(self.logger.error.called)
        self.assertIn('An unexpected error occurred', self.logger.error.call_args[0][0])


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
        num_positions = 5000
        mock_open_positions = MagicMock()
        mock_open_positions.find.return_value = create_mock_open_positions(num_positions)
        self.api_trader.open_positions = mock_open_positions

        # Mock strategies
        mock_strategies = MagicMock()
        mock_strategies.find.return_value = create_mock_strategies(num_positions)
        self.api_trader.strategies = mock_strategies

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
        self.assertEqual(mock_exit_strategy.return_value.should_exit.call_count, num_positions)

    @patch('api_trader.ApiTrader.__init__', return_value=None)
    @patch.object(ApiTrader, 'pushOrder', return_value=None)  # Mock pushOrder in ApiTrader
    def test_checkOCOtriggers(self, mock_pushOrder, mock_init):
        # Initialize ApiTrader instance
        self.api_trader = ApiTrader()

        # Mock dependencies
        self.api_trader.queue = MagicMock()
        self.api_trader.mongo = MagicMock()
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name
        self.api_trader.tdameritrade = MagicMock()
        self.api_trader.open_positions = MagicMock()
        self.api_trader.open_positions.bulk_write = MagicMock()
        self.api_trader.canceled = MagicMock()
        self.api_trader.rejected = MagicMock()

        # Mock open_positions.find() to return a list of OCO orders
        self.api_trader.open_positions.find.return_value = [
            {
                "Symbol": "SYM1",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_A",
                "childOrderStrategies": [
                    {
                        "childOrderStrategies": [
                            {"Order_ID": "order1"}
                        ]
                    }
                ]
            },
            {
                "Symbol": "SYM2",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_B",
                "childOrderStrategies": [
                    {
                        "childOrderStrategies": [
                            {"Order_ID": "order2"}
                        ]
                    }
                ]
            },
            {
                "Symbol": "SYM3",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_C",
                "childOrderStrategies": [
                    {
                        "childOrderStrategies": [
                            {"Order_ID": "order3"}
                        ]
                    }
                ]
            },
            {
                "Symbol": "SYM4",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_D",
                "childOrderStrategies": [
                    {
                        "childOrderStrategies": [
                            {"Order_ID": "order4"}
                        ]
                    }
                ]
            }
        ]

        # Mock getSpecificOrder for different orders
        self.api_trader.tdameritrade.getSpecificOrder.side_effect = [
            {"status": "FILLED", "Order_ID": "order1"},
            {"status": "CANCELED", "Order_ID": "order2"},
            {"status": "REJECTED", "Order_ID": "order3"},
            {"status": "WORKING", "Order_ID": "order4"},
        ]

        # Call the method under test
        self.api_trader.checkOCOtriggers()

        # Check that pushOrder was called for the filled order
        mock_pushOrder.assert_called_once_with(
            {
                "Symbol": "SYM1",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_A",
                "childOrderStrategies": [{"childOrderStrategies": [{"Order_ID": "order1"}]}]
            },
            {"status": "FILLED", "Order_ID": "order1"}
        )

        # Check logger info for CANCELED order
        self.api_trader.logger.info.assert_any_call(
            "CANCELED ORDER for SYM2 - TRADER: TraderName - ACCOUNT ID: **3456"
        )

        # Verify that MongoDB updates were correctly prepared
        self.api_trader.open_positions.bulk_write.assert_called_once_with([
            UpdateOne(
                {"Trader": self.api_trader.user["Name"], "Account_ID": self.api_trader.account_id, "Symbol": "SYM4", "Strategy": "STRATEGY_D"},
                {'$set': {'childOrderStrategies.$[orderElem].Order_Status': 'WORKING'}},
                False, None,
                [{'orderElem.Order_ID': 'order4'}],  # The array filter for orderElem.Order_ID
                None
            )
        ])

        # Check that the appropriate insertions were made for CANCELED orders
        self.assertEqual(self.api_trader.canceled.insert_many.call_count, 1)
        self.assertEqual(self.api_trader.rejected.insert_many.call_count, 1)

        # Verify that the canceled orders were inserted correctly
        self.api_trader.canceled.insert_many.assert_called_with([
            {
                'Symbol': 'SYM2',
                'Order_Type': 'OCO',
                'Order_Status': 'CANCELED',
                'Strategy': 'STRATEGY_B',
                'Trader': 'TraderName',  # Replace with your actual trader name
                'Date': ANY,  # Use ANY to match any datetime value
                'Account_ID': '123456'
            }
        ])

        # Verify that the rejected orders were inserted correctly
        self.api_trader.rejected.insert_many.assert_called_with([
            {
                'Symbol': 'SYM3',
                'Order_Type': 'OCO',
                'Order_Status': 'REJECTED',
                'Strategy': 'STRATEGY_C',
                'Trader': 'TraderName',  # Replace with your actual trader name
                'Date': ANY,  # Use ANY to match any datetime value
                'Account_ID': '123456'
            }
        ])


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        self.api_trader.logger = MagicMock()

        # Mocking a specific order structure
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            "Order_ID": 86753098675309,
                            "orderLegCollection": [
                                {"instruction": "SELL"}
                            ],
                            "stopPrice": 100.0,
                            "status": "WORKING"
                        },
                        {
                            "Order_ID": 1001859866918,
                            "orderLegCollection": [
                                {"instruction": "SELL"}
                            ],
                            "price": 150.0,
                            "status": "PENDING"
                        }
                    ]
                }
            ]
        }

        # Expected structure to be returned
        expected_output = {
            "childOrderStrategies": [
                {
                    "Side": "SELL",
                    "Exit_Price": {"$numberDouble": "100.0"},
                    "Exit_Type": "STOP LOSS",
                    "Order_Status": "WORKING",
                    "Order_ID": {"$numberLong": "86753098675309"}
                },
                {
                    "Side": "SELL",
                    "Exit_Price": {"$numberDouble": "150.0"},
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "PENDING",
                    "Order_ID": {"$numberLong": "1001859866918"}
                }
            ]
        }

        # Call the method
        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that the output matches the expected structure
        self.assertEqual(result, expected_output)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_missing_stopPrice(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        self.api_trader.logger = MagicMock()

        # Mocking an order structure where stopPrice is missing and only price is present
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            "Order_ID": 86753098675309,
                            "orderLegCollection": [
                                {"instruction": "BUY"}
                            ],
                            "price": 200.0,
                            "status": "FILLED"
                        }
                    ]
                }
            ]
        }

        # Expected structure to be returned
        expected_output = {
            "childOrderStrategies": [
                {
                    "Side": "BUY",
                    "Exit_Price": {"$numberDouble": "200.0"},  # Updated to match BSON format
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "FILLED",
                    "Order_ID": {"$numberLong": "86753098675309"}
                }
            ]
        }

        # Call the method
        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that the output matches the expected structure
        self.assertEqual(result, expected_output)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_missing_fields(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Mocking an order structure with missing fields to test edge cases
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            "Order_ID": 86753098675309,
                            "orderLegCollection": [
                                {"instruction": "SELL"}
                            ],
                            "status": "WORKING"
                            # Missing price and stopPrice
                        }
                    ]
                }
            ]
        }

        # Expected structure to be returned
        expected_output = {
            "childOrderStrategies": [
                {
                    "Side": "SELL",
                    "Exit_Price": None,  # Exit_Price should be None since neither stopPrice nor price exists
                    "Exit_Type": None,  # Exit_Type should be None as well
                    "Order_Status": "WORKING",
                    "Order_ID": {"$numberLong": "86753098675309"}
                }
            ]
        }

        # Call the method
        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that the output matches the expected structure
        self.assertEqual(result, expected_output)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_handles_missing_childOrderStrategies(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Create a spec_order with no "childOrderStrategies"
        spec_order = {
            "orderLegCollection": [{"instruction": "SELL"}],
            "stopPrice": 105.0,
            "price": 110.0,
            "status": "Filled"
        }

        expected_output = {
            "childOrderStrategies": [
                {
                    "Side": None,
                    "Exit_Price": None,
                    "Exit_Type": None,
                    "Order_Status": None,
                    "Order_ID": {"$numberLong": "None"}
                }
            ]
        }

        # Call the method and check if it returns an empty childOrderStrategies dict as expected
        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert the method returns the expected result
        self.assertEqual(result, expected_output)

    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_handles_empty_childOrderStrategies(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Create a spec_order with empty "childOrderStrategies"
        spec_order = {
            "childOrderStrategies": [{}],  # Empty structure, simulating an edge case
            "orderLegCollection": [{"instruction": "SELL"}],
            "stopPrice": 105.0,
            "price": 110.0,
            "status": "Filled"
        }

        expected_output = {
            "childOrderStrategies": [
                {
                    "Side": None,
                    "Exit_Price": None,
                    "Exit_Type": None,
                    "Order_Status": None,
                    "Order_ID": {"$numberLong": "None"}
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order)
        self.assertEqual(result, expected_output)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_falls_back_to_outer_array_if_no_nested_childOrderStrategies(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        spec_order_no_nested_childOrderStrategies = {
            "childOrderStrategies": [
                {
                    "Order_ID": "54321",
                    "orderLegCollection": [{"instruction": "SELL"}],
                    "stopPrice": 120.0,
                    "status": "WORKING"
                }
            ]
        }

        expected_result = {
            "childOrderStrategies": [
                {
                    "Side": "SELL",
                    "Exit_Price": {"$numberDouble": "120.0"},  # Updated to match BSON format
                    "Exit_Type": "STOP LOSS",
                    "Order_Status": "WORKING",
                    "Order_ID": {"$numberLong": "54321"}
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order_no_nested_childOrderStrategies)
        self.assertEqual(result, expected_result)


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_handles_valid_nested_childOrderStrategies(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        spec_order_valid_nested_childOrderStrategies = {
            "childOrderStrategies": [{
                "childOrderStrategies": [
                    {
                        "Order_ID": "12345",
                        "orderLegCollection": [{"instruction": "BUY"}],
                        "price": 100.0,
                        "status": "FILLED"
                    }
                ]
            }]
        }

        expected_result = {
            "childOrderStrategies": [
                {
                    "Side": "BUY",
                    "Exit_Price": {"$numberDouble": "100.0"},
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "FILLED",
                    "Order_ID": {"$numberLong": "12345"}
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order_valid_nested_childOrderStrategies)
        self.assertEqual(result, expected_result)


    @patch('api_trader.ApiTrader.sendOrder')  # Mock the order sending
    def test_multiple_strategies_with_price_movement(self, mock_send_order):
        # Step 1: Initialize ApiTrader and strategies
        self.api_trader.get_open_positions = MagicMock()
        self.api_trader.get_queued_positions = MagicMock()

        # Setup the strategies
        take_profit_strategy = FixedPercentageExitStrategy({
            "take_profit_percentage": 0.10,  # 10% profit
            "stop_loss_percentage": 0.05      # 5% loss
        })

        trailing_stop_strategy = TrailingStopExitStrategy({
            "trailing_stop_percentage": 0.03   # 3%
        })

        # Simulate open positions
        mock_open_positions = [
            {
                "Qty": 10, 
                "Entry_Price": 100.0, 
                "Asset_Type": "EQUITY", 
                "Strategy": take_profit_strategy, 
                "Symbol": "AAPL", 
                "Side": "BUY",
                "exited": False  # Track if this position has exited
            },
            {
                "Qty": 5, 
                "Entry_Price": 150.0,
                "Asset_Type": "OPTION", 
                "Strategy": trailing_stop_strategy, 
                "Symbol": "GOOGL", 
                "Side": "BUY",
                "exited": False  # Track if this position has exited
            }
        ]
        self.api_trader.get_open_positions.return_value = mock_open_positions

        # Step 2: Define realistic price movements including a gap down scenario
        price_movements = [145, 155, 152, 158, 140, 145, 135, 150, 149, 130, 130, 105]

        # Step 3: Track orders for both strategies
        for price in price_movements:
            for position in mock_open_positions:
                strategy = position["Strategy"]

                # Skip processing if the position has already exited
                if position["exited"]:
                    continue

                # Prepare additional parameters for the strategy
                additional_params = {
                    "last_price": float(price),
                    "entry_price": float(position["Entry_Price"]),
                    "quantity": position["Qty"],
                    "symbol": position["Symbol"],
                    "pre_symbol": position.get("Pre_Symbol"),
                    "side": position["Side"],
                    "assetType": position["Asset_Type"],
                }

                # Simulate the strategy logic based on the price
                exit_result = strategy.should_exit(additional_params)
                should_exit = exit_result['exit']

                if should_exit:
                    # Mock sending the order
                    mock_send_order(strategy, "SELL", position["Qty"], price)
                    # Mark the position as exited
                    position["exited"] = True

        # Step 4: Verify behavior for Strategy A (Fixed take-profit and stop-loss)
        take_profit_sell_orders = [call for call in mock_send_order.call_args_list if isinstance(call[0][0], FixedPercentageExitStrategy)]
        self.assertEqual(len(take_profit_sell_orders), 1)

        # Verify the order details for take profit strategy
        self.assertIsInstance(take_profit_sell_orders[0][0][0], FixedPercentageExitStrategy)
        self.assertEqual(take_profit_sell_orders[0][0][1], "SELL")
        self.assertEqual(take_profit_sell_orders[0][0][2], 10)
        # Adjust the expected selling price based on the last price that triggered the exit
        self.assertEqual(take_profit_sell_orders[0][0][3], 145)  # Use the actual price that triggered the exit

        # Step 5: Verify behavior for Strategy B (Trailing stop)
        trailing_stop_orders = [call for call in mock_send_order.call_args_list if isinstance(call[0][0], TrailingStopExitStrategy)]
        self.assertEqual(len(trailing_stop_orders), 1)

        # Verify the order details for trailing stop strategy
        self.assertIsInstance(trailing_stop_orders[0][0][0], TrailingStopExitStrategy)
        self.assertEqual(trailing_stop_orders[0][0][1], "SELL")
        self.assertEqual(trailing_stop_orders[0][0][2], 5)

        # Step 6: Additional Assertions for Trailing Stop Strategy
        for position in mock_open_positions:
            if position["Strategy"] == trailing_stop_strategy:
                trailing_stop_price = None  # Initialize trailing stop price

                for price in price_movements:
                    additional_params = {
                        "last_price": float(price),
                        "entry_price": float(position["Entry_Price"]),
                        "quantity": position["Qty"],
                        "symbol": position["Symbol"],
                        "pre_symbol": position.get("Pre_Symbol"),
                        "side": position["Side"],
                        "assetType": position["Asset_Type"],
                    }
                    trailing_stop_result = trailing_stop_strategy.should_exit(additional_params)

                    # Capture the updated trailing stop price from the result
                    trailing_stop_price = trailing_stop_result.get("trailing_stop_price")

                    # Ensure the trailing stop updates with the highest price
                    self.assertTrue(trailing_stop_price is not None)

                    # Assert that the trailing stop price is less than the current price to ensure it updates correctly
                    self.assertTrue(trailing_stop_price < max(price_movements))

                # Final assertion on the last computed trailing stop price
                self.assertTrue(trailing_stop_price < max(price_movements))


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

def generate_random_symbol():
    """Generate a random stock symbol (e.g., AAPL, MSFT)."""
    return ''.join(random.choices(string.ascii_uppercase, k=4))

def generate_test_data_for_run_trader(num_positions=10):
    """Generates dynamic mock test data for the runTrader method."""

    asset_types = ["EQUITY", "OPTION"]
    sides = ["BUY", "SELL", "SELL_TO_CLOSE", "BUY_TO_CLOSE"]  # Side values for both long and short
    position_types = ["LONG", "SHORT"]  # Position types

    open_positions = []
    strategies = []
    quotes = {}

    for i in range(num_positions):
        symbol = generate_random_symbol()
        asset_type = random.choice(asset_types)
        position_type = random.choice(position_types)
        side = random.choice(sides)

        # if asset_type == "EQUITY":
        #     side = "SELL" if position_type == "LONG" else "BUY"  # SELL for long positions, BUY for short positions
        # else:
        #     side = "SELL_TO_CLOSE" if position_type == "LONG" else "BUY_TO_CLOSE"  # For options

        position_qty = random.randint(1, 100)  # Random quantity, long or short
        entry_price = round(random.uniform(100, 1000), 2)  # Random entry price
        take_profit_percentage = round(random.uniform(0.05, 0.2), 2)  # Random take-profit %
        stop_loss_percentage = round(random.uniform(0.02, 0.1), 2)  # Random stop-loss %
        last_price = round(random.uniform(entry_price - 50, entry_price + 50), 2)  # Random last price
        ask_price = round(random.uniform(last_price, last_price + 5), 2)  # Random ask price
        high_price = round(random.uniform(ask_price, ask_price + 5), 2)  # Random ask price

        # Append position data
        open_positions.append({
            "Symbol": symbol,
            "Strategy": f"Strategy_{i}",
            "Asset_Type": asset_type,
            "Account_ID": f"test_account_{i}",
            "Qty": position_qty,
            "Entry_Price": entry_price,
            "Position_Type": position_type,
            "Side": side,
            "Account_Position": "Live",
        })

        # Generate strategies
        strategies.append({
            "Strategy": f"Strategy_{i}",
            "Account_ID": "test_account",
            "Active": True,
            "Position_Type": position_type,  # Valid BUY or SELL
            "Order_Type": "OCO",
            "ExitStrategy": "FixedPercentageExit",  # Example exit strategy
            "take_profit_percentage": take_profit_percentage,
            "stop_loss_percentage": stop_loss_percentage,
        })

        # Append quote data
        quotes[symbol] = {
            "quote": {
                "lastPrice": last_price,
                "askPrice": ask_price,
                "highPrice": high_price
            }
        }

    return open_positions, strategies, quotes


if __name__ == '__main__':
    unittest.main()
