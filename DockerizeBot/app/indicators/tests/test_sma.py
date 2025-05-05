from django.test import TestCase
from indicators.calculations.sma import sma

class SMATestCase(TestCase):
    def test_sma_basic(self):
        data = [1, 2, 3, 4, 5]
        result = sma(data, 3)
        self.assertEqual(result, [2.0, 3.0, 4.0])
