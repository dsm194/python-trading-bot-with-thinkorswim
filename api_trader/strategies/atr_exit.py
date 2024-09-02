from api_trader.strategies.exit_strategy import ExitStrategy

class ATRExitStrategy(ExitStrategy):
    def __init__(self, atr_value: float, atr_multiplier: float):
        self.atr_value = atr_value
        self.atr_multiplier = atr_multiplier

    def calculate_take_profit(self, entry_price: float) -> float:
        """Calculate take-profit price based on ATR."""
        return round(entry_price + (self.atr_value * self.atr_multiplier), 2 if entry_price >= 1 else 4)

    def calculate_stop_loss(self, entry_price: float) -> float:
        """Calculate stop-loss price based on ATR."""
        return round(entry_price - (self.atr_value * self.atr_multiplier), 2 if entry_price >= 1 else 4)
