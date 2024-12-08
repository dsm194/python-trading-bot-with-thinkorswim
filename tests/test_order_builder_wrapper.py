import unittest
from unittest import mock
from unittest.mock import MagicMock, patch
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


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_get_open_positions(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"

        # Mock open positions data in MongoDB
        # Mock open positions data in MongoDB
        mock_open_positions = [
            {"Symbol": "AAPL", "Trader": "TestUser", "Account_ID": "test_account", "Strategy": "Strategy_A"},
            {"Symbol": "GOOG", "Trader": "TestUser", "Account_ID": "test_account", "Strategy": "Strategy_A"},
            {"Symbol": "TSLA", "Trader": "OtherUser", "Account_ID": "other_account", "Strategy": "Strategy_B"}
        ]
        # Modify the mock find method to return filtered positions
        self.api_trader.mongo.open_positions.find.return_value = [
            position for position in mock_open_positions if position["Trader"] == "TestUser" and position["Account_ID"] == "test_account"
        ]

        # Call the get_open_positions method
        result = self.api_trader.get_open_positions(self.api_trader.user, self.api_trader.account_id, "Strategy_A")

        # Assertions
        self.api_trader.mongo.open_positions.find.assert_called_once_with(
            {"Trader": "TestUser", "Account_ID": "test_account", "Strategy": "Strategy_A"}
        )
        self.assertEqual(len(result), 2)  # Only positions for "TestUser" and "test_account" should be returned
        self.assertIn("AAPL", [pos["Symbol"] for pos in result])
        self.assertIn("GOOG", [pos["Symbol"] for pos in result])
        self.assertNotIn("TSLA", [pos["Symbol"] for pos in result])
    

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_get_current_strategy_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()

        # Mock the open positions returned by get_open_positions
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 150.00},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 1000.00},
            {"Symbol": "TSLA", "Strategy": "Strategy_B", "Qty": 8, "Entry_Price": 700.00},
        ]
        
        strategy = "Strategy_A"

        # Ensure get_open_positions returns only the open positions for Strategy_A
        self.api_trader.get_open_positions.return_value = [
            position for position in mock_open_positions if position["Strategy"] == strategy
        ]

        # Call the method under test
        result = self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: (10 * 150.00) + (5 * 1000.00) = 1500 + 5000 = 6500
        expected_allocation = 6500.00

        # Assertions
        self.api_trader.get_open_positions.assert_called_once()  # Ensure open positions are fetched
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_get_current_strategy_allocation_no_positions(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()

        # Simulate no open positions for the strategy
        self.api_trader.get_open_positions.return_value = []

        # Call the method under test
        strategy = "Strategy_A"
        result = self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: No positions, so allocation should be 0
        self.assertEqual(result, 0.0)


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_get_current_strategy_allocation_with_outstanding_orders(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()
        self.api_trader.get_queued_positions = MagicMock()

        # Mock the open positions returned by get_open_positions
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 150.00},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 1000.00},
            {"Symbol": "TSLA", "Strategy": "Strategy_B", "Qty": 8, "Entry_Price": 700.00},
        ]
        
        # Ensure get_open_positions returns the mock data
        self.api_trader.get_open_positions.return_value = mock_open_positions

        # Mock the outstanding orders in the queue for the same strategy
        mock_queued_orders = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 145.00, "Order_Status": "QUEUED"},
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 3, "Entry_Price": 995.00, "Order_Status": "QUEUED"},
        ]

        # Ensure get_open_positions returns the mock data
        self.api_trader.get_queued_positions.return_value = mock_queued_orders

        strategy = "Strategy_A"
        # Ensure get_open_positions returns only the open positions for Strategy_A
        self.api_trader.get_open_positions.return_value = [
            position for position in mock_open_positions if position["Strategy"] == strategy
        ]
        # Ensure get_queued_positions returns only the queued orders for Strategy_A
        self.api_trader.get_queued_positions.return_value = [
            order for order in mock_queued_orders if order["Strategy"] == strategy
        ]

        # Call the method under test
        result = self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result:
        # From open positions: (10 * 150.00) + (5 * 1000.00) = 1500 + 5000 = 6500
        # From outstanding orders: (5 * 145.00) + (3 * 995.00) = 725 + 2985 = 3710
        # Total: 6500 + 3710 = 10210
        expected_allocation = 10210.00

        # Assertions
        self.api_trader.get_open_positions.assert_called_once()  # Ensure open positions are fetched
        self.api_trader.get_queued_positions.assert_called_once()  # Ensure queued orders are fetched
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_get_current_strategy_allocation_zero_qty_or_price(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()

        # Mock positions with zero quantities or entry prices
        mock_open_positions = [
            {"Symbol": "AAPL", "Strategy": "Strategy_A", "Qty": 0, "Entry_Price": 150.00},  # Zero quantity
            {"Symbol": "GOOG", "Strategy": "Strategy_A", "Qty": 5, "Entry_Price": 0.00},   # Zero entry price
            {"Symbol": "TSLA", "Strategy": "Strategy_A", "Qty": 10, "Entry_Price": 100.00}  # Valid position
        ]
        
        # Ensure get_open_positions returns the mock data
        self.api_trader.get_open_positions.return_value = mock_open_positions

        # Call the method under test
        strategy = "Strategy_A"
        result = self.api_trader.get_current_strategy_allocation(strategy, self.api_trader.user, self.api_trader.account_id)

        # Expected result: Only the valid position (10 * 100.00) = 1000
        expected_allocation = 1000.00

        # Assertions
        self.api_trader.get_open_positions.assert_called_once()  # Ensure open positions are fetched
        self.assertEqual(result, expected_allocation)  # Ensure allocation is correct


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_option_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()
        self.api_trader.get_queued_positions = MagicMock()

        """Test strategy allocation calculation for options."""
        mock_open_positions = [{"Qty": 2, "Entry_Price": 3.0, "Asset_Type": "OPTION"}]
        mock_queued_positions = [{"Qty": 1, "Entry_Price": 4.0, "Asset_Type": "OPTION"}]

        # Ensure get_open_positions returns the mock data
        self.api_trader.get_open_positions.return_value = mock_open_positions
        self.api_trader.get_queued_positions.return_value = mock_queued_positions
        
        allocation = self.api_trader.get_current_strategy_allocation("TestStrategy", "User123", "Acc123")
        
        # (2 * 3 * 100) + (1 * 4 * 100) = 600 + 400 = 1000
        self.assertEqual(allocation, 1000)


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_mixed_allocation(self, mock_init):
        # Create an instance of ApiTrader
        self.api_trader = ApiTrader()

        # Mock attributes
        self.api_trader.mongo = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "test_account"
        self.api_trader.get_open_positions = MagicMock()
        self.api_trader.get_queued_positions = MagicMock()

        """Test strategy allocation calculation for a mix of equities and options."""
        mock_open_positions = [
            {"Qty": 10, "Entry_Price": 50.0, "Asset_Type": "EQUITY"},
            {"Qty": 2, "Entry_Price": 3.0, "Asset_Type": "OPTION"}
        ]
        mock_queued_positions = [
            {"Qty": 5, "Entry_Price": 45.0, "Asset_Type": "EQUITY"},
            {"Qty": 1, "Entry_Price": 4.0, "Asset_Type": "OPTION"}
        ]
        
        # Ensure get_open_positions returns the mock data
        self.api_trader.get_open_positions.return_value = mock_open_positions
        self.api_trader.get_queued_positions.return_value = mock_queued_positions

        allocation = self.api_trader.get_current_strategy_allocation("TestStrategy", "User123", "Acc123")
        
        # (10 * 50) + (5 * 45) + (2 * 3 * 100) + (1 * 4 * 100) = 725 + 600 + 400 = 1725
        self.assertEqual(allocation, 1725)


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_standard_order_open_position(self, mock_init):

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
        api_trader.tdameritrade.getQuoteUnified.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        self.assertIsNotNone(order)
        self.assertIsNotNone(obj)
        self.assertEqual(obj['Qty'], 6) # Expect 6 shares (1000 / 150)
        self.assertEqual(obj['Entry_Price'], 150.00)


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_standard_order_close_position(self, mock_init):
        
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
        api_trader.tdameritrade.getQuoteUnified.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = api_trader.standardOrder(trade_data, strategy_object, direction='CLOSE POSITION', user=api_trader.user, account_id=api_trader.account_id)

        self.assertIsNotNone(order)
        self.assertEqual(obj['Exit_Price'], 148.00)
        self.assertEqual(obj['Qty'], 10)


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_order_blocked_when_exceeding_max_position_size(self, mock_init):
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
        
        # Mock strategy settings with a MaxPositionSize of $5000
        # This should result in a new allocation of $1500, exceeding the $5000 limit
        strategy_object = {
            'Position_Size': 1500,
            'MaxPositionSize': 5000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }

        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.logger = MagicMock()

        api_trader.tdameritrade.getQuoteUnified.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Set current allocated and mock new order size
        api_trader.get_current_strategy_allocation = MagicMock(return_value=4000)

        result = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Verify the order was blocked
        self.assertIsNone(result[0])
        api_trader.logger.warning.assert_called_with(
            f"Order stopped: BUY order for AAPL not placed. "
            f"Required position size $5500.0 exceeds max position size for this strategy. "
            f"Strategy status: {strategy_object['Active']}, Shares: 10, Max position size: $5000"
        )


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_order_processed_when_within_max_position_size(self, mock_init):

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
            'Position_Size': 1500,
            'MaxPositionSize': 5000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }

        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.logger = MagicMock()

        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Set current allocated and mock new order size
        api_trader.get_current_strategy_allocation = MagicMock(return_value=3000)

        # Call standardOrder
        result = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Verify the order was processed
        self.assertIsNotNone(result[0])  # Ensure order is placed
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()
    

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_order_processed_when_at_exact_max_position_size(self, mock_init):
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
            'Position_Size': 1500,
            'MaxPositionSize': 5000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }

        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.logger = MagicMock()

        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Set current allocated and mock new order size
        api_trader.get_current_strategy_allocation = MagicMock(return_value=3500)

        # Call standardOrder
        result = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Verify the order was processed
        self.assertIsNotNone(result[0])  # Ensure order is placed
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_order_processed_without_max_position_size(self, mock_init):
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

        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Set current allocated and mock new order size
        api_trader.get_current_strategy_allocation = MagicMock(return_value=4000)

        result = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Verify the order was blocked
        self.assertIsNotNone(result[0])
        api_trader.logger.warning.assert_not_called()
        api_trader.logger.error.assert_not_called()


    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_zero_price_raises_value_error(self, mock_init):

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
        api_trader.tdameritrade.getQuoteUnified.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Assert that the ValueError is raised when price is zero
        with self.assertRaises(ValueError):
            api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Get the actual log message
        log_messages = [call[0][0] for call in api_trader.logger.error.call_args_list]
        
        # Define the expected start of the message
        expected_start = "Price is zero for asset - cannot calculate shares:"
        
        # Check that at least one log message starts with the expected string
        self.assertTrue(any(message.startswith(expected_start) for message in log_messages),
                        f"Expected log message starting with '{expected_start}' not found.")


    @patch('api_trader.OrderBuilderWrapper.load_strategy')
    @patch('api_trader.OrderBuilderWrapper.standardOrder')
    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    def test_OCO_order(self, mock_init, mock_standard_order, mock_load_strategy):
        strategy = MagicMock()
        mock_load_strategy.return_value = strategy
        
        trade_data = {
            'Symbol': 'AAPL',
            'Side': 'BUY',
            'Strategy': 'FixedPercentageExit',
        }
        
        strategy_object = {
            'Position_Size': 1000,
            'Order_Type': 'limit',
            'Position_Type': 'equity',
            'Active': True
        }

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

        # Mock standardOrder to return these mocks as order and some object
        mock_standard_order.side_effect = [
            (parent_order_mock, {}),  # First call (parent order)
            (exit_order_mock, {})     # Second call (exit order)
        ]

        # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
        api_trader = ApiTrader()
        api_trader.user = MagicMock()
        api_trader.account_id = MagicMock()
        api_trader.tdameritrade = MagicMock()
        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Call the method you want to test
        order, obj = api_trader.OCOorder(trade_data, strategy_object, direction='OPEN POSITION', user=api_trader.user, account_id=api_trader.account_id)

        # Assert expected outcomes
        self.assertIsNotNone(order)
        self.assertIn('childOrderStrategies', obj)
        self.assertEqual(len(obj['childOrderStrategies']), 1)


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
