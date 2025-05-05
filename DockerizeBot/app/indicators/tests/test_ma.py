from django.test import TestCase
from indicators.calculations.ma import moving_average

class MovingAverageTestCase(TestCase):
    def test_basic_ma(self):
        data = [1, 2, 3, 4, 5]
        period = 3
        expected = [2.0, 3.0, 4.0]
        result = moving_average(data, period)
        self.assertEqual(result, expected)

    def test_invalid_period(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2], 3)

    def test_zero_period(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2, 3], 0)