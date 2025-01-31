import asyncio
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import UpdateOne


class PositionUpdater:
    def __init__(self, open_positions: AsyncIOMotorCollection, logger, batch_interval=5, max_workers=4, max_batch_size=None):
        self.open_positions = open_positions  # Async MongoDB collection
        self.logger = logger
        self.batch_interval = batch_interval  # Time in seconds for batch updates
        self.update_queue = asyncio.Queue()  # Queue for updates
        self.update_cache = {}  # Cache to deduplicate updates
        self.lock = asyncio.Lock()  # Lock for thread-safe cache operations
        self.stop_event = asyncio.Event()  # Control loop stopping
        self.max_workers = max_workers  # Number of worker tasks
        self.max_batch_size = max_batch_size  # Optional max batch size
        self.worker_tasks = []  # Store asyncio.Task objects for workers

    async def queue_max_price_update(self, position_id, max_price):
        """Queues an update to max_price for a position."""
        async with self.lock:
            if position_id in self.update_cache:
                self.update_cache[position_id]["Max_Price"] = max_price
                return  # No need to re-add if already queued
            else:
                update = {"Max_Price": max_price}
                self.update_cache[position_id] = update

        # Put outside lock to prevent blocking other tasks
        await self.update_queue.put(position_id)

    async def worker(self):
        """Worker task to process updates from the queue in batches."""
        try:
            while not self.stop_event.is_set():
                try:
                    await asyncio.sleep(self.batch_interval)  # Process updates at regular intervals

                    updates = []
                    async with self.lock:
                        while not self.update_queue.empty() and (
                            self.max_batch_size is None or len(updates) < self.max_batch_size
                        ):
                            position_id = await self.update_queue.get()
                            if position_id in self.update_cache:
                                update = self.update_cache.pop(position_id)
                                updates.append(UpdateOne({"_id": position_id}, {"$set": update}))
                            self.update_queue.task_done()

                    if updates:
                        result = await self.open_positions.bulk_write(updates)
                        self.logger.info(f"Batch update complete: {result.modified_count} documents modified.")

                except asyncio.CancelledError:
                    self.logger.info("Worker task was cancelled.")
                    break
                except Exception as e:
                    self.logger.error(f"Error during batch update: {str(e)}")
        finally:
            self.logger.info("Worker task has exited.")

    async def start_workers(self):
        """Starts multiple worker tasks."""
        self.worker_tasks = [asyncio.create_task(self.worker()) for _ in range(self.max_workers)]

    async def stop(self):
        """Stops all worker tasks and clears the queue."""
        self.stop_event.set()
        await self.update_queue.join()  # Ensure all pending tasks are processed
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

        # Clear worker tasks to allow clean restart if needed
        self.worker_tasks.clear()

    async def monitor_queue(self):
        """Monitor the queue size periodically."""
        while not self.stop_event.is_set():
            self.logger.debug(f"Update queue size: {self.update_queue.qsize()}, Cache size: {len(self.update_cache)}")
            await asyncio.sleep(self.batch_interval)
