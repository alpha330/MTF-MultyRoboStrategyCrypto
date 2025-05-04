from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from shared.redis_client import redis_client

class TrendView(APIView):
    def post(self, request):
        trend = request.data.get('trend')
        redis_client.set('trend', trend)
        return Response({'trend': trend})

    def get(self, request):
        trend = redis_client.get('trend') or 'unknown'
        return Response({'trend': trend})

class ConfirmationView(APIView):
    def post(self, request):
        confirmation = request.data.get('confirmation')
        redis_client.set('confirmation', confirmation)
        return Response({'confirmation': confirmation})

    def get(self, request):
        confirmation = redis_client.get('confirmation') or 'unknown'
        return Response({'confirmation': confirmation})

class SignalView(APIView):
    def post(self, request):
        signal = request.data.get('signal')
        redis_client.set('signal', signal)
        return Response({'signal': signal})

    def get(self, request):
        signal = redis_client.get('signal') or 'unknown'
        return Response({'signal': signal})
