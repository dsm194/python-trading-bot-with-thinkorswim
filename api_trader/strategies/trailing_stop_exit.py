from api_trader.strategies.exit_strategy import ExitStrategy
from schwab.orders.common import OrderType, OrderStrategyType, Duration, Session, StopPriceLinkType, StopPriceLinkBasis
from schwab.orders.generic import OrderBuilder

class TrailingStopExitStrategy(ExitStrategy):

    def __init__(self, strategy_settings, order_builder_cls=OrderBuilder):
        super().__init__(strategy_settings)
        self.order_builder_cls = order_builder_cls

    def should_exit(self, additional_params):

        last_price = additional_params['last_price']
        entry_price = additional_params['entry_price']
        # Track the highest price observed so far (can be stored in additional_params or in the database)
        max_price = additional_params.get('max_price', entry_price)  # Start max_price at entry price
        trailing_stop_percentage = self.strategy_settings.get("trailing_stop_percentage")

        # Update max_price if the current price is higher than the previous max_price
        if last_price > max_price:
            max_price = last_price

        # Calculate the trailing stop price based on the highest price observed
        trailing_stop_price = max_price * (1 - trailing_stop_percentage)

        # Store the updated max_price back into additional_params
        additional_params['max_price'] = max_price

        # Return the exit condition along with the updated trailing stop price and max_price
        return {
            "exit": last_price <= trailing_stop_price,
            "trailing_stop_price": trailing_stop_price,
            "additional_params": additional_params,
            "reason": "Trailing Stop"
        }


    def create_exit_order(self, exit_result):
        from api_trader.order_builder import AssetType
        """
        Builds a single trailing stop order.
        """
        trailing_stop_percentage = self.strategy_settings.get("trailing_stop_percentage")
        # trailing_stop_price = exit_result['trailing_stop_price']
        additional_params = exit_result['additional_params']  # Access additional_params
        symbol = additional_params['symbol']
        qty = additional_params['quantity']
        side = additional_params['side']
        assetType = additional_params['assetType']

        # Determine the instruction (inverse of the side)
        instruction = self.get_instruction_for_side(side=side)

        # Create trailing stop order
        trailing_stop_order_builder = self.order_builder_cls()
        trailing_stop_order_builder.set_order_type(OrderType.TRAILING_STOP)
        trailing_stop_order_builder.set_session(Session.NORMAL)
        trailing_stop_order_builder.set_duration(Duration.GOOD_TILL_CANCEL)
        trailing_stop_order_builder.set_order_strategy_type(OrderStrategyType.SINGLE)
        trailing_stop_order_builder.set_stop_price_link_type(StopPriceLinkType.PERCENT)
        trailing_stop_order_builder.set_stop_price_link_basis(StopPriceLinkBasis.MARK)
        trailing_stop_order_builder.set_stop_price_offset(100 * trailing_stop_percentage)

        if assetType == AssetType.EQUITY:
            trailing_stop_order_builder.add_equity_leg(instruction=instruction, symbol=symbol, quantity=qty)
        else:
            trailing_stop_order_builder.add_option_leg(instruction=instruction, symbol=symbol, quantity=qty)

        # Return the built trailing stop order
        return trailing_stop_order_builder.build()
    