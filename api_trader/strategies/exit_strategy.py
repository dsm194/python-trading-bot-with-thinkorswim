from abc import ABC, abstractmethod
from schwab.orders.common import EquityInstruction


class StrategySettings:
    def __init__(self, settings_json):
        self.settings = settings_json

    def get(self, key, default=None):
        return self.settings.get(key, default)
    
class ExitStrategy(ABC):
    def __init__(self, strategy_settings: StrategySettings):
        self.strategy_settings = strategy_settings

    @abstractmethod
    def apply_exit_strategy(self, parent_order):
        raise NotImplementedError("Subclasses should implement this method.")

    def get_instruction_for_side(self, side):
        return {
            "BUY_TO_OPEN": EquityInstruction.SELL,
            "BUY": EquityInstruction.SELL,
            "SELL": EquityInstruction.BUY,
            "SELL_TO_OPEN": EquityInstruction.BUY,
            "BUY_TO_COVER": EquityInstruction.SELL_SHORT,
            "SELL_SHORT": EquityInstruction.BUY_TO_COVER
        }[side]
