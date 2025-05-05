from django.test import TestCase
from ocilators.calculations.macd import calculate_macd

class MACDTestCase(TestCase):
    def test_macd_output_lengths(self):
        prices = [i for i in range(60)]  # دیتای ساختگی
        result = calculate_macd(prices)
        self.assertEqual(len(result['macd_line']), len(result['signal_line']))
        self.assertEqual(len(result['macd_line']), len(result['histogram']))

    def test_macd_not_enough_data(self):
        prices = [i for i in range(20)]
        with self.assertRaises(ValueError):
            calculate_macd(prices)

