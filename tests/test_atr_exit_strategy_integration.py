import datetime
import random
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from api_trader import ApiTrader
from api_trader.strategies.atr_exit import ATRExitStrategy


class TestATRExitStrategyIntegration(unittest.IsolatedAsyncioTestCase):

    @patch('api_trader.ApiTrader.__init__', return_value=None)  # Mock constructor to avoid actual init
    @patch('pandas_market_calendars.get_calendar')
    @patch('tdameritrade.TDAmeritrade.get_price_history_every_day', new_callable=AsyncMock)
    async def test_fetch_historical_data(self, mock_get_price_history, mock_get_calendar, mock_init):
            # Generate ~30 fake trading days
            mock_schedule = self._generate_fake_market_schedule(num_days=30, start_date=datetime.datetime(2023, 10, 15))

            mock_calendar = MagicMock()
            mock_calendar.schedule.return_value = mock_schedule
            mock_get_calendar.return_value = mock_calendar

            # Generate enough fake candles for atrPeriod=15
            fake_candles = self._generate_fake_candle_data(num_bars=30)
            mock_get_price_history.return_value = {"candles": fake_candles}

            # Instantiate ApiTrader (which calls OrderBuilderWrapper.__init__)
            self.api_trader = ApiTrader()

            # Create a mock strategy_settings object with the necessary attributes
            mock_strategy_settings = MagicMock()
            mock_strategy_settings.get.side_effect = lambda key: {
                "atr_profit_factor": 2.0,
                "atr_stop_loss_factor": 1.5,
            }.get(key)

            # Create a dummy TDAmeritrade mock for price history calls
            class DummyTDAMock:
                async def get_price_history_every_day(self, symbol, **kwargs):
                    return await mock_get_price_history(symbol, **kwargs)

            # Instantiate the ATRExitStrategy with the mocked objects
            atr_exit_strategy = ATRExitStrategy(mock_strategy_settings, DummyTDAMock())

            # Act: Call the method under test
            historical_data = await atr_exit_strategy.fetch_historical_data("AAPL", atr_period=15)

            # Assert: Validate the mock was called correctly and the result is as expected
            mock_get_price_history.assert_called_once()
            self.assertIsInstance(historical_data, dict)
            self.assertIn("candles", historical_data)
            self.assertEqual(len(historical_data["candles"]), 30)

            # Now, for the first candle:
            first_candle = historical_data["candles"][0]
            self.assertIn("close", first_candle)
            self.assertIsInstance(first_candle["close"], (int, float))

    # Add this helper method to correctly calculate the start date
    def _calculate_start_date(self, market_days_back, end_date):
        current_date = end_date
        market_days = 0

        while market_days < market_days_back:
            current_date -= datetime.timedelta(days=1)
            if current_date.weekday() < 5:  # Check if it's a weekday (market open)
                market_days += 1

        return current_date


    def _generate_fake_candle_data(self, num_bars=30, start_date=None):
        """
        Generates fake daily candles (skipping weekends) for testing.
        Returns a list of dicts like: 
        [{"datetime": ..., "close": 150}, ...] 
        By default, starts from 'start_date' going forward (or use a default).
        """

        if start_date is None:
            # Default to ~1 month ago
            start_date = datetime.datetime(2023, 10, 1)

        candles = []
        current_date = start_date
        close_price = 150.0  # arbitrary starting price

        bars_created = 0
        while bars_created < num_bars:
            # Skip weekends
            if current_date.weekday() < 5:  # Monday=0, ... Friday=4
                # Make up some variation in close price
                close_price += random.uniform(-2, 2)
                close_price = max(close_price, 1.0)  # avoid negative or zero

                # Convert to an integer timestamp if TDA expects that
                dt_millis = int(current_date.timestamp() * 1000)
                
                candles.append({
                    "datetime": dt_millis,
                    "close": round(close_price, 2),
                    # Optionally add open, high, low, volume, etc.
                    # "open": ...
                    # "high": ...
                    # "low": ...
                    # "volume": ...
                })
                bars_created += 1

            # Move to the next calendar day
            current_date += datetime.timedelta(days=1)

        return candles
    
    def _generate_fake_market_schedule(self, num_days=30, start_date=None):
        """
        Generates a mock market schedule for num_days (skipping weekends),
        returning a pandas DataFrame with 'market_open' and 'market_close' columns.
        """

        if start_date is None:
            # Default to a certain date if none provided
            start_date = datetime.datetime(2023, 10, 1, 9, 30)  # e.g., 9:30 AM on Oct 1

        open_times = []
        close_times = []

        current_date = start_date
        days_created = 0

        while days_created < num_days:
            # Skip weekends
            if current_date.weekday() < 5:  # Monday=0 ... Friday=4
                # Create market_open at 9:30, market_close at 16:00
                market_open = current_date.replace(hour=9, minute=30, second=0, microsecond=0)
                market_close = current_date.replace(hour=16, minute=0, second=0, microsecond=0)

                open_times.append(pd.Timestamp(market_open))
                close_times.append(pd.Timestamp(market_close))

                days_created += 1

            # Advance one day
            current_date += datetime.timedelta(days=1)

        mock_schedule = pd.DataFrame({
            "market_open": open_times,
            "market_close": close_times,
        })
        return mock_schedule



if __name__ == "__main__":
    unittest.main()
