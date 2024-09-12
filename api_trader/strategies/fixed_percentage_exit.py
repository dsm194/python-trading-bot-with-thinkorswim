from api_trader.strategies.exit_strategy import ExitStrategy
from schwab.orders.common import OrderType, OrderStrategyType, Duration, Session, one_cancels_other
from schwab.orders.generic import OrderBuilder

class FixedPercentageExitStrategy(ExitStrategy):

    def __init__(self, strategy_settings, order_builder_cls=OrderBuilder):
        super().__init__(strategy_settings)
        self.order_builder_cls = order_builder_cls

    def should_exit(self, additional_params):
        
        last_price = additional_params['last_price']
        entry_price = additional_params['entry_price']
        take_profit_percentage = self.strategy_settings.get("take_profit_percentage")
        stop_loss_percentage = self.strategy_settings.get("stop_loss_percentage")

        take_profit_price = entry_price * (1 + take_profit_percentage)
        take_profit_price = round(take_profit_price, 2) if take_profit_price >= 1 else round(take_profit_price, 4)
        stop_loss_price = entry_price * (1 - stop_loss_percentage)
        stop_loss_price = round(stop_loss_price, 2) if stop_loss_price >= 1 else round(stop_loss_price, 4)

        return {
            "exit": last_price <= stop_loss_price or last_price >= take_profit_price,
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "additional_params": additional_params,
            "reason": "OCO"
        }

    def create_exit_order(self, exit_result):
        from api_trader.order_builder import AssetType

        """
        Builds an OCO (One-Cancels-Other) order with both take-profit and stop-loss.
        """

        take_profit_price = exit_result['take_profit_price']
        stop_loss_price = exit_result['stop_loss_price']
        additional_params = exit_result['additional_params']
        symbol = additional_params['symbol']
        qty = additional_params['quantity']
        side = additional_params['side']
        assetType = additional_params['assetType']

        # Round prices for order placement
        take_profit_price = round(take_profit_price, 2) if take_profit_price >= 1 else round(take_profit_price, 4)
        stop_loss_price = round(stop_loss_price, 2) if stop_loss_price >= 1 else round(stop_loss_price, 4)

        # Determine the instruction (inverse of the side)
        instruction = self.get_instruction_for_side(side=side)

        # Create take profit order
        take_profit_order_builder = self.order_builder_cls()
        take_profit_order_builder.set_order_type(OrderType.LIMIT)
        take_profit_order_builder.set_session(Session.NORMAL)
        take_profit_order_builder.set_duration(Duration.GOOD_TILL_CANCEL)
        take_profit_order_builder.set_order_strategy_type(OrderStrategyType.SINGLE)
        take_profit_order_builder.set_price(str(take_profit_price))

        if assetType == AssetType.EQUITY:
            take_profit_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            take_profit_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Create stop loss order
        stop_loss_order_builder = self.order_builder_cls()
        stop_loss_order_builder.set_order_type(OrderType.STOP)
        stop_loss_order_builder.set_session(Session.NORMAL)
        stop_loss_order_builder.set_duration(Duration.GOOD_TILL_CANCEL)
        stop_loss_order_builder.set_order_strategy_type(OrderStrategyType.SINGLE)
        stop_loss_order_builder.set_stop_price(str(stop_loss_price))

        if assetType == AssetType.EQUITY:
            stop_loss_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            stop_loss_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Return the OCO order
        return one_cancels_other(take_profit_order_builder.build(), stop_loss_order_builder.build()).build()
    