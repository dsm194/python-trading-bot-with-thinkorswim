import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from api_trader.position_updater import PositionUpdater


class TestPositionUpdater(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock MongoDB collection and logger
        self.open_positions_mock = AsyncMock()
        self.logger_mock = MagicMock()

        # Initialize PositionUpdater with mock dependencies
        self.position_updater = PositionUpdater(
            open_positions=self.open_positions_mock,
            logger=self.logger_mock,
            batch_interval=0.1,  # Set a short interval for testing
            max_workers=2
        )

    async def test_queue_max_price_update(self):
        """Test max price updates with worker processing."""
        await self.position_updater.start_workers()  # Start workers

        """Test that max price updates are queued and cached correctly."""
        await self.position_updater.queue_max_price_update("position_1", 150.0)
        await self.position_updater.queue_max_price_update("position_2", 250.0)

        # Verify cache and queue state
        self.assertIn("position_1", self.position_updater.update_cache)
        self.assertEqual(self.position_updater.update_cache["position_1"]["Max_Price"], 150.0)
        self.assertIn("position_2", self.position_updater.update_cache)
        self.assertEqual(self.position_updater.update_cache["position_2"]["Max_Price"], 250.0)
        self.assertEqual(self.position_updater.update_queue.qsize(), 2)

    async def test_worker_processes_updates(self):
        """Test that the worker processes updates from the queue."""
        await self.position_updater.queue_max_price_update("position_1", 150.0)
        await self.position_updater.queue_max_price_update("position_2", 250.0)

        # Mock bulk_write and start a single worker
        with patch.object(self.open_positions_mock, 'bulk_write', return_value=AsyncMock(modified_count=2)):
            worker_task = asyncio.create_task(self.position_updater.worker())

            # Allow the worker to process the queue
            await asyncio.sleep(0.3)
            await self.position_updater.stop()
            await worker_task

            # Verify that bulk_write was called correctly
            self.open_positions_mock.bulk_write.assert_called_once()
            bulk_operations = self.open_positions_mock.bulk_write.call_args[0][0]
            self.assertEqual(len(bulk_operations), 2)

    async def test_start_and_stop_workers(self):
        """Test that multiple workers can start and stop cleanly."""
        await self.position_updater.start_workers()

        # Verify workers are running
        self.assertEqual(len(self.position_updater.worker_tasks), 2)

        # Stop the workers
        await self.position_updater.stop()

        # Verify workers have stopped
        for task in self.position_updater.worker_tasks:
            self.assertTrue(task.done())

    async def test_monitor_queue(self):
        """Test the queue monitoring logs the queue size periodically."""
        with patch.object(self.logger_mock, 'info') as mock_log:
            await self.position_updater.start_workers()

            monitor_task = asyncio.create_task(self.position_updater.monitor_queue())

            # Add some updates and allow monitoring to run
            await self.position_updater.queue_max_price_update("position_1", 150.0)
            await asyncio.sleep(0.3)
            await self.position_updater.stop()
            await monitor_task

            # Verify logger was called with queue size info
            mock_log.assert_any_call("Update queue size: 1, Cache size: 1")

    async def test_worker_handles_exception(self):
        """Test that the worker logs errors without crashing."""
        await self.position_updater.queue_max_price_update("position_1", 150.0)

        # Simulate an error in bulk_write
        with patch.object(self.open_positions_mock, 'bulk_write', side_effect=Exception("Test error")):
            worker_task = asyncio.create_task(self.position_updater.worker())

            # Allow the worker to process and encounter the error
            await asyncio.sleep(0.3)
            await self.position_updater.stop()
            await worker_task

            # Verify error was logged
            self.logger_mock.error.assert_called_with("Error during batch update: Test error")

    async def asyncTearDown(self):
        await self.position_updater.stop()  # Ensure cleanup


# Run the tests
if __name__ == "__main__":
    unittest.main()
