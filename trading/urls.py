from django.urls import path
from . import views

urlpatterns = [
    # Dashboard Views
    path('signals/', views.signal_dashboard, name='signal_dashboard'),
    path('signals/<str:signal_id>/', views.signal_detail, name='signal_detail'),
    path('history/', views.trade_history, name='trade_history'),
    
    # Trading Diagnostics (Sanity & Confidence Layer)
    path('diagnostics/', views.diagnostics_view, name='trading_diagnostics'),
    
    # Trade Actions
    path('signals/<str:signal_id>/live/', views.execute_live_trade, name='execute_live_trade'),
    path('signals/<str:signal_id>/shadow/', views.execute_shadow_trade, name='execute_shadow_trade'),
    path('signals/<str:signal_id>/reject/', views.reject_signal, name='reject_signal'),
    
    # Asset Management
    path('assets/', views.asset_list, name='asset_list'),
    path('assets/create/', views.asset_create, name='asset_create'),
    path('assets/<int:asset_id>/', views.asset_detail, name='asset_detail'),
    path('assets/<int:asset_id>/edit/', views.asset_edit, name='asset_edit'),
    path('assets/<int:asset_id>/toggle-active/', views.asset_toggle_active, name='asset_toggle_active'),
    path('assets/<int:asset_id>/toggle-trading-mode/', views.asset_toggle_trading_mode, name='asset_toggle_trading_mode'),
    path('assets/<int:asset_id>/breakout-config/', views.breakout_config_edit, name='breakout_config_edit'),
    path('assets/<int:asset_id>/event-config/', views.event_config_edit, name='event_config_create'),
    path('assets/<int:asset_id>/event-config/<str:phase>/', views.event_config_edit, name='event_config_edit'),
    path('assets/<int:asset_id>/event-config/<str:phase>/delete/', views.event_config_delete, name='event_config_delete'),
    
    # Breakout Range API
    path('api/assets/<int:asset_id>/breakout-ranges/', views.api_breakout_range_history, name='api_breakout_range_history'),
    path('api/assets/<int:asset_id>/breakout-ranges/latest/', views.api_breakout_range_latest, name='api_breakout_range_latest'),
    
    # Trading Diagnostics API
    path('api/trading/diagnostics/', views.api_diagnostics, name='api_trading_diagnostics'),
    
    # API Endpoints
    path('api/signals/', views.api_signals, name='api_signals'),
    path('api/signals/since/<str:since>/', views.api_signals_since, name='api_signals_since'),
    path('api/trade/<str:signal_id>/', views.api_signal_detail, name='api_signal_detail'),
    path('api/account-state/', views.api_account_state, name='api_account_state'),
    path('api/worker/status/', views.api_worker_status, name='api_worker_status'),
    path('api/assets/', views.api_active_assets, name='api_active_assets'),
    path('api/debug/breakout-range/', views.api_breakout_range_diagnostics, name='api_breakout_range_diagnostics'),
]
