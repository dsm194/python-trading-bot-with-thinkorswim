import unittest
from unittest.mock import AsyncMock, MagicMock

from api_trader.tasks import Tasks


class TestTasksReconciliationAlerts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_trader = MagicMock()
        self.api_trader.user = {"Name": "TestUser"}
        self.api_trader.account_id = "1113"
        self.api_trader.async_mongo.open_positions.update_one = AsyncMock()
        open_positions_cursor = MagicMock()
        open_positions_cursor.to_list = AsyncMock(return_value=[])
        self.api_trader.async_mongo.open_positions.find = MagicMock(
            return_value=open_positions_cursor
        )
        self.api_trader.tdameritrade.getOrdersAsync = AsyncMock(return_value=[])
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

    async def test_expired_oco_is_flagged_for_reconciliation(self):
        self.tasks.async_mongo.open_positions.update_one.return_value = MagicMock(
            modified_count=1
        )
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "EXPIRED"},
                {"Order_ID": 2, "Order_Status": "EXPIRED"},
            ],
        }

        flagged = await self.tasks._flag_terminal_oco_for_reconciliation(position)

        self.assertTrue(flagged)
        update = self.tasks.async_mongo.open_positions.update_one.call_args.args[1]
        self.assertTrue(update["$set"]["Needs_Reconciliation"])
        self.tasks.logger.critical.assert_called_once()
        self.api_trader.push.send.assert_called_once()

    async def test_replacement_working_oco_is_adopted_before_alert(self):
        self.tasks.tdameritrade.getOrdersAsync = AsyncMock(return_value=[
            {
                "Order_ID": 999,
                "status": "WORKING",
                "orderStrategyType": "OCO",
                "childOrderStrategies": [
                    {
                        "Order_ID": 1001,
                        "status": "WORKING",
                        "price": 120,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                    {
                        "Order_ID": 1002,
                        "status": "WORKING",
                        "stopPrice": 90,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                ],
            }
        ])
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "Asset_Type": "EQUITY",
            "Qty": 10,
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "EXPIRED"},
                {"Order_ID": 2, "Order_Status": "EXPIRED"},
            ],
        }

        adopted = await self.tasks._adopt_replacement_oco_if_available(position)

        self.assertTrue(adopted)
        self.tasks.async_mongo.open_positions.update_one.assert_awaited_once()
        update = self.tasks.async_mongo.open_positions.update_one.call_args.args[1]
        self.assertEqual(update["$set"]["Replacement_OCO_Order_ID"], 999)
        self.assertEqual(
            update["$set"]["childOrderStrategies"][0]["Order_ID"],
            1001,
        )
        self.assertFalse(update["$set"]["Needs_Reconciliation"])
        self.tasks.logger.critical.assert_not_called()
        self.api_trader.push.send.assert_not_called()

    async def test_adoption_does_not_queue_stale_child_status_bulk_update(self):
        self.tasks.tdameritrade.getSpecificOrderAsync = AsyncMock(
            return_value={"status": "EXPIRED"}
        )
        self.tasks.tdameritrade.getOrdersAsync = AsyncMock(return_value=[
            {
                "Order_ID": 999,
                "status": "WORKING",
                "orderStrategyType": "OCO",
                "childOrderStrategies": [
                    {
                        "Order_ID": 1001,
                        "status": "WORKING",
                        "price": 120,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                    {
                        "Order_ID": 1002,
                        "status": "WORKING",
                        "stopPrice": 90,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                ],
            }
        ])
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "Account_ID": "1113",
            "Asset_Type": "EQUITY",
            "Order_Type": "OCO",
            "Qty": 10,
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "WORKING"},
                {"Order_ID": 2, "Order_Status": "WORKING"},
            ],
        }

        await self.tasks._process_position(position)

        self.tasks.async_mongo.open_positions.update_one.assert_awaited_once()
        self.assertTrue(self.tasks.bulk_updates_queue.empty())
        self.assertEqual(position["Replacement_OCO_Order_ID"], 999)

    async def test_replacement_oco_is_not_adopted_when_multiple_positions_match(self):
        ambiguous_cursor = MagicMock()
        ambiguous_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": "position-2",
                "Symbol": "SEMR",
                "Strategy": "STRATEGY_B",
                "Asset_Type": "EQUITY",
                "Qty": 10,
                "childOrderStrategies": [
                    {"Order_ID": 3, "Order_Status": "EXPIRED"},
                    {"Order_ID": 4, "Order_Status": "EXPIRED"},
                ],
            }
        ])
        self.tasks.async_mongo.open_positions.find = MagicMock(
            return_value=ambiguous_cursor
        )
        self.tasks.tdameritrade.getOrdersAsync = AsyncMock(return_value=[
            {
                "Order_ID": 999,
                "status": "WORKING",
                "orderStrategyType": "OCO",
                "childOrderStrategies": [
                    {
                        "Order_ID": 1001,
                        "status": "WORKING",
                        "price": 120,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                    {
                        "Order_ID": 1002,
                        "status": "WORKING",
                        "stopPrice": 90,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                ],
            }
        ])
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "Asset_Type": "EQUITY",
            "Qty": 10,
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "EXPIRED"},
                {"Order_ID": 2, "Order_Status": "EXPIRED"},
            ],
        }

        adopted = await self.tasks._adopt_replacement_oco_if_available(position)

        self.assertFalse(adopted)
        self.tasks.async_mongo.open_positions.update_one.assert_not_awaited()
        self.tasks.logger.warning.assert_called()

    async def test_replacement_oco_can_disambiguate_by_exit_prices(self):
        same_symbol_cursor = MagicMock()
        same_symbol_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": "position-2",
                "Symbol": "SEMR",
                "Strategy": "STRATEGY_B",
                "Asset_Type": "EQUITY",
                "Qty": 10,
                "childOrderStrategies": [
                    {"Order_ID": 3, "Order_Status": "EXPIRED", "Exit_Price": 130},
                    {"Order_ID": 4, "Order_Status": "EXPIRED", "Exit_Price": 80},
                ],
            }
        ])
        self.tasks.async_mongo.open_positions.find = MagicMock(
            return_value=same_symbol_cursor
        )
        self.tasks.tdameritrade.getOrdersAsync = AsyncMock(return_value=[
            {
                "Order_ID": 999,
                "status": "WORKING",
                "orderStrategyType": "OCO",
                "childOrderStrategies": [
                    {
                        "Order_ID": 1001,
                        "status": "WORKING",
                        "price": 120,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                    {
                        "Order_ID": 1002,
                        "status": "WORKING",
                        "stopPrice": 90,
                        "orderLegCollection": [
                            {"instruction": "SELL", "symbol": "SEMR", "quantity": 10}
                        ],
                    },
                ],
            }
        ])
        position = {
            "_id": "position-1",
            "Symbol": "SEMR",
            "Strategy": "STRATEGY_A",
            "Asset_Type": "EQUITY",
            "Qty": 10,
            "childOrderStrategies": [
                {"Order_ID": 1, "Order_Status": "EXPIRED", "Exit_Price": 120},
                {"Order_ID": 2, "Order_Status": "EXPIRED", "Exit_Price": 90},
            ],
        }

        adopted = await self.tasks._adopt_replacement_oco_if_available(position)

        self.assertTrue(adopted)
        self.tasks.async_mongo.open_positions.update_one.assert_awaited_once()
