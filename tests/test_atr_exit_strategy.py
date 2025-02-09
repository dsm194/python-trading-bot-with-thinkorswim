from api_trader.strategies.atr_exit import ATRExitStrategy
from unittest.mock import MagicMock
import unittest

class TestATRExitStrategy(unittest.TestCase):

    @unittest.expectedFailure
    def test_compute_atr_from_data(self):
        #  Arrange: Provide enough data for the ATR calculation (14 periods)
        data = [
            {"high": 150, "low": 145, "close": 148},
            {"high": 151, "low": 146, "close": 149},
            {"high": 152, "low": 147, "close": 150},
            {"high": 153, "low": 148, "close": 151},
            {"high": 154, "low": 149, "close": 152},
            {"high": 155, "low": 150, "close": 153},
            {"high": 156, "low": 151, "close": 154},
            {"high": 157, "low": 152, "close": 155},
            {"high": 158, "low": 153, "close": 156},
            {"high": 159, "low": 154, "close": 157},
            {"high": 160, "low": 155, "close": 158},
            {"high": 161, "low": 156, "close": 159},
            {"high": 162, "low": 157, "close": 160},
            {"high": 163, "low": 158, "close": 161},
        ]  # 14 periods of data

        # Define a mock strategy settings object
        mock_strategy_settings = MagicMock()
        # Modify the lambda function to handle both arguments (key and default)
        mock_strategy_settings.get.side_effect = lambda key, default=None: {
            "atr_period": 14,
        }.get(key, default)

        # Instantiate the ATRExitStrategy with the mocked objects
        atr_exit_strategy = ATRExitStrategy(mock_strategy_settings, None)

        # Act: Call the method under test
        atr = atr_exit_strategy.compute_atr_from_data(data)

        # Assert: Check if the ATR is computed correctly
        self.assertIsNotNone(atr)
        self.assertTrue(atr > 0)  # Ensure ATR is a positive value

    @unittest.expectedFailure
    def test_compute_atr_from_data_insufficient_data(self):
        # Mock data with insufficient periods for ATR computation
        mock_data = [
            {"datetime": 1698844800000, "high": 155, "low": 145, "close": 150},
            {"datetime": 1698758400000, "high": 154, "low": 146, "close": 152},
        ]
        
        mock_strategy_settings = MagicMock()
        mock_strategy_settings.get.return_value = 14  # Assume we need 14 periods

        atr_exit_strategy = ATRExitStrategy(mock_strategy_settings, MagicMock())
        
        # Assuming the method should raise an exception or return None if there's insufficient data
        with self.assertRaises(ValueError):
            atr_exit_strategy.compute_atr_from_data(mock_data)

    @unittest.expectedFailure
    def test_compute_atr_from_data_empty_data(self):
        # Test for empty data input
        mock_data = []

        mock_strategy_settings = MagicMock()
        mock_strategy_settings.get.return_value = 14  # Assume we need 14 periods

        atr_exit_strategy = ATRExitStrategy(mock_strategy_settings, MagicMock())

        # Check if the method handles empty data gracefully (e.g., by returning None or raising an error)
        with self.assertRaises(ValueError):
            atr_exit_strategy.compute_atr_from_data(mock_data)
