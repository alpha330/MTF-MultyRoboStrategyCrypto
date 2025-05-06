from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .calculations.rsi import calculate_rsi, calculate_rsi_series
from .calculations.macd import calculate_macd

@api_view(["POST"])
def rsi_view(request):
    try:
        prices = request.data.get("prices", [])
        period = int(request.data.get("period", 14))
        series = request.query_params.get("series", "false").lower() == "true"

        if not prices or len(prices) < period + 1:
            return Response({"error": "Not enough price data"}, status=400)

        if series:
            rsi_series = calculate_rsi_series(prices, period=period)
            rsi_clean = rsi_series.dropna().tolist()
            return Response({"rsi_series": rsi_clean})
        else:
            rsi = calculate_rsi(prices, period=period)
            return Response({"rsi": rsi})

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    
@api_view(['POST'])
def macd_view(request):
    try:
        prices = request.data.get("prices")
        series = request.query_params.get("series") == "true"

        if not prices or not isinstance(prices, list):
            return Response({"error": "Field 'prices' must be a list of numbers."}, status=400)

        result = calculate_macd(prices, series=series)
        return Response(result)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
