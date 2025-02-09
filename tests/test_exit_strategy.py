import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from api_trader.order_builder import AssetType
from api_trader.strategies.exit_strategy import ExitStrategy
from api_trader.strategies.strategy_settings import StrategySettings

# A concrete subclass of ExitStrategy for testing purposes
class MockExitStrategy(ExitStrategy):
    def should_exit(self, additional_params):
        return {"exit": False}  # Default mock behavior

    def create_exit_order(self, exit_result):
        return "MockExitOrder"  # Default mock order

class TestExitStrategy(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Set up mock strategy settings
        self.strategy_settings = MagicMock(spec=StrategySettings)
        # Use a concrete subclass for testing
        self.exit_strategy = MockExitStrategy(self.strategy_settings)

    async def test_apply_exit_strategy_creates_order_if_exit_condition_met(self):
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
        self.exit_strategy.should_exit = AsyncMock(return_value={"exit": True})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = AsyncMock(return_value="MockOrder")

        # Call apply_exit_strategy
        result = await self.exit_strategy.apply_exit_strategy(trade_data)

        # Check that the exit condition was checked
        self.exit_strategy.should_exit.assert_called_once_with({
            "last_price": 150.0,
            "entry_price": 145.0,
            "quantity": 10,
            "symbol": "AAPL",
            "pre_symbol": None,
            "side": "BUY",
            "assetType": "EQUITY"
        })

        # Check that create_exit_order was called and result is returned
        self.exit_strategy.create_exit_order.assert_called_once_with({"exit": True})
        self.assertEqual(result, "MockOrder")

    async def test_apply_exit_strategy_returns_none_if_no_exit_condition_and_always_create_exit_false(self):
        trade_data = {
            "Last_Price": 150.0,
            "Entry_Price": 145.0,
            "Qty": 10,
            "Symbol": "AAPL",
            "Side": "BUY",
            "Asset_Type": "EQUITY"
        }

        # Mock the should_exit method to return exit condition not met
        self.exit_strategy.should_exit = AsyncMock(return_value={"exit": False})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = AsyncMock(return_value="MockOrder")

        # Call apply_exit_strategy with always_create_exit=False
        result = await self.exit_strategy.apply_exit_strategy(trade_data, always_create_exit=False)

        # Check that no exit order is created
        self.assertIsNone(result)
        self.exit_strategy.create_exit_order.assert_not_called()

    async def test_apply_exit_strategy_creates_order_if_always_create_exit_true(self):
        trade_data = {
            "Last_Price": 150.0,
            "Entry_Price": 145.0,
            "Qty": 10,
            "Symbol": "AAPL",
            "Side": "BUY",
            "Asset_Type": "EQUITY"
        }

        # Mock the should_exit method to return exit condition not met
        self.exit_strategy.should_exit = AsyncMock(return_value={"exit": False})

        # Mock the create_exit_order method
        self.exit_strategy.create_exit_order = AsyncMock(return_value="MockOrder")

        # Call apply_exit_strategy with always_create_exit=True
        result = await self.exit_strategy.apply_exit_strategy(trade_data, always_create_exit=True)

        # Check that create_exit_order was called despite no exit condition met
        self.exit_strategy.create_exit_order.assert_called_once_with({"exit": False})
        self.assertEqual(result, "MockOrder")

    @patch('schwab.orders.common.EquityInstruction')
    @patch('schwab.orders.common.OptionInstruction')
    async def test_get_instruction_for_side(self, mock_OptionInstruction, mock_EquityInstruction):
        # Mock EquityInstruction constants
        mock_EquityInstruction.SELL = "SELL"
        mock_EquityInstruction.BUY = "BUY"
        mock_EquityInstruction.SELL_SHORT = "SELL_SHORT"
        mock_EquityInstruction.BUY_TO_COVER = "BUY_TO_COVER"

        mock_OptionInstruction.SELL_TO_CLOSE = "SELL_TO_CLOSE"
        mock_OptionInstruction.BUY_TO_CLOSE = "BUY_TO_CLOSE"
        mock_OptionInstruction.BUY_TO_OPEN = "BUY_TO_OPEN"
        mock_OptionInstruction.SELL_TO_OPEN = "SELL_TO_OPEN"

        # Test the get_instruction_for_side method with different sides
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "BUY"), mock_EquityInstruction.SELL)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "SELL"), mock_EquityInstruction.BUY)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "BUY_TO_COVER"), mock_EquityInstruction.SELL_SHORT)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "SELL_TO_OPEN"), mock_EquityInstruction.BUY)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "BUY_TO_OPEN"), mock_EquityInstruction.SELL)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.EQUITY, "SELL_SHORT"), mock_EquityInstruction.BUY_TO_COVER)

        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "BUY"), mock_OptionInstruction.SELL_TO_CLOSE)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "BUY_TO_OPEN"), mock_OptionInstruction.SELL_TO_CLOSE)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "SELL_TO_OPEN"), mock_OptionInstruction.BUY_TO_CLOSE)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "SELL"), mock_OptionInstruction.BUY_TO_OPEN)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "BUY_TO_CLOSE"), mock_OptionInstruction.SELL_TO_OPEN)
        self.assertEqual(await self.exit_strategy.get_instruction_for_side(AssetType.OPTION, "SELL_TO_CLOSE"), mock_OptionInstruction.BUY_TO_OPEN)


if __name__ == '__main__':
    unittest.main()
