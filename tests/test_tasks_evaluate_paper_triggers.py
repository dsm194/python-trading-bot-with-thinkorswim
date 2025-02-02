import unittest
from unittest.mock import AsyncMock, MagicMock

from api_trader.tasks import Tasks


class TestEvaluatePaperTriggers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Mocking the quote manager and passing it to Tasks
        self.quote_manager = MagicMock()
        self.position_updater = AsyncMock()
        self.tasks = Tasks(self.quote_manager, self.position_updater)
        self.tasks.user = {"Name": "Test User"}
        self.tasks.account_id = "test_account_id"

        self.quote_manager.unsubscribe = AsyncMock()

        # Mock dependencies within Tasks
        self.tasks.open_positions = MagicMock()
        self.tasks.position_updater.queue_max_price_update = AsyncMock()
        self.tasks.sendOrder = AsyncMock()
        self.tasks.logger = MagicMock()
        self.tasks.strategy_dict = {
            "STRATEGY_1": {
                "ExitStrategy": MagicMock(),
                "Order_Type": "STANDARD"
            }
        }
        self.tasks.positions_by_symbol = {
            "SYM1": [{
                "_id": "position_id_1",
                "Symbol": "SYM1",
                "Strategy": "STRATEGY_1",
                "Entry_Price": 100.00,
                "Qty": 10,
                "Position_Type": "LONG",
                "Side": "BUY",
                "Max_Price": 120.0,
                "Asset_Type": "EQUITY"
            }]
        }
    
    async def test_evaluate_paper_triggers_retrieves_correct_strategy(self):
        # Mock quote data
        quote_data = {"last_price": 130, "regular_market_last_price": 125}
        exit_result = MagicMock()
        exit_result.should_exit.return_value = {
            "exit": False,
            "additional_params": {"max_price": 120.0}
        }
        self.tasks.strategy_dict = {
            "STRATEGY_1": {"ExitStrategy": exit_result}
        }

        # Test call
        await self.tasks.evaluate_paper_triggers("SYM1", quote_data)

        # Assert the strategy was retrieved and should_exit was checked
        self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"].should_exit.assert_called_once()

    async def test_evaluate_paper_triggers_handles_missing_exit_strategy(self):
        # Set up a position with a strategy not in strategy_dict
        self.tasks.positions_by_symbol["SYM2"] = [{
            "_id": "position_id_2",
            "Symbol": "SYM2",
            "Strategy": "STRATEGY_UNKNOWN",
            "Entry_Price": 100.00,
            "Qty": 10,
            "Position_Type": "LONG",
            "Side": "BUY",
            "max_price": 120.0,
            "Asset_Type": "EQUITY"
        }]

        await self.tasks.evaluate_paper_triggers("SYM2", {"last_price": 130, "regular_market_last_price": 125})

        # Verify the warning was logged for missing strategy
        self.tasks.logger.warning.assert_called_once()


    async def test_evaluate_paper_triggers_market_open(self):
        # Mock quote data and other parameters
        quote_data = {"last_price": 130, "regular_market_last_price": 125}
        self.tasks._cached_market_hours = {"isOpen": True}
        
        # Prepare the strategy data with an ExitStrategy mock
        mock_exit_strategy = MagicMock()
        mock_exit_strategy.should_exit.return_value = {
            "exit": False,
            "additional_params": {"max_price": 120.0}
        }
        self.tasks.strategy_dict = {
            "STRATEGY_1": {"ExitStrategy": mock_exit_strategy}
        }

        # Call the method
        await self.tasks.evaluate_paper_triggers("SYM1", quote_data)

        # Verify last_price was used when market is open
        mock_exit_strategy.should_exit.assert_called_once_with({
            "entry_price": 100.00,
            "quantity": 10,
            "last_price": 130,
            "max_price": 120.0
        })


    async def test_evaluate_paper_triggers_market_closed(self):
        # Mock quote data and other parameters
        quote_data = {"last_price": 130, "regular_market_last_price": 125}
        self.tasks._cached_market_hours = {"isOpen": False}
        
        # Prepare the strategy data with an ExitStrategy mock
        mock_exit_strategy = MagicMock()
        mock_exit_strategy.should_exit.return_value = {
            "exit": False,
            "additional_params": {"max_price": 120.0}
        }
        self.tasks.strategy_dict = {
            "STRATEGY_1": {"ExitStrategy": mock_exit_strategy}
        }

        # Call the method
        await self.tasks.evaluate_paper_triggers("SYM1", quote_data)

        # Verify regular_market_last_price was used when market is closed
        mock_exit_strategy.should_exit.assert_called_once_with({
            "entry_price": 100.00,
            "quantity": 10,
            "last_price": 125,
            "max_price": 120.0
        })


    async def test_evaluate_paper_triggers_updates_max_price(self):
        # Mock should_exit to return a new max_price
        self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"].should_exit.return_value = {
            "exit": False,
            "additional_params": {"max_price": 135.0}
        }

        await self.tasks.evaluate_paper_triggers("SYM1", {"last_price": 130, "regular_market_last_price": 125})

        # Assert max_price is updated in database
        self.tasks.position_updater.queue_max_price_update.assert_called_once_with("position_id_1", 135.0)

    async def test_evaluate_paper_triggers_triggers_exit(self):
        # Mock should_exit to indicate exit
        self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"].should_exit.return_value = {
            "exit": True,
            "additional_params": {"max_price": 135.0}
        }

        await self.tasks.evaluate_paper_triggers("SYM1", {"last_price": 130, "regular_market_last_price": 125})

        # Verify sendOrder was called to close position
        self.tasks.sendOrder.assert_called_once_with(
            {
                "_id": "position_id_1",
                "Symbol": "SYM1",
                "Strategy": "STRATEGY_1",
                "Entry_Price": 100.00,
                "Qty": 10,
                "Position_Type": "LONG",
                "Side": "SELL",
                "Max_Price": 135.0,
                "Asset_Type": "EQUITY"
            },
            {"ExitStrategy": self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"], "Order_Type": "STANDARD"},
            "CLOSE POSITION"
        )
        self.quote_manager.unsubscribe.assert_called_once_with(["SYM1"])


if __name__ == "__main__":
    unittest.main()
