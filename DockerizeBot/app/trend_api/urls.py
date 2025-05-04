from django.urls import path
from . import views

urlpatterns = [
    path('trend/', views.TrendView.as_view(), name='trend'),
    path('confirmation/', views.ConfirmationView.as_view(), name='confirmation'),
    path('signal/', views.SignalView.as_view(), name='signal'),
]
