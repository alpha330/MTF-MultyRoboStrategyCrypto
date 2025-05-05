from django.test import TestCase
from indicators.calculations.bollinger_band import calculate_bollinger_bands

class TestBollingerBands(TestCase):
    def test_bollinger_valid_output(self):
        prices = [i for i in range(1, 21)]
        period = 5
        sma, upper, lower = calculate_bollinger_bands(prices, period)
        self.assertEqual(len(sma), len(prices))
        self.assertEqual(len(upper), len(prices))
        self.assertEqual(len(lower), len(prices))
        self.assertIsNone(sma[0])
        self.assertIsInstance(upper[-1], float)

    def test_bollinger_not_enough_data(self):
        with self.assertRaises(ValueError):
            calculate_bollinger_bands([1, 2, 3], period=5)

    def test_bollinger_invalid_period(self):
        with self.assertRaises(ValueError):
            calculate_bollinger_bands([1, 2, 3], period=0)

    def test_bollinger_known_values(self):
        prices = [1, 2, 3, 4, 5]
        period = 5
        sma, upper, lower = calculate_bollinger_bands(prices, period)
        expected_sma = sum(prices) / 5
        self.assertAlmostEqual(sma[-1], expected_sma)
