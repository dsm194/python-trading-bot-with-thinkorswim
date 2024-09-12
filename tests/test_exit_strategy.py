import unittest
from unittest.mock import MagicMock, patch
from api_trader.strategies.exit_strategy import ExitStrategy
from api_trader.strategies.strategy_settings import StrategySettings

# A concrete subclass of ExitStrategy for testing purposes
class MockExitStrategy(ExitStrategy):
    def should_exit(self, additional_params):
        return {"exit": False}  # Default mock behavior

    def create_exit_order(self, exit_result):
        return "MockExitOrder"  # Default mock order

class TestExitStrategy(unittest.TestCase):

    def setUp(self):
        # Set up mock strategy settings
        self.strategy_settings = MagicMock(spec=StrategySettings)
        # Use a concrete subclass for testing
        self.exit_strategy = MockExitStrategy(self.strategy_settings)

    def test_apply_exit_strategy_creates_order_if_exit_condition_met(self):
        # Set up trade data
        trade_data = {
            "Last_Price": 150.0,
            "Entry_Price": 145.0,
            "Qty": 10,
            "Symbol": "AAPL",
            "Side": "BUY",
            "Asset_Type": "EQUITY"
        }

        # Mock the should_exit method to return an exit condition met
        self.exit_strategy.should_exit = MagicMock(return_value={"exit": True})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = MagicMock(return_value="MockOrder")

        # Call apply_exit_strategy
        result = self.exit_strategy.apply_exit_strategy(trade_data)

        # Check that the exit condition was checked
        self.exit_strategy.should_exit.assert_called_once_with({
            "last_price": 150.0,
            "entry_price": 145.0,
            "quantity": 10,
            "symbol": "AAPL",
            "side": "BUY",
            "assetType": "EQUITY"
        })

        # Check that create_exit_order was called and result is returned
        self.exit_strategy.create_exit_order.assert_called_once_with({"exit": True})
        self.assertEqual(result, "MockOrder")

    def test_apply_exit_strategy_returns_none_if_no_exit_condition_and_always_create_exit_false(self):
        trade_data = {
            "Last_Price": 150.0,
            "Entry_Price": 145.0,
            "Qty": 10,
            "Symbol": "AAPL",
            "Side": "BUY",
            "Asset_Type": "EQUITY"
        }

        # Mock the should_exit method to return exit condition not met
        self.exit_strategy.should_exit = MagicMock(return_value={"exit": False})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = MagicMock(return_value="MockOrder")

        # Call apply_exit_strategy with always_create_exit=False
        result = self.exit_strategy.apply_exit_strategy(trade_data, always_create_exit=False)

        # Check that no exit order is created
        self.assertIsNone(result)
        self.exit_strategy.create_exit_order.assert_not_called()

    def test_apply_exit_strategy_creates_order_if_always_create_exit_true(self):
        trade_data = {
            "Last_Price": 150.0,
            "Entry_Price": 145.0,
            "Qty": 10,
            "Symbol": "AAPL",
            "Side": "BUY",
            "Asset_Type": "EQUITY"
        }

        # Mock the should_exit method to return exit condition not met
        self.exit_strategy.should_exit = MagicMock(return_value={"exit": False})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = MagicMock(return_value="MockOrder")

        # Call apply_exit_strategy with always_create_exit=True
        result = self.exit_strategy.apply_exit_strategy(trade_data, always_create_exit=True)

        # Check that create_exit_order was called despite no exit condition met
        self.exit_strategy.create_exit_order.assert_called_once_with({"exit": False})
        self.assertEqual(result, "MockOrder")

    @patch('schwab.orders.common.EquityInstruction')
    def test_get_instruction_for_side(self, mock_EquityInstruction):
        # Mock EquityInstruction constants
        mock_EquityInstruction.SELL = "SELL"
        mock_EquityInstruction.BUY = "BUY"
        mock_EquityInstruction.SELL_SHORT = "SELL_SHORT"
        mock_EquityInstruction.BUY_TO_COVER = "BUY_TO_COVER"

        # Test the get_instruction_for_side method with different sides
        self.assertEqual(self.exit_strategy.get_instruction_for_side("BUY"), "SELL")
        self.assertEqual(self.exit_strategy.get_instruction_for_side("SELL"), "BUY")
        self.assertEqual(self.exit_strategy.get_instruction_for_side("BUY_TO_COVER"), "SELL_SHORT")
        self.assertEqual(self.exit_strategy.get_instruction_for_side("SELL_SHORT"), "BUY_TO_COVER")


if __name__ == '__main__':
    unittest.main()
