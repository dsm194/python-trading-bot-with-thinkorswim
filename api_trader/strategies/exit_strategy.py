from abc import ABC, abstractmethod
from api_trader.strategies.strategy_settings import StrategySettings
    
class ExitStrategy(ABC):
    def __init__(self, strategy_settings: StrategySettings):
        self.strategy_settings = strategy_settings

    @abstractmethod
    def should_exit(self, additional_params):
        """
        Checks whether an exit condition is met.
        """
        pass

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
            "side": trade_data["Side"],
            "assetType": trade_data["Asset_Type"],
        }

        # Check if the exit condition is met
        result = self.should_exit(additional_params)

        if result['exit'] or always_create_exit:
            # Delegate the actual order creation to the subclass
            return self.create_exit_order(result)

        return None  # No exit condition met

    @abstractmethod
    def create_exit_order(self, exit_result):
        """
        Subclasses should implement this to return the correct type of exit order.
        This can be a single order, OCO, trailing stop, or any other type of order.
        """
        raise NotImplementedError("Subclasses should implement this method.")

    def get_instruction_for_side(self, side):
        from schwab.orders.common import EquityInstruction
        return {
            "BUY_TO_OPEN": EquityInstruction.SELL,
            "BUY": EquityInstruction.SELL,
            "SELL": EquityInstruction.BUY,
            "SELL_TO_OPEN": EquityInstruction.BUY,
            "BUY_TO_COVER": EquityInstruction.SELL_SHORT,
            "SELL_SHORT": EquityInstruction.BUY_TO_COVER
        }[side]

