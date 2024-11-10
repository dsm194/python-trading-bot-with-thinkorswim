import asyncio
from collections import defaultdict

import pymongo


class PositionUpdater:
    def __init__(self, open_positions, logger, batch_interval=5):
        self.open_positions = open_positions  # MongoDB collection
        self.logger = logger
        self.batch_interval = batch_interval  # Time in seconds for batch updates
        self.price_updates = defaultdict(dict)  # {position_id: updated_max_price}
        self.lock = asyncio.Lock()  # Ensure thread-safe updates
        self.stop_event = asyncio.Event()  # Control loop stopping

    async def schedule_batch_update(self):
        """Runs the batch update task at regular intervals."""
        while not self.stop_event.is_set():
            await asyncio.sleep(self.batch_interval)
            await self.flush_updates()

    async def stop(self):
        """Sets the stop event to end the loop gracefully."""
        self.stop_event.set()

    async def queue_max_price_update(self, position_id, max_price):
        """Queues an update to max_price for a position."""
        async with self.lock:
            self.price_updates[position_id] = {"Max_Price": max_price}

    async def flush_updates(self):
        """Writes all queued updates to MongoDB in a batch."""
        async with self.lock:
            if not self.price_updates:
                return
            
            # Prepare bulk update operations
            operations = [
                pymongo.UpdateOne({"_id": position_id}, {"$set": update})
                for position_id, update in self.price_updates.items()
            ]
            # Clear the local cache after preparing operations
            self.price_updates.clear()

            # Execute batch update
            if operations:
                result = self.open_positions.bulk_write(operations)
                self.logger.info(operations)
                self.logger.info(f"{result.modified_count} positions updated in MongoDB.")