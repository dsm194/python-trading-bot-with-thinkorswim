import unittest
from unittest.mock import MagicMock, patch
from api_trader.strategies.trailing_stop_exit import TrailingStopExitStrategy
from api_trader.strategies.strategy_settings import StrategySettings
from schwab.orders.common import OrderType, OrderStrategyType, Duration, Session, StopPriceLinkType, StopPriceLinkBasis, EquityInstruction

# A concrete subclass for testing purposes (since ExitStrategy is abstract)
class TestTrailingStopExitStrategy(unittest.TestCase):

    def setUp(self):

        self.order_builder_cls = MagicMock()
        self.order_builder_instance = MagicMock()
        self.order_builder_cls.return_value = self.order_builder_instance

        # Mock strategy settings with a trailing stop percentage of 10%
        self.strategy_settings = MagicMock(spec=StrategySettings)
        self.strategy_settings.get = MagicMock(return_value=0.1)  # 10% trailing stop

        # Instantiate TrailingStopExitStrategy with mocked strategy settings
        self.exit_strategy = TrailingStopExitStrategy(self.strategy_settings, self.order_builder_cls)

    def test_should_exit_updates_max_price_and_calculates_trailing_stop(self):
        # Set up additional_params with trade details
        additional_params = {
            "last_price": 150.0,
            "max_price": 145.0,  # previous high price
            "symbol": "AAPL",
            "quantity": 10,
            "side": "BUY",
            "assetType": "EQUITY"
        }

        # Call should_exit to test updating max_price and trailing stop calculation
        result = self.exit_strategy.should_exit(additional_params)

        # Check that max_price is updated to the higher last_price
        self.assertEqual(result["additional_params"]["max_price"], 150.0)

        # Calculate expected trailing stop price (90% of max_price due to 10% trailing stop)
        expected_trailing_stop_price = 150.0 * (1 - 0.1)
        self.assertEqual(result["trailing_stop_price"], expected_trailing_stop_price)

        # Check that the exit condition is false because the last price is still above the trailing stop
        self.assertFalse(result["exit"])

    def test_should_exit_triggers_exit_when_price_below_trailing_stop(self):
        # Set up additional_params with a last price below the trailing stop
        additional_params = {
            "last_price": 130.0,  # price below the trailing stop
            "max_price": 150.0,  # previous high price
            "symbol": "AAPL",
            "quantity": 10,
            "side": "BUY",
            "assetType": "EQUITY"
        }

        # Call should_exit to check if it triggers an exit
        result = self.exit_strategy.should_exit(additional_params)

        # Calculate expected trailing stop price (90% of max_price due to 10% trailing stop)
        expected_trailing_stop_price = 150.0 * (1 - 0.1)
        self.assertEqual(result["trailing_stop_price"], expected_trailing_stop_price)

        # Check that the exit condition is true because the last price is below the trailing stop
        self.assertTrue(result["exit"])

    def test_create_exit_order_builds_trailing_stop_order(self):
        exit_result = {
            "trailing_stop_price": 135.0,
            "additional_params": {
                "symbol": "AAPL",
                "quantity": 10,
                "side": "BUY",
                "assetType": "EQUITY"
            }
        }

        self.exit_strategy.get_instruction_for_side = MagicMock(return_value=EquityInstruction.SELL)
        self.order_builder_instance.build.return_value = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'TRAILING_STOP',
            'stopPriceLinkBasis': 'MARK',
            'stopPriceLinkType': 'PERCENT',
            'stopPriceOffset': 10.0,
            'orderLegCollection': [{'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}],
            'orderStrategyType': 'SINGLE'
        }

        result_order = self.exit_strategy.create_exit_order(exit_result)

        self.order_builder_cls.assert_called_once()
        self.order_builder_instance.set_order_type.assert_called_once_with(OrderType.TRAILING_STOP)
        self.order_builder_instance.set_session.assert_called_once_with(Session.NORMAL)
        self.order_builder_instance.set_duration.assert_called_once_with(Duration.GOOD_TILL_CANCEL)
        self.order_builder_instance.set_order_strategy_type.assert_called_once_with(OrderStrategyType.SINGLE)
        self.order_builder_instance.set_stop_price_link_type.assert_called_once_with(StopPriceLinkType.PERCENT)
        self.order_builder_instance.set_stop_price_link_basis.assert_called_once_with(StopPriceLinkBasis.MARK)
        self.order_builder_instance.set_stop_price_offset.assert_called_once_with(10.0)

        self.order_builder_instance.add_equity_leg.assert_called_once_with(
            instruction=EquityInstruction.SELL, symbol="AAPL", quantity=10
        )

        self.order_builder_instance.build.assert_called_once()

        expected_order = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'TRAILING_STOP',
            'stopPriceLinkBasis': 'MARK',
            'stopPriceLinkType': 'PERCENT',
            'stopPriceOffset': 10.0,
            'orderLegCollection': [{'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}],
            'orderStrategyType': 'SINGLE'
        }

        self.assertEqual(result_order, expected_order)


    def test_create_exit_order_with_non_equity_asset(self):
        # Set up the exit result with additional_params
        exit_result = {
            "trailing_stop_price": 135.0,
            "additional_params": {
                "symbol": "AAPL",
                "quantity": 10,
                "side": "BUY",
                "assetType": "OPTION"  # Non-equity asset
            }
        }

        # Mock the instruction for the side
        self.exit_strategy.get_instruction_for_side = MagicMock(return_value=EquityInstruction.SELL)

        # Mock the build method's return value
        self.order_builder_instance.build.return_value = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'TRAILING_STOP',
            'stopPriceLinkBasis': 'MARK',
            'stopPriceLinkType': 'PERCENT',
            'stopPriceOffset': 10.0,
            'orderLegCollection': [{'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}],
            'orderStrategyType': 'SINGLE'
        }

        # Call create_exit_order
        result_order = self.exit_strategy.create_exit_order(exit_result)

        # Assert that the order builder was instantiated
        self.order_builder_cls.assert_called_once()

        # Check the methods called on the order builder instance
        self.order_builder_instance.set_order_type.assert_called_once_with(OrderType.TRAILING_STOP)
        self.order_builder_instance.set_session.assert_called_once_with(Session.NORMAL)
        self.order_builder_instance.set_duration.assert_called_once_with(Duration.GOOD_TILL_CANCEL)
        self.order_builder_instance.set_order_strategy_type.assert_called_once_with(OrderStrategyType.SINGLE)
        self.order_builder_instance.set_stop_price_link_type.assert_called_once_with(StopPriceLinkType.PERCENT)
        self.order_builder_instance.set_stop_price_link_basis.assert_called_once_with(StopPriceLinkBasis.MARK)
        self.order_builder_instance.set_stop_price_offset.assert_called_once_with(10.0)

        # Check that the option leg is added instead of the equity leg
        self.order_builder_instance.add_option_leg.assert_called_once_with(
            instruction=EquityInstruction.SELL, symbol="AAPL", quantity=10
        )

        # Verify the build method was called
        self.order_builder_instance.build.assert_called_once()

        # Verify the final order structure
        expected_order = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'TRAILING_STOP',
            'stopPriceLinkBasis': 'MARK',
            'stopPriceLinkType': 'PERCENT',
            'stopPriceOffset': 10.0,
            'orderLegCollection': [{'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}],
            'orderStrategyType': 'SINGLE'
        }

        self.assertEqual(result_order, expected_order)

    
    def test_should_exit(self):
        # Mock additional params
        additional_params = {
            'last_price': 100,
            'max_price': 110,  # Max observed price
        }

        # Test that it should exit if the last_price drops below the trailing stop price
        result = self.exit_strategy.should_exit(additional_params)
        self.assertFalse(result['exit'])  # No exit yet

        additional_params['last_price'] = 99  # Price drops
        result = self.exit_strategy.should_exit(additional_params)
        self.assertTrue(result['exit'])  # Now we should exit

    def test_should_exit_updates_max_price(self):
        additional_params = {
            'last_price': 110,
            'max_price': 105
        }
        # Test that the max price updates if the last price goes higher
        result = self.exit_strategy.should_exit(additional_params)
        self.assertEqual(result['additional_params']['max_price'], 110)

if __name__ == '__main__':
    unittest.main()
    
