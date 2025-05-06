from django.test import TestCase
from ocilators.calculations.rsi import calculate_rsi_series

class RSITestCase(TestCase):
    def test_rsi_typical(self):
        prices = [i + (i % 3) for i in range(100)]
        rsi = calculate_rsi_series(prices)
        self.assertAlmostEqual(rsi, 78.26086956521739, places=5)

    def test_rsi_not_enough_data(self):
        with self.assertRaises(ValueError):
            calculate_rsi_series([1, 2, 3, 4], period=14)
