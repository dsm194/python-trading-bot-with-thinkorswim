from abc import ABC, abstractmethod
from datetime import datetime
from api_trader.strategies.strategy_settings import StrategySettings
    
class ExitStrategy(ABC):
    def __init__(self, strategy_settings: StrategySettings):
        self.strategy_settings = strategy_settings

    @abstractmethod
    def should_exit(self, additional_params):
        """
        Checks whether an exit condition is met.
        """
        # ✅ **Options-Specific Exit Condition**: If near expiration, exit immediately
        if (str(additional_params.get("assetType", "").lower()) == "option" and
            self.is_near_expiration(additional_params.get("expiration_date"))):

            exit_price = float(additional_params.get("last_price") or 0)

            # If expiration is past today, exit at 0
            if additional_params.get("expiration_date") and additional_params["expiration_date"] < datetime.today().date():
                exit_price = 0

            return self.create_exit_order({
                "exit": True,
                "take_profit_price": exit_price,
                "stop_loss_price": exit_price,
                "additional_params": additional_params,
                "reason": "Expiration approaching",
            })

        return {"exit": False}  # Default: Let subclasses determine the exit condition

    def apply_exit_strategy(self, trade_data, always_create_exit=True):
        """
        Uses the exit strategy to create exit orders based on conditions.
        Calls the should_exit method to determine if the exit condition is met.
        Subclasses are responsible for returning the correct type of order (OCO, single, etc.).
        """
        # Prepare additional parameters for the strategy
        additional_params = {
            "last_price": float(trade_data["Last_Price"]),
            "entry_price": float(trade_data["Entry_Price"]),
            "quantity": trade_data["Qty"],
            "symbol": trade_data["Symbol"],
            "pre_symbol": trade_data.get("Pre_Symbol"),
            "side": trade_data["Side"],
            "assetType": trade_data["Asset_Type"],
            "expiration_date": trade_data.get("Exp_Date"),  # Add expiration date if available
        }

        # Check if the exit condition is met
        result = self.should_exit(additional_params)

        if result['exit'] or always_create_exit:
            # Delegate the actual order creation to the subclass
            return self.create_exit_order(result)

        return None  # No exit condition met

    def is_near_expiration(self, expiration_date, exit_days_before_expiration=7):
        """
        Determines if the option is near expiration.
        """
        if not expiration_date:
            return False  # No expiration date available, assume it's not near expiration

        today = datetime.today().date()

        # Ensure expiration_date is a datetime.date object
        if isinstance(expiration_date, datetime):
            expiration_date = expiration_date.date()

        days_until_expiration = (expiration_date - today).days

        return days_until_expiration <= exit_days_before_expiration

    @abstractmethod
    def create_exit_order(self, exit_result):
        """
        Subclasses should implement this to return the correct type of exit order.
        This can be a single order, OCO, trailing stop, or any other type of order.
        """
        raise NotImplementedError("Subclasses should implement this method.")

    def get_instruction_for_side(self, assetType, side):
        from api_trader.order_builder import AssetType
        from schwab.orders.common import EquityInstruction, OptionInstruction

        equity_instructions = {
            "BUY_TO_OPEN": EquityInstruction.SELL,
            "BUY": EquityInstruction.SELL,
            "SELL": EquityInstruction.BUY,
            "SELL_TO_OPEN": EquityInstruction.BUY,
            "BUY_TO_COVER": EquityInstruction.SELL_SHORT,
            "SELL_SHORT": EquityInstruction.BUY_TO_COVER
        }

        option_instructions = {
            "BUY_TO_OPEN": OptionInstruction.SELL_TO_CLOSE,
            "BUY": OptionInstruction.SELL_TO_CLOSE,
            "SELL_TO_OPEN": OptionInstruction.BUY_TO_CLOSE,
            "SELL": OptionInstruction.BUY_TO_OPEN,
            "BUY_TO_CLOSE": OptionInstruction.SELL_TO_OPEN,
            "SELL_TO_CLOSE": OptionInstruction.BUY_TO_OPEN
        }

        if assetType == AssetType.OPTION:
            return option_instructions.get(side)
        else:
            return equity_instructions.get(side)

