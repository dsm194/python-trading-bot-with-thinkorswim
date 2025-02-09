import asyncio
import datetime

import pandas as pd
import pandas_market_calendars as mcal
from schwab.orders.common import (Duration, OrderStrategyType, OrderType,
                                  Session, one_cancels_other)
from schwab.orders.generic import OrderBuilder

from api_trader.order_builder import AssetType
from api_trader.strategies.exit_strategy import ExitStrategy
from api_trader.strategies.strategy_settings import StrategySettings
from tdameritrade import TDAmeritrade


class ATRExitStrategy(ExitStrategy):
    def __init__(self, strategy_settings: StrategySettings, tdameritrade: TDAmeritrade, order_builder_cls=OrderBuilder):
        super().__init__(strategy_settings)
        self.tdameritrade = tdameritrade
        self.order_builder_cls = order_builder_cls

        self.atr_profit_factor = strategy_settings.get("atr_profit_factor")
        self.atr_stop_loss_factor = strategy_settings.get("atr_stop_loss_factor")

        # Store ATR values for symbols at entry time
        self.entry_atr_values = {}

        # Use a threading.Lock (since we are mixing threads)
        self.lock = asyncio.Lock()

        self._start_date_cache = {}

    # -------------------------------------------------------------------------
    # 1. Asynchronous "should_exit" (required by ExitStrategy)
    # -------------------------------------------------------------------------
    async def should_exit(self, additional_params):
        """
        Checks whether the exit conditions are met. (Asynchronous)
        """
        symbol = additional_params["symbol"]
        entry_price = additional_params["entry_price"]
        last_price = additional_params["last_price"]

        # Asynchronously ensure we have an ATR for this symbol
        async with self.lock:
            if symbol not in self.entry_atr_values:
                atr = await self.calculate_atr(symbol)
                self.entry_atr_values[symbol] = atr
            else:
                atr = self.entry_atr_values[symbol]

        # Calculate profit target and stop loss
        profit_target = entry_price + self.atr_profit_factor * atr
        stop_loss = entry_price - self.atr_stop_loss_factor * atr

        # Store the atr back into additional_params
        additional_params['atr'] = atr

        return {
            "exit": last_price >= profit_target or last_price <= stop_loss,
            "take_profit_price": profit_target,
            "stop_loss_price": stop_loss,
            "additional_params": additional_params,
            "reason": "OCO"
        }

    # -------------------------------------------------------------------------
    # 2. Asynchronous create_exit_order (required by ExitStrategy)
    # -------------------------------------------------------------------------
    async def create_exit_order(self, exit_result):
        """ Builds an OCO (One-Cancels-Other) order with both take-profit and stop-loss. """

        take_profit_price = exit_result['take_profit_price']
        stop_loss_price = exit_result['stop_loss_price']
        additional_params = exit_result['additional_params']
        symbol = additional_params['symbol']
        pre_symbol = additional_params.get('pre_symbol')
        qty = additional_params['quantity']
        side = additional_params['side']
        assetType = additional_params['assetType']

        # Round prices for order placement
        take_profit_price = round(take_profit_price, 2) if take_profit_price >= 1 else round(take_profit_price, 4)
        stop_loss_price = round(stop_loss_price, 2) if stop_loss_price >= 1 else round(stop_loss_price, 4)

        # Determine the instruction (inverse of the side)
        instruction = await self.get_instruction_for_side(assetType, side)

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
            take_profit_order_builder.add_option_leg(instruction=instruction, symbol=pre_symbol, quantity=qty)

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
            stop_loss_order_builder.add_option_leg(instruction=instruction, symbol=pre_symbol, quantity=qty)

        # Return the OCO order
        return one_cancels_other(take_profit_order_builder.build(), stop_loss_order_builder.build()).build()
    

    # -------------------------------------------------------------------------
    # 3. Public "calculate_atr" for asynchronous usage
    # -------------------------------------------------------------------------
    async def calculate_atr(self, symbol, atr_period=None):
        """
        Async method that:
          1) Fetches historical data
          2) Computes ATR (CPU/light logic) 
             (If CPU-bound or big, consider `asyncio.to_thread`.)
        """
        if atr_period is None:
            atr_period = self.strategy_settings.get("atr_period", 14)

        try:
            # 1. Fetch data (async)
            historical_data = await self.fetch_historical_data(symbol, atr_period)

            # 2. Compute the ATR:
            atr_value_new = await self.compute_atr_from_data(historical_data, atr_period)
            return atr_value_new
        except Exception as e:
            print(f"Error in calculate_atr for {symbol}: {e}")
            raise

    # -------------------------------------------------------------------------
    # 5. Async "fetch_historical_data"
    # -------------------------------------------------------------------------
    async def fetch_historical_data(self, symbol, atr_period=15):
        """
        Fetches historical data for the given symbol. (Async)
        """
        end_date = datetime.datetime.now()
        start_date = self._get_start_date_for_atr_period(end_date, atr_period * 2)

        historical_data = await self.tdameritrade.get_price_history_every_day(
            symbol,
            start_datetime=start_date,
            end_datetime=end_date,
            need_extended_hours_data=False
        )
        return historical_data

    # -------------------------------------------------------------------------
    # 6. Helper to compute start date for ATR period
    # -------------------------------------------------------------------------
    def _get_start_date_for_atr_period(self, end_date, atr_period):
        cache_key = (end_date.date(), atr_period)
        if cache_key in self._start_date_cache:
            return self._start_date_cache[cache_key]
        
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(
            start_date=end_date - datetime.timedelta(days=atr_period * 2),
            end_date=end_date
        )
        market_days = list(schedule['market_open'])

        if len(market_days) < atr_period:
            raise ValueError("Not enough market days in the range to calculate ATR.")

        # Nth-to-last market day for the ATR period
        start_date = market_days[-atr_period]
        self._start_date_cache[cache_key] = start_date
        return start_date

    # -------------------------------------------------------------------------
    # 7. "compute_atr_from_data" as is
    # -------------------------------------------------------------------------
    async def compute_atr_from_data(self, data, atr_period=14):

        # Convert TDA data => DataFrame
        candles = data["candles"]
        df = pd.DataFrame(candles)

        # If columns already match 'open','high','low','close', no rename needed
        # If TDA columns differ, rename them here:
        # df.rename(columns={'openPrice': 'open', 'highPrice': 'high', ...}, inplace=True)

        # Compute ATR using pandas-ta
        df.ta.atr(length=atr_period, append=True)
        atr_col = f"ATRr_{atr_period}"
        if atr_col not in df.columns:
            raise ValueError("Failed to compute ATR via pandas-ta")

        # Return the latest ATR
        return df[atr_col].iloc[-1]
