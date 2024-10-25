# EXCEPTION HANDLER DECORATOR FOR HANDLER EXCEPTIONS AND LOGGING THEM
import asyncio
from assets.helper_functions import modifiedAccountID
import traceback


def exception_handler(func):

    async def async_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return await func(self, *args, **kwargs)
        except Exception as e:
            msg = f"{self.user['Name']} - {modifiedAccountID(self.account_id)} - {traceback.format_exc()}"
            logger.error(msg)

    def sync_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            msg = f"{self.user['Name']} - {modifiedAccountID(self.account_id)} - {traceback.format_exc()}"
            logger.error(msg)

    # Choose which wrapper to use based on whether the function is asynchronous
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

