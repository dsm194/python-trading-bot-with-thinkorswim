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
        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION')

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
        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        order, obj = api_trader.standardOrder(trade_data, strategy_object, direction='CLOSE POSITION')

        self.assertIsNotNone(order)
        self.assertEqual(obj['Exit_Price'], 148.00)
        self.assertEqual(obj['Qty'], 10)

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
        api_trader.tdameritrade.getQuote.side_effect = [
            mock_quote_response  # Successful quote response
        ]

        # Assert that the ValueError is raised when price is zero
        with self.assertRaises(ValueError):
            api_trader.standardOrder(trade_data, strategy_object, direction='OPEN POSITION')

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
        order, obj = api_trader.OCOorder(trade_data, strategy_object, direction='OPEN POSITION')

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
