from django.test import TestCase
from ocilators.calculations.stochastic import stochastic_oscillator

class StochasticOscillatorTestCase(TestCase):
    def test_stochastic_values(self):
        close = [44, 44.15, 43.9, 44.35, 44.2, 44.05, 44.1, 44.6, 44.8, 44.7, 45.0, 44.9, 45.3, 45.4, 45.2]
        high = [45, 44.6, 44.3, 44.7, 44.5, 44.4, 44.6, 45, 45.1, 44.9, 45.3, 45.2, 45.6, 45.7, 45.5]
        low =  [43.8, 43.9, 43.5, 44, 43.9, 43.7, 44, 44.2, 44.4, 44.3, 44.7, 44.8, 45, 45.1, 45]

        percent_k, percent_d = stochastic_oscillator(close, high, low)

        # فقط چک می‌کنیم که دیتا تولید شده و از نوع list باشه
        self.assertEqual(len(percent_k), len(close))
        self.assertEqual(len(percent_d), len(close))
        self.assertIsInstance(percent_k, list)
        self.assertIsInstance(percent_d, list)
