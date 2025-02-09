import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from schwab.orders.common import (Duration, EquityInstruction,
                                  OrderStrategyType, OrderType, Session)

from api_trader.strategies.fixed_percentage_exit import \
    FixedPercentageExitStrategy


class TestFixedPercentageExitStrategy(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Define mock strategy settings
        self.strategy_settings = {
            "take_profit_percentage": 0.10,  # 10% profit
            "stop_loss_percentage": 0.05    # 5% loss
        }

        # Patch OrderBuilder and one_cancels_other
        self.patcher_order_builder = patch('api_trader.strategies.fixed_percentage_exit.OrderBuilder')
        self.mock_order_builder_cls = self.patcher_order_builder.start()
        self.mock_order_builder_instance = MagicMock()
        self.mock_order_builder_cls.return_value = self.mock_order_builder_instance

        self.patcher_one_cancels_other = patch('api_trader.strategies.fixed_percentage_exit.one_cancels_other')
        self.mock_one_cancels_other = self.patcher_one_cancels_other.start()

        # Set up default mock return values for OrderBuilder
        self.mock_order_builder_instance.set_order_type = MagicMock()
        self.mock_order_builder_instance.set_session = MagicMock()
        self.mock_order_builder_instance.set_duration = MagicMock()
        self.mock_order_builder_instance.set_price = MagicMock()
        self.mock_order_builder_instance.set_stop_price = MagicMock()
        self.mock_order_builder_instance.add_equity_leg = MagicMock()
        self.mock_order_builder_instance.add_option_leg = MagicMock()
        self.mock_order_builder_instance.build = MagicMock()

        # Create an instance of FixedPercentageExitStrategy
        self.exit_strategy = FixedPercentageExitStrategy(self.strategy_settings, self.mock_order_builder_cls)

    def tearDown(self):
        # Stop all patches
        self.patcher_order_builder.stop()
        self.patcher_one_cancels_other.stop()

    async def test_should_exit_take_profit(self):
        additional_params = {
            'last_price': 110.0,
            'entry_price': 100.0
        }

        result = await self.exit_strategy.should_exit(additional_params)
        
        self.assertTrue(result['exit'])
        self.assertEqual(result['take_profit_price'], 110.0)
        self.assertEqual(result['stop_loss_price'], 95.0)
        self.assertEqual(result['reason'], 'OCO')

    async def test_should_exit_stop_loss(self):
        additional_params = {
            'last_price': 95.0,
            'entry_price': 100.0
        }

        result = await self.exit_strategy.should_exit(additional_params)
        
        self.assertTrue(result['exit'])
        self.assertEqual(result['take_profit_price'], 110.0)
        self.assertEqual(result['stop_loss_price'], 95.0)
        self.assertEqual(result['reason'], 'OCO')

    async def test_should_not_exit(self):
        additional_params = {
            'last_price': 98.0,
            'entry_price': 100.0
        }

        result = await self.exit_strategy.should_exit(additional_params)
        
        self.assertFalse(result['exit'])
        self.assertEqual(result['take_profit_price'], 110.0)
        self.assertEqual(result['stop_loss_price'], 95.0)
        self.assertEqual(result['reason'], 'OCO')

    async def test_create_exit_order_builds_oco_order_equity(self):
        # Set up the exit result with additional_params
        exit_result = {
            "take_profit_price": 110.0,
            "stop_loss_price": 95.0,
            "additional_params": {
                "symbol": "AAPL",
                "quantity": 10,
                "side": "SELL",
                "assetType": "EQUITY"  # Equity asset
            }
        }

        # Mock the instruction for the side
        self.exit_strategy.get_instruction_for_side = AsyncMock(return_value=EquityInstruction.SELL)

        # Mock the build method's return value
        self.mock_order_builder_instance.build.return_value = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'LIMIT',
            'price': '110.0',
            'orderLegCollection': [{'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}],
            'orderStrategyType': 'SINGLE'
        }
        
        self.mock_one_cancels_other.return_value.build.return_value = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'OCO',
            'orderLegCollection': [
                {'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10},
                {'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}
            ],
            'orderStrategyType': 'OCO'
        }

        # Call create_exit_order
        result_order = await self.exit_strategy.create_exit_order(exit_result)

        # Assert that the order builder was instantiated
        self.mock_order_builder_cls.assert_called()
        self.assertEqual(self.mock_order_builder_cls.call_count, 2)

        # Check the methods called on the order builder instance
        self.mock_order_builder_instance.set_order_type.assert_any_call(OrderType.LIMIT)
        self.mock_order_builder_instance.set_session.assert_called_with(Session.NORMAL)
        self.mock_order_builder_instance.set_duration.assert_called_with(Duration.GOOD_TILL_CANCEL)
        self.mock_order_builder_instance.set_order_strategy_type.assert_any_call(OrderStrategyType.SINGLE)
        self.mock_order_builder_instance.set_price.assert_called_with('110.0')

        # Check that the equity leg is added
        self.mock_order_builder_instance.add_equity_leg.assert_called_with(
            instruction=EquityInstruction.SELL, symbol='AAPL', quantity=10
        )

        # Verify the build method was called
        self.mock_order_builder_instance.build.assert_any_call()

        # Verify the final OCO order structure
        expected_order = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'OCO',
            'orderLegCollection': [
                {'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10},
                {'instruction': 'SELL', 'symbol': 'AAPL', 'quantity': 10}
            ],
            'orderStrategyType': 'OCO'
        }

        self.assertEqual(result_order, expected_order)


    async def test_create_exit_order_builds_oco_order_option(self):
        # Set up the exit result with additional_params
        exit_result = {
            "take_profit_price": 110.0,
            "stop_loss_price": 95.0,
            "additional_params": {
                "symbol": "AAPL",
                "pre_symbol": ".AAPL241101C225",
                "quantity": 10,
                "side": "SELL",
                "assetType": "OPTION"  # Option asset
            }
        }

        # Mock the instruction for the side
        self.exit_strategy.get_instruction_for_side = AsyncMock(return_value='SELL')

        # Mock the build method's return value for take profit order
        self.mock_order_builder_instance.build.side_effect = [
            {
                'session': 'NORMAL',
                'duration': 'GOOD_TILL_CANCEL',
                'orderType': 'LIMIT',
                'price': '110.0',
                'orderLegCollection': [{'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10}],
                'orderStrategyType': 'SINGLE'
            },
            {
                'session': 'NORMAL',
                'duration': 'GOOD_TILL_CANCEL',
                'orderType': 'STOP',
                'stopPrice': '95.0',
                'orderLegCollection': [{'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10}],
                'orderStrategyType': 'SINGLE'
            }
        ]

        # Mock the OCO order build result
        self.mock_one_cancels_other.return_value.build.return_value = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'OCO',
            'orderLegCollection': [
                {'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10},
                {'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10}
            ],
            'orderStrategyType': 'OCO'
        }

        # Call create_exit_order
        result_order = await self.exit_strategy.create_exit_order(exit_result)

        # Assert that the order builder was instantiated
        self.mock_order_builder_cls.assert_called()
        self.assertEqual(self.mock_order_builder_cls.call_count, 2)

        # Check the methods called on the order builder instance
        self.mock_order_builder_instance.set_order_type.assert_any_call(OrderType.LIMIT)
        self.mock_order_builder_instance.set_session.assert_called_with(Session.NORMAL)
        self.mock_order_builder_instance.set_duration.assert_called_with(Duration.GOOD_TILL_CANCEL)
        self.mock_order_builder_instance.set_order_strategy_type.assert_any_call(OrderStrategyType.SINGLE)
        self.mock_order_builder_instance.set_price.assert_called_with('110.0')

        # Check that the option leg is added
        self.mock_order_builder_instance.add_option_leg.assert_called_with(
            instruction='SELL', symbol='.AAPL241101C225', quantity=10
        )

        # Verify the build method was called
        self.mock_order_builder_instance.build.assert_any_call()

        # Verify the final OCO order structure
        expected_order = {
            'session': 'NORMAL',
            'duration': 'GOOD_TILL_CANCEL',
            'orderType': 'OCO',
            'orderLegCollection': [
                {'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10},
                {'instruction': 'SELL', 'symbol': '.AAPL241101C225', 'quantity': 10}
            ],
            'orderStrategyType': 'OCO'
        }

        self.assertEqual(result_order, expected_order)