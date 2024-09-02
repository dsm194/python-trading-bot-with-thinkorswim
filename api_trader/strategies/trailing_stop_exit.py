from api_trader.strategies.exit_strategy import ExitStrategy
from schwab.orders.common import OrderType, OrderStrategyType, Duration, Session, StopPriceLinkType, StopPriceLinkBasis
from schwab.orders.generic import OrderBuilder

class TrailingStopExitStrategy(ExitStrategy):

    def apply_exit_strategy(self, parent_order):
        from api_trader.order_builder import AssetType

        # Extract necessary details from the parent_order
        # entry_price = float(parent_order._price)
        qty = parent_order._orderLegCollection[0]['quantity']
        symbol = parent_order._orderLegCollection[0]['instrument']._symbol
        assetType = parent_order._orderLegCollection[0]['instrument']._assetType
        side = parent_order._orderLegCollection[0]['instruction']
        trailing_stop_percentage = self.strategy_settings.get("trailing_stop_percentage")

        # Determine the instruction (inverse of the side)
        instruction = self.get_instruction_for_side(side=side)

        # Create trailing stop order
        trailing_stop_order_builder = (OrderBuilder()
            .set_order_type(OrderType.TRAILING_STOP)
            .set_session(Session.NORMAL)
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_stop_price_link_type(StopPriceLinkType.PERCENT)
            .set_stop_price_link_basis(StopPriceLinkBasis.MARK)
            .set_stop_price_offset(100 * trailing_stop_percentage))

        if assetType == AssetType.EQUITY:
            trailing_stop_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            trailing_stop_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Return the built trailing stop order
        return trailing_stop_order_builder.build()
