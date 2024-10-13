from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pathlib import Path
import os

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")

TIMEZONE = os.getenv('TIMEZONE')


def getDatetime():
    """ function obtains the datetime based on timezone using the pytz library.

    Returns:
        [Datetime Object]: [formated datetime object]
    """

    dt = datetime.now(tz=timezone.utc).replace(microsecond=0)

    dt = dt.astimezone(ZoneInfo(TIMEZONE))

    return datetime.strptime(dt.strftime(
        "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")


def getUTCDatetime():
    """ function obtains the utc datetime. will use this for all timestamps with the bot. GET FEEDBACK FROM DISCORD GROUP ON THIS BEFORE PUBLISH.

    Returns:
        [Datetime Object]: [formated datetime object]
    """

    dt = datetime.now(tz=timezone.utc).replace(microsecond=0)

    return dt.isoformat()

def convertStringToDatetime(date_string, timezone = timezone.utc):
    return datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone)


def selectSleep():
    """
    PRE-MARKET(0400 - 0930 ET): 1 SECOND
    MARKET OPEN(0930 - 1600 ET): 1 SECOND
    AFTER MARKET(1600 - 2000 ET): 1 SECOND

    WEEKENDS: 60 SECONDS
    WEEKDAYS(2000 - 0400 ET): 60 SECONDS

    EVERYTHING WILL BE BASED OFF CENTRAL TIME

    OBJECTIVE IS TO FREE UP UNNECESSARY SERVER USAGE
    """

    dt = getDatetime()

    day = dt.strftime("%a")

    tm = dt.strftime("%H:%M:%S")

    weekends = ["Sat", "Sun"]

    # IF CURRENT TIME GREATER THAN 8PM AND LESS THAN 4AM, OR DAY IS WEEKEND, THEN RETURN 60 SECONDS
    if tm > "20:00" or tm < "04:00" or day in weekends:

        return 60

    # ELSE RETURN 1 SECOND
    return 1


def modifiedAccountID(account_id):

    return '*' * (len(str(account_id)) - 4) + str(account_id)[-4:]

def assign_order_ids(order_strategy):
    import random

    """Recursively assign order IDs to child orders, updating 'Order_ID'."""
    if isinstance(order_strategy, dict):
        # Add or update 'Order_ID' if it's not present or is None
        if "Order_ID" not in order_strategy or order_strategy["Order_ID"] is None:
            order_strategy["Order_ID"] = -random.randint(100_000_000, 999_999_999)
        
        # Recursively assign order IDs to any childOrderStrategies
        if "childOrderStrategies" in order_strategy:
            for child in order_strategy["childOrderStrategies"]:
                assign_order_ids(child)
