import asyncio
import pymongo

class PositionUpdater:
    def __init__(self, open_positions, logger, batch_interval=5, max_workers=4):
        self.open_positions = open_positions  # MongoDB collection
        self.logger = logger
        self.batch_interval = batch_interval  # Time in seconds for batch updates
        self.update_queue = asyncio.Queue()  # Queue for updates
        self.update_cache = {}  # Cache to deduplicate updates
        self.lock = asyncio.Lock()  # Lock for thread-safe cache operations
        self.stop_event = asyncio.Event()  # Control loop stopping
        self.max_workers = max_workers  # Number of worker tasks
        self.worker_tasks = []  # Store asyncio.Task objects for workers

    async def queue_max_price_update(self, position_id, max_price):
        """Queues an update to max_price for a position."""
        async with self.lock:
            if position_id in self.update_cache:
                # Update the existing cache entry
                self.update_cache[position_id]["Max_Price"] = max_price
            else:
                # Add to cache and enqueue the update
                update = {"Max_Price": max_price}
                self.update_cache[position_id] = update
                await self.update_queue.put(position_id)

    async def worker(self):
        """Worker task to process updates from the queue in batches."""
        try:
            while not self.stop_event.is_set():
                try:
                    # Wait in small intervals to check stop_event
                    for _ in range(int(self.batch_interval * 10)):  # 100ms increments
                        if self.stop_event.is_set():
                            raise asyncio.CancelledError
                        await asyncio.sleep(0.1)

                    updates = []
                    async with self.lock:
                        while not self.update_queue.empty():
                            position_id = await self.update_queue.get()
                            if position_id in self.update_cache:
                                update = self.update_cache.pop(position_id)
                                updates.append(
                                    pymongo.UpdateOne({"_id": position_id}, {"$set": update})
                                )
                            self.update_queue.task_done()

                    if updates:
                        # Apply the batch update to MongoDB
                        result = self.open_positions.bulk_write(updates)
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

    async def monitor_queue(self):
        """Monitor the queue size periodically."""
        while not self.stop_event.is_set():
            self.logger.info(f"Update queue size: {self.update_queue.qsize()}")
            await asyncio.sleep(self.batch_interval)