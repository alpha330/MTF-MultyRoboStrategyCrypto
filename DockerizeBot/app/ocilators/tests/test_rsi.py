from django.test import TestCase
from ocilators.calculations.rsi import calculate_rsi_series

class RSITestCase(TestCase):
    def test_rsi_typical(self):
        prices = [
            44.34, 44.09, 44.15, 43.61, 44.33,
            44.83, 45.10, 45.42, 45.84, 46.08,
            45.89, 46.03, 45.61, 46.28, 46.28
        ]
        rsi = calculate_rsi_series(prices)
        self.assertAlmostEqual(rsi, 70.464, places=2)

    def test_rsi_not_enough_data(self):
        with self.assertRaises(ValueError):
            calculate_rsi_series([1, 2, 3, 4], period=14)
