# EXCEPTION HANDLER DECORATOR FOR HANDLER EXCEPTIONS AND LOGGING THEM
import asyncio
import traceback


def exception_handler(func):
    async def async_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return await func(self, *args, **kwargs)
        except asyncio.CancelledError:
            # Specific handling for task cancellation
            logger.warning(f"Task was cancelled during {func.__name__}")
            raise  # Re-raise to propagate the cancellation
        except Exception:
            msg = f"{func.__name__} - {traceback.format_exc()}"
            logger.error(msg)
            raise

    def sync_wrapper(self, *args, **kwargs):
        logger = self.logger
        try:
            return func(self, *args, **kwargs)
        except Exception:
            msg = f"{func.__name__} - {traceback.format_exc()}"
            logger.error(msg)
            raise

    # Use the appropriate wrapper based on whether the function is async or sync
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper