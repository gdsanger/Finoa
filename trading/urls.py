from django.urls import path
from . import views

urlpatterns = [
    # Dashboard Views
    path('signals/', views.signal_dashboard, name='signal_dashboard'),
    path('signals/<str:signal_id>/', views.signal_detail, name='signal_detail'),
    path('history/', views.trade_history, name='trade_history'),
    
    # Trade Actions
    path('signals/<str:signal_id>/live/', views.execute_live_trade, name='execute_live_trade'),
    path('signals/<str:signal_id>/shadow/', views.execute_shadow_trade, name='execute_shadow_trade'),
    path('signals/<str:signal_id>/reject/', views.reject_signal, name='reject_signal'),
    
    # API Endpoints
    path('api/signals/', views.api_signals, name='api_signals'),
    path('api/trade/<str:signal_id>/', views.api_signal_detail, name='api_signal_detail'),
    path('api/account-state/', views.api_account_state, name='api_account_state'),
]
