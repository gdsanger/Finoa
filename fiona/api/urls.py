"""
URL configuration for the Fiona Backend API Layer.

Endpoints:
- GET  /api/signals              - List active signals
- GET  /api/signals/{id}         - Signal details
- POST /api/trade/live           - Execute live trade
- POST /api/trade/shadow         - Execute shadow trade
- POST /api/trade/reject         - Reject signal
- GET  /api/trades               - Trade history
"""
from django.urls import path
from . import views

app_name = 'fiona_api'

urlpatterns = [
    # Signal endpoints
    path('signals/', views.api_list_signals, name='list_signals'),
    path('signals/<str:signal_id>/', views.api_get_signal, name='get_signal'),
    
    # Trade action endpoints
    path('trade/live/', views.api_execute_live_trade, name='execute_live_trade'),
    path('trade/shadow/', views.api_execute_shadow_trade, name='execute_shadow_trade'),
    path('trade/reject/', views.api_reject_signal, name='reject_signal'),
    
    # Trade history
    path('trades/', views.api_list_trades, name='list_trades'),
]
