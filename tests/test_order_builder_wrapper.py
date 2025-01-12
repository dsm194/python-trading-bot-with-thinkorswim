import asyncio
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch
from api_trader import ApiTrader, OrderBuilderWrapper
from api_trader.strategies import fixed_percentage_exit, trailing_stop_exit

class TestOrderBuilderWrapper(unittest.TestCase):

    @patch('api_trader.OrderBuilderWrapper.load_default_settings')
    def setUp(self, mock_load_default_settings):
        self.wrapper = OrderBuilderWrapper()
        # Mock strategy cache to avoid actual file I/O
        self.wrapper.strategy_cache = {}
        mock_load_default_settings.return_value = {'some_setting': 'value'}

    def test_load_default_settings(self):
        result = self.wrapper.load_default_settings('FixedPercentageExit')
        self.assertEqual(result, {'take_profit_percentage': 0.06, 'stop_loss_percentage': 0.03})

    @patch('api_trader.OrderBuilderWrapper._construct_exit_strategy')
    def test_load_strategy(self, mock_construct_exit_strategy):
        strategy_object = {'ExitStrategy': 'FixedPercentageExit', 'ExitStrategySettings': {}}
        mock_construct_exit_strategy.return_value = MagicMock()

        strategy = self.wrapper.load_strategy(strategy_object)
        
        # Check if the strategy is returned and cached
        self.assertIsNotNone(strategy)
        self.assertIn('FixedPercentageExit', self.wrapper.strategy_cache)
        self.assertEqual(strategy, self.wrapper.strategy_cache['FixedPercentageExit'])

    def test_construct_exit_strategy(self):
        # Create a mock for strategy settings
        mock_settings = {'FixedPercentageExit': {'percentage': 10}}
        
        strategy_object = {'ExitStrategy': 'FixedPercentageExit', 'ExitStrategySettings': mock_settings}
        
        with patch('api_trader.OrderBuilderWrapper._construct_exit_strategy', wraps=self.wrapper._construct_exit_strategy) as mock_construct:
            strategy = self.wrapper._construct_exit_strategy(strategy_object)
            self.assertIsInstance(strategy, fixed_percentage_exit.FixedPercentageExitStrategy)
            self.assertEqual(strategy.strategy_settings, mock_settings['FixedPercentageExit'])

    def test_get_current_strategy_allocation(self):
        asyncio.run(self.async_test_get_current_strategy_allocation())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_get_current_strategy_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Mock the open positions returned by get_open_positions
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 150.00},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 1000.00},
        ]
        
        mock_queued_positions = [
            {"Symbol": "MSFT", "Strategy": "Strategy_A", "Qty": 2, "Entry_Price": 200.00},
        ]

        # Create an AsyncMock for the cursor
        mock_open_positions_cursor = AsyncMock()
        mock_queued_positions_cursor = AsyncMock()

        # Mock the async iteration behavior
        mock_open_positions_cursor.__aiter__.return_value = iter(mock_open_positions)  # directly mock __aiter__
        mock_queued_positions_cursor.__aiter__.return_value = iter(mock_queued_positions)  # mock __aiter__

        # Ensure that find() returns the mocked cursors
        self.api_trader.async_mongo.open_positions.find.return_value = mock_open_positions_cursor
        self.api_trader.async_mongo.queue.find.return_value = mock_queued_positions_cursor

        # Call the method under test
        strategy = "Strategy_A"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: 
        # (10 * 150.00) + (5 * 1000.00) + (2 * 200.00) = 1500 + 5000 + 400 = 6900
        expected_allocation = 6900.00

        # Assertions
        self.assertEqual(result, expected_allocation)

    def test_get_current_strategy_allocation_no_positions(self):
        asyncio.run(self.async_test_get_current_strategy_allocation_no_positions())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_get_current_strategy_allocation_no_positions(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()  # Change to MagicMock
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Create a MagicMock cursor object
        mock_open_positions_cursor = MagicMock()
        mock_queued_positions_cursor = MagicMock()

        # Mock the async iteration behavior for empty results
        # Mock __aiter__ and __anext__ for the async iteration
        mock_open_positions_cursor.__aiter__.return_value = iter([])  # Empty list for open positions
        mock_queued_positions_cursor.__aiter__.return_value = iter([])  # Empty list for queued positions

        # Mock MongoDB find calls to return the mocked cursors
        self.api_trader.async_mongo.open_positions.find.return_value = mock_open_positions_cursor
        self.api_trader.async_mongo.queue.find.return_value = mock_queued_positions_cursor

        # Call the method under test
        strategy = "Strategy_A"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: No positions, so allocation should be 0
        self.assertEqual(result, 0.0)

        # Verify that the async methods are awaited
        self.api_trader.async_mongo.open_positions.find.assert_called_once_with(
            {"Trader": self.api_trader.user["Name"], "Account_ID": self.api_trader.account_id, "Strategy": strategy},
            {"_id": 0, "Qty": 1, "Entry_Price": 1, "Asset_Type": 1}
        )

        self.api_trader.async_mongo.queue.find.assert_called_once_with(
            {"Trader": self.api_trader.user["Name"], "Account_ID": self.api_trader.account_id, "Strategy": strategy, "Order_Status": {"$in": ["PENDING_ACTIVATION", "QUEUED"]}, "Direction": "OPEN POSITION"},
            {"_id": 0, "Qty": 1, "Entry_Price": 1, "Asset_Type": 1}
        )

    def test_get_current_strategy_allocation_with_outstanding_orders(self):
        asyncio.run(self.async_test_get_current_strategy_allocation_with_outstanding_orders())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_get_current_strategy_allocation_with_outstanding_orders(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Mock the open positions returned by get_open_positions
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 150.00},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 1000.00},
            {"Symbol": "TSLA", "Strategy": "Strategy_B", "Qty": 8, "Entry_Price": 700.00},
        ]

        # Mock the outstanding orders in the queue for the same strategy
        mock_queued_orders = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 145.00, "Order_Status": "QUEUED"},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 3, "Entry_Price": 995.00, "Order_Status": "QUEUED"},
        ]

        # Create a mock for the open positions cursor (async iterable)
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.__aiter__.return_value = iter(
            [position for position in mock_open_positions if position["Strategy"] == "Strategy_A"]
        )

        # Create a mock for the queued orders cursor (async iterable)
        mock_queued_positions_cursor = MagicMock()
        mock_queued_positions_cursor.__aiter__.return_value = iter(
            [order for order in mock_queued_orders if order["Strategy"] == "Strategy_A"]
        )

        # Mock the behavior of async_mongo to return the mocked cursors
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)
        self.api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queued_positions_cursor)

        # Call the method under test
        strategy = "Strategy_A"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result:
        # From open positions: (10 * 150.00) + (5 * 1000.00) = 1500 + 5000 = 6500
        # From outstanding orders: (5 * 145.00) + (3 * 995.00) = 725 + 2985 = 3710
        # Total: 6500 + 3710 = 10210
        expected_allocation = 10210.00

        # Assertions
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct


    def test_get_current_strategy_allocation_zero_qty_or_price(self):
        asyncio.run(self.async_test_get_current_strategy_allocation_zero_qty_or_price())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_get_current_strategy_allocation_zero_qty_or_price(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Mock positions with zero quantities or entry prices
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 0, "Entry_Price": 150.00},  # Zero quantity
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 0.00},   # Zero entry price
            {"Symbol": "TSLA", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 100.00}  # Valid position
        ]

        # Mock the async behavior of get_open_positions
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.__aiter__.return_value = iter(
            [position for position in mock_open_positions if position["Strategy"] == "Strategy_A"]
        )

        # Mock the async behavior of get_queued_positions returning empty
        mock_queued_positions_cursor = MagicMock()
        mock_queued_positions_cursor.__aiter__.return_value = iter([])  # Empty list for queued positions

        # Mock the behavior of async_mongo to return the mocked cursors
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)
        self.api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queued_positions_cursor)

        # Call the method under test
        strategy = "Strategy_A"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: Only the valid position (10 * 100.00) = 1000
        expected_allocation = 1000.00

        # Assertions
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct

    def test_option_allocation(self):
        asyncio.run(self.async_test_option_allocation())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_option_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Test strategy allocation calculation for options
        mock_open_positions = [{"Qty": 2, "Entry_Price": 3.0, "Asset_Type": "OPTION"}]
        mock_queued_positions = [{"Qty": 1, "Entry_Price": 4.0, "Asset_Type": "OPTION"}]

        # Create a mock for the open positions cursor (async iterable)
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.__aiter__.return_value = iter(
            [position for position in mock_open_positions if position["Asset_Type"] == "OPTION"]
        )

        # Create a mock for the queued orders cursor (async iterable)
        mock_queued_positions_cursor = MagicMock()
        mock_queued_positions_cursor.__aiter__.return_value = iter(
            [order for order in mock_queued_positions if order["Asset_Type"] == "OPTION"]
        )

        # Mock the behavior of async_mongo to return the mocked cursors
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)
        self.api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queued_positions_cursor)

        # Call the method under test
        strategy = "TestStrategy"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result:
        # From open positions: (2 * 3 * 100) = 600
        # From outstanding orders: (1 * 4 * 100) = 400
        # Total: 600 + 400 = 1000
        expected_allocation = 1000

        # Assertions
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct

    def test_mixed_allocation(self):
        asyncio.run(self.async_test_mixed_allocation())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_mixed_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.async_mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Test strategy allocation calculation for a mix of equities and options
        mock_open_positions = [
            {"Qty": 10, "Entry_Price": 50.0, "Asset_Type": "EQUITY"},
            {"Qty": 2, "Entry_Price": 3.0, "Asset_Type": "OPTION"}
        ]
        mock_queued_positions = [
            {"Qty": 5, "Entry_Price": 45.0, "Asset_Type": "EQUITY"},
            {"Qty": 1, "Entry_Price": 4.0, "Asset_Type": "OPTION"}
        ]

        # Create a mock for the open positions cursor (async iterable)
        mock_open_positions_cursor = MagicMock()
        mock_open_positions_cursor.__aiter__.return_value = iter(
            [position for position in mock_open_positions if position["Asset_Type"] in ["EQUITY", "OPTION"]]
        )

        # Create a mock for the queued orders cursor (async iterable)
        mock_queued_positions_cursor = MagicMock()
        mock_queued_positions_cursor.__aiter__.return_value = iter(
            [order for order in mock_queued_positions if order["Asset_Type"] in ["EQUITY", "OPTION"]]
        )

        # Mock the behavior of async_mongo to return the mocked cursors
        self.api_trader.async_mongo.open_positions.find = MagicMock(return_value=mock_open_positions_cursor)
        self.api_trader.async_mongo.queue.find = MagicMock(return_value=mock_queued_positions_cursor)

        # Call the method under test
        strategy = "TestStrategy"
        result = await self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result:
        # Equities: (10 * 50) + (5 * 45) = 725
        # Options: (2 * 3 * 100) + (1 * 4 * 100) = 600 + 400 = 1000
        # Total: 725 + 1000 = 1725
        expected_allocation = 1725

        # Assertions
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct

    def test_standard_order_open_position(self):
        asyncio.run(self.async_test_standard_order_open_position())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_standard_order_open_position(self, mock_init):

        # Set up the mock behavior for tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }
        
        # Prepare mock data for the test
        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 100,
            "Position_Size": 1000
        }
        
        strategy_object = {
            "ExitStrategy": "FixedPercentageExit",
            "ExitStrategySettings": {},  # Add appropriate settings if needed
            "Position_Size": 1000,
            "Active": True,
            "Order_Type": "LIMIT",
            "Position_Type": "LONG"
        }
        
         # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock()
        api_trader.tdameritrade.getQuoteAsync.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = await api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        self.assertIsNotNone(order)
        self.assertIsNotNone(obj)
        self.assertEqual(obj['Qty'], 6) # Expect 6 shares (1000 / 150)
        self.assertEqual(obj['Entry_Price'], 150.00)

    def test_standard_order_close_position(self):
        asyncio.run(self.async_test_standard_order_close_position())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_standard_order_close_position(self, mock_init):
        
        # Set up the mock behavior for tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }
        
        trade_data = {
            'Symbol': 'AAPL',
            "Side": "SELL",
            "Strategy": "FixedPercentageExit",
            'Qty': 10,
            'Entry_Price': 140.00,
            'Entry_Date': '2024-09-07',
            'Position_Size': 1000
        }
        
        strategy_object = {
            'Position_Size': 1000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }
        
        # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock()
        api_trader.tdameritrade.getQuoteAsync.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = await api_trader.standardOrder(trade_data, strategy_object, direction='CLOSE POSITION', user=api_trader.user, account_id=api_trader.account_id)

        self.assertIsNotNone(order)
        self.assertEqual(obj['Exit_Price'], 148.00)
        self.assertEqual(obj['Qty'], 10)

    def test_order_blocked_when_exceeding_max_position_size(self):
        asyncio.run(self.async_test_order_blocked_when_exceeding_max_position_size())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_order_blocked_when_exceeding_max_position_size(self, mock_init):
        # Set up the mock behavior for tdameritrade.getQuoteAsync
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }

        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 10,
            "Position_Size": 1500
        }
        
        # Mock strategy settings with a MaxPositionSize of $5000
        strategy_object = {
            "Position_Size": 1500,
            "MaxPositionSize": 5000,
            "Order_Type": "limit",
            "Position_Type": "equity",
            "Active": True
        }

        api_trader = ApiTrader()
        api_trader.user = {"Name": "TestUser"}
        api_trader.account_id = "test_account"
        api_trader.logger = MagicMock()

        # Mock tdameritrade.getQuoteAsync to return mock_quote_response
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=mock_quote_response)

        # Mock current allocated value to simulate a near-limit scenario
        api_trader.get_current_strategy_allocation = AsyncMock(return_value=4000)

        # Call standardOrder method under test
        result = await api_trader.standardOrder(
            trade_data, 
            strategy_object, 
            direction="OPEN POSITION", 
            user=api_trader.user, 
            account_id=api_trader.account_id
        )

        # Verify the order was blocked
        self.assertIsNone(result[0])  # The order should not be created
        api_trader.logger.warning.assert_called_with(
            f"Order stopped: BUY order for AAPL not placed. "
            f"Required position size $5500.0 exceeds max position size for this strategy. "
            f"Strategy status: {strategy_object['Active']}, Shares: 10, Max position size: $5000"
        )

        # Verify that tdameritrade.getQuoteAsync was called with the correct symbol
        api_trader.tdameritrade.getQuoteAsync.assert_awaited_once_with("AAPL")
        
        # Adjusted assertion for get_current_strategy_allocation
        api_trader.get_current_strategy_allocation.assert_awaited_once_with(
            "FixedPercentageExit",  # Ensure keyword arguments are used
            user=api_trader.user,            # Ensure keyword arguments are used
            account_id=api_trader.account_id # Ensure keyword arguments are used
        )


    def test_order_processed_when_within_max_position_size(self):
        asyncio.run(self.async_test_order_processed_when_within_max_position_size())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_order_processed_when_within_max_position_size(self, mock_init):
        # Mock quote response
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }

        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 10,
            "Position_Size": 1500
        }

        # Mock strategy settings with a MaxPositionSize of $5000
        strategy_object = {
            "Position_Size": 1500,
            "MaxPositionSize": 5000,
            "Order_Type": "limit",
            "Position_Type": "equity",
            "Active": True
        }

        api_trader = ApiTrader()
        api_trader.user = {"Name": "TestUser"}
        api_trader.account_id = "test_account"
        api_trader.logger = MagicMock()

        # Mock tdameritrade.getQuoteAsync to return mock_quote_response
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=mock_quote_response)

        # Mock current allocated value to simulate available capacity
        api_trader.get_current_strategy_allocation = AsyncMock(return_value=3000)

        # Call standardOrder
        result = await api_trader.standardOrder(
            trade_data,
            strategy_object,
            direction="OPEN POSITION",
            user=api_trader.user,
            account_id=api_trader.account_id
        )

        # Verify the order was processed
        self.assertIsNotNone(result[0])  # Ensure order is placed
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()

        # Verify tdameritrade.getQuoteAsync was called with the correct symbol
        api_trader.tdameritrade.getQuoteAsync.assert_awaited_once_with("AAPL")

        # Verify get_current_strategy_allocation with positional and keyword arguments
        api_trader.get_current_strategy_allocation.assert_awaited_once_with(
            "FixedPercentageExit",  # Positional argument for strategy
            user=api_trader.user,   # Keyword argument for user
            account_id=api_trader.account_id  # Keyword argument for account_id
        )
    
    def test_order_processed_when_at_exact_max_position_size(self):
        asyncio.run(self.async_test_order_processed_when_at_exact_max_position_size())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_order_processed_when_at_exact_max_position_size(self, mock_init):
        # Mock quote response
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }

        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 10,
            "Position_Size": 1500
        }

        # Mock strategy settings with a MaxPositionSize of $5000
        strategy_object = {
            "Position_Size": 1500,
            "MaxPositionSize": 5000,
            "Order_Type": "limit",
            "Position_Type": "equity",
            "Active": True
        }

        # Create ApiTrader instance and set up mocks
        api_trader = ApiTrader()
        api_trader.user = {"Name": "TestUser"}
        api_trader.account_id = "test_account"
        api_trader.logger = MagicMock()

        # Mock tdameritrade.getQuoteAsync to return mock_quote_response
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=mock_quote_response)

        # Mock current allocated value to match the MaxPositionSize after the new order
        api_trader.get_current_strategy_allocation = AsyncMock(return_value=3500)

        # Call standardOrder
        result = await api_trader.standardOrder(
            trade_data,
            strategy_object,
            direction="OPEN POSITION",
            user=api_trader.user,
            account_id=api_trader.account_id
        )

        # Verify the order was processed
        self.assertIsNotNone(result[0])  # Ensure order is placed
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()

        # Verify tdameritrade.getQuoteAsync was called with the correct symbol
        api_trader.tdameritrade.getQuoteAsync.assert_awaited_once_with("AAPL")

        # Verify get_current_strategy_allocation with positional and keyword arguments
        api_trader.get_current_strategy_allocation.assert_awaited_once_with(
            "FixedPercentageExit",  # Strategy
            user=api_trader.user,   # User
            account_id=api_trader.account_id  # Account ID
        )

    def test_order_processed_without_max_position_size(self):
        asyncio.run(self.async_test_order_processed_without_max_position_size())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_order_processed_without_max_position_size(self, mock_init):
        # Set up the mock behavior for tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00  # Mock sell price
                }
            }
        }

        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 10,
            "Position_Size": 1500
        }
        
        # Mock strategy settings, no max position size, so the order should always be processed
        strategy_object = {
            'Position_Size': 1500,
            # 'MaxPositionSize': 5000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }

        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.logger = MagicMock()

        api_trader.tdameritrade.getQuoteAsync = AsyncMock(side_effect = [mock_quote_response])

        # Set current allocated and mock new order size
        api_trader.get_current_strategy_allocation = MagicMock(return_value=4000)

        result = await api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Verify the order was blocked
        self.assertIsNotNone(result[0])
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()

    def test_zero_price_raises_value_error(self):
        asyncio.run(self.async_test_zero_price_raises_value_error())

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_zero_price_raises_value_error(self, mock_init):

         # Set up the mock behavior for tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 0.00,  # Mock buy price
                    "bidPrice": 0.00  # Mock sell price
                }
            }
        }
        
        # Prepare mock data for the test
        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
            "Qty": 100,
            "Position_Size": 1000
        }
        
        strategy_object = {
            "ExitStrategy": "FixedPercentageExit",
            "ExitStrategySettings": {},  # Add appropriate settings if needed
            "Position_Size": 1000,
            "Active": True,
            "Order_Type": "LIMIT",
            "Position_Type": "LONG"
        }
        
         # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.logger = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(side_effect = [mock_quote_response])

        # Assert that the ValueError is raised when price is zero
        with self.assertRaises(ValueError):
            await api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Get the actual log message
        log_messages = [call[0][0] for call in api_trader.logger.error.call_args_list]
        
        # Define the expected start of the message
        expected_start = "Price is zero for asset - cannot calculate shares:"
        
        # Check that at least one log message starts with the expected string
        self.assertTrue(any(message.startswith(expected_start) for message in log_messages),
                        f"Expected log message starting with '{expected_start}' not found.")

    def test_OCO_order(self):
        asyncio.run(self.async_test_OCO_order())

    @patch('api_trader.OrderBuilderWrapper.standardOrder', new_callable=AsyncMock)
    @patch('api_trader.OrderBuilderWrapper.load_strategy', new_callable=MagicMock)
    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    async def async_test_OCO_order(self, mock_init, mock_load_strategy, mock_standard_order):
        # Mock return value for standardOrder
        parent_order_mock = MagicMock()
        obj_mock = {"childOrderStrategies": []}
        mock_standard_order.return_value = (parent_order_mock, obj_mock)

        # Mock return value for load_strategy
        strategy = MagicMock()
        exit_order_mock = MagicMock()  # Mock the exit order
        strategy.apply_exit_strategy.return_value = exit_order_mock
        mock_load_strategy.return_value = strategy

        # Trade data and other parameters
        trade_data = {
            "Symbol": "AAPL",
            "Side": "BUY",
            "Strategy": "FixedPercentageExit",
        }
        strategy_object = {
            "Position_Size": 1000,
            "Order_Type": "limit",
            "Position_Type": "equity",
            "Active": True,
        }

        # Mock the response of tdameritrade.getQuote()
        mock_quote_response = {
            "AAPL": {
                "quote": {
                    "askPrice": 150.00,  # Mock buy price
                    "bidPrice": 148.00,  # Mock sell price
                }
            }
        }

        # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuoteAsync = AsyncMock(return_value=mock_quote_response)

        # Call OCOorder
        order, obj = await api_trader.OCOorder(
            trade_data, strategy_object, "OPEN POSITION", api_trader.user, api_trader.account_id
        )

        # Assertions
        self.assertIsNotNone(order)
        self.assertIn("childOrderStrategies", obj)
        self.assertEqual(len(obj["childOrderStrategies"]), 1)  # Expect 1 exit order
        self.assertEqual(obj["childOrderStrategies"][0], exit_order_mock)  # Confirm correct exit order



    @patch('api_trader.strategies.trailing_stop_exit.TrailingStopExitStrategy')
    def test_trailing_stop_exit_strategy_constructed(self, mock_trailing_stop_exit_strategy):
        # Mock strategy settings for TrailingStopExitStrategy
        mock_strategy_settings = {
            "TrailingStopExit": {
                "trailing_stop_percentage": 0.05
            }
        }
        
        strategy_object = {'ExitStrategy': 'TrailingStopExit', 'ExitStrategySettings': mock_strategy_settings}

        # Call the method to construct the exit strategy
        result = self.wrapper._construct_exit_strategy(strategy_object)

        # Verify that TrailingStopExitStrategy was constructed and called with the right settings
        mock_trailing_stop_exit_strategy.assert_called_once_with(mock_strategy_settings['TrailingStopExit'])

        # Check that the result is an instance of the mock TrailingStopExitStrategy
        self.assertEqual(result, mock_trailing_stop_exit_strategy.return_value)


if __name__ == '__main__':
    unittest.main()
