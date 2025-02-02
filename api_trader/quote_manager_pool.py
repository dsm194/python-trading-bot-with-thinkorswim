import asyncio
from api_trader.quote_manager import QuoteManager


class QuoteManagerPool:
    def __init__(self, loop):
        self.managers = {}
        self.loop = loop

    def get_or_create_manager(self, tdameritrade, logger):
        asyncio.set_event_loop(self.loop)
        # Extract the underlying account ID
        account_id = QuoteManager._extract_underlying_account_id(tdameritrade.async_client.token_metadata.token, logger)

        if not account_id:
            raise ValueError("Failed to extract underlying account ID. Cannot create or retrieve QuoteManager.")

        # Check if a manager for this account ID already exists
        if account_id not in self.managers:
            self.managers[account_id] = QuoteManager(tdameritrade, logger)
        
        return self.managers[account_id]

    async def shutdown(self):
        for manager in self.managers.values():
            await manager.shutdown()  # Ensure all QuoteManager instances are cleanly shut down