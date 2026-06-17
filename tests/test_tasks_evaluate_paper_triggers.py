import asyncio
import datetime as dt
import unittest
from unittest.mock import AsyncMock, MagicMock

from api_trader.tasks import Tasks


class TestEvaluatePaperTriggers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Mocking the quote manager and passing it to Tasks
        self.api_trader = MagicMock()
        self.tasks = Tasks(self.api_trader)

        self.api_trader.quote_manager.unsubscribe = AsyncMock()

        # Mock dependencies within Tasks
        self.tasks.open_positions = MagicMock()
        self.tasks.position_updater.queue_max_price_update = AsyncMock()
        self.tasks.api_trader.sendOrder = AsyncMock(return_value=True)
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
        self.tasks.api_trader.sendOrder.assert_called_once_with(
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
        self.api_trader.quote_manager.unsubscribe.assert_called_once_with(["SYM1"])

    async def test_evaluate_paper_triggers_keeps_position_when_close_order_fails(self):
        self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"].should_exit.return_value = {
            "exit": True,
            "additional_params": {"max_price": 135.0}
        }
        self.tasks.api_trader.sendOrder = AsyncMock(return_value=False)

        await self.tasks.evaluate_paper_triggers("SYM1", {"last_price": 130, "regular_market_last_price": 125})

        self.assertIn("SYM1", self.tasks.positions_by_symbol)
        self.assertEqual(len(self.tasks.positions_by_symbol["SYM1"]), 1)
        self.api_trader.quote_manager.unsubscribe.assert_not_called()

    async def test_concurrent_evaluate_paper_triggers_closes_and_unsubscribes_once(self):
        # Mock should_exit to indicate exit
        self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"].should_exit.return_value = {
            "exit": True,
            "additional_params": {"max_price": 135.0}
        }

        async def slow_send_order(*args, **kwargs):
            return True

        self.tasks.api_trader.sendOrder = AsyncMock(side_effect=slow_send_order)

        await asyncio.gather(
            self.tasks.evaluate_paper_triggers("SYM1", {"last_price": 130, "regular_market_last_price": 125}),
            self.tasks.evaluate_paper_triggers("SYM1", {"last_price": 130, "regular_market_last_price": 125}),
        )

        self.tasks.api_trader.sendOrder.assert_awaited_once()
        self.api_trader.quote_manager.unsubscribe.assert_awaited_once_with(["SYM1"])

    async def test_checkOCOpapertriggers_closes_expired_options_without_subscribing(self):
        expired_position = {
            "_id": "expired_position",
            "Symbol": "CP",
            "Pre_Symbol": "CP    250718C00082500",
            "Exp_Date": "2025-07-18",
            "Option_Type": "CALL",
            "Strategy": "STRATEGY_1",
            "Account_ID": "paper_account",
            "Asset_Type": "OPTION",
            "Order_Type": "STANDARD",
            "Qty": 1,
            "Entry_Price": 2.85,
            "Entry_Date": dt.datetime(2025, 7, 1, tzinfo=dt.timezone.utc),
            "Side": "BUY_TO_OPEN",
            "Position_Size": 285,
            "Position_Type": "LONG",
            "Account_Position": "Paper",
        }

        self.tasks.user = {"Name": "TestUser"}
        self.tasks.account_id = "paper_account"
        self.tasks.auto_close_expired_paper_options = True
        self.tasks.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={"isOpen": True})
        self.api_trader.quote_manager.subscribed_symbols = {
            "CP    250718C00082500": {"symbol": "CP    250718C00082500", "asset_type": "OPTION"}
        }
        self.api_trader.quote_manager.add_callback = AsyncMock()
        self.api_trader.quote_manager.add_quotes = AsyncMock()

        expired_options_cursor = MagicMock()
        expired_options_cursor.to_list = AsyncMock(return_value=[expired_position])
        open_positions_cursor = MagicMock()
        open_positions_cursor.to_list = AsyncMock(return_value=[])
        second_expired_options_cursor = MagicMock()
        second_expired_options_cursor.to_list = AsyncMock(return_value=[expired_position])
        second_open_positions_cursor = MagicMock()
        second_open_positions_cursor.to_list = AsyncMock(return_value=[])
        self.tasks.async_mongo.open_positions.find = MagicMock(
            side_effect=[
                expired_options_cursor,
                open_positions_cursor,
                second_expired_options_cursor,
                second_open_positions_cursor,
            ]
        )
        self.tasks.async_mongo.closed_positions.insert_one = AsyncMock()
        delete_result = MagicMock()
        delete_result.deleted_count = 1
        self.tasks.async_mongo.open_positions.delete_one = AsyncMock(return_value=delete_result)

        strategies_cursor = MagicMock()
        strategies_cursor.to_list = AsyncMock(return_value=[])
        self.tasks.async_mongo.strategies.find.return_value = strategies_cursor

        await self.tasks.checkOCOpapertriggers()

        self.tasks.async_mongo.closed_positions.insert_one.assert_awaited_once()
        closed_position = self.tasks.async_mongo.closed_positions.insert_one.call_args.args[0]
        self.assertEqual(closed_position["Pre_Symbol"], "CP    250718C00082500")
        self.assertEqual(closed_position["Exit_Price"], 0)
        self.assertEqual(closed_position["Data_Integrity"], "Expired Paper Option")
        self.tasks.async_mongo.open_positions.delete_one.assert_awaited_once_with({"_id": "expired_position"})
        self.api_trader.quote_manager.unsubscribe.assert_awaited_once_with(["CP    250718C00082500"])
        self.api_trader.quote_manager.add_quotes.assert_not_called()

    async def test_checkOCOpapertriggers_dry_runs_expired_option_cleanup_by_default(self):
        expired_position = {
            "_id": "expired_position",
            "Symbol": "CP",
            "Pre_Symbol": "CP    250718C00082500",
            "Exp_Date": "2025-07-18",
            "Option_Type": "CALL",
            "Strategy": "STRATEGY_1",
            "Account_ID": "paper_account",
            "Asset_Type": "OPTION",
            "Order_Type": "STANDARD",
            "Qty": 1,
            "Entry_Price": 2.85,
            "Entry_Date": dt.datetime(2025, 7, 1, tzinfo=dt.timezone.utc),
            "Side": "BUY_TO_OPEN",
            "Position_Size": 285,
            "Position_Type": "LONG",
            "Account_Position": "Paper",
        }

        self.tasks.user = {"Name": "TestUser"}
        self.tasks.account_id = "paper_account"
        self.tasks.auto_close_expired_paper_options = False
        self.tasks.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={"isOpen": True})
        self.api_trader.quote_manager.subscribed_symbols = {}
        self.api_trader.quote_manager.add_callback = AsyncMock()
        self.api_trader.quote_manager.add_quotes = AsyncMock()

        expired_options_cursor = MagicMock()
        expired_options_cursor.to_list = AsyncMock(return_value=[expired_position])
        open_positions_cursor = MagicMock()
        open_positions_cursor.to_list = AsyncMock(return_value=[])
        second_expired_options_cursor = MagicMock()
        second_expired_options_cursor.to_list = AsyncMock(return_value=[expired_position])
        second_open_positions_cursor = MagicMock()
        second_open_positions_cursor.to_list = AsyncMock(return_value=[])
        self.tasks.async_mongo.open_positions.find = MagicMock(
            side_effect=[
                expired_options_cursor,
                open_positions_cursor,
                second_expired_options_cursor,
                second_open_positions_cursor,
            ]
        )
        self.tasks.async_mongo.closed_positions.insert_one = AsyncMock()
        self.tasks.async_mongo.open_positions.delete_one = AsyncMock()

        strategies_cursor = MagicMock()
        strategies_cursor.to_list = AsyncMock(return_value=[])
        self.tasks.async_mongo.strategies.find.return_value = strategies_cursor

        await self.tasks.checkOCOpapertriggers()

        self.tasks.async_mongo.closed_positions.insert_one.assert_not_called()
        self.tasks.async_mongo.open_positions.delete_one.assert_not_called()
        self.api_trader.quote_manager.unsubscribe.assert_not_called()
        self.tasks.logger.info.assert_any_call(
            "[DRY RUN] Would close expired paper option CP    250718C00082500 at 0 "
            "(position_id=expired_position, account_id=paper_account, strategy=STRATEGY_1). "
            "Set AUTO_CLOSE_EXPIRED_PAPER_OPTIONS=True to enable."
        )

        await self.tasks.checkOCOpapertriggers()

        dry_run_calls = [
            call for call in self.tasks.logger.info.call_args_list
            if "[DRY RUN] Would close expired paper option" in call.args[0]
        ]
        self.assertEqual(len(dry_run_calls), 1)

    async def test_checkOCOpapertriggers_subscribes_active_options(self):
        active_position = {
            "_id": "active_position",
            "Symbol": "CP",
            "Pre_Symbol": "CP    260718C00082500",
            "Exp_Date": "2026-07-18",
            "Option_Type": "CALL",
            "Strategy": "STRATEGY_1",
            "Account_ID": "paper_account",
            "Asset_Type": "OPTION",
            "Order_Type": "STANDARD",
            "Qty": 1,
            "Entry_Price": 2.85,
            "Entry_Date": dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc),
            "Side": "BUY_TO_OPEN",
            "Position_Size": 285,
            "Position_Type": "LONG",
            "Account_Position": "Paper",
        }

        self.tasks.user = {"Name": "TestUser"}
        self.tasks.account_id = "paper_account"
        self.tasks.tdameritrade.getMarketHoursAsync = AsyncMock(return_value={"isOpen": True})
        self.api_trader.quote_manager.subscribed_symbols = {}
        self.api_trader.quote_manager.add_callback = AsyncMock()
        self.api_trader.quote_manager.add_quotes = AsyncMock()

        expired_options_cursor = MagicMock()
        expired_options_cursor.to_list = AsyncMock(return_value=[])
        open_positions_cursor = MagicMock()
        open_positions_cursor.to_list = AsyncMock(return_value=[active_position])
        self.tasks.async_mongo.open_positions.find = MagicMock(
            side_effect=[expired_options_cursor, open_positions_cursor]
        )

        strategies_cursor = MagicMock()
        strategies_cursor.to_list = AsyncMock(return_value=[{"Strategy": "STRATEGY_1"}])
        self.tasks.async_mongo.strategies.find.return_value = strategies_cursor
        self.tasks.api_trader.load_strategy = MagicMock(return_value=self.tasks.strategy_dict["STRATEGY_1"]["ExitStrategy"])

        await self.tasks.checkOCOpapertriggers()

        self.tasks.async_mongo.closed_positions.insert_one.assert_not_called()
        self.api_trader.quote_manager.add_quotes.assert_awaited_once_with([
            {"symbol": "CP    260718C00082500", "asset_type": "OPTION"}
        ])


if __name__ == "__main__":
    unittest.main()
