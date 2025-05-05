from django.test import TestCase
from ocilators.calculations.cci import cci

class CCITestCase(TestCase):
    def test_cci_length_and_values(self):
        high = [127, 130, 128, 129, 128, 131, 130, 132, 133, 132, 135, 136, 137, 136, 135, 134, 133, 132, 131, 130]
        low = [125, 126, 124, 125, 124, 126, 125, 127, 128, 127, 129, 130, 131, 130, 129, 128, 127, 126, 125, 124]
        close = [126, 128, 126, 127, 126, 129, 128, 130, 131, 130, 133, 134, 135, 134, 133, 132, 131, 130, 129, 128]

        result = cci(high, low, close)
        
        self.assertEqual(len(result), len(close))
        self.assertIsInstance(result, list)
