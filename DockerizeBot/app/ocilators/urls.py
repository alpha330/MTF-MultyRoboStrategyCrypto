from django.urls import path
from .views import rsi_view,macd_view

urlpatterns = [
    path('rsi/', rsi_view, name='rsi'),
    path('macd/', macd_view, name='macd'),
]