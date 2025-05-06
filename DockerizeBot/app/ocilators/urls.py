from django.urls import path
from .views import rsi_view

urlpatterns = [
    path('rsi/', rsi_view, name='rsi'),
]