import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from collections import defaultdict
from api_trader.position_updater import PositionUpdater


class TestPositionUpdater(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock MongoDB collection and logger
        self.open_positions_mock = MagicMock()
        self.logger_mock = MagicMock()

        # Initialize PositionUpdater with mock dependencies
        self.position_updater = PositionUpdater(
            open_positions=self.open_positions_mock,
            logger=self.logger_mock,
            batch_interval=0.1  # Set a short interval for testing
        )

    async def test_queue_max_price_update(self):
        """Test that max price updates are queued correctly."""
        await self.position_updater.queue_max_price_update("position_1", 150.0)
        await self.position_updater.queue_max_price_update("position_2", 250.0)

        # Verify that updates are stored correctly in the price_updates dictionary
        self.assertIn("position_1", self.position_updater.price_updates)
        self.assertEqual(self.position_updater.price_updates["position_1"]["max_price"], 150.0)
        self.assertIn("position_2", self.position_updater.price_updates)
        self.assertEqual(self.position_updater.price_updates["position_2"]["max_price"], 250.0)

    async def test_flush_updates(self):
        """Test that queued updates are flushed to MongoDB correctly."""
        
        # self.open_positions_mock.bulk_write.return_value = MagicMock(modified_count=2)

        # Queue some updates
        await self.position_updater.queue_max_price_update("position_1", 150.0)
        await self.position_updater.queue_max_price_update("position_2", 250.0)

        # Call flush_updates and verify MongoDB bulk_write behavior
        await self.position_updater.flush_updates()

        # Ensure bulk_write was called with the correct operations
        self.open_positions_mock.bulk_write.assert_called_once()
        bulk_operations = self.open_positions_mock.bulk_write.call_args[0][0]

        # Verify the structure of each operation in bulk update
        self.assertEqual(len(bulk_operations), 2)
        self.assertEqual(bulk_operations[0]._filter, {"_id": "position_1"})
        self.assertEqual(bulk_operations[0]._doc["$set"]["max_price"], 150.0)
        self.assertEqual(bulk_operations[1]._filter, {"_id": "position_2"})
        self.assertEqual(bulk_operations[1]._doc["$set"]["max_price"], 250.0)

        # Verify price_updates dictionary is cleared after flush
        self.assertEqual(len(self.position_updater.price_updates), 0)

    async def test_schedule_batch_update(self):
        """Test that schedule_batch_update flushes updates at regular intervals."""
        # Mock flush_updates to observe its calls
        with patch.object(self.position_updater, 'flush_updates', new_callable=AsyncMock) as mock_flush_updates:
            # Start the schedule_batch_update loop in the background
            async def stop_after_delay():
                await asyncio.sleep(0.3)  # Allow a few intervals to pass
                await self.position_updater.stop()  # Stop the loop

            stop_task = asyncio.create_task(stop_after_delay())
            await self.position_updater.schedule_batch_update()
            await stop_task

            # Check that flush_updates was called multiple times
            self.assertGreaterEqual(mock_flush_updates.call_count, 2)

    async def test_stop_stops_schedule_batch_update(self):
        """Test that stop() method stops the batch update loop."""
        with patch.object(self.position_updater, 'flush_updates', new_callable=AsyncMock) as mock_flush_updates:
            # Start and immediately stop the schedule_batch_update loop
            stop_task = asyncio.create_task(self.position_updater.schedule_batch_update())
            await self.position_updater.stop()  # Signal stop
            await stop_task  # Wait for loop to end

            # Ensure flush_updates is not called after stop
            self.assertTrue(self.position_updater.stop_event.is_set())

    async def asyncTearDown(self):
        await self.position_updater.stop()  # Ensure cleanup

# Run the tests
if __name__ == "__main__":
    unittest.main()
