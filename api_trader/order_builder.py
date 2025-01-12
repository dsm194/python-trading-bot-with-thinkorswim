# imports
import asyncio
from api_trader.strategies import fixed_percentage_exit
from api_trader.strategies import atr_exit
from api_trader.strategies import trailing_stop_exit
from assets.helper_functions import getUTCDatetime
from dotenv import load_dotenv
from pathlib import Path
import os
import json

from schwab.orders.common import first_triggers_second
from schwab.orders.equities import equity_buy_limit, equity_sell_limit
from schwab.orders.options import option_buy_to_open_limit, option_sell_to_close_limit

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")

BUY_PRICE = os.getenv('BUY_PRICE')
SELL_PRICE = os.getenv('SELL_PRICE')

# Access the JSON blob and parse it into a dictionary
default_strategy_settings = json.loads(os.getenv("DEFAULT_STRATEGY_SETTINGS"))

# Define the AssetType enum manually
class AssetType:
    EQUITY = "EQUITY"
    OPTION = "OPTION"

class OrderBuilderWrapper:

    def __init__(self, async_mongo=None):
        self.strategy_cache = {}
        """
        Initialize with an optional mongo for fetching open_positions.
        """
        self.async_mongo = async_mongo

        super().__init__()

    async def get_current_strategy_allocation(self, strategy, user, account_id):
        """
        Fetch the current allocation for a given strategy. If open_positions are not provided,
        use the internal mongo reference to fetch them.
        """
        open_positions_cursor = self.async_mongo.open_positions.find(
            {
                "Trader": user["Name"],
                "Account_ID": account_id,
                "Strategy": strategy
            },
            {"_id": 0, "Qty": 1, "Entry_Price": 1, "Asset_Type": 1}
        )
        queued_positions_cursor = self.async_mongo.queue.find(
            {
                "Trader": user["Name"],
                "Account_ID": account_id,
                "Strategy": strategy,
                "Order_Status": {"$in": ["PENDING_ACTIVATION", "QUEUED"]},
                "Direction": "OPEN POSITION"
            },
            {"_id": 0, "Qty": 1, "Entry_Price": 1, "Asset_Type": 1}
        )

        # Use async for to iterate over the cursors
        async def calculate_allocation(cursor):
            allocation = 0
            async for position in cursor:
                qty = position["Qty"]
                entry_price = position["Entry_Price"]
                asset_type = position.get("Asset_Type", "EQUITY")
                if asset_type.upper() == "OPTION":
                    allocation += qty * entry_price * 100
                else:
                    allocation += qty * entry_price
            return allocation

        # Calculate total allocation
        total_allocation = await asyncio.gather(
            calculate_allocation(open_positions_cursor),
            calculate_allocation(queued_positions_cursor)
        )

        return sum(total_allocation)
    
        
    def load_default_settings(self, strategy_type):
        # Load the default settings for the given strategy type from the config file
        return default_strategy_settings.get(strategy_type, {})


    def load_strategy(self, strategy_object):
        strategy_name = strategy_object.get('ExitStrategy')
        
        # Check if the strategy is already cached
        if strategy_name in self.strategy_cache:
            return self.strategy_cache[strategy_name]
        
        # If not cached, load the strategy
        strategy = self._construct_exit_strategy(strategy_object)
        
        # Store it in the cache
        self.strategy_cache[strategy_name] = strategy
        
        return strategy

    def _construct_exit_strategy(self, strategy_object):
        """
        Constructs and returns the appropriate exit strategy instance based on the
        'ExitStrategy' field in strategy_object. Defaults to 'FixedPercentageExit'
        if the provided type is unrecognized.
        """

        # Default to 'FixedPercentageExit' if 'ExitStrategy' is not provided
        strategy_type = strategy_object.get('ExitStrategy', 'FixedPercentageExit')

        # Extract settings from the strategy_object and ensure it's a dictionary
        settings = strategy_object.get('ExitStrategySettings', {})

        # If settings is a string (as it might be in MongoDB), try to parse it into a dictionary
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except json.JSONDecodeError:
                # If the string cannot be parsed, reset to an empty dictionary
                settings = {}

        recognized_strategies = ('FixedPercentageExit', 'TrailingStopExit')
        # If the strategy_type is not recognized, default to 'FixedPercentageExit'
        if strategy_type not in recognized_strategies:
            strategy_type = 'FixedPercentageExit'

        # Retrieve settings for the chosen strategy_type (potentially updated above)
        strategy_specific_settings = settings.get(strategy_type)
        # If no specific settings found, load default settings
        if strategy_specific_settings is None:
            strategy_specific_settings = self.load_default_settings(strategy_type)

        # Update the settings dictionary
        settings[strategy_type] = strategy_specific_settings

        # Instantiate the correct exit strategy based on the (possibly updated) strategy_type
        if strategy_type == 'FixedPercentageExit':
            return fixed_percentage_exit.FixedPercentageExitStrategy(settings[strategy_type])
        elif strategy_type == 'TrailingStopExit':
            return trailing_stop_exit.TrailingStopExitStrategy(settings[strategy_type])
        # elif strategy_type == 'ATRExit':
        #     return atr_exit.ATRExitStrategy(settings[strategy_type])
        # Add other strategy types as needed


    async def standardOrder(self, trade_data, strategy_object, direction, user, account_id, OCOorder=False):

        order = None
        symbol = trade_data["Symbol"]
        side = trade_data["Side"]
        strategy = trade_data["Strategy"]
        asset_type = AssetType.OPTION if "Pre_Symbol" in trade_data else AssetType.EQUITY

        ##############################################################

        # MONGO OBJECT
        obj = {
            "Symbol": symbol,
            "Qty": None,
            "Position_Size": None,
            "Strategy": strategy,
            "Trader": self.user["Name"],
            "Order_ID": None,
            "Order_Status": None,
            "Side": side,
            "Asset_Type": asset_type,
            "Account_ID": self.account_id,
            "Position_Type": strategy_object["Position_Type"],
            "Order_Type": strategy_object["Order_Type"],
            "Direction": direction
        }

        ##############################################################

        # IF OPTION
        if asset_type == AssetType.OPTION:
            obj.update({
                "Pre_Symbol": trade_data["Pre_Symbol"],
                "Exp_Date": trade_data["Exp_Date"],
                "Option_Type": trade_data["Option_Type"]
            })

        # GET QUOTE FOR SYMBOL
        resp = await self.tdameritrade.getQuoteAsync(symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"])
        
        # if we didn't find the symbol, exit - we can't create the order
        if resp is None:
            return None, None

        price = float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][BUY_PRICE]) if side in ["BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"] else float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][SELL_PRICE])

        # Removed this logic - I don't see any issue w/ OCO order using correct ask/bid prices
        # OCO ORDER NEEDS TO USE ASK PRICE FOR ISSUE WITH THE ORDER BEING TERMINATED UPON BEING PLACED
        # if OCOorder:
        #     price = float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][SELL_PRICE])

        price = round(price, 2) if price >= 1 else round(price, 4)
        priceAsString = str(price)

        # IF OPENING A POSITION
        if direction == "OPEN POSITION":

            if price == 0:
                self.logger.error(f"Price is zero for asset - cannot calculate shares: STRATEGY: {strategy}; ACTIVE: {strategy_object['Active']}; {side}; SYMBOL: {symbol}; PRICE: {price}; QUOTE {resp};")
                raise ValueError("Price cannot be zero.")

            position_size = int(strategy_object["Position_Size"])
            shares = int(position_size / price) if asset_type == AssetType.EQUITY else int((position_size / 100) / price)

            max_position_size = strategy_object.get("MaxPositionSize", None)
            if max_position_size:
                current_allocated = await self.get_current_strategy_allocation(strategy, user=user, account_id=account_id)
                new_allocation = shares * price
                
                if current_allocated + new_allocation > float(max_position_size):
                    self.logger.warning(
                        f"Order stopped: {side} order for {symbol} not placed. "
                        f"Required position size ${current_allocated + new_allocation} exceeds max position size for this strategy. "
                        f"Strategy status: {strategy_object['Active']}, Shares: {shares}, Max position size: ${max_position_size}"
                    )
                    return None, None

            if strategy_object["Active"] and shares > 0:
                if asset_type == AssetType.EQUITY:
                    order = equity_buy_limit(symbol=trade_data["Symbol"], quantity=shares, price=priceAsString)
                else:
                    order = option_buy_to_open_limit(symbol=trade_data["Pre_Symbol"], quantity=shares, price=priceAsString)
                    
                obj.update({
                    "Qty": shares,
                    "Position_Size": position_size,
                    "Entry_Price": price,
                    "Last_Price": price,
                    "Max_Price": price,
                    "Entry_Date": getUTCDatetime(),
                })
            else:
                self.logger.warning(f"{side} ORDER STOPPED: STRATEGY: {strategy}; ACTIVE: {strategy_object['Active']}; SYMBOL: {symbol}; SHARES: {shares}; PRICE: {price}; POSITION_SIZE: {position_size};")
                return None, None

        # IF CLOSING A POSITION
        elif direction == "CLOSE POSITION":

            if asset_type == AssetType.EQUITY:
                order = equity_sell_limit(symbol=trade_data["Symbol"], quantity=trade_data["Qty"], price=priceAsString)
            else:
                order = option_sell_to_close_limit(symbol=trade_data["Pre_Symbol"], quantity=trade_data["Qty"], price=priceAsString)

            obj.update({
                "Entry_Price": trade_data["Entry_Price"],
                "Entry_Date": trade_data["Entry_Date"],
                "Exit_Price": price,
                "Last_Price": price,
                "Exit_Date": getUTCDatetime(),
                "Qty": trade_data["Qty"],
                "Position_Size": trade_data["Position_Size"]
            })
        ############################################################################

        return order, obj

    async def OCOorder(self, trade_data, strategy_object, direction, user, account_id):

        # Load the strategy using the new load_strategy method
        strategy = self.load_strategy(strategy_object)

        # Call standardOrder to get parent_order and obj
        order, obj = await self.standardOrder(trade_data, strategy_object, direction, user, account_id, OCOorder=True)

        # Check if parent_order is None
        if order is not None:
            if direction == "OPEN POSITION":
                exit_order = strategy.apply_exit_strategy(obj)

                order = first_triggers_second(order, exit_order)

                obj["childOrderStrategies"] = [exit_order]
            else:
                obj["childOrderStrategies"] = trade_data["childOrderStrategies"]

        return order, obj
