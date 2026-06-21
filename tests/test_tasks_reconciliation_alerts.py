import unittest
from unittest.mock import AsyncMock, MagicMock

from api_trader.tasks import Tasks


class TestTasksReconciliationAlerts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_trader = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "1113"
        self.api_trader.async_mongo.open_positions.update_one = AsyncMock()
        self.tasks = Tasks(self.api_trader)

    async def test_terminal_oco_is_flagged_and_alerted_once(self):
        self.tasks.async_mongo.open_positions.update_one.return_value = MagicMock(
            modified_count=1
        )
        self.tasks._process_child_order = AsyncMock(return_value=False)
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "CANCELED"},
                {"Order_ID": 2, "Order_Status": "CANCELED"},
            ],
        }

        await self.tasks._process_position(position)
        await self.tasks._process_position(position)

        self.tasks.async_mongo.open_positions.update_one.assert_awaited_once()
        update = self.tasks.async_mongo.open_positions.update_one.call_args.args[1]
        self.assertTrue(update["$set"]["Needs_Reconciliation"])
        self.assertEqual(
            update["$set"]["Reconciliation_Reason"],
            "All OCO child orders are terminal without a fill",
        )
        self.tasks.logger.critical.assert_called_once()
        self.api_trader.push.send.assert_called_once()

    async def test_working_child_does_not_trigger_reconciliation(self):
        position = {
            "_id": "position-1",
            "Symbol": "AAPL",
            "Strategy": "STRATEGY_A",
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "CANCELED"},
                {"Order_ID": 2, "Order_Status": "WORKING"},
            ],
        }

        flagged = await self.tasks._flag_terminal_oco_for_reconciliation(position)

        self.assertFalse(flagged)
        self.tasks.async_mongo.open_positions.update_one.assert_not_awaited()
        self.tasks.logger.critical.assert_not_called()
        self.api_trader.push.send.assert_not_called()

    async def test_atomic_update_prevents_duplicate_alert(self):
        self.tasks.async_mongo.open_positions.update_one.return_value = MagicMock(
            modified_count=0
        )
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "REJECTED"},
            ],
        }

        flagged = await self.tasks._flag_terminal_oco_for_reconciliation(position)

        self.assertFalse(flagged)
        self.tasks.logger.critical.assert_not_called()
        self.api_trader.push.send.assert_not_called()
