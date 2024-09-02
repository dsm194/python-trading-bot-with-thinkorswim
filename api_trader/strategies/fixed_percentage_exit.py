from api_trader.strategies.exit_strategy import ExitStrategy
from schwab.orders.common import OrderType, OrderStrategyType, Duration, Session, one_cancels_other
from schwab.orders.generic import OrderBuilder


class FixedPercentageExitStrategy(ExitStrategy):
    
    def apply_exit_strategy(self, parent_order):
        from api_trader.order_builder import AssetType
        
        # Extract necessary details from the parent_order
        entry_price = float(parent_order._price)
        qty = parent_order._orderLegCollection[0]['quantity']
        symbol = parent_order._orderLegCollection[0]['instrument']._symbol
        assetType = parent_order._orderLegCollection[0]['instrument']._assetType
        side = parent_order._orderLegCollection[0]['instruction']
        take_profit_percentage = self.strategy_settings.get("take_profit_percentage")   #TODO: define defaults at this point?
        stop_loss_percentage = self.strategy_settings.get("stop_loss_percentage")

        # Calculate take-profit and stop-loss prices
        take_profit_price = entry_price * (1 + take_profit_percentage)
        stop_loss_price = entry_price * (1 - stop_loss_percentage)

        # Round prices for order placement
        take_profit_price = round(take_profit_price, 2) if take_profit_price >= 1 else round(take_profit_price, 4)
        stop_loss_price = round(stop_loss_price, 2) if stop_loss_price >= 1 else round(stop_loss_price, 4)

        # Determine the instruction (inverse of the side)
        instruction = self.get_instruction_for_side(side=side)

        # Create take profit order
        take_profit_order_builder = (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_session(Session.NORMAL)
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_order_strategy_type(OrderStrategyType.SINGLE))
        take_profit_order_builder.set_price(str(take_profit_price))

        if assetType == AssetType.EQUITY:
            take_profit_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            take_profit_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Create stop loss order
        stop_loss_order_builder = (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_session(Session.NORMAL)
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_order_strategy_type(OrderStrategyType.SINGLE))
        stop_loss_order_builder.set_stop_price(str(stop_loss_price))

        if assetType == AssetType.EQUITY:
            stop_loss_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            stop_loss_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Return the OCO order
        return one_cancels_other(take_profit_order_builder.build(), stop_loss_order_builder.build()).build()


