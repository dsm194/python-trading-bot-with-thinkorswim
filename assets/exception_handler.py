# EXCEPTION HANDLER DECORATOR FOR HANDLER EXCEPTIONS AND LOGGING THEM
import asyncio
from assets.helper_functions import modifiedAccountID
import traceback


def exception_handler(func):
    async def async_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return await func(self, *args, **kwargs)
        except Exception:
            msg = f"{self.user['Name']} - {modifiedAccountID(self.account_id)} - {traceback.format_exc()}"
            logger.error(msg)
            raise

    def sync_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return func(self, *args, **kwargs)
        except Exception:
            msg = f"{self.user['Name']} - {modifiedAccountID(self.account_id)} - {traceback.format_exc()}"
            logger.error(msg)
            raise

    # Use the appropriate wrapper based on whether the function is async or sync
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper