from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
import certifi

ca = certifi.where()

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")

MONGO_URI = os.getenv('MONGO_URI')


class AsyncMongoDB:

    def __init__(self, logger):
        self.logger = logger
        self.client = None
        self.db = None
        self.users = None
        self.strategies = None
        self.open_positions = None
        self.closed_positions = None
        self.rejected = None
        self.canceled = None
        self.queue = None
        self.forbidden = None

    async def connect(self):
        """
        Asynchronously connects to MongoDB and initializes collections.
        """
        try:
            self.logger.info("CONNECTING TO MONGO (Async)...", extra={'log': False})

            if MONGO_URI is not None:
                self.client = AsyncIOMotorClient(
                    MONGO_URI, authSource="admin", tlsCAFile=ca
                )

                # Test the connection asynchronously
                await self.client.server_info()

                self.db = self.client["Api_Trader"]

                # Initialize collections
                self.users = self.db["users"]
                self.strategies = self.db["strategies"]
                self.open_positions = self.db["open_positions"]
                self.closed_positions = self.db["closed_positions"]
                self.rejected = self.db["rejected"]
                self.canceled = self.db["canceled"]
                self.queue = self.db["queue"]
                self.forbidden = self.db["forbidden"]

                self.logger.info("CONNECTED TO MONGO (Async)!\n", extra={'log': False})

                return True
            else:
                raise Exception("MISSING MONGO URI")

        except Exception as e:
            self.logger.error(f"FAILED TO CONNECT TO MONGO (Async)! - {e}")
            return False

    async def close(self):
        """
        Closes the MongoDB connection.
        """
        if self.client:
            self.client.close()
            self.logger.info("CLOSED MONGO CONNECTION (Async).", extra={'log': False})
