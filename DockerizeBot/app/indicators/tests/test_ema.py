from django.test import TestCase
from indicators.calculations.ema import calculate_ema

class TestEMA(TestCase):
    def test_ema_basic(self):
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        period = 3
        result = calculate_ema(prices, period)
        self.assertEqual(len(result), len(prices))
        self.assertTrue(all(isinstance(x, float) or x is None for x in result))

    def test_ema_invalid_period(self):
        with self.assertRaises(ValueError):
            calculate_ema([10, 11, 12], 0)

    def test_ema_not_enough_data(self):
        with self.assertRaises(ValueError):
            calculate_ema([10, 11], 5)

    def test_ema_known_values(self):
        prices = [10, 11, 12, 13, 14]
        period = 3
        result = calculate_ema(prices, period)
        self.assertAlmostEqual(result[2], 11.0)  # SMA first
        self.assertAlmostEqual(result[3], (13 - 11.0) * (2/4) + 11.0)
