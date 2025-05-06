from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

class MACDViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/ocilators/macd/'
        self.valid_data = {
            "prices": [i + (i % 5) for i in range(100)]
        }

    def test_macd_success(self):
        response = self.client.post(self.url, self.valid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('macd', response.data)
        self.assertIn('signal', response.data)
        self.assertIn('histogram', response.data)

    def test_macd_missing_prices(self):
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

