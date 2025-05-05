from django.test import TestCase
from indicators.calculations.ichimoku import calculate_ichimoku

class TestIchimoku(TestCase):
    def test_valid_ichimoku_output(self):
        highs = [i + 2 for i in range(100)]
        lows = [i for i in range(100)]
        closes = [i + 1 for i in range(100)]

        result = calculate_ichimoku(highs, lows, closes)
        self.assertEqual(len(result["tenkan_sen"]), len(closes))
        self.assertEqual(len(result["kijun_sen"]), len(closes))
        self.assertEqual(len(result["senkou_span_a"]), len(closes))
        self.assertEqual(len(result["senkou_span_b"]), len(closes))
        self.assertEqual(len(result["chikou_span"]), len(closes))

    def test_invalid_input_length(self):
        with self.assertRaises(ValueError):
            calculate_ichimoku([1, 2, 3], [1, 2], [1, 2, 3])
