import asyncio
import os
import random
import string
from unittest import mock
from unittest.mock import AsyncMock, PropertyMock, patch, MagicMock, ANY
import unittest

import httpx
from api_trader import ApiTrader

from pymongo.errors import WriteConcernError, WriteError
from pymongo import UpdateOne

from api_trader.strategies.fixed_percentage_exit import FixedPercentageExitStrategy
from api_trader.strategies.trailing_stop_exit import TrailingStopExitStrategy
from assets.helper_functions import modifiedAccountID
from assets.helper_functions import getUTCDatetime, modifiedAccountID

class TestApiTrader(unittest.IsolatedAsyncioTestCase):

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
        self.async_mongo = AsyncMock()
        self.push = MagicMock()
        self.logger = MagicMock()
        self.account_id = "12345"
        self.tdameritrade = MagicMock()
        self.quote_manager_pool = MagicMock()

        with patch.dict(os.environ, {'RUN_TASKS': 'False'}):  # Set the environment variable for the test
            # Instantiate ApiTrader
            self.api_trader = ApiTrader(
                user=self.user,
                async_mongo=self.async_mongo,
                push=self.push,
                logger=self.logger,
                account_id=self.account_id,
                tdameritrade=self.tdameritrade,
                quote_manager_pool=self.quote_manager_pool
            )

        self.queue_order = {
            "_id": "111111",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Direction": "OPEN POSITION",
            "Account_ID": self.account_id,
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
    @patch("api_trader.position_updater.PositionUpdater.worker", new_callable=AsyncMock)
    @patch("api_trader.position_updater.PositionUpdater.start_workers", new_callable=AsyncMock)
    @patch("api_trader.position_updater.PositionUpdater.monitor_queue", new_callable=AsyncMock)
    async def test_initialization_live_trader(self, mock_monitor_queue, mock_start_workers, mock_worker):
        """Test ApiTrader initialization when RUN_TASKS is True and Account_Position is 'Live'."""

        # Set up your mocks and variables
        self.user = {
            "Name": "TestUser",
            "Accounts": {
                "12345": {
                    "Account_Position": "Live"
                }
            }
        }
        self.async_mongo = AsyncMock()
        self.push = MagicMock()
        self.logger = MagicMock()
        self.account_id = "12345"
        self.tdameritrade = MagicMock()
        self.quote_manager_pool = MagicMock()

        # Mock the get_or_create_manager method of the quote_manager_pool
        self.quote_manager_pool.get_or_create_manager = MagicMock(return_value=MagicMock())

        # Initialize the ApiTrader
        self.api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        # Check if RUN_LIVE_TRADER is set to True
        self.assertTrue(self.api_trader.RUN_LIVE_TRADER)

        # Verify the async_mongo object is assigned correctly
        self.assertIs(self.api_trader.async_mongo, self.async_mongo)

        # Verify quote_manager is retrieved from the pool
        self.quote_manager_pool.get_or_create_manager.assert_called_once_with(self.tdameritrade, self.logger)
        self.assertIsInstance(self.api_trader.quote_manager, MagicMock)

        await asyncio.sleep(0.1)

        # Verify that mocked async methods are awaited
        mock_start_workers.assert_awaited_once()
        mock_monitor_queue.assert_awaited_once()
        mock_worker.assert_not_awaited()


    @patch.dict(os.environ, {'RUN_TASKS': 'False'})  # Set the environment variable for the test
    @patch('api_trader.ApiTrader.run_tasks_with_exit_check')
    async def test_initialization_paper_trader(self, mock_run_tasks_with_exit_check):
        """Test ApiTrader initialization when RUN_TASKS is False and Account_Position is 'Paper'."""

        # Update user account position to 'Paper'
        self.user["Accounts"]["12345"]["Account_Position"] = "Paper"

        # Mock the quote_manager_pool for initialization
        self.quote_manager_pool = MagicMock()
        self.quote_manager_pool.get_or_create_manager = MagicMock(return_value=MagicMock())

        # Initialize ApiTrader
        self.api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        # Verify RUN_LIVE_TRADER is set to False for Paper accounts
        self.assertFalse(self.api_trader.RUN_LIVE_TRADER)

        # Assert that tasks are NOT scheduled when RUN_TASKS is False
        with patch("asyncio.create_task") as mock_create_task:
            await asyncio.sleep(0.1)  # Allow any tasks to start if they were incorrectly scheduled
            mock_create_task.assert_not_called()

        # Verify quote_manager is retrieved from the pool
        self.quote_manager_pool.get_or_create_manager.assert_called_once_with(self.tdameritrade, self.logger)

        # Assert that no threading-related attributes (like task_thread) are created
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

    async def test_send_order_live(self):
        """Test the sendOrder method when RUN_LIVE_TRADER is True."""

        # Setup mocks
        trade_data = {"Symbol": "AAPL", "Strategy": "test_strategy", "Side": "BUY"}
        strategy_object = {"Order_Type": "STANDARD", "Position_Type": "LONG", "Position_Size": 500, "Active": True}

        # Mock dependencies
        parent_order_mock = MagicMock()
        mock_standard_order = AsyncMock(return_value=(parent_order_mock, {}))
        mock_place_order = AsyncMock(return_value={"Order_ID": "12345"})
        mock_queue_order = AsyncMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        # Create ApiTrader instance with mock dependencies
        api_trader = ApiTrader(
            user=MagicMock(),
            async_mongo=AsyncMock(),
            push=MagicMock(),
            logger=MagicMock(),
            account_id="test_account",
            tdameritrade=MagicMock(),
            quote_manager_pool=quote_manager_pool
        )
        api_trader.logger = MagicMock()
        api_trader.mongo = MagicMock()
        api_trader.queueOrder = mock_queue_order
        api_trader.tdameritrade.placeTDAOrderAsync = mock_place_order
        api_trader.standardOrder = mock_standard_order
        api_trader.RUN_LIVE_TRADER = True

        # Call method: Open Position Scenario
        await api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")

        # Assertions for successful order placement
        mock_standard_order.assert_called_once_with(trade_data, strategy_object, "OPEN POSITION", api_trader.user, api_trader.account_id)
        mock_place_order.assert_called_once_with(parent_order_mock)
        mock_queue_order.assert_called_once()
        api_trader.logger.error.assert_not_called()

        # Simulate failure during order placement
        mock_standard_order.side_effect = Exception("Failed to place order")

        # Use assertRaises to expect the exception
        with self.assertRaises(Exception) as cm:
            await api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")
        
        self.assertEqual(str(cm.exception), "Failed to place order")

        # Validate that error logs contain the expected substring
        log_messages = [call[0][0] for call in api_trader.logger.error.call_args_list]
        self.assertTrue(any("Failed to place order" in message for message in log_messages))

        # Reset the side effect to avoid raising exceptions on subsequent calls
        mock_standard_order.side_effect = None

        # Test placing an order with RUN_LIVE_TRADER set to False
        api_trader.RUN_LIVE_TRADER = False
        await api_trader.sendOrder(trade_data, strategy_object, "OPEN POSITION")

        # Assert that placeTDAOrderAsync was not called in paper trading mode
        self.assertEqual(mock_place_order.call_count, 1)  # Should be called only once in live mode
        mock_queue_order.assert_called()  # Paper trading still enqueues the order


    @patch('api_trader.ApiTrader.queueOrder')
    async def test_send_order_paper(self, mock_queue_order):
        """Test the sendOrder method when RUN_LIVE_TRADER is False (paper trading mode)."""

        # Setup dependencies
        user = MagicMock()
        mongo = MagicMock()
        async_mongo = AsyncMock()
        push = MagicMock()
        logger = MagicMock()
        account_id = "test_account"
        tdameritrade = MagicMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        mock_quotes_data = create_mock_quotes(1)

        # Mock trade data and strategy object
        trade_data = {
            "Symbol": list(mock_quotes_data.keys())[0],
            "Strategy": "test_strategy",
            "Side": "SELL",
            "Qty": 10,
            "Entry_Price": 150.0,
            "Entry_Date": getUTCDatetime(),
            "Exit_Price": 155.0,
            "Last_Price": 156.0,
            "Exit_Date": getUTCDatetime(),
            "Position_Size": 5
        }
        strategy_object = {"Order_Type": "STANDARD", "Position_Type": "LONG"}

        # Create ApiTrader instance with mock dependencies
        api_trader = ApiTrader(
            user=user,
            async_mongo=async_mongo,
            push=push,
            logger=logger,
            account_id=account_id,
            tdameritrade=tdameritrade,
            quote_manager_pool=quote_manager_pool
        )
        api_trader.RUN_LIVE_TRADER = False  # Set to paper trading mode
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=mock_quotes_data)

        # Call sendOrder method
        await api_trader.sendOrder(trade_data, strategy_object, "CLOSE POSITION")

        # Verify that queueOrder is called
        mock_queue_order.assert_called_once()

    @patch.object(ApiTrader, 'queueOrder', new_callable=AsyncMock)
    @patch.object(ApiTrader, 'OCOorder', new_callable=AsyncMock)
    async def test_send_order_oco(self, mock_OCOorder, mock_queueOrder):
        """Test the OCO order branch in the sendOrder method."""

        # Setup dependencies
        user = MagicMock()
        mongo = MagicMock()
        async_mongo = AsyncMock()
        push = MagicMock()
        logger = MagicMock()
        account_id = "12345"
        tdameritrade = MagicMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        # Create ApiTrader instance with mock dependencies
        api_trader = ApiTrader(
            user=user,
            async_mongo=async_mongo,
            push=push,
            logger=logger,
            account_id=account_id,
            tdameritrade=tdameritrade,
            quote_manager_pool=quote_manager_pool
        )
        api_trader.RUN_LIVE_TRADER = True
        api_trader.tdameritrade.placeTDAOrderAsync = AsyncMock(return_value={"Order_ID": account_id})

        # Mock OCOorder response
        mock_OCOorder.return_value = ("mock_order", {"key": "value"})

        # Test the OCO order branch
        strategy_object = {"Order_Type": "OCO", "Position_Type": "LONG"}
        trade_data = {
            "Symbol": "AAPL",
            "Strategy": "test_strategy",
            "Side": "SELL",
            "Qty": 10,
            "Price": 150.00
        }

        # Call sendOrder
        await api_trader.sendOrder(trade_data, strategy_object, "CLOSE POSITION")

        # Verify the OCOorder method was called with the correct arguments
        mock_OCOorder.assert_called_once_with(trade_data, strategy_object, "CLOSE POSITION", user, account_id)

        # Construct the expected order details after updates
        updated_obj = {
            'key': 'value',
            'Order_ID': account_id,
            'Account_Position': 'Live',
            'Order_Status': 'QUEUED'
        }

        # Verify that queueOrder was called with the updated order details
        mock_queueOrder.assert_called_once_with(updated_obj)

        # Verify that placeTDAOrderAsync was called with the correct order object
        api_trader.tdameritrade.placeTDAOrderAsync.assert_called_once_with("mock_order")
        

    async def test_queueOrder(self):
        # Prepare the input order
        order = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Quantity": 10,
            "Account_ID": "12345"
        }

        # Call the queueOrder method
        await self.api_trader.queueOrder(order)

        # Verify that the queue.update_one was called with the correct arguments
        self.api_trader.async_mongo.queue.update_one.assert_called_once_with(
            {"Trader": "TestUser", "Symbol": "AAPL", "Strategy": "TestStrategy", "Account_ID": "12345"},
            {"$set": order},
            upsert=True
        )

    @patch('api_trader.ApiTrader.pushOrder')  # Mock pushOrder
    async def test_update_status_filled_order(self, mock_pushOrder):
        """Test updateStatus method for a FILLED order."""

        # Setup dependencies
        user = MagicMock()
        async_mongo = MagicMock()
        push = MagicMock()
        logger = MagicMock()
        account_id = "test_account"
        tdameritrade = MagicMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        # Create ApiTrader instance with mock dependencies
        api_trader = ApiTrader(
            user=user,
            async_mongo=async_mongo,
            push=push,
            logger=logger,
            account_id=account_id,
            tdameritrade=tdameritrade,
            quote_manager_pool=quote_manager_pool
        )

        # Mock methods and attributes
        api_trader.tdameritrade.getSpecificOrderAsync = AsyncMock(
            side_effect=[{"status": "FILLED", "Order_ID": "12345"}]
        )

        # Create a mock for the queue cursor (async iterable)
        mock_queue_cursor = AsyncMock()

        # Mock async iteration (__aiter__) to simulate async cursor behavior
        mock_queue_cursor.__aiter__.return_value = iter([
            {
                "Symbol": "AAPL",
                "Order_ID": "12345",
                "Order_Type": "STANDARD",
                "Trader": "test_trader",
                "Account_ID": "test_account",
                "Direction": "OPEN POSITION",  # Ensure direction is correct
                "Qty": 100,
                "Entry_Price": 150,
                "Strategy": "test_strategy",
                "Asset_Type": "EQUITY",
                "Side": "BUY"
            }
        ])

        # Mock the to_list method correctly as an async method
        mock_queue_cursor.to_list = AsyncMock(return_value=[
            {
                "Symbol": "AAPL",
                "Order_ID": "12345",
                "Order_Type": "STANDARD",
                "Trader": "test_trader",
                "Account_ID": "test_account",
                "Direction": "OPEN POSITION",
                "Qty": 100,
                "Entry_Price": 150,
                "Strategy": "test_strategy",
                "Asset_Type": "EQUITY",
                "Side": "BUY"
            }
        ])

        api_trader.async_mongo.queue.find.return_value = mock_queue_cursor

        # Call updateStatus
        await api_trader.updateStatus()

        # Debugging: Check if pushOrder was called
        print(f"pushOrder called {mock_pushOrder.call_count} times.")

        # Assert pushOrder was called once with the queued order and the specific order
        mock_pushOrder.assert_called_once_with(
            {
                "Symbol": "AAPL",
                "Order_ID": "12345",
                "Order_Type": "STANDARD",
                "Trader": "test_trader",
                "Account_ID": "test_account",
                "Direction": "OPEN POSITION",
                "Qty": 100,
                "Entry_Price": 150,
                "Strategy": "test_strategy",
                "Asset_Type": "EQUITY",
                "Side": "BUY"
            },
            {"status": "FILLED", "Order_ID": "12345"}
        )

        # Verify no warnings were logged
        api_trader.logger.warning.assert_not_called()



    @patch('api_trader.ApiTrader.pushOrder')  # Mock pushOrder
    async def test_update_status_order_not_found(self, mock_pushOrder):
        """Test updateStatus method when the order is not found in paper trading mode."""

        # Setup dependencies
        user = MagicMock()
        mongo = MagicMock()
        async_mongo = AsyncMock()
        push = MagicMock()
        logger = MagicMock()
        account_id = "test_account"
        tdameritrade = MagicMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        # Create ApiTrader instance with mock dependencies
        api_trader = ApiTrader(
            user=user,
            async_mongo=async_mongo,
            push=push,
            logger=logger,
            account_id=account_id,
            tdameritrade=tdameritrade,
            quote_manager_pool=quote_manager_pool
        )

        # Set RUN_LIVE_TRADER to False (paper trading mode)
        api_trader.RUN_LIVE_TRADER = False

        # Mock methods and attributes
        api_trader.tdameritrade.getSpecificOrderAsync = AsyncMock(
            side_effect=[{"message": "Order not found"}]
        )

        mock_queue_cursor = AsyncMock()
        mock_queue_cursor.to_list = AsyncMock(return_value=[
            {
                "Symbol": "AAPL",
                "Order_ID": "12345",
                "Order_Type": "STANDARD",
                "Trader": "test_trader",
                "Account_ID": "test_account",
                "Direction": "OPEN POSITION",
                "Qty": 100,
                "Entry_Price": 150,
                "Strategy": "test_strategy",
                "Asset_Type": "EQUITY",
                "Side": "BUY"
            }
        ])
        api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queue_cursor)

        # Call updateStatus
        await api_trader.updateStatus()

        # Assert pushOrder was called with "Reliable" data integrity
        mock_pushOrder.assert_called_once_with(
            {
                "Symbol": "AAPL",
                "Order_ID": "12345",
                "Order_Type": "STANDARD",
                "Trader": "test_trader",
                "Account_ID": "test_account",
                "Direction": "OPEN POSITION",
                "Qty": 100,
                "Entry_Price": 150,
                "Strategy": "test_strategy",
                "Asset_Type": "EQUITY",
                "Side": "BUY"
            },
            {"price": 150, "shares": 100},
            "Reliable"  # Correctly expecting "Reliable" here for paper trading mode
        )

        # Verify logger warning was called instead, since the order wasn't found
        expected_log_message_warning = "Order ID not found. Moving AAPL to positions."
        api_trader.logger.warning.assert_any_call(expected_log_message_warning)

    @patch.object(ApiTrader, 'pushOrder', return_value=None)
    async def test_update_status_canceled_rejected(self, mock_pushOrder):
        # Correctly structured user object
        user = {
            "Name": "TestUser",
            "Accounts": {
                "12345": {
                    "Account_Position": "Live"
                }
            }
        }
        
        mongo = MagicMock()
        async_mongo = AsyncMock()
        push = MagicMock()
        logger = MagicMock()
        account_id = "12345"
        tdameritrade = MagicMock()
        quote_manager_pool = MagicMock()

        # Mock quote_manager_pool behavior
        quote_manager_pool.get_or_create_manager.return_value = MagicMock()

        # Instantiate ApiTrader with corrected user object
        api_trader = ApiTrader(
            user=user,
            async_mongo=async_mongo,
            push=push,
            logger=logger,
            account_id=account_id,
            tdameritrade=tdameritrade,
            quote_manager_pool=quote_manager_pool
        )

        # Mock the queued orders in the `queue` collection
        mock_queue_cursor = AsyncMock()
        mock_queue_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": "111111",
                "Order_ID": "12345",
                "Symbol": "SYM0",
                "Order_Type": "OCO",
                "Qty": 10,
                "Strategy": "STRATEGY_0",
                "Entry_Price": 100.0,
                "Trader": "TestUser",
                "Account_ID": "12345",
            }
        ])
        api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queue_cursor)

        # Mock collections for canceled and rejected orders
        api_trader.async_mongo.queue.delete_one = AsyncMock()
        api_trader.async_mongo.canceled.insert_one = AsyncMock()
        api_trader.async_mongo.rejected.insert_one = AsyncMock()

        # Mock the response for "CANCELED" status
        api_trader.tdameritrade.getSpecificOrderAsync = AsyncMock(
            return_value={"Order_ID": "12345", "status": "CANCELED"}
        )

        # Call updateStatus for "CANCELED"
        await api_trader.updateStatus()

        # Verify queue removal
        api_trader.async_mongo.queue.delete_one.assert_called_once_with({"_id": "111111"})

        # Verify that "CANCELED" order was logged and inserted into the canceled collection
        expected_canceled_order = {
            'Symbol': 'SYM0',
            'Order_Type': 'OCO',
            'Order_Status': 'CANCELED',
            'Strategy': 'STRATEGY_0',
            'Trader': 'TestUser',
            'Date': mock.ANY,  # Mock datetime
            'Account_ID': '12345'
        }
        api_trader.async_mongo.canceled.insert_one.assert_called_once_with(expected_canceled_order)

        # Mock the response for "REJECTED" status
        api_trader.tdameritrade.getSpecificOrderAsync.return_value = {
            "Order_ID": "12345",
            "status": "REJECTED"
        }

        # Reset mocks for the second test case
        api_trader.async_mongo.queue.delete_one.reset_mock()
        api_trader.async_mongo.canceled.insert_one.reset_mock()
        api_trader.async_mongo.rejected.insert_one.reset_mock()

        # Call updateStatus for "REJECTED"
        await api_trader.updateStatus()

        # Verify queue removal for "REJECTED"
        api_trader.async_mongo.queue.delete_one.assert_called_once_with({"_id": "111111"})

        # Verify that "REJECTED" order was logged and inserted into the rejected collection
        expected_rejected_order = {
            'Symbol': 'SYM0',
            'Order_Type': 'OCO',
            'Order_Status': 'REJECTED',
            'Strategy': 'STRATEGY_0',
            'Trader': 'TestUser',
            'Date': mock.ANY,  # Mock datetime
            'Account_ID': '12345'
        }
        api_trader.async_mongo.rejected.insert_one.assert_called_once_with(expected_rejected_order)

        # Verify total calls to insert_one
        self.assertEqual(api_trader.async_mongo.rejected.insert_one.call_count, 1)

        # Final assertions
        api_trader.logger.info.assert_any_call(
            f"CANCELED order for SYM0 ({modifiedAccountID(expected_canceled_order['Account_ID'])})"
        )
        api_trader.logger.info.assert_any_call(
            f"REJECTED order for SYM0 ({modifiedAccountID(expected_rejected_order['Account_ID'])})"
        )

    @patch.object(ApiTrader, 'pushOrder', return_value=None)
    async def test_update_status_else_branch(self, mock_pushOrder):
        # Create an instance of ApiTrader
        api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool,
        )

        # Mock the queued order
        mock_queue_cursor = AsyncMock()
        mock_queue_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": "111111",
                "Order_ID": "12345",
                "Symbol": "SYM0",
                "Order_Type": "OCO",
                "Qty": 10,
                "Strategy": "STRATEGY_0",
                "Entry_Price": 100.0,
                "Account_ID": "12345",
            }
        ])
        api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queue_cursor)

        # Mock the specific order response with a non-matching status
        api_trader.tdameritrade.getSpecificOrderAsync = AsyncMock(
            return_value={"Order_ID": "12345", "status": "PENDING"}  # Non-matching status
        )

        # Call updateStatus to trigger the else branch
        await api_trader.updateStatus()

        # Verify that the order was not removed from the queue
        api_trader.async_mongo.queue.delete_one.assert_not_called()

        # Verify that neither the canceled nor the rejected collections were updated
        api_trader.async_mongo.canceled.insert_one.assert_not_called()
        api_trader.async_mongo.rejected.insert_one.assert_not_called()

        # Verify that update_one was called with the correct arguments
        expected_filter = {'_id': '111111'}
        expected_update = {"$set": {"Order_Status": "PENDING"}}

        api_trader.async_mongo.queue.update_one.assert_called_once_with(expected_filter, expected_update)

    async def test_pushOrder_open_position(self):
        # Call the pushOrder method
        await self.api_trader.pushOrder(self.queue_order, self.spec_order)

        # Extract the arguments used in the call to insert_one
        called_args = self.api_trader.async_mongo.open_positions.insert_one.call_args[0][0]

        # Create the expected dictionary, but without the Entry_Date field
        expected_args = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Position_Size": 10,
            "Position_Type": "LONG",
            "Data_Integrity": "Reliable",
            "Trader": "TestUser",
            "Account_ID": self.account_id,
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
        self.api_trader.async_mongo.queue.delete_one.assert_called_once_with({'_id': '111111'})
        # self.push.send.assert_called_once_with(
        #     ">>>> \n Side: BUY \n Symbol: AAPL \n Qty: 10 \n Price: $150.0 \n Strategy: TestStrategy \n Trader: TestUser"
        # )

    async def test_pushOrder_close_position(self):
        # Prepare the mock data
        self.queue_order = {
            "_id": "111111",
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Direction": "CLOSE POSITION",
            "Account_ID": self.account_id,
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
        
        self.api_trader.async_mongo.open_positions.find_one.return_value = {
            "Qty": 10,
            "Entry_Price": 150.0,
            "Entry_Date": "2024-01-01"
        }
        
        # Mock the `count_documents` method to return 0
        self.api_trader.async_mongo.closed_positions.count_documents.return_value = 0

        # Call the pushOrder method
        await self.api_trader.pushOrder(self.queue_order, self.spec_order)

        # Extract the arguments used in the call to insert_one
        called_args = self.api_trader.async_mongo.closed_positions.insert_one.call_args[0][0]

        # Create the expected dictionary for closed positions, without the Exit_Date
        expected_args = {
            "Symbol": "AAPL",
            "Strategy": "TestStrategy",
            "Position_Size": 10,
            "Position_Type": "LONG",
            "Data_Integrity": "Reliable",
            "Trader": "TestUser",
            "Account_ID": self.account_id,
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
        self.api_trader.async_mongo.open_positions.delete_one.assert_called_once_with(
            {
                "Trader": "TestUser",
                "Account_ID": "12345",
                "Symbol": "AAPL",
                "Strategy": "TestStrategy",
            }
        )

        # Verify the queue deletion
        self.api_trader.async_mongo.queue.delete_one.assert_called_once_with({'_id': '111111'})

    async def test_pushOrder_mongo_exception(self):
        """Test that pushOrder handles MongoDB exceptions."""
        # Setup mocks to raise exceptions
        self.api_trader.async_mongo.open_positions.insert_one.side_effect = WriteConcernError("WriteConcernError")
        self.api_trader.async_mongo.queue.delete_one.side_effect = WriteError("WriteError")

        # Ensure the logger is properly initialized and mocked
        with patch.object(self.api_trader, 'logger') as mock_logger:
            # Call the pushOrder method
            self.queue_order["Direction"] = "OPEN POSITION"
            with self.assertRaises(WriteError):
                await self.api_trader.pushOrder(self.queue_order, self.spec_order)

            # Extract logged messages from mock_logger
            log_messages = [call.args[0] for call in mock_logger.error.call_args_list]

            # Define expected substrings
            expected_substrings = [
                "Traceback (most recent call last):",
                "Insert failed for AAPL: WriteConcernError",
                "Retry 1 failed for AAPL: WriteConcernError",
                "Retry 2 failed for AAPL: WriteConcernError",
                "Retry 3 failed for AAPL: WriteConcernError",  # Retry logic should log 3 attempts
            ]

            # Check if expected substrings are in the log messages
            for expected_substring in expected_substrings:
                self.assertTrue(any(expected_substring in message for message in log_messages),
                                f"Expected log message containing '{expected_substring}' not found.")

        # Check that the delete_one method was called even after the insert_one failed
        self.api_trader.async_mongo.queue.delete_one.assert_called_once_with({'_id': '111111'})

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock the constructor to avoid actual init
    @patch('api_trader.ApiTrader.sendOrder')
    async def test_run_trader(self, mock_sendOrder, mock_init):
        # Mock relevant methods/attributes used in run_trader
        self.user_mock = {"Name": "TestUser"}  # Ensure self.user["Name"] is accessible
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "test_account"
        self.api_trader.updateStatus = AsyncMock()
        
        self.api_trader.async_mongo.users.find_one = AsyncMock(return_value = self.user_mock)

        # Mock open_positions.find_one to return None (no open positions)
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.to_list = AsyncMock(return_value=[])  # No forbidden symbols
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock queue.find to return None (no queued orders)
        mock_queue_cursor = MagicMock()
        mock_queue_cursor.to_list = AsyncMock(return_value=[])  # No forbidden symbols
        self.api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queue_cursor)

        # Mock strategies.find_one to return a strategy object
        mock_strategies_cursor = MagicMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=[{"Strategy": "test_strategy", "Account_ID": "test_account", "Position_Type": "LONG", "Order_Type": "STANDARD"}])
        self.api_trader.async_mongo.strategies.find.return_value = mock_strategies_cursor

        # Mock forbidden symbols to be empty
        mock_forbidden_cursor = MagicMock()
        mock_forbidden_cursor.to_list = AsyncMock(return_value=[])  # No forbidden symbols
        self.api_trader.async_mongo.forbidden.find = MagicMock(return_value=mock_forbidden_cursor)

        # Create trade data to simulate an open position condition
        trade_data = [{"Symbol": "AAPL", "Strategy": "test_strategy", "Side": "BUY", "Asset_Type": "EQUITY"}]

        # Call run_trader method
        await self.api_trader.runTrader(trade_data=trade_data)

        # Add assertions here
        self.api_trader.updateStatus.assert_called_once()  # Ensure status is updated
        mock_sendOrder.assert_called_once_with(
            {"Symbol": "AAPL", "Strategy": "test_strategy", "Side": "BUY", "Asset_Type": "EQUITY", "Position_Type": "LONG"},
            {"Strategy": "test_strategy", "Account_ID": "test_account", "Position_Type": "LONG", "Order_Type": "STANDARD"},
            "OPEN POSITION"
        )

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    @patch('api_trader.ApiTrader.sendOrder')
    async def test_runTrader_with_dynamic_round_trip_orders(self, mock_sendOrder, mock_init):
        """Test runTrader method when orders are dynamically generated."""
        
        # Mock relevant methods/attributes used in run_trader
        self.api_trader.user = MagicMock()
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "test_account"  # Set this to a specific account ID for your test
        self.api_trader.updateStatus = AsyncMock()

        # Generate dynamic test data for round-trip orders
        open_positions, strategies, quotes = generate_test_data_for_run_trader(num_positions=10)

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

        self.api_trader.async_mongo.users.find_one = AsyncMock(return_value = self.user_mock)

        # Mock forbidden symbols to be empty
        mock_forbidden_cursor = MagicMock()
        mock_forbidden_cursor.to_list = AsyncMock(return_value=[])
        self.api_trader.async_mongo.forbidden.find.return_value = mock_forbidden_cursor

        # Mock strategies to just return a single
        mock_strategies_cursor = MagicMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=strategies)
        self.api_trader.async_mongo.strategies.find.return_value = mock_strategies_cursor

        # Mock the async iterable for open_positions and queue collections
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.to_list = AsyncMock(return_value=
            [position for position in open_positions if position["Asset_Type"] == "OPTION"]
        )
        self.api_trader.async_mongo.open_positions.find.return_value = mock_open_positions_cursor

        mock_queued_positions_cursor = MagicMock()
        mock_queued_positions_cursor.to_list = AsyncMock(return_value=
            [order for order in open_positions if order["Asset_Type"] == "OPTION"]
        )
        mock_queued_positions_cursor.to_list = AsyncMock(return_value=[])
        self.api_trader.async_mongo.queue.find.return_value = mock_queued_positions_cursor

        # Mock the getQuotes method to return simulated quotes data
        self.api_trader.tdameritrade.getQuotesUnified.return_value = quotes

        # Call runTrader with the mock data
        trade_data = [{"Symbol": position["Symbol"], "Strategy": position["Strategy"], "Side": position["Side"], 'Asset_Type': position["Asset_Type"]} for position in open_positions]
        await self.api_trader.runTrader(trade_data=trade_data)

        # Add assertions here
        self.api_trader.async_mongo.open_positions.find.assert_called()  # Ensure mongo query is performed
        self.api_trader.async_mongo.queue.find.assert_called()  # Ensure mongo query is performed
        self.api_trader.async_mongo.strategies.find.assert_called()  # Ensure mongo query is performed
        self.api_trader.updateStatus.assert_called()  # Ensure status is updated
        mock_sendOrder.assert_called()


    async def test_initialization_error_handling(self):
        # Create a mock mongo object
        mock_async_mongo = AsyncMock()

        # Configure the quote_manager_pool mock to raise an exception for get_or_create_manager
        self.quote_manager_pool.get_or_create_manager.side_effect = Exception("Forced Error")

        # Instantiate ApiTrader
        ApiTrader(
            user=self.user,
            async_mongo=mock_async_mongo,
            push=self.push,
            logger=self.logger,
            account_id=self.account_id,
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        # Verify that logger.error was called with the expected message
        self.logger.error.assert_called_once_with(
            "Error initializing ApiTrader: Forced Error"
        )


    async def test_checkOCOpapertriggers_read_timeout(self):
        """Test that a ReadTimeout exception in add_quotes is handled and logged properly."""
        
        # Mock getMarketHoursUnified to return normal data
        self.api_trader.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={'isOpen': True})

        # Mock the quote manager and make add_quotes raise a ReadTimeout exception
        self.api_trader.quote_manager = AsyncMock()
        self.api_trader.quote_manager.stop_event = MagicMock()
        self.api_trader.quote_manager.add_quotes = AsyncMock(side_effect=httpx.ReadTimeout("Read operation timed out."))

        num_positions = 1
        # # Mock open_positions.find to behave like an AsyncIOMotorCursor
        # mock_open_positions = AsyncMock()
        # mock_cursor = AsyncMock()
        # mock_cursor.to_list = AsyncMock(return_value=create_mock_open_positions(num_positions))  # Mock `to_list` to return data
        # mock_open_positions.find.return_value = mock_cursor
        # self.api_trader.async_mongo.open_positions = mock_open_positions

        # Mock open_positions.find to mimic AsyncIOMotorCursor
        mock_open_positions_cursor = AsyncMock()
        mock_open_positions_cursor.to_list = AsyncMock(return_value=create_mock_open_positions(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock strategies.find similarly
        mock_strategies_cursor = AsyncMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=create_mock_strategies(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.strategies.find = MagicMock(return_value=mock_strategies_cursor)

        # Mock file existence check for stop_signal_file
        with patch('os.path.exists', return_value=False), \
            patch.object(self.api_trader.logger, 'error') as mock_logger_error:
            
            # Call the method
            await self.api_trader.checkOCOpapertriggers()

            # Verify that the logger captured the exception message from add_quotes
            mock_logger_error.assert_called_once()
            self.assertIn("Read operation timed out.", mock_logger_error.call_args[0][0])


    async def test_checkOCOpapertriggers_connect_timeout(self):
        """Test that an exception in add_quotes is handled and logged properly."""
        
        # Mock getMarketHours to return normal data to avoid exceptions there
        self.api_trader.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={'isOpen': True})

        # Mock the quote manager and make add_quotes raise an exception
        self.api_trader.quote_manager = AsyncMock()
        self.api_trader.quote_manager.stop_event = MagicMock()
        self.api_trader.quote_manager.add_quotes = AsyncMock(side_effect = httpx.ConnectTimeout("Connection timed out."))

        num_positions = 1
        # Mock open_positions.find to mimic AsyncIOMotorCursor
        mock_open_positions_cursor = AsyncMock()
        mock_open_positions_cursor.to_list = AsyncMock(return_value=create_mock_open_positions(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock strategies
        mock_strategies_cursor = AsyncMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=create_mock_strategies(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.strategies.find = MagicMock(return_value=mock_strategies_cursor)
        
        # Patch the logger to capture error output
        with patch.object(self.api_trader.logger, 'error') as mock_logger_error:
            # Call the method
            await self.api_trader.checkOCOpapertriggers()

            # Verify that the logger captured the exception message from add_quotes
            mock_logger_error.assert_called_once()
            self.assertIn("Connection timed out.", mock_logger_error.call_args[0][0])


    async def test_checkOCOpapertriggers_general_exception_in_add_quotes(self):
        """Test that an exception in add_quotes is handled and logged properly."""
        
        # Mock getMarketHours to return normal data to avoid exceptions there
        self.api_trader.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={'isOpen': True})

        # Mock the quote manager and make add_quotes raise an exception
        self.api_trader.quote_manager = AsyncMock()
        self.api_trader.quote_manager.stop_event = MagicMock()
        self.api_trader.quote_manager.add_quotes.side_effect = Exception("An unexpected error in add_quotes")

        num_positions = 1

        # Mock open_positions.find to mimic AsyncIOMotorCursor
        mock_open_positions_cursor = AsyncMock()
        mock_open_positions_cursor.to_list = AsyncMock(return_value=create_mock_open_positions(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock strategies to return test data
        mock_strategies_cursor = AsyncMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=create_mock_strategies(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.strategies.find = MagicMock(return_value=mock_strategies_cursor)

        # Patch the logger to capture error output
        with patch.object(self.api_trader.logger, 'error') as mock_logger_error:
            # Call the method
            await self.api_trader.checkOCOpapertriggers()

            # Verify that the logger captured the exception message from add_quotes
            mock_logger_error.assert_called_once()
            self.assertIn("An unexpected error in add_quotes", mock_logger_error.call_args[0][0])

    @patch('api_trader.strategies.fixed_percentage_exit.FixedPercentageExitStrategy')  # Mocking ExitStrategy
    async def test_checkOCOpapertriggers_with_large_data(self, mock_exit_strategy):
        # Initialize ApiTrader with proper dependencies
        self.user = {
            "Name": "TestUser",
            "Accounts": {
                "test_account": {
                    "Account_Position": "Live"
                }
            }
        }

        api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id="test_account",
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        num_positions = 5000

        # Mock instance attributes
        api_trader.async_mongo.open_positions = AsyncMock()
        api_trader.strategies = MagicMock()
        api_trader.quote_manager = AsyncMock()
        api_trader.quote_manager.add_quotes = AsyncMock()
        api_trader.quote_manager.add_callback = AsyncMock()
        api_trader.lock = asyncio.Lock()
        api_trader.positions_by_symbol = {}
        api_trader.strategy_dict = {}
        api_trader.RUN_LIVE_TRADER = True
        api_trader.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={"isOpen": True})
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=create_mock_quotes(num_positions))
        api_trader.tdameritrade.placeTDAOrderAsync = AsyncMock(return_value={"Order_ID": 12345})

        # Properly mock the stop_event
        mock_stop_event = MagicMock()
        mock_stop_event.is_set = MagicMock(return_value=False)  # is_set should not be awaitable
        mock_stop_event.set = MagicMock()
        mock_stop_event.clear = MagicMock()
        mock_stop_event.wait = AsyncMock()
        
        api_trader.quote_manager.stop_event = mock_stop_event

        # Mock open_positions and strategies
        mock_strategies_cursor = AsyncMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=create_mock_strategies(num_positions))  # Mock `to_list`
        self.api_trader.async_mongo.strategies.find = MagicMock(return_value=mock_strategies_cursor)
        
        # Mock open_positions.find to mimic AsyncIOMotorCursor
        mock_open_positions_cursor = AsyncMock()
        mock_open_positions = create_mock_open_positions(num_positions)
        mock_open_positions_cursor.to_list = AsyncMock(return_value=mock_open_positions)  # Mock `to_list`
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock the return value of FixedPercentageExitStrategy's should_exit
        mock_exit_response = {
            "exit": True,
            "take_profit_price": 160.00,
            "stop_loss_price": 140.00,
            "additional_params": {"ATR": 2.5, "max_price": 180.00},
            "reason": "OCO"
        }
        mock_exit_strategy.return_value.should_exit.return_value = mock_exit_response

        # Run the method to test
        await api_trader.checkOCOpapertriggers()

        # Trigger evaluate_paper_triggers manually to simulate callback behavior
        for position in mock_open_positions:
            await api_trader.evaluate_paper_triggers(position["Symbol"], {"last_price": 170})

        # Assertions
        self.assertEqual(api_trader.async_mongo.open_positions.find.call_count, 1)
        self.assertEqual(api_trader.async_mongo.strategies.find.call_count, 1)
        api_trader.quote_manager.add_quotes.assert_called_once_with(
            [{'symbol': position['Symbol'], 'asset_type': position['Asset_Type']} for position in mock_open_positions]
        )
        self.assertEqual(mock_exit_strategy.return_value.should_exit.call_count, num_positions)
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()


    @patch('api_trader.strategies.fixed_percentage_exit.FixedPercentageExitStrategy')
    async def test_checkOCOpapertriggers_with_streaming_quotes(self, mock_exit_strategy):
        api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id="test_account",
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        # Set up ApiTrader attributes and mocks
        api_trader.queue = MagicMock()
        api_trader.rejected = MagicMock()
        api_trader.stop_signal_file = "mock_stop_signal_file"
        api_trader.RUN_LIVE_TRADER = True
        api_trader.open_positions = MagicMock()
        api_trader.strategies = MagicMock()
        api_trader.lock = asyncio.Lock()
        api_trader.positions_by_symbol = {}
        api_trader.strategy_dict = {}
        
        # Mock getMarketHours to return open market hours
        api_trader.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={"isOpen": True})
        
        # Mock open_positions.find to mimic AsyncIOMotorCursor
        mock_open_positions_cursor = AsyncMock()
        mock_open_positions = [{"Symbol": "AAPL", "Asset_Type": "EQUITY", "Trader": self.api_trader.user, "Account_ID": self.api_trader.account_id}]
        mock_open_positions_cursor.to_list = AsyncMock(return_value=mock_open_positions)  # Mock `to_list`
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)
        
        # Mock strategies with a list of mock strategies
        mock_strategies_cursor = AsyncMock()
        mock_strategies_cursor.to_list = AsyncMock(return_value=[{"Strategy": "TestStrategy", "Account_ID": self.api_trader.account_id}])  # Mock `to_list`
        self.api_trader.async_mongo.strategies.find = MagicMock(return_value=mock_strategies_cursor)
        
        # Mock add_quotes as async
        api_trader.quote_manager = AsyncMock()
        api_trader.quote_manager.add_quotes = AsyncMock()
        api_trader.quote_manager.add_callback = AsyncMock()
        
        # Properly mock the stop_event
        mock_stop_event = MagicMock()
        mock_stop_event.is_set = MagicMock(return_value=False)  # is_set should not be awaitable
        mock_stop_event.set = MagicMock()
        mock_stop_event.clear = MagicMock()
        mock_stop_event.wait = AsyncMock()
        
        api_trader.quote_manager.stop_event = mock_stop_event
        
        await api_trader.checkOCOpapertriggers()

        # Assertions to validate that methods were called as expected
        api_trader.quote_manager.add_callback.assert_awaited_once_with(api_trader.evaluate_paper_triggers)
        api_trader.async_mongo.open_positions.find.assert_called()
        api_trader.async_mongo.strategies.find.assert_called()
        api_trader.quote_manager.add_quotes.assert_awaited_once_with([{"symbol": "AAPL", "asset_type": "EQUITY"}])

    @patch.object(ApiTrader, 'pushOrder', return_value=None)  # Mock pushOrder in ApiTrader
    async def test_checkOCOtriggers(self, mock_pushOrder):
        
        api_trader = ApiTrader(
            user=self.user,
            async_mongo=self.async_mongo,
            push=self.push,
            logger=self.logger,
            account_id="test_account",
            tdameritrade=self.tdameritrade,
            quote_manager_pool=self.quote_manager_pool
        )

        # Mock dependencies
        api_trader.queue = AsyncMock()
        api_trader.async_mongo.open_positions = AsyncMock()
        api_trader.async_mongo.open_positions.bulk_write = AsyncMock()
        api_trader.async_mongo.canceled = AsyncMock()
        api_trader.async_mongo.rejected = AsyncMock()

        mock_open_positions = [
            {
                "Symbol": "SYM1",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_A",
                "childOrderStrategies": [
                    {
                        "childOrderStrategies": [
                            {"Order_ID": 12345}
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
                            {"Order_ID": 67890}
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
                            {"Order_ID": 13579}
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
                            {"Order_ID": 24680}
                        ]
                    }
                ]
            }
        ]

        # Mock open_positions.find to mimic AsyncIOMotorCursor
        # mock_open_positions_cursor = AsyncMock()
        # # mock_open_positions = [{"Symbol": "AAPL", "Asset_Type": "EQUITY", "Trader": self.api_trader.user, "Account_ID": self.api_trader.account_id}]
        # mock_open_positions_cursor.to_list = AsyncMock(return_value=mock_open_positions)  # Mock `to_list`
        # api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)

        # Mock cursor to simulate async iteration
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = iter(mock_open_positions)  # Mock async iteration
        api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_cursor)

        # Mock getSpecificOrder for different orders
        api_trader.tdameritrade.getSpecificOrderAsync = AsyncMock(
            side_effect = [
                {"status": "FILLED", "Order_ID": 12345},
                {"status": "CANCELED", "Order_ID": 67890},
                {"status": "REJECTED", "Order_ID": 13579},
                {"status": "WORKING", "Order_ID": 24680},
            ])

        # Call the method under test
        await api_trader.checkOCOtriggers()

        # Check that pushOrder was called for the filled order
        mock_pushOrder.assert_called_once_with(
            {
                "Symbol": "SYM1",
                "Order_Type": "OCO",
                "Strategy": "STRATEGY_A",
                "childOrderStrategies": [{"childOrderStrategies": [{"Order_ID": 12345}]}],
                "Direction": "CLOSE POSITION",
                "Side": "SELL"
            },
            {"status": "FILLED", "Order_ID": 12345}
        )

        # Check logger info for CANCELED order
        api_trader.logger.info.assert_any_call(
            f"CANCELED ORDER for SYM2 - TRADER: {api_trader.user["Name"]} - ACCOUNT ID: {modifiedAccountID(api_trader.account_id)}"
        )

        # Verify that MongoDB updates were correctly prepared
        api_trader.async_mongo.open_positions.bulk_write.assert_called_once_with([
            UpdateOne(
                {"Trader": api_trader.user["Name"], "Account_ID": api_trader.account_id, "Symbol": "SYM4", "Strategy": "STRATEGY_D"},
                {'$set': {'childOrderStrategies.$[orderElem].Order_Status': 'WORKING'}},
                False, None,
                [{'orderElem.Order_ID': 24680}],  # The array filter for orderElem.Order_ID
                None
            )
        ])

        # Check that the appropriate insertions were made for CANCELED orders
        self.assertEqual(api_trader.async_mongo.canceled.insert_many.call_count, 1)
        self.assertEqual(api_trader.async_mongo.rejected.insert_many.call_count, 1)

        # Verify that the canceled orders were inserted correctly
        api_trader.async_mongo.canceled.insert_many.assert_called_with([
            {
                'Symbol': 'SYM2',
                'Order_Type': 'OCO',
                'Order_Status': 'CANCELED',
                'Strategy': 'STRATEGY_B',
                'Trader': api_trader.user["Name"],  # Replace with your actual trader name
                'Date': ANY,  # Use ANY to match any datetime value
                'Account_ID': api_trader.account_id
            }
        ])

        # Verify that the rejected orders were inserted correctly
        api_trader.async_mongo.rejected.insert_many.assert_called_with([
            {
                'Symbol': 'SYM3',
                'Order_Type': 'OCO',
                'Order_Status': 'REJECTED',
                'Strategy': 'STRATEGY_C',
                'Trader': api_trader.user["Name"],  # Replace with your actual trader name
                'Date': ANY,  # Use ANY to match any datetime value
                'Account_ID': api_trader.account_id
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
                            "Order_ID": 86753098675310,
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
                    "Exit_Price": 100.0,
                    "Exit_Type": "STOP LOSS",
                    "Order_Status": "WORKING",
                    "Order_ID": 86753098675309
                },
                {
                    "Side": "SELL",
                    "Exit_Price": 150.0,
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "PENDING",
                    "Order_ID": 86753098675310
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
                    "Exit_Price": 200.0,
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "FILLED",
                    "Order_ID": 86753098675309
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
                    "Order_ID": 86753098675309
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
                    "Order_ID": None
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
                    "Order_ID": None
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
                    "Exit_Price": 120.0,  # Updated to match BSON format
                    "Exit_Type": "STOP LOSS",
                    "Order_Status": "WORKING",
                    "Order_ID": 54321
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
                    "Exit_Price": 100.0,
                    "Exit_Type": "TAKE PROFIT",
                    "Order_Status": "FILLED",
                    "Order_ID": 12345
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order_valid_nested_childOrderStrategies)
        self.assertEqual(result, expected_result)

    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_numeric_order_ID(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Mocking a valid numeric order ID
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            "Order_ID": "1001870497109",  # Valid numeric string
                            "orderLegCollection": [{"instruction": "BUY"}],
                            "price": 200.0,
                            "status": "FILLED"
                        }
                    ]
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that Order_ID is properly converted to an integer
        self.assertEqual(result["childOrderStrategies"][0]["Order_ID"], 1001870497109)
        self.api_trader.logger.error.assert_not_called()


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_non_numeric_order_ID(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Mocking an invalid non-numeric order ID
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            "Order_ID": "INVALID_ID",  # Non-numeric string
                            "orderLegCollection": [{"instruction": "SELL"}],
                            "price": 150.0,
                            "status": "PENDING"
                        }
                    ]
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that Order_ID is None because it's not numeric
        self.assertIsNone(result["childOrderStrategies"][0]["Order_ID"])

        # Check that an error was logged for the invalid Order_ID
        self.api_trader.logger.error.assert_called_once_with(f"Invalid or non-numeric Order_ID detected: {spec_order['childOrderStrategies'][0]['childOrderStrategies'][0]}")


    @patch('api_trader.ApiTrader.__init__', return_value=None)
    def test_extractOCOchildren_missing_order_ID(self, mock_init):
        # Initialize the ApiTrader instance
        self.api_trader = ApiTrader()
        # Mock dependencies
        self.api_trader.logger = MagicMock()
        self.api_trader.account_id = "123456"  # Set this to a specific account ID for your test
        self.api_trader.user = {'Name': 'TraderName'}  # Mocking user name

        # Mocking a missing Order_ID
        spec_order = {
            "childOrderStrategies": [
                {
                    "childOrderStrategies": [
                        {
                            # No Order_ID present
                            "orderLegCollection": [{"instruction": "SELL"}],
                            "price": 150.0,
                            "status": "PENDING"
                        }
                    ]
                }
            ]
        }

        result = self.api_trader.extractOCOchildren(spec_order)

        # Assert that Order_ID is None because it's missing
        self.assertIsNone(result["childOrderStrategies"][0]["Order_ID"])

        # Check that an error was logged for the missing Order_ID
        self.api_trader.logger.error.assert_called_once_with(f"Missing Order_ID detected: {spec_order['childOrderStrategies'][0]['childOrderStrategies'][0]}")


    @patch('api_trader.ApiTrader.sendOrder', new_callable=AsyncMock)  # Mock the order sending as async
    async def test_multiple_strategies_with_price_movement(self, mock_send_order):
        # Step 1: Initialize ApiTrader and strategies

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
                    await mock_send_order(strategy, "SELL", position["Qty"], price)
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
                "bidPrice": 100.00 - i,  # Mock value for bidPrice
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
        bid_price = round(random.uniform(high_price, high_price + 5), 2)  # Random bid price

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
                "highPrice": high_price,
                "bidPrice": bid_price,
            }
        }

    return open_positions, strategies, quotes


if __name__ == '__main__':
    unittest.main()
