from django.urls import path
from . import views

urlpatterns = [
    # Dashboard Views
    path('signals/', views.signal_dashboard, name='signal_dashboard'),
    path('signals/<str:signal_id>/', views.signal_detail, name='signal_detail'),
    path('history/', views.trade_history, name='trade_history'),
    
    # Trading Diagnostics (Sanity & Confidence Layer)
    path('diagnostics/', views.diagnostics_view, name='trading_diagnostics'),
    
    # Breakout Distance Chart v1
    path('chart/', views.breakout_distance_chart_view, name='breakout_distance_chart'),
    
    # Trade Actions
    path('signals/<str:signal_id>/live/', views.execute_live_trade, name='execute_live_trade'),
    path('signals/<str:signal_id>/shadow/', views.execute_shadow_trade, name='execute_shadow_trade'),
    path('signals/<str:signal_id>/reject/', views.reject_signal, name='reject_signal'),
    path('signals/delete-forbidden/', views.delete_forbidden_signals, name='delete_forbidden_signals'),
    path('signals/delete-selected/', views.delete_selected_signals, name='delete_selected_signals'),
    
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
    
    # Session Phase Configuration
    path('assets/<int:asset_id>/phases/', views.phase_config_list, name='phase_config_list'),
    path('assets/<int:asset_id>/phases/create-defaults/', views.phase_config_create_defaults, name='phase_config_create_defaults'),
    path('assets/<int:asset_id>/phases/<str:phase>/', views.phase_config_edit, name='phase_config_edit'),
    path('assets/<int:asset_id>/phases/<str:phase>/delete/', views.phase_config_delete, name='phase_config_delete'),
    path('assets/<int:asset_id>/phases/<str:phase>/toggle/', views.phase_config_toggle, name='phase_config_toggle'),
    
    # Market Data Layer - Realtime Breakout Distance Candles
    path('api/breakout-distance-candles', views.api_breakout_distance_candles, name='api_breakout_distance_candles'),
    path('api/market-data/status/', views.api_market_data_status, name='api_market_data_status'),
    
    # Breakout Range API
    path('api/assets/<int:asset_id>/breakout-ranges/', views.api_breakout_range_history, name='api_breakout_range_history'),
    path('api/assets/<int:asset_id>/breakout-ranges/latest/', views.api_breakout_range_latest, name='api_breakout_range_latest'),
    
    # Breakout Distance Chart v1 API
    path('api/chart/<str:asset_code>/candles', views.api_chart_candles, name='api_chart_candles'),
    path('api/chart/<str:asset_code>/breakout-context', views.api_chart_breakout_context, name='api_chart_breakout_context'),
    path('api/chart/<str:asset_code>/session-ranges', views.api_chart_session_ranges, name='api_chart_session_ranges'),
    
    # Breakout Distance Chart API (legacy)
    path('api/assets/<str:asset_code>/diagnostics/breakout-distance-chart', views.api_breakout_distance_chart, name='api_breakout_distance_chart'),
    path('api/assets/<int:asset_id>/diagnostics/breakout-distance-chart/', views.api_breakout_distance_chart_by_id, name='api_breakout_distance_chart_by_id'),
    
    # Trading Diagnostics API
    path('api/trading/diagnostics/', views.api_diagnostics, name='api_trading_diagnostics'),
    # Session Phase API
    path('api/assets/<int:asset_id>/phases/', views.api_phase_configs, name='api_phase_configs'),
    
    # Price vs Range - Live Status API & HTMX
    path('api/price-range-status/', views.api_price_range_status, name='api_price_range_status'),
    path('htmx/price-range-status/', views.htmx_price_range_status, name='htmx_price_range_status'),
    
    # API Endpoints
    path('api/signals/', views.api_signals, name='api_signals'),
    path('api/signals/since/<str:since>/', views.api_signals_since, name='api_signals_since'),
    path('api/trade/<str:signal_id>/', views.api_signal_detail, name='api_signal_detail'),
    path('api/account-state/', views.api_account_state, name='api_account_state'),
    path('api/all-brokers-account-state/', views.api_all_brokers_account_state, name='api_all_brokers_account_state'),
    path('api/worker/status/', views.api_worker_status, name='api_worker_status'),
    path('api/assets/', views.api_active_assets, name='api_active_assets'),
    path('api/debug/breakout-range/', views.api_breakout_range_diagnostics, name='api_breakout_range_diagnostics'),
    
    # Sidebar API
    path('api/sidebar/assets/', views.api_sidebar_assets, name='api_sidebar_assets'),
]

