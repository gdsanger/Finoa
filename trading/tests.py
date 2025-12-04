from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from unittest.mock import MagicMock, patch
import uuid
import json

from .models import (
    Signal,
    Trade,
    WorkerStatus,
    TradingAsset,
    AssetBreakoutConfig,
    AssetEventConfig,
    AssetSessionPhaseConfig,
)


class SignalModelTest(TestCase):
    """Tests for Signal model."""
    
    def test_signal_creation(self):
        """Test basic signal creation."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            range_high=Decimal('78.60'),
            range_low=Decimal('77.50'),
            stop_loss=Decimal('77.80'),
            take_profit=Decimal('79.50'),
            position_size=Decimal('2.00'),
            gpt_confidence=Decimal('85.00'),
            risk_status='GREEN',
        )
        
        self.assertEqual(signal.setup_type, 'BREAKOUT')
        self.assertEqual(signal.direction, 'LONG')
        self.assertEqual(signal.status, 'ACTIVE')
        self.assertTrue(signal.can_execute_live)
        self.assertTrue(signal.is_active)
    
    def test_signal_cannot_execute_live_when_red(self):
        """Test that live trade is blocked when risk status is RED."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            risk_status='RED',
        )
        
        self.assertFalse(signal.can_execute_live)
    
    def test_signal_can_execute_live_when_yellow(self):
        """Test that live trade is allowed when risk status is YELLOW."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            risk_status='YELLOW',
        )
        
        self.assertTrue(signal.can_execute_live)
    
    def test_signal_str_representation(self):
        """Test signal string representation."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
        )
        
        str_repr = str(signal)
        self.assertIn('BREAKOUT', str_repr)
        self.assertIn('LONG', str_repr)


class TradeModelTest(TestCase):
    """Tests for Trade model."""
    
    def setUp(self):
        self.signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            risk_status='GREEN',
        )
    
    def test_trade_creation(self):
        """Test basic trade creation."""
        trade = Trade.objects.create(
            signal=self.signal,
            trade_type='LIVE',
            entry_price=Decimal('78.50'),
            stop_loss=Decimal('77.80'),
            take_profit=Decimal('79.50'),
            position_size=Decimal('2.00'),
        )
        
        self.assertEqual(trade.trade_type, 'LIVE')
        self.assertEqual(trade.status, 'OPEN')
        self.assertEqual(trade.signal, self.signal)
    
    def test_shadow_trade_creation(self):
        """Test shadow trade creation."""
        trade = Trade.objects.create(
            signal=self.signal,
            trade_type='SHADOW',
            entry_price=Decimal('78.50'),
        )
        
        self.assertEqual(trade.trade_type, 'SHADOW')


class SignalDashboardViewTest(TestCase):
    """Tests for Signal Dashboard view."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_signal_dashboard_accessible(self):
        """Test that signal dashboard is accessible."""
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Signal Dashboard')
    
    def test_signal_dashboard_requires_login(self):
        """Test that signal dashboard requires login."""
        self.client.logout()
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_signal_dashboard_shows_active_signals(self):
        """Test that dashboard shows active signals from database."""
        # Create an active signal
        Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            risk_status='GREEN',
            status='ACTIVE',
        )
        
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Breakout')
    
    def test_signal_dashboard_empty_when_no_signals(self):
        """Test that dashboard shows empty state when no signals exist."""
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Keine aktiven Signale')
    
    def test_signal_dashboard_shows_account_info_section(self):
        """Test that dashboard shows account info section with balance and margin."""
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 200)
        # Check for account info card elements
        self.assertContains(response, 'Konto &amp; Margin')
        self.assertContains(response, 'Kontostand')
        self.assertContains(response, 'Margin (genutzt)')
        self.assertContains(response, 'Margin (verfügbar)')
        self.assertContains(response, 'account-info')


class SignalDetailViewTest(TestCase):
    """Tests for Signal Detail view."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            range_high=Decimal('78.60'),
            range_low=Decimal('77.50'),
            stop_loss=Decimal('77.80'),
            take_profit=Decimal('79.50'),
            position_size=Decimal('2.00'),
            ki_reasoning='Test reasoning',
            gpt_confidence=Decimal('85.00'),
            gpt_reasoning='GPT test reasoning',
            risk_status='GREEN',
            risk_reasoning='Risk test reasoning',
        )
    
    def test_signal_detail_accessible(self):
        """Test that signal detail is accessible."""
        response = self.client.get(f'/fiona/signals/{self.signal.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Signal Details')
    
    def test_signal_detail_shows_data(self):
        """Test that signal detail shows signal data."""
        response = self.client.get(f'/fiona/signals/{self.signal.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test reasoning')
        self.assertContains(response, 'GPT test reasoning')


class TradeExecutionViewTest(TestCase):
    """Tests for trade execution views."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            stop_loss=Decimal('77.80'),
            take_profit=Decimal('79.50'),
            position_size=Decimal('2.00'),
            risk_status='GREEN',
        )
    
    def test_execute_live_trade_success(self):
        """Test executing a live trade."""
        response = self.client.post(f'/fiona/signals/{self.signal.id}/live/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Signal should be updated
        self.signal.refresh_from_db()
        self.assertEqual(self.signal.status, 'EXECUTED')
        
        # Trade should be created
        trade = Trade.objects.filter(signal=self.signal).first()
        self.assertIsNotNone(trade)
        self.assertEqual(trade.trade_type, 'LIVE')
    
    def test_execute_shadow_trade_success(self):
        """Test executing a shadow trade."""
        response = self.client.post(f'/fiona/signals/{self.signal.id}/shadow/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Signal should be updated
        self.signal.refresh_from_db()
        self.assertEqual(self.signal.status, 'SHADOW')
        
        # Trade should be created
        trade = Trade.objects.filter(signal=self.signal).first()
        self.assertIsNotNone(trade)
        self.assertEqual(trade.trade_type, 'SHADOW')
    
    def test_reject_signal_success(self):
        """Test rejecting a signal."""
        response = self.client.post(f'/fiona/signals/{self.signal.id}/reject/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Signal should be updated
        self.signal.refresh_from_db()
        self.assertEqual(self.signal.status, 'REJECTED')
    
    def test_execute_live_trade_blocked_when_red(self):
        """Test that live trade is blocked when risk status is RED."""
        self.signal.risk_status = 'RED'
        self.signal.save()
        
        response = self.client.post(f'/fiona/signals/{self.signal.id}/live/')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])


class TradeHistoryViewTest(TestCase):
    """Tests for Trade History view."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_trade_history_accessible(self):
        """Test that trade history is accessible."""
        response = self.client.get('/fiona/history/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trade Historie')
    
    def test_trade_history_requires_login(self):
        """Test that trade history requires login."""
        self.client.logout()
        response = self.client.get('/fiona/history/')
        self.assertEqual(response.status_code, 302)


class APIEndpointsTest(TestCase):
    """Tests for API endpoints."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_api_signals_returns_json(self):
        """Test that API returns JSON."""
        response = self.client.get('/fiona/api/signals/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertIn('signals', data)
    
    def test_api_signal_detail_returns_json(self):
        """Test that API detail returns JSON."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
        )
        
        response = self.client.get(f'/fiona/api/trade/{signal.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertEqual(data['setup_type'], 'BREAKOUT')
    
    def test_api_account_state_returns_json(self):
        """Test that account state API returns JSON when broker not configured."""
        response = self.client.get('/fiona/api/account-state/')
        # Should return 503 when broker is not configured
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertIn('success', data)
        self.assertFalse(data['success'])
        self.assertIn('error', data)
        self.assertIn('connected', data)
        self.assertFalse(data['connected'])
    
    def test_api_account_state_requires_login(self):
        """Test that account state API requires login."""
        self.client.logout()
        response = self.client.get('/fiona/api/account-state/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))


class WorkerStatusModelTest(TestCase):
    """Tests for WorkerStatus model."""
    
    def test_worker_status_creation(self):
        """Test basic worker status creation."""
        now = timezone.now()
        status = WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            spread=Decimal('0.05'),
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,
        )
        
        self.assertEqual(status.phase, 'LONDON_CORE')
        self.assertEqual(status.epic, 'CC.D.CL.UNC.IP')
        self.assertEqual(status.setup_count, 0)
        self.assertEqual(status.worker_interval, 60)
    
    def test_worker_status_get_current(self):
        """Test getting current worker status."""
        now = timezone.now()
        
        # Initially should return None
        self.assertIsNone(WorkerStatus.get_current())
        
        # Create a status
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
        )
        
        # Should return the status
        current = WorkerStatus.get_current()
        self.assertIsNotNone(current)
        self.assertEqual(current.phase, 'LONDON_CORE')
    
    def test_worker_status_update_status(self):
        """Test updating worker status."""
        now = timezone.now()
        
        # Create initial status
        status1 = WorkerStatus.update_status(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
        )
        
        self.assertEqual(WorkerStatus.objects.count(), 1)
        
        # Update status (should replace the old one)
        status2 = WorkerStatus.update_status(
            last_run_at=now + timedelta(seconds=60),
            phase='US_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=1,
            diagnostic_message='Found 1 setup(s)',
        )
        
        # Should still have only 1 record
        self.assertEqual(WorkerStatus.objects.count(), 1)
        
        # Should be the new status
        current = WorkerStatus.get_current()
        self.assertEqual(current.phase, 'US_CORE')
        self.assertEqual(current.setup_count, 1)
    
    def test_worker_status_str_representation(self):
        """Test worker status string representation."""
        now = timezone.now()
        status = WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
        )
        
        str_repr = str(status)
        self.assertIn('Worker Status', str_repr)
        self.assertIn('LONDON_CORE', str_repr)


class WorkerStatusAPITest(TestCase):
    """Tests for Worker Status API endpoint."""
class APISignalsSinceTest(TestCase):
    """Tests for the /api/signals/since/ endpoint."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_api_worker_status_returns_json(self):
        """Test that worker status API returns JSON."""
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertIn('success', data)
        self.assertIn('worker_status', data)
    
    def test_api_worker_status_no_data(self):
        """Test worker status when no data exists."""
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['worker_status'], 'NO_DATA')
        self.assertIsNone(data['data'])
    
    def test_api_worker_status_online(self):
        """Test worker status shows ONLINE when recent."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            spread=Decimal('0.05'),
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['worker_status'], 'ONLINE')
        self.assertIsNotNone(data['data'])
        self.assertEqual(data['data']['phase'], 'LONDON_CORE')
        self.assertEqual(data['data']['epic'], 'CC.D.CL.UNC.IP')
        self.assertEqual(data['data']['setup_count'], 0)
    
    def test_api_worker_status_offline(self):
        """Test worker status shows OFFLINE when stale."""
        # Create a status from 5 minutes ago (more than 2 * 60s threshold)
        old_time = timezone.now() - timedelta(minutes=5)
        WorkerStatus.objects.create(
            last_run_at=old_time,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['worker_status'], 'OFFLINE')
        # Data should still be present
        self.assertIsNotNone(data['data'])
    
    def test_api_worker_status_requires_login(self):
        """Test that worker status API requires login."""
        self.client.logout()
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_api_worker_status_includes_price_info(self):
        """Test that worker status includes price info."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            spread=Decimal('0.05'),
            setup_count=1,
            diagnostic_message='Found 1 setup(s)',
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('price_info', data['data'])
        self.assertEqual(data['data']['price_info']['bid'], '75.5000')
        self.assertEqual(data['data']['price_info']['ask'], '75.5500')
        self.assertEqual(data['data']['price_info']['spread'], '0.0500')


class SignalDashboardWorkerStatusTest(TestCase):
    """Tests for Worker Status in Signal Dashboard."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_signal_dashboard_shows_worker_status_section(self):
        """Test that dashboard shows worker status section."""
        response = self.client.get('/fiona/signals/')
        self.assertEqual(response.status_code, 200)
        # Check for worker status card elements
        self.assertContains(response, 'Worker Status')
        self.assertContains(response, 'worker-status')
        self.assertContains(response, 'Letzte Aktivität')
        self.assertContains(response, 'Diagnose')
    def test_api_signals_since_returns_json(self):
        """Test that API returns JSON with correct structure."""
        from django.utils import timezone
        
        # Use a timestamp from the past
        since = '2020-01-01T00:00:00Z'
        response = self.client.get(f'/fiona/api/signals/since/{since}/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertIn('now', data)
        self.assertIn('count', data)
        self.assertIn('signals', data)
        self.assertIsInstance(data['signals'], list)
    
    def test_api_signals_since_filters_by_timestamp(self):
        """Test that endpoint correctly filters signals by created_at > since."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create an old signal (before our 'since' timestamp)
        old_signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            status='ACTIVE',
        )
        # Manually set created_at to a past date
        old_signal.created_at = timezone.now() - timedelta(days=10)
        old_signal.save(update_fields=['created_at'])
        
        # Create a new signal (after our 'since' timestamp)
        new_signal = Signal.objects.create(
            setup_type='EIA_REVERSION',
            session_phase='US_CORE',
            direction='SHORT',
            trigger_price=Decimal('80.00'),
            status='ACTIVE',
        )
        
        # Use timestamp between old and new signal
        since = (timezone.now() - timedelta(days=5)).isoformat()
        response = self.client.get(f'/fiona/api/signals/since/{since}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should only contain the new signal
        self.assertEqual(data['count'], 1)
        self.assertEqual(len(data['signals']), 1)
        self.assertEqual(data['signals'][0]['id'], str(new_signal.id))
    
    def test_api_signals_since_excludes_inactive_signals(self):
        """Test that endpoint excludes non-ACTIVE signals."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create an executed signal
        Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            status='EXECUTED',
        )
        
        # Create an active signal
        active_signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='SHORT',
            status='ACTIVE',
        )
        
        since = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.get(f'/fiona/api/signals/since/{since}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should only contain the active signal
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['signals'][0]['id'], str(active_signal.id))
    
    def test_api_signals_since_invalid_timestamp(self):
        """Test that endpoint returns error for invalid timestamp."""
        response = self.client.get('/fiona/api/signals/since/invalid-timestamp/')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('error', data)
    
    def test_api_signals_since_requires_login(self):
        """Test that endpoint requires login."""
        self.client.logout()
        response = self.client.get('/fiona/api/signals/since/2020-01-01T00:00:00Z/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_api_signals_since_returns_signal_details(self):
        """Test that endpoint returns complete signal details."""
        from django.utils import timezone
        from datetime import timedelta
        
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            range_high=Decimal('78.60'),
            range_low=Decimal('77.50'),
            stop_loss=Decimal('77.80'),
            take_profit=Decimal('79.50'),
            position_size=Decimal('2.00'),
            gpt_confidence=Decimal('85.00'),
            risk_status='GREEN',
            status='ACTIVE',
        )
        
        since = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.get(f'/fiona/api/signals/since/{since}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['count'], 1)
        signal_data = data['signals'][0]
        
        # Verify all expected fields are present
        self.assertEqual(signal_data['id'], str(signal.id))
        self.assertEqual(signal_data['setup_type'], 'BREAKOUT')
        self.assertEqual(signal_data['setup_type_display'], 'Breakout')
        self.assertEqual(signal_data['session_phase'], 'LONDON_CORE')
        self.assertEqual(signal_data['session_phase_display'], 'London Core')
        self.assertEqual(signal_data['instrument'], 'CL')
        self.assertEqual(signal_data['direction'], 'LONG')
        self.assertIsNotNone(signal_data['trigger_price'])  # Just check it exists
        self.assertEqual(signal_data['risk_status'], 'GREEN')
        self.assertIn('created_at', signal_data)
    
    def test_api_signals_since_returns_now_timestamp(self):
        """Test that endpoint returns current server time."""
        from django.utils import timezone
        from datetime import timedelta
        from django.utils.dateparse import parse_datetime
        
        before_request = timezone.now()
        since = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.get(f'/fiona/api/signals/since/{since}/')
        after_request = timezone.now()
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        now_timestamp = parse_datetime(data['now'])
        self.assertIsNotNone(now_timestamp)
        # The 'now' timestamp should be between before and after request times
        self.assertGreaterEqual(now_timestamp, before_request.replace(microsecond=0))
        self.assertLessEqual(now_timestamp, after_request)


class BreakoutRangeDiagnosticsAPITest(TestCase):
    """Tests for Breakout Range Diagnostics API endpoint."""

class WorkerStatusDiagnosticsTest(TestCase):
    """Tests for WorkerStatus diagnostic criteria and countdown."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
    def test_api_breakout_range_diagnostics_requires_login(self):
        """Test that breakout range diagnostics API requires login."""
        self.client.logout()
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_api_breakout_range_diagnostics_no_worker_data(self):
        """Test breakout range diagnostics when no worker data exists.
        
        The endpoint should still return success=True with diagnostic data,
        even if worker status is not available. It will show NOT_AVAILABLE
        for range data but still provides useful configuration info.
        """
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)
        # Worker status should indicate no data
        self.assertIsNone(data['worker_status']['phase'])
    
    def test_api_breakout_range_diagnostics_with_worker_data(self):
        """Test breakout range diagnostics when worker data exists."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            spread=Decimal('0.05'),
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)
        self.assertIn('epic', data)
        self.assertIn('range_type', data)
    
    def test_api_breakout_range_diagnostics_asia_range(self):
        """Test breakout range diagnostics for Asia range."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/?range_type=asia')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['range_type'], 'asia')
        self.assertIn('range_type', data['data'])
        self.assertEqual(data['data']['range_type'], 'Asia Range')
    
    def test_api_breakout_range_diagnostics_pre_us_range(self):
        """Test breakout range diagnostics for Pre-US range."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='US_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/?range_type=pre_us')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['range_type'], 'pre_us')
        self.assertIn('range_type', data['data'])
        self.assertEqual(data['data']['range_type'], 'Pre-US Range')
    
    def test_api_breakout_range_diagnostics_custom_epic(self):
        """Test breakout range diagnostics with custom epic parameter."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        custom_epic = 'IX.D.DAX.DAILY.IP'
        response = self.client.get(f'/fiona/api/debug/breakout-range/?epic={custom_epic}')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['epic'], custom_epic)
    
    def test_api_breakout_range_diagnostics_includes_config(self):
        """Test that breakout range diagnostics includes configuration values."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Check config is present with expected keys
        self.assertIn('config', data['data'])
        config = data['data']['config']
        self.assertIn('min_range_ticks', config)
        self.assertIn('max_range_ticks', config)
        self.assertIn('min_breakout_body_fraction', config)
        self.assertIn('tick_size', config)
    
    def test_api_breakout_range_diagnostics_includes_diagnostics(self):
        """Test that breakout range diagnostics includes diagnostic messages."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Check diagnostics are present
        self.assertIn('diagnostics', data['data'])
        diagnostics = data['data']['diagnostics']
        self.assertIn('message', diagnostics)
        self.assertIn('detailed_explanation', diagnostics)

    def test_worker_status_stores_diagnostic_criteria(self):
        """Test that WorkerStatus stores diagnostic criteria."""
        now = timezone.now()
        criteria = [
            {"name": "Session Phase", "passed": True, "detail": "LONDON_CORE"},
            {"name": "Asia Range available", "passed": True, "detail": "75.0 - 75.5"},
            {"name": "Price breakout", "passed": False, "detail": "Price within range"},
        ]
        
        status = WorkerStatus.update_status(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            diagnostic_criteria=criteria,
            worker_interval=60,
        )
        
        self.assertEqual(status.diagnostic_criteria, criteria)
        
        # Retrieve and verify
        retrieved = WorkerStatus.get_current()
        self.assertEqual(len(retrieved.diagnostic_criteria), 3)
        self.assertEqual(retrieved.diagnostic_criteria[0]['name'], 'Session Phase')
        self.assertTrue(retrieved.diagnostic_criteria[0]['passed'])
    
    def test_api_worker_status_includes_diagnostic_criteria(self):
        """Test that worker status API returns diagnostic criteria."""
        now = timezone.now()
        criteria = [
            {"name": "Session Phase", "passed": True, "detail": "LONDON_CORE"},
            {"name": "Asia Range available", "passed": False, "detail": "No data"},
        ]
        
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            diagnostic_criteria=criteria,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('diagnostic_criteria', data['data'])
        self.assertEqual(len(data['data']['diagnostic_criteria']), 2)
        self.assertEqual(data['data']['diagnostic_criteria'][0]['name'], 'Session Phase')
    
    def test_api_worker_status_includes_countdown(self):
        """Test that worker status API returns countdown to next run."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now - timedelta(seconds=30),  # 30 seconds ago
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('seconds_until_next_run', data['data'])
        # Should be approximately 30 seconds (60 - 30)
        self.assertGreater(data['data']['seconds_until_next_run'], 25)
        self.assertLessEqual(data['data']['seconds_until_next_run'], 35)
    
    def test_api_worker_status_countdown_zero_when_overdue(self):
        """Test that countdown is 0 when worker is overdue."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now - timedelta(seconds=120),  # 2 minutes ago
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            worker_interval=60,  # Should have run 1 minute ago
        )
        
        response = self.client.get('/fiona/api/worker/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['data']['seconds_until_next_run'], 0)
    
    def test_worker_status_empty_criteria_default(self):
        """Test that diagnostic_criteria defaults to empty list."""
        now = timezone.now()
        status = WorkerStatus.update_status(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            setup_count=0,
            diagnostic_message='No setups found',
            # Not passing diagnostic_criteria
            worker_interval=60,
        )
        
        self.assertEqual(status.diagnostic_criteria, [])


# =============================================================================
# Trading Asset Tests
# =============================================================================

class TradingAssetModelTest(TestCase):
    """Tests for TradingAsset model."""
    
    def test_asset_creation(self):
        """Test basic trading asset creation."""
        asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        self.assertEqual(asset.name, 'US Crude Oil')
        self.assertEqual(asset.symbol, 'CL')
        self.assertEqual(asset.epic, 'CC.D.CL.UNC.IP')
        self.assertTrue(asset.is_active)
    
    def test_asset_str_representation(self):
        """Test asset string representation."""
        asset = TradingAsset.objects.create(
            name='Gold',
            symbol='GOLD',
            epic='CC.D.GOLD.UNC.IP',
            is_active=True,
        )
        
        self.assertIn('Gold', str(asset))
        self.assertIn('GOLD', str(asset))
        self.assertIn('✓', str(asset))
    
    def test_asset_inactive_str_representation(self):
        """Test inactive asset string representation."""
        asset = TradingAsset.objects.create(
            name='Silver',
            symbol='SILVER',
            epic='CC.D.SILVER.UNC.IP',
            is_active=False,
        )
        
        self.assertIn('✗', str(asset))
    
    def test_asset_epic_unique(self):
        """Test that EPIC must be unique."""
        TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        with self.assertRaises(Exception):
            TradingAsset.objects.create(
                name='WTI Duplicate',
                symbol='CL2',
                epic='CC.D.CL.UNC.IP',  # Same EPIC
            )


class AssetBreakoutConfigTest(TestCase):
    """Tests for AssetBreakoutConfig model."""
    
    def test_breakout_config_creation(self):
        """Test breakout config creation."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            asia_range_start='00:00',
            asia_range_end='08:00',
            asia_min_range_ticks=10,
            asia_max_range_ticks=200,
        )
        
        self.assertEqual(config.asset, asset)
        self.assertEqual(config.asia_range_start, '00:00')
        self.assertEqual(config.asia_min_range_ticks, 10)
    
    def test_breakout_config_one_to_one(self):
        """Test that each asset can have only one breakout config."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        AssetBreakoutConfig.objects.create(asset=asset)
        
        with self.assertRaises(Exception):
            AssetBreakoutConfig.objects.create(asset=asset)
    
    # =========================================================================
    # NEW TESTS for Extended Breakout Configuration
    # =========================================================================
    
    def test_breakout_config_london_core_fields(self):
        """Test that London Core fields are properly stored and retrieved."""
        asset = TradingAsset.objects.create(
            name='Gold',
            symbol='GOLD',
            epic='CC.D.GOLD.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            london_range_start='08:00',
            london_range_end='12:00',
            london_min_range_ticks=15,
            london_max_range_ticks=150,
        )
        
        self.assertEqual(config.london_range_start, '08:00')
        self.assertEqual(config.london_range_end, '12:00')
        self.assertEqual(config.london_min_range_ticks, 15)
        self.assertEqual(config.london_max_range_ticks, 150)
    
    def test_breakout_config_eia_fields(self):
        """Test that EIA Pre/Post fields are properly stored and retrieved."""
        asset = TradingAsset.objects.create(
            name='WTI EIA',
            symbol='CL',
            epic='CC.D.CL.EIA.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            eia_min_body_fraction=Decimal('0.70'),
            eia_required_impulse_strength=Decimal('0.60'),
            eia_reversion_window_min_sec=45,
            eia_reversion_window_max_sec=360,
            eia_max_impulse_duration_min=3,
            eia_min_impulse_atr=Decimal('0.15'),
            eia_impulse_range_high=Decimal('1.50'),
            eia_impulse_range_low=Decimal('0.25'),
        )
        
        self.assertEqual(config.eia_min_body_fraction, Decimal('0.70'))
        self.assertEqual(config.eia_required_impulse_strength, Decimal('0.60'))
        self.assertEqual(config.eia_reversion_window_min_sec, 45)
        self.assertEqual(config.eia_reversion_window_max_sec, 360)
        self.assertEqual(config.eia_max_impulse_duration_min, 3)
        self.assertEqual(config.eia_min_impulse_atr, Decimal('0.15'))
        self.assertEqual(config.eia_impulse_range_high, Decimal('1.50'))
        self.assertEqual(config.eia_impulse_range_low, Decimal('0.25'))
    
    def test_breakout_config_candle_quality_fields(self):
        """Test that candle quality filter fields are properly stored."""
        asset = TradingAsset.objects.create(
            name='NAS100',
            symbol='NAS100',
            epic='IX.D.NAS.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            min_wick_ratio=Decimal('0.30'),
            max_wick_ratio=Decimal('2.00'),
            min_candle_body_absolute=Decimal('0.05'),
            max_spread_ticks=5,
            filter_doji_breakouts=True,
        )
        
        self.assertEqual(config.min_wick_ratio, Decimal('0.30'))
        self.assertEqual(config.max_wick_ratio, Decimal('2.00'))
        self.assertEqual(config.min_candle_body_absolute, Decimal('0.05'))
        self.assertEqual(config.max_spread_ticks, 5)
        self.assertTrue(config.filter_doji_breakouts)
    
    def test_breakout_config_advanced_filter_fields(self):
        """Test that advanced filter fields are properly stored."""
        asset = TradingAsset.objects.create(
            name='DAX',
            symbol='DAX',
            epic='IX.D.DAX.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            consecutive_candle_filter=3,
            momentum_threshold=Decimal('0.25'),
            volatility_throttle_min_atr=Decimal('0.10'),
            session_volatility_cap=Decimal('2.50'),
        )
        
        self.assertEqual(config.consecutive_candle_filter, 3)
        self.assertEqual(config.momentum_threshold, Decimal('0.25'))
        self.assertEqual(config.volatility_throttle_min_atr, Decimal('0.10'))
        self.assertEqual(config.session_volatility_cap, Decimal('2.50'))
    
    def test_breakout_config_extended_atr_fields(self):
        """Test that extended ATR fields (including max ATR) are properly stored."""
        asset = TradingAsset.objects.create(
            name='EURUSD',
            symbol='EURUSD',
            epic='CS.D.EURUSD.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            require_atr_minimum=True,
            min_atr_value=Decimal('0.0015'),
            max_atr_value=Decimal('0.0050'),
        )
        
        self.assertTrue(config.require_atr_minimum)
        self.assertEqual(config.min_atr_value, Decimal('0.0015'))
        self.assertEqual(config.max_atr_value, Decimal('0.0050'))
    
    def test_breakout_config_volume_spike_field(self):
        """Test that volume spike field is properly stored."""
        asset = TradingAsset.objects.create(
            name='SP500',
            symbol='SP500',
            epic='IX.D.SP500.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(
            asset=asset,
            min_volume_spike=Decimal('1.50'),
        )
        
        self.assertEqual(config.min_volume_spike, Decimal('1.50'))
    
    def test_breakout_config_defaults(self):
        """Test that breakout config has correct default values."""
        asset = TradingAsset.objects.create(
            name='Default Test',
            symbol='TEST',
            epic='CC.D.TEST.UNC.IP',
        )
        
        config = AssetBreakoutConfig.objects.create(asset=asset)
        
        # Check all new default values
        self.assertEqual(config.london_range_start, '08:00')
        self.assertEqual(config.london_range_end, '12:00')
        self.assertEqual(config.london_min_range_ticks, 10)
        self.assertEqual(config.london_max_range_ticks, 200)
        self.assertEqual(config.eia_min_body_fraction, Decimal('0.60'))
        self.assertEqual(config.eia_required_impulse_strength, Decimal('0.50'))
        self.assertEqual(config.eia_reversion_window_min_sec, 30)
        self.assertEqual(config.eia_reversion_window_max_sec, 300)
        self.assertEqual(config.eia_max_impulse_duration_min, 5)
        self.assertEqual(config.consecutive_candle_filter, 0)
        self.assertTrue(config.filter_doji_breakouts)
        self.assertEqual(config.min_breakout_distance_ticks, 1)


class AssetEventConfigTest(TestCase):
    """Tests for AssetEventConfig model."""
    
    def test_event_config_creation(self):
        """Test event config creation."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        config = AssetEventConfig.objects.create(
            asset=asset,
            phase='EIA_POST',
            event_type='EIA',
            is_required=True,
        )
        
        self.assertEqual(config.asset, asset)
        self.assertEqual(config.phase, 'EIA_POST')
        self.assertEqual(config.event_type, 'EIA')
        self.assertTrue(config.is_required)
    
    def test_event_config_unique_per_phase(self):
        """Test that each asset can have only one config per phase."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        AssetEventConfig.objects.create(
            asset=asset,
            phase='EIA_POST',
            event_type='EIA',
        )
        
        with self.assertRaises(Exception):
            AssetEventConfig.objects.create(
                asset=asset,
                phase='EIA_POST',  # Same phase
                event_type='NONE',
            )
    
    def test_event_config_multiple_phases(self):
        """Test that asset can have configs for different phases."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        config1 = AssetEventConfig.objects.create(
            asset=asset,
            phase='LONDON_CORE',
            event_type='NONE',
        )
        
        config2 = AssetEventConfig.objects.create(
            asset=asset,
            phase='US_CORE',
            event_type='US_OPEN',
        )
        
        self.assertEqual(asset.event_configs.count(), 2)


class AssetManagementViewTest(TestCase):
    """Tests for Asset Management Views."""
    
    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_asset_list_accessible(self):
        """Test that asset list is accessible."""
        response = self.client.get('/fiona/assets/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'trading/asset_list.html')
    
    def test_asset_list_shows_assets(self):
        """Test that asset list shows existing assets."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            is_active=True,
        )
        
        response = self.client.get('/fiona/assets/')
        self.assertContains(response, 'WTI')
        self.assertContains(response, 'CL')
    
    def test_asset_create_get(self):
        """Test that asset create form is accessible."""
        response = self.client.get('/fiona/assets/create/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'trading/asset_form.html')
    
    def test_asset_create_post(self):
        """Test creating a new asset."""
        response = self.client.post('/fiona/assets/create/', {
            'name': 'Gold',
            'symbol': 'GOLD',
            'epic': 'CC.D.GOLD.UNC.IP',
            'category': 'commodity',
            'tick_size': '0.01',
            'is_active': 'on',
        })
        
        # Should redirect to asset detail on success
        self.assertEqual(response.status_code, 302)
        
        # Asset should be created
        asset = TradingAsset.objects.get(epic='CC.D.GOLD.UNC.IP')
        self.assertEqual(asset.name, 'Gold')
        self.assertTrue(asset.is_active)
        
        # Breakout config should be created automatically
        self.assertTrue(hasattr(asset, 'breakout_config'))
    
    def test_asset_detail_accessible(self):
        """Test that asset detail is accessible."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        response = self.client.get(f'/fiona/assets/{asset.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'trading/asset_detail.html')
        self.assertContains(response, 'WTI')
    
    def test_asset_toggle_active(self):
        """Test toggling asset active status."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            is_active=True,
        )
        
        response = self.client.post(f'/fiona/assets/{asset.id}/toggle-active/')
        self.assertEqual(response.status_code, 200)
        
        asset.refresh_from_db()
        self.assertFalse(asset.is_active)
    
    def test_api_active_assets(self):
        """Test API endpoint for active assets."""
        TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            is_active=True,
        )
        TradingAsset.objects.create(
            name='Gold',
            symbol='GOLD',
            epic='CC.D.GOLD.UNC.IP',
            is_active=False,
        )
        
        response = self.client.get('/fiona/api/assets/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)  # Only active assets
        self.assertEqual(data['assets'][0]['epic'], 'CC.D.CL.UNC.IP')


class SignalWithAssetTest(TestCase):
    """Tests for Signal model with TradingAsset reference."""
    
    def test_signal_with_trading_asset(self):
        """Test that signal can reference a trading asset."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='LONG',
            trading_asset=asset,
        )
        
        self.assertEqual(signal.trading_asset, asset)
        self.assertEqual(signal.trading_asset.name, 'WTI')
    
    def test_signal_without_trading_asset(self):
        """Test that signal can be created without trading asset (backwards compat)."""
        signal = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='LONG',
        )
        
        self.assertIsNone(signal.trading_asset)
    
    def test_asset_signals_related_name(self):
        """Test that we can access signals from asset via related name."""
        asset = TradingAsset.objects.create(
            name='WTI',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
        )
        
        Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            direction='LONG',
            trading_asset=asset,
        )
        Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='US_CORE',
            direction='SHORT',
            trading_asset=asset,
        )
        
        self.assertEqual(asset.signals.count(), 2)


# =============================================================================
# Breakout Range Model Tests
# =============================================================================

class BreakoutRangeModelTest(TestCase):
    """Tests for BreakoutRange model."""
    
    def setUp(self):
        """Set up test data."""
        self.asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_breakout_range_creation(self):
        """Test basic breakout range creation."""
        from .models import BreakoutRange
        
        now = timezone.now()
        start_time = now - timedelta(hours=8)
        
        br = BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=start_time,
            end_time=now,
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
            height_points=Decimal('1.00'),
            candle_count=480,
            atr=Decimal('0.50'),
            valid_flags={'incomplete_range': False, 'too_small': False},
            is_valid=True,
        )
        
        self.assertEqual(br.phase, 'ASIA_RANGE')
        self.assertEqual(br.high, Decimal('75.50'))
        self.assertEqual(br.low, Decimal('74.50'))
        self.assertEqual(br.height_ticks, 100)
        self.assertTrue(br.is_valid)
    
    def test_breakout_range_save_snapshot(self):
        """Test save_range_snapshot class method."""
        from .models import BreakoutRange
        
        now = timezone.now()
        start_time = now - timedelta(hours=4)
        
        br = BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=start_time,
            end_time=now,
            high=76.00,
            low=75.00,
            tick_size=0.01,
            candle_count=240,
            atr=0.45,
            valid_flags={'incomplete_range': False},
            is_valid=True,
        )
        
        self.assertEqual(br.phase, 'LONDON_CORE')
        self.assertEqual(br.high, Decimal('76.00'))
        self.assertEqual(br.low, Decimal('75.00'))
        self.assertEqual(br.height_points, Decimal('1.00'))
        self.assertEqual(br.height_ticks, 100)
        self.assertEqual(br.atr, Decimal('0.45'))
    
    def test_get_latest_for_asset_phase(self):
        """Test getting latest range for asset and phase."""
        from .models import BreakoutRange
        
        now = timezone.now()
        
        # Create older range
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=32),
            end_time=now - timedelta(hours=24),
            high=74.50,
            low=73.50,
            tick_size=0.01,
        )
        
        # Create newer range
        newer = BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=75.50,
            low=74.50,
            tick_size=0.01,
        )
        
        latest = BreakoutRange.get_latest_for_asset_phase(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(latest.id, newer.id)
        self.assertEqual(latest.high, Decimal('75.50'))
    
    def test_get_latest_for_asset(self):
        """Test getting latest ranges for all phases."""
        from .models import BreakoutRange
        
        now = timezone.now()
        
        # Create ranges for different phases
        asia = BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=75.50,
            low=74.50,
            tick_size=0.01,
        )
        
        london = BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=now - timedelta(hours=4),
            end_time=now,
            high=76.00,
            low=75.00,
            tick_size=0.01,
        )
        
        latest = BreakoutRange.get_latest_for_asset(self.asset)
        
        self.assertEqual(len(latest), 2)
        self.assertIn('ASIA_RANGE', latest)
        self.assertIn('LONDON_CORE', latest)
        self.assertEqual(latest['ASIA_RANGE'].id, asia.id)
        self.assertEqual(latest['LONDON_CORE'].id, london.id)
    
    def test_breakout_range_to_dict(self):
        """Test to_dict serialization."""
        from .models import BreakoutRange
        
        now = timezone.now()
        start_time = now - timedelta(hours=8)
        
        br = BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='PRE_US_RANGE',
            start_time=start_time,
            end_time=now,
            high=77.00,
            low=76.50,
            tick_size=0.01,
            candle_count=120,
            atr=0.30,
            valid_flags={'incomplete_range': False},
            is_valid=True,
        )
        
        data = br.to_dict()
        
        self.assertEqual(data['phase'], 'PRE_US_RANGE')
        self.assertEqual(data['asset_symbol'], 'CL')
        self.assertEqual(float(data['high']), 77.00)
        self.assertEqual(float(data['low']), 76.50)
        self.assertEqual(data['height_ticks'], 50)
        self.assertTrue(data['is_valid'])


class BreakoutRangeAPITest(TestCase):
    """Tests for Breakout Range API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='CL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_api_breakout_range_history(self):
        """Test breakout range history API."""
        from .models import BreakoutRange
        
        now = timezone.now()
        
        # Create some ranges
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=32),
            end_time=now - timedelta(hours=24),
            high=74.50,
            low=73.50,
            tick_size=0.01,
        )
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=75.50,
            low=74.50,
            tick_size=0.01,
        )
        
        response = self.client.get(f'/fiona/api/assets/{self.asset.id}/breakout-ranges/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 2)
        self.assertEqual(len(data['ranges']), 2)
    
    def test_api_breakout_range_history_filter_by_phase(self):
        """Test breakout range history API with phase filter."""
        from .models import BreakoutRange
        
        now = timezone.now()
        
        # Create ranges for different phases
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=75.50,
            low=74.50,
            tick_size=0.01,
        )
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=now - timedelta(hours=4),
            end_time=now,
            high=76.00,
            low=75.00,
            tick_size=0.01,
        )
        
        response = self.client.get(f'/fiona/api/assets/{self.asset.id}/breakout-ranges/?phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['ranges'][0]['phase'], 'ASIA_RANGE')
    
    def test_api_breakout_range_latest(self):
        """Test latest breakout ranges API."""
        from .models import BreakoutRange
        
        now = timezone.now()
        
        # Create ranges for different phases
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=75.50,
            low=74.50,
            tick_size=0.01,
        )
        BreakoutRange.save_range_snapshot(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=now - timedelta(hours=4),
            end_time=now,
            high=76.00,
            low=75.00,
            tick_size=0.01,
        )
        
        response = self.client.get(f'/fiona/api/assets/{self.asset.id}/breakout-ranges/latest/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('ASIA_RANGE', data['ranges'])
        self.assertIn('LONDON_CORE', data['ranges'])
    
    def test_api_breakout_range_diagnostics_all_phases(self):
        """Test breakout range diagnostics for all phases."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/?range_type=all')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['range_type'], 'all')
        self.assertIn('ASIA_RANGE', data['data'])
        self.assertIn('LONDON_CORE', data['data'])
        self.assertIn('PRE_US_RANGE', data['data'])
        self.assertIn('US_CORE_TRADING', data['data'])
    
    def test_api_breakout_range_diagnostics_london_core(self):
        """Test breakout range diagnostics for London Core."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/?range_type=london_core')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['range_type'], 'london_core')
        self.assertEqual(data['data']['range_type'], 'London Core')
    
    def test_api_breakout_range_diagnostics_us_core_trading(self):
        """Test breakout range diagnostics for US Core Trading."""
        now = timezone.now()
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='US_CORE_TRADING',
            epic='CC.D.CL.UNC.IP',
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        response = self.client.get('/fiona/api/debug/breakout-range/?range_type=us_core_trading')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['range_type'], 'us_core_trading')
        self.assertEqual(data['data']['range_type'], 'US Core Trading')
    
    def test_api_breakout_range_diagnostics_uses_asset_specific_price(self):
        """Test that breakout range diagnostics uses asset-specific price when available.
        
        This tests the fix for the issue where the "Aktueller Preis" tile in the 
        Breakout Range Diagnose card was always showing the same price regardless
        of which asset was selected.
        """
        from trading.models import AssetPriceStatus
        
        now = timezone.now()
        
        # Create worker status with one price (e.g., for WTI)
        WorkerStatus.objects.create(
            last_run_at=now,
            phase='LONDON_CORE',
            epic='CC.D.CL.UNC.IP',  # WTI
            bid_price=Decimal('75.50'),
            ask_price=Decimal('75.55'),
            setup_count=0,
            worker_interval=60,
        )
        
        # Create an asset with a different price status
        asset = TradingAsset.objects.create(
            name='Gold',
            symbol='GOLD',
            epic='CC.D.GOLD.UNC.IP',
            tick_size=Decimal('0.10'),
            is_active=True,
        )
        
        # Create asset-specific price for Gold with significantly different price
        AssetPriceStatus.update_price(
            asset=asset,
            bid_price=Decimal('2050.00'),
            ask_price=Decimal('2050.50'),
        )
        
        # Now query breakout range diagnostics for this specific asset
        response = self.client.get(f'/fiona/api/debug/breakout-range/?asset_id={asset.id}')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # The current price in diagnostics should be the asset-specific price (Gold)
        # not the worker status price (WTI)
        current_market = data['data'].get('current_market', {})
        current_price = current_market.get('price')
        
        # The expected price is the midpoint of Gold's bid/ask: (2050.00 + 2050.50) / 2 = 2050.25
        if current_price is not None:
            self.assertAlmostEqual(float(current_price), 2050.25, places=2,
                msg="Expected Gold price (~2050.25), but got a different value")
        
        # Also verify we're not getting the WTI price (75.525)
        if current_price is not None:
            self.assertNotAlmostEqual(float(current_price), 75.525, places=1,
                msg="Price should be Gold's price, not WTI's price from worker status")


# =============================================================================
# Breakout Config Form Tests (Issue: Fields not saving/displaying correctly)
# =============================================================================

class BreakoutConfigFormTest(TestCase):
    """Tests for Breakout Config Form submission and value display.
    
    Tests specifically address the issue where the following fields were not 
    being saved/displayed correctly:
    - EIA Pre/Post: Min Body für EIA, Required Impulse Strength, Min Impulse ATR, 
                    Impulse Range High, Impulse Range Low
    - Candle-Quality Filter: Min Wick Ratio, Max Wick Ratio, Min Body absolute
    - Advanced Filter: Momentum Threshold, Volatility Throttle, Session Volatility Cap
    - Breakout-Anforderungen: Min./Max. Körpergröße
    - ATR Einstellungen: Min./Max. ATR-Wert
    """
    
    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Create asset with breakout config
        self.asset = TradingAsset.objects.create(
            name='WTI Test',
            symbol='CL',
            epic='CC.D.CL.UNC.TEST',
        )
        AssetBreakoutConfig.objects.create(asset=self.asset)
    
    def test_breakout_config_form_saves_eia_fields(self):
        """Test that EIA Pre/Post fields are saved correctly when form is submitted."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'min_breakout_body_fraction': '0.50',
            'min_breakout_distance_ticks': '1',
            'consecutive_candle_filter': '0',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'filter_doji_breakouts': 'on',
            # EIA fields being tested
            'eia_min_body_fraction': '0.65',
            'eia_required_impulse_strength': '0.55',
            'eia_min_impulse_atr': '0.15',
            'eia_impulse_range_high': '1.25',
            'eia_impulse_range_low': '0.35',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify values
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertEqual(config.eia_min_body_fraction, Decimal('0.65'))
        self.assertEqual(config.eia_required_impulse_strength, Decimal('0.55'))
        self.assertEqual(config.eia_min_impulse_atr, Decimal('0.15'))
        self.assertEqual(config.eia_impulse_range_high, Decimal('1.25'))
        self.assertEqual(config.eia_impulse_range_low, Decimal('0.35'))
    
    def test_breakout_config_form_saves_candle_quality_fields(self):
        """Test that Candle-Quality Filter fields are saved correctly."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'min_breakout_body_fraction': '0.50',
            'min_breakout_distance_ticks': '1',
            'consecutive_candle_filter': '0',
            'eia_min_body_fraction': '0.60',
            'eia_required_impulse_strength': '0.50',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'filter_doji_breakouts': 'on',
            # Candle Quality fields being tested
            'min_wick_ratio': '0.30',
            'max_wick_ratio': '2.00',
            'min_candle_body_absolute': '0.05',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify values
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertEqual(config.min_wick_ratio, Decimal('0.30'))
        self.assertEqual(config.max_wick_ratio, Decimal('2.00'))
        self.assertEqual(config.min_candle_body_absolute, Decimal('0.05'))
    
    def test_breakout_config_form_saves_advanced_filter_fields(self):
        """Test that Advanced Filter fields are saved correctly."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'min_breakout_body_fraction': '0.50',
            'min_breakout_distance_ticks': '1',
            'eia_min_body_fraction': '0.60',
            'eia_required_impulse_strength': '0.50',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'filter_doji_breakouts': 'on',
            # Advanced Filter fields being tested
            'consecutive_candle_filter': '3',
            'momentum_threshold': '0.20',
            'volatility_throttle_min_atr': '0.10',
            'session_volatility_cap': '2.50',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify values
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertEqual(config.consecutive_candle_filter, 3)
        self.assertEqual(config.momentum_threshold, Decimal('0.20'))
        self.assertEqual(config.volatility_throttle_min_atr, Decimal('0.10'))
        self.assertEqual(config.session_volatility_cap, Decimal('2.50'))
    
    def test_breakout_config_form_saves_breakout_requirements(self):
        """Test that Breakout-Anforderungen fields are saved correctly."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'eia_min_body_fraction': '0.60',
            'eia_required_impulse_strength': '0.50',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'consecutive_candle_filter': '0',
            'filter_doji_breakouts': 'on',
            'min_breakout_distance_ticks': '1',
            # Breakout Requirements fields being tested
            'min_breakout_body_fraction': '0.55',
            'max_breakout_body_fraction': '0.90',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify values
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertEqual(config.min_breakout_body_fraction, Decimal('0.55'))
        self.assertEqual(config.max_breakout_body_fraction, Decimal('0.90'))
    
    def test_breakout_config_form_saves_atr_fields(self):
        """Test that ATR Einstellungen fields are saved correctly."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'min_breakout_body_fraction': '0.50',
            'min_breakout_distance_ticks': '1',
            'eia_min_body_fraction': '0.60',
            'eia_required_impulse_strength': '0.50',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'consecutive_candle_filter': '0',
            'filter_doji_breakouts': 'on',
            # ATR fields being tested
            'require_atr_minimum': 'on',
            'min_atr_value': '0.15',
            'max_atr_value': '0.50',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify values
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertTrue(config.require_atr_minimum)
        self.assertEqual(config.min_atr_value, Decimal('0.15'))
        self.assertEqual(config.max_atr_value, Decimal('0.50'))
    
    def test_breakout_config_form_displays_saved_values(self):
        """Test that saved values are displayed correctly when editing the form."""
        # First, set specific values on the config
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        config.eia_min_body_fraction = Decimal('0.65')
        config.eia_required_impulse_strength = Decimal('0.55')
        config.eia_min_impulse_atr = Decimal('0.15')
        config.eia_impulse_range_high = Decimal('1.25')
        config.eia_impulse_range_low = Decimal('0.35')
        config.min_wick_ratio = Decimal('0.30')
        config.max_wick_ratio = Decimal('2.00')
        config.min_candle_body_absolute = Decimal('0.05')
        config.momentum_threshold = Decimal('0.20')
        config.volatility_throttle_min_atr = Decimal('0.10')
        config.session_volatility_cap = Decimal('2.50')
        config.min_breakout_body_fraction = Decimal('0.55')
        config.max_breakout_body_fraction = Decimal('0.90')
        config.min_atr_value = Decimal('0.15')
        config.max_atr_value = Decimal('0.50')
        config.save()
        
        # Reload to verify save worked
        config.refresh_from_db()
        
        # Now load the form and check if values are displayed
        response = self.client.get(f'/fiona/assets/{self.asset.id}/breakout-config/')
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check that saved values appear in the form correctly using regex
        # to handle different decimal representations
        import re
        
        # Helper function to check if a value is present in the response
        def check_value(field_name, expected_value):
            # The value might be rendered with trailing zeros, so we look for
            # the pattern value="X.YZ" where the number starts with expected_value
            pattern = f'name="{field_name}"[^>]*value="({expected_value}[0-9]*)"'
            match = re.search(pattern, content)
            self.assertIsNotNone(
                match, 
                f'Could not find {field_name} with value starting with {expected_value}'
            )
        
        # EIA fields
        check_value('eia_min_body_fraction', '0.65')
        check_value('eia_required_impulse_strength', '0.55')
        check_value('eia_min_impulse_atr', '0.15')
        check_value('eia_impulse_range_high', '1.25')
        check_value('eia_impulse_range_low', '0.35')
        # Candle Quality fields
        check_value('min_wick_ratio', '0.30')
        check_value('max_wick_ratio', '2.00')
        check_value('min_candle_body_absolute', '0.05')
        # Advanced Filter fields
        check_value('momentum_threshold', '0.20')
        check_value('volatility_throttle_min_atr', '0.10')
        check_value('session_volatility_cap', '2.50')
        # Breakout Requirements
        check_value('min_breakout_body_fraction', '0.55')
        check_value('max_breakout_body_fraction', '0.90')
        # ATR fields
        check_value('min_atr_value', '0.15')
        check_value('max_atr_value', '0.50')
    
    def test_breakout_config_form_handles_empty_optional_fields(self):
        """Test that optional fields can be left empty and are saved as None."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/breakout-config/', {
            # Required fields
            'asia_range_start': '00:00',
            'asia_range_end': '08:00',
            'asia_min_range_ticks': '10',
            'asia_max_range_ticks': '200',
            'london_range_start': '08:00',
            'london_range_end': '12:00',
            'london_min_range_ticks': '10',
            'london_max_range_ticks': '200',
            'pre_us_start': '13:00',
            'pre_us_end': '15:00',
            'us_min_range_ticks': '10',
            'us_max_range_ticks': '200',
            'min_breakout_body_fraction': '0.50',
            'min_breakout_distance_ticks': '1',
            'eia_min_body_fraction': '0.60',
            'eia_required_impulse_strength': '0.50',
            'eia_reversion_window_min_sec': '30',
            'eia_reversion_window_max_sec': '300',
            'eia_max_impulse_duration_min': '5',
            'consecutive_candle_filter': '0',
            'filter_doji_breakouts': 'on',
            # Leave all optional fields empty
            'eia_min_impulse_atr': '',
            'eia_impulse_range_high': '',
            'eia_impulse_range_low': '',
            'min_wick_ratio': '',
            'max_wick_ratio': '',
            'min_candle_body_absolute': '',
            'max_spread_ticks': '',
            'momentum_threshold': '',
            'volatility_throttle_min_atr': '',
            'session_volatility_cap': '',
            'max_breakout_body_fraction': '',
            'min_atr_value': '',
            'max_atr_value': '',
            'min_volume_spike': '',
        })
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Reload config and verify optional fields are None
        config = AssetBreakoutConfig.objects.get(asset=self.asset)
        self.assertIsNone(config.eia_min_impulse_atr)
        self.assertIsNone(config.eia_impulse_range_high)
        self.assertIsNone(config.eia_impulse_range_low)
        self.assertIsNone(config.min_wick_ratio)
        self.assertIsNone(config.max_wick_ratio)
        self.assertIsNone(config.min_candle_body_absolute)
        self.assertIsNone(config.max_spread_ticks)
        self.assertIsNone(config.momentum_threshold)
        self.assertIsNone(config.volatility_throttle_min_atr)
        self.assertIsNone(config.session_volatility_cap)
        self.assertIsNone(config.max_breakout_body_fraction)
        self.assertIsNone(config.min_atr_value)
        self.assertIsNone(config.max_atr_value)
        self.assertIsNone(config.min_volume_spike)


# =============================================================================
# AssetDiagnostics Model Tests
# =============================================================================

class AssetDiagnosticsModelTest(TestCase):
    """Tests for AssetDiagnostics model."""
    
    def setUp(self):
        self.asset = TradingAsset.objects.create(
            name='Test Oil',
            symbol='OIL',
            epic='CC.D.TEST.OIL',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        self.now = timezone.now()
    
    def test_diagnostics_creation(self):
        """Test basic diagnostics record creation."""
        from .models import AssetDiagnostics
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
            current_phase='LONDON_CORE',
            trading_mode='STRICT',
        )
        
        self.assertEqual(diagnostics.asset, self.asset)
        self.assertEqual(diagnostics.current_phase, 'LONDON_CORE')
        self.assertEqual(diagnostics.trading_mode, 'STRICT')
        self.assertEqual(diagnostics.candles_evaluated, 0)
        self.assertEqual(diagnostics.setups_generated_total, 0)
    
    def test_increment_strategy_reason(self):
        """Test incrementing strategy reason codes."""
        from .models import AssetDiagnostics, ReasonCode
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
        )
        
        diagnostics.increment_strategy_reason(ReasonCode.STRAT_BODY_TOO_SMALL, 5)
        diagnostics.increment_strategy_reason(ReasonCode.STRAT_NO_RANGE, 3)
        diagnostics.increment_strategy_reason(ReasonCode.STRAT_BODY_TOO_SMALL, 2)  # Add more
        
        self.assertEqual(diagnostics.reason_counts_strategy[ReasonCode.STRAT_BODY_TOO_SMALL], 7)
        self.assertEqual(diagnostics.reason_counts_strategy[ReasonCode.STRAT_NO_RANGE], 3)
    
    def test_increment_risk_reason(self):
        """Test incrementing risk reason codes."""
        from .models import AssetDiagnostics, ReasonCode
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
        )
        
        diagnostics.increment_risk_reason(ReasonCode.RISK_SPREAD_TOO_WIDE, 4)
        diagnostics.increment_risk_reason(ReasonCode.RISK_MAX_DAILY_LOSS_REACHED, 1)
        
        self.assertEqual(diagnostics.reason_counts_risk[ReasonCode.RISK_SPREAD_TOO_WIDE], 4)
        self.assertEqual(diagnostics.reason_counts_risk[ReasonCode.RISK_MAX_DAILY_LOSS_REACHED], 1)
    
    def test_get_top_strategy_reasons(self):
        """Test getting top strategy rejection reasons."""
        from .models import AssetDiagnostics, ReasonCode
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
        )
        
        diagnostics.reason_counts_strategy = {
            ReasonCode.STRAT_BODY_TOO_SMALL: 10,
            ReasonCode.STRAT_NO_RANGE: 5,
            ReasonCode.STRAT_ATR_TOO_LOW: 3,
        }
        
        top_reasons = diagnostics.get_top_strategy_reasons(2)
        
        self.assertEqual(len(top_reasons), 2)
        self.assertEqual(top_reasons[0][0], ReasonCode.STRAT_BODY_TOO_SMALL)
        self.assertEqual(top_reasons[0][1], 10)
        self.assertEqual(top_reasons[1][0], ReasonCode.STRAT_NO_RANGE)
    
    def test_get_all_top_reasons(self):
        """Test getting all top reasons from both engines."""
        from .models import AssetDiagnostics, ReasonCode
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
        )
        
        diagnostics.reason_counts_strategy = {
            ReasonCode.STRAT_BODY_TOO_SMALL: 10,
        }
        diagnostics.reason_counts_risk = {
            ReasonCode.RISK_SPREAD_TOO_WIDE: 8,
        }
        
        top_reasons = diagnostics.get_all_top_reasons(5)
        
        self.assertEqual(len(top_reasons), 2)
        # Should be sorted by count
        self.assertEqual(top_reasons[0][0], ReasonCode.STRAT_BODY_TOO_SMALL)
        self.assertEqual(top_reasons[0][3], 'strategy')
        self.assertEqual(top_reasons[1][0], ReasonCode.RISK_SPREAD_TOO_WIDE)
        self.assertEqual(top_reasons[1][3], 'risk')
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        from .models import AssetDiagnostics
        
        diagnostics = AssetDiagnostics.objects.create(
            asset=self.asset,
            window_start=self.now - timedelta(hours=1),
            window_end=self.now,
            current_phase='US_CORE_TRADING',
            trading_mode='DIAGNOSTIC',
            candles_evaluated=100,
            setups_generated_total=5,
            setups_approved_by_risk=2,
        )
        
        data = diagnostics.to_dict()
        
        self.assertEqual(data['asset_symbol'], 'OIL')
        self.assertEqual(data['current_phase'], 'US_CORE_TRADING')
        self.assertEqual(data['trading_mode'], 'DIAGNOSTIC')
        self.assertEqual(data['counters']['candles_evaluated'], 100)
        self.assertEqual(data['counters']['setups']['generated_total'], 5)
        self.assertEqual(data['counters']['risk']['approved'], 2)
    
    def test_get_aggregated_for_period(self):
        """Test aggregating diagnostics over a time period."""
        from .models import AssetDiagnostics, ReasonCode
        
        # Create multiple diagnostics records
        for i in range(3):
            d = AssetDiagnostics.objects.create(
                asset=self.asset,
                window_start=self.now - timedelta(hours=3-i),
                window_end=self.now - timedelta(hours=2-i),
                current_phase='LONDON_CORE',
                candles_evaluated=50,
                setups_generated_total=2,
                setups_rejected_by_risk=1,
            )
            d.increment_strategy_reason(ReasonCode.STRAT_BODY_TOO_SMALL, 3)
            d.save()
        
        # Aggregate over last 4 hours
        aggregated = AssetDiagnostics.get_aggregated_for_period(
            self.asset,
            self.now - timedelta(hours=4),
            self.now
        )
        
        self.assertEqual(aggregated['record_count'], 3)
        self.assertEqual(aggregated['counters']['candles_evaluated'], 150)
        self.assertEqual(aggregated['counters']['setups']['generated_total'], 6)
        self.assertEqual(aggregated['counters']['risk']['rejected'], 3)
        self.assertEqual(aggregated['reason_counts_strategy'][ReasonCode.STRAT_BODY_TOO_SMALL], 9)


class ReasonCodeTest(TestCase):
    """Tests for ReasonCode constants and utilities."""
    
    def test_is_strategy_reason(self):
        """Test identifying strategy reasons."""
        from .models import ReasonCode
        
        self.assertTrue(ReasonCode.is_strategy_reason(ReasonCode.STRAT_BODY_TOO_SMALL))
        self.assertTrue(ReasonCode.is_strategy_reason(ReasonCode.STRAT_NO_RANGE))
        self.assertFalse(ReasonCode.is_strategy_reason(ReasonCode.RISK_SPREAD_TOO_WIDE))
    
    def test_is_risk_reason(self):
        """Test identifying risk reasons."""
        from .models import ReasonCode
        
        self.assertTrue(ReasonCode.is_risk_reason(ReasonCode.RISK_SPREAD_TOO_WIDE))
        self.assertTrue(ReasonCode.is_risk_reason(ReasonCode.RISK_MAX_DAILY_LOSS_REACHED))
        self.assertFalse(ReasonCode.is_risk_reason(ReasonCode.STRAT_BODY_TOO_SMALL))
    
    def test_get_description(self):
        """Test getting human-readable descriptions."""
        from .models import ReasonCode
        
        desc = ReasonCode.get_description(ReasonCode.STRAT_BODY_TOO_SMALL)
        self.assertEqual(desc, 'Candle body too small')
        
        desc = ReasonCode.get_description(ReasonCode.RISK_SPREAD_TOO_WIDE)
        self.assertEqual(desc, 'Spread too wide')
        
        # Unknown code should return the code itself
        desc = ReasonCode.get_description('UNKNOWN_CODE')
        self.assertEqual(desc, 'UNKNOWN_CODE')


class TradingModeTest(TestCase):
    """Tests for trading mode functionality."""
    
    def test_default_trading_mode(self):
        """Test that default trading mode is STRICT."""
        asset = TradingAsset.objects.create(
            name='Test Asset',
            symbol='TEST',
            epic='CC.D.TEST.IP',
        )
        
        self.assertEqual(asset.trading_mode, 'STRICT')
        self.assertFalse(asset.is_diagnostic_mode)
    
    def test_diagnostic_mode(self):
        """Test setting diagnostic mode."""
        asset = TradingAsset.objects.create(
            name='Test Asset',
            symbol='TEST',
            epic='CC.D.TEST.IP',
            trading_mode='DIAGNOSTIC',
        )
        
        self.assertEqual(asset.trading_mode, 'DIAGNOSTIC')
        self.assertTrue(asset.is_diagnostic_mode)
    
    def test_trading_mode_display(self):
        """Test trading mode is shown in string representation."""
        asset = TradingAsset.objects.create(
            name='Test Asset',
            symbol='TEST',
            epic='CC.D.TEST.IP',
            trading_mode='DIAGNOSTIC',
        )
        
        self.assertIn('[DIAG]', str(asset))


class DiagnosticsViewTest(TestCase):
    """Tests for diagnostics views."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.asset = TradingAsset.objects.create(
            name='Test Oil',
            symbol='OIL',
            epic='CC.D.TEST.OIL',
            is_active=True,
        )
    
    def test_diagnostics_view_requires_login(self):
        """Test that diagnostics view requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/diagnostics/')
        
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_diagnostics_view_loads(self):
        """Test that diagnostics view loads successfully."""
        response = self.client.get('/fiona/diagnostics/')
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trading Diagnostics')
        self.assertContains(response, 'Test Oil')
    
    def test_diagnostics_view_window_parameter(self):
        """Test window parameter handling."""
        response = self.client.get('/fiona/diagnostics/?window=15')
        
        self.assertEqual(response.status_code, 200)
        # Check that 15 min option is active
        self.assertContains(response, 'window=15')
    
    def test_diagnostics_api_endpoint(self):
        """Test diagnostics API endpoint."""
        response = self.client.get('/fiona/api/trading/diagnostics/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)  # One active asset
        self.assertEqual(len(data['diagnostics']), 1)
        self.assertEqual(data['diagnostics'][0]['asset_symbol'], 'OIL')
    
    def test_diagnostics_api_with_asset_filter(self):
        """Test diagnostics API with asset filter."""
        response = self.client.get(f'/fiona/api/trading/diagnostics/?asset={self.asset.id}')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)
    
    def test_toggle_trading_mode(self):
        """Test toggling trading mode via API."""
        self.assertEqual(self.asset.trading_mode, 'STRICT')
        
        response = self.client.post(f'/fiona/assets/{self.asset.id}/toggle-trading-mode/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['trading_mode'], 'DIAGNOSTIC')
        self.assertTrue(data['is_diagnostic'])
        
        # Refresh from database
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.trading_mode, 'DIAGNOSTIC')
        
        # Toggle back to STRICT
        response = self.client.post(f'/fiona/assets/{self.asset.id}/toggle-trading-mode/')
        data = response.json()
        
        self.assertEqual(data['trading_mode'], 'STRICT')
        self.assertFalse(data['is_diagnostic'])
# Session Phase Configuration Tests
# =============================================================================

from .models import AssetSessionPhaseConfig


class AssetSessionPhaseConfigModelTest(TestCase):
    """Tests for AssetSessionPhaseConfig model."""
    
    def setUp(self):
        self.asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            is_active=True,
        )
    
    def test_phase_config_creation(self):
        """Test basic phase configuration creation."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
            is_trading_phase=False,
            event_type='NONE',
            requires_event=False,
            enabled=True,
        )
        
        self.assertEqual(config.phase, 'ASIA_RANGE')
        self.assertEqual(config.start_time_utc, '00:00')
        self.assertEqual(config.end_time_utc, '08:00')
        self.assertTrue(config.is_range_build_phase)
        self.assertFalse(config.is_trading_phase)
        self.assertTrue(config.enabled)
    
    def test_phase_config_str_representation(self):
        """Test phase config string representation."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='US_CORE_TRADING',
            start_time_utc='15:00',
            end_time_utc='22:00',
            is_range_build_phase=False,
            is_trading_phase=True,
            enabled=True,
        )
        
        str_repr = str(config)
        self.assertIn('OIL', str_repr)
        self.assertIn('Trading', str_repr)
        self.assertIn('✓', str_repr)
    
    def test_phase_config_disabled_str_representation(self):
        """Test disabled phase config string representation."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='EIA_PRE',
            start_time_utc='15:25',
            end_time_utc='15:30',
            event_type='EIA',
            requires_event=True,
            enabled=False,
        )
        
        self.assertIn('✗', str(config))
    
    def test_phase_config_to_dict(self):
        """Test phase config to_dict method."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time_utc='08:00',
            end_time_utc='12:00',
            is_range_build_phase=True,
            is_trading_phase=False,
            event_type='NONE',
            requires_event=False,
            enabled=True,
            notes='Test notes',
        )
        
        data = config.to_dict()
        self.assertEqual(data['phase'], 'LONDON_CORE')
        self.assertEqual(data['start_time_utc'], '08:00')
        self.assertEqual(data['end_time_utc'], '12:00')
        self.assertTrue(data['is_range_build_phase'])
        self.assertFalse(data['is_trading_phase'])
        self.assertEqual(data['notes'], 'Test notes')
    
    def test_get_default_phases_for_oil(self):
        """Test default phases for oil assets."""
        defaults = AssetSessionPhaseConfig.get_default_phases_for_asset('OIL')
        
        # Should have all standard phases including EIA
        phases = [d['phase'] for d in defaults]
        self.assertIn('ASIA_RANGE', phases)
        self.assertIn('LONDON_CORE', phases)
        self.assertIn('PRE_US_RANGE', phases)
        self.assertIn('US_CORE_TRADING', phases)
        self.assertIn('EIA_PRE', phases)
        self.assertIn('EIA_POST', phases)
        
        # Check EIA phases have correct event type
        eia_pre = next(d for d in defaults if d['phase'] == 'EIA_PRE')
        self.assertEqual(eia_pre['event_type'], 'EIA')
        self.assertTrue(eia_pre['requires_event'])
    
    def test_get_default_phases_for_nas100(self):
        """Test default phases for NAS100 assets."""
        defaults = AssetSessionPhaseConfig.get_default_phases_for_asset('NAS100')
        
        phases = [d['phase'] for d in defaults]
        self.assertIn('ASIA_RANGE', phases)
        self.assertIn('LONDON_CORE', phases)
        self.assertIn('PRE_US_RANGE', phases)
        self.assertIn('US_CORE_TRADING', phases)
        # NAS100 should NOT have EIA phases
        self.assertNotIn('EIA_PRE', phases)
        self.assertNotIn('EIA_POST', phases)
        
        # Check US Core Trading timing for NAS100
        us_core = next(d for d in defaults if d['phase'] == 'US_CORE_TRADING')
        self.assertEqual(us_core['start_time_utc'], '14:30')  # Different from oil
    
    def test_create_default_phases_for_asset(self):
        """Test creating default phases for an asset."""
        created = AssetSessionPhaseConfig.create_default_phases_for_asset(self.asset)
        
        # Should have created multiple phases
        self.assertGreater(len(created), 4)
        
        # Verify they're in the database
        configs = AssetSessionPhaseConfig.objects.filter(asset=self.asset)
        self.assertEqual(configs.count(), len(created))
    
    def test_create_default_phases_idempotent(self):
        """Test that creating default phases is idempotent."""
        # Create defaults first time
        created1 = AssetSessionPhaseConfig.create_default_phases_for_asset(self.asset)
        count1 = AssetSessionPhaseConfig.objects.filter(asset=self.asset).count()
        
        # Create again - should not create duplicates
        created2 = AssetSessionPhaseConfig.create_default_phases_for_asset(self.asset)
        count2 = AssetSessionPhaseConfig.objects.filter(asset=self.asset).count()
        
        self.assertEqual(count1, count2)
        self.assertEqual(len(created2), 0)  # Nothing new created
    
    def test_get_phases_for_asset(self):
        """Test getting phases for an asset."""
        # Create some phases
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time_utc='08:00',
            end_time_utc='12:00',
        )
        
        phases = AssetSessionPhaseConfig.get_phases_for_asset(self.asset)
        self.assertEqual(phases.count(), 2)
    
    def test_get_enabled_phases_for_asset(self):
        """Test getting only enabled phases for an asset."""
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            enabled=True,
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time_utc='08:00',
            end_time_utc='12:00',
            enabled=False,  # Disabled
        )
        
        enabled = AssetSessionPhaseConfig.get_enabled_phases_for_asset(self.asset)
        self.assertEqual(enabled.count(), 1)
        self.assertEqual(enabled.first().phase, 'ASIA_RANGE')
    
    def test_unique_together_constraint(self):
        """Test that phase + asset must be unique."""
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
        )
        
        # Creating duplicate should raise exception
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            AssetSessionPhaseConfig.objects.create(
                asset=self.asset,
                phase='ASIA_RANGE',  # Same phase
                start_time_utc='01:00',
                end_time_utc='09:00',
            )


class PhaseConfigViewsTest(TestCase):
    """Tests for phase configuration views."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            is_active=True,
        )
    
    def test_phase_config_list_view(self):
        """Test phase config list view."""
        response = self.client.get(f'/fiona/assets/{self.asset.id}/phases/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sessions & Phases')
    
    def test_phase_config_list_with_configs(self):
        """Test phase config list view with existing configurations."""
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
        )
        
        response = self.client.get(f'/fiona/assets/{self.asset.id}/phases/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Asia Range')
    
    def test_phase_config_create_defaults(self):
        """Test creating default phase configurations."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/create-defaults/')
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Verify phases were created
        configs = AssetSessionPhaseConfig.objects.filter(asset=self.asset)
        self.assertGreater(configs.count(), 4)
    
    def test_phase_config_edit_view_get(self):
        """Test GET request to phase config edit view."""
        response = self.client.get(f'/fiona/assets/{self.asset.id}/phases/US_CORE_TRADING/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'US Core Trading')
    
    def test_phase_config_edit_view_create(self):
        """Test creating a new phase config via POST."""
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/US_CORE_TRADING/', {
            'start_time_utc': '15:00',
            'end_time_utc': '22:00',
            'is_range_build_phase': '',  # False
            'is_trading_phase': 'on',
            'event_type': 'NONE',
            'requires_event': '',  # False
            'event_offset_minutes': '0',
            'enabled': 'on',
            'notes': 'Test config',
        })
        self.assertEqual(response.status_code, 302)  # Redirect
        
        # Verify config was created
        config = AssetSessionPhaseConfig.objects.get(asset=self.asset, phase='US_CORE_TRADING')
        self.assertEqual(config.start_time_utc, '15:00')
        self.assertEqual(config.end_time_utc, '22:00')
        self.assertTrue(config.is_trading_phase)
        self.assertFalse(config.is_range_build_phase)
    
    def test_phase_config_edit_view_update(self):
        """Test updating an existing phase config via POST."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
        )
        
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/ASIA_RANGE/', {
            'start_time_utc': '01:00',  # Changed
            'end_time_utc': '09:00',    # Changed
            'is_range_build_phase': 'on',
            'is_trading_phase': '',
            'event_type': 'NONE',
            'requires_event': '',
            'event_offset_minutes': '0',
            'enabled': 'on',
            'notes': '',
        })
        self.assertEqual(response.status_code, 302)
        
        config.refresh_from_db()
        self.assertEqual(config.start_time_utc, '01:00')
        self.assertEqual(config.end_time_utc, '09:00')
    
    def test_phase_config_delete(self):
        """Test deleting a phase config."""
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
        )
        
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/ASIA_RANGE/delete/')
        self.assertEqual(response.status_code, 302)
        
        # Verify config was deleted
        self.assertFalse(
            AssetSessionPhaseConfig.objects.filter(asset=self.asset, phase='ASIA_RANGE').exists()
        )
    
    def test_phase_config_toggle(self):
        """Test toggling phase config enabled status."""
        config = AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            enabled=True,
        )
        
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/ASIA_RANGE/toggle/')
        self.assertEqual(response.status_code, 200)
        
        config.refresh_from_db()
        self.assertFalse(config.enabled)
        
        # Toggle again
        response = self.client.post(f'/fiona/assets/{self.asset.id}/phases/ASIA_RANGE/toggle/')
        config.refresh_from_db()
        self.assertTrue(config.enabled)


class PhaseConfigAPITest(TestCase):
    """Tests for phase configuration API endpoints."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.asset = TradingAsset.objects.create(
            name='US Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            is_active=True,
        )
    
    def test_api_get_phase_configs(self):
        """Test GET /api/assets/{id}/phases/ endpoint."""
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
        )
        
        response = self.client.get(f'/fiona/api/assets/{self.asset.id}/phases/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['phases'][0]['phase'], 'ASIA_RANGE')
    
    def test_api_post_phase_config(self):
        """Test POST /api/assets/{id}/phases/ endpoint to create config."""
        import json
        
        response = self.client.post(
            f'/fiona/api/assets/{self.asset.id}/phases/',
            data=json.dumps({
                'phase': 'US_CORE_TRADING',
                'start_time_utc': '15:00',
                'end_time_utc': '22:00',
                'is_range_build_phase': False,
                'is_trading_phase': True,
                'event_type': 'NONE',
                'requires_event': False,
                'enabled': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['created'])
        
        # Verify config was created
        config = AssetSessionPhaseConfig.objects.get(asset=self.asset, phase='US_CORE_TRADING')
        self.assertTrue(config.is_trading_phase)
    
    def test_api_post_phase_config_update(self):
        """Test POST /api/assets/{id}/phases/ endpoint to update config."""
        import json
        
        # Create initial config
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
        )
        
        # Update via API
        response = self.client.post(
            f'/fiona/api/assets/{self.asset.id}/phases/',
            data=json.dumps({
                'phase': 'ASIA_RANGE',
                'start_time_utc': '01:00',  # Changed
                'end_time_utc': '09:00',    # Changed
                'is_range_build_phase': True,
                'is_trading_phase': False,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertFalse(data['created'])  # Updated, not created
        
        # Verify update
        config = AssetSessionPhaseConfig.objects.get(asset=self.asset, phase='ASIA_RANGE')
        self.assertEqual(config.start_time_utc, '01:00')
    
    def test_api_active_assets_includes_phase_configs(self):
        """Test that api_active_assets includes session phase configs."""
        # Create phase configs
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='US_CORE_TRADING',
            start_time_utc='15:00',
            end_time_utc='22:00',
            is_trading_phase=True,
            enabled=True,
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='EIA_PRE',
            start_time_utc='15:25',
            end_time_utc='15:30',
            event_type='EIA',
            requires_event=True,
            enabled=False,  # Disabled
        )
        
        response = self.client.get('/fiona/api/assets/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)
        
        asset_data = data['assets'][0]
        self.assertIn('session_phase_configs', asset_data)
        # Should only include enabled phase configs
        self.assertEqual(len(asset_data['session_phase_configs']), 1)
        self.assertEqual(asset_data['session_phase_configs'][0]['phase'], 'US_CORE_TRADING')


# ============================================================================
# Price vs Range - Live Status Tests
# ============================================================================

class PriceRangeStatusServiceTest(TestCase):
    """Tests for the Price vs Range - Live Status service."""
    
    def setUp(self):
        """Set up test data."""
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        AssetBreakoutConfig.objects.create(
            asset=self.asset,
            min_breakout_distance_ticks=2,
        )
    
    def test_compute_price_range_status_no_range(self):
        """Test status computation when no range data exists."""
        from trading.services import compute_price_range_status
        
        status = compute_price_range_status(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(status.status_code, 'NO_RANGE')
        self.assertEqual(status.asset, 'OIL')
        self.assertEqual(status.phase, 'ASIA_RANGE')
    
    def test_compute_price_range_status_no_price(self):
        """Test status when range exists but no price data available."""
        from trading.services import compute_price_range_status
        from trading.models import BreakoutRange
        
        # Create range data but no price status
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
        )
        
        status = compute_price_range_status(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(status.status_code, 'NO_PRICE')
        self.assertEqual(status.status_text, 'NO PRICE DATA')
        # Range data should still be populated
        self.assertEqual(status.range_high, Decimal('75.50'))
        self.assertEqual(status.range_low, Decimal('74.50'))
        # But price data should be None
        self.assertIsNone(status.current_bid)
        self.assertIsNone(status.current_ask)
    
    def test_compute_price_range_status_inside_range(self):
        """Test status when price is inside range."""
        from trading.services import compute_price_range_status
        from trading.models import BreakoutRange, AssetPriceStatus
        
        # Create range data
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
            height_points=Decimal('1.00'),
        )
        
        # Create asset price status with price inside range
        AssetPriceStatus.objects.create(
            asset=self.asset,
            bid_price=Decimal('75.00'),
            ask_price=Decimal('75.05'),
        )
        
        status = compute_price_range_status(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(status.status_code, 'INSIDE_RANGE')
        self.assertEqual(status.range_high, Decimal('75.50'))
        self.assertEqual(status.range_low, Decimal('74.50'))
        self.assertEqual(status.current_bid, Decimal('75.00'))
    
    def test_compute_price_range_status_near_breakout_long(self):
        """Test status when price is near breakout (long side)."""
        from trading.services import compute_price_range_status
        from trading.models import BreakoutRange, AssetPriceStatus
        
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
        )
        
        # Price very close to range high (within min_breakout_distance)
        AssetPriceStatus.objects.create(
            asset=self.asset,
            bid_price=Decimal('75.49'),  # 1 tick from high
            ask_price=Decimal('75.50'),
        )
        
        status = compute_price_range_status(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(status.status_code, 'NEAR_BREAKOUT_LONG')
    
    def test_compute_price_range_status_breakout_long(self):
        """Test status when price has broken out long."""
        from trading.services import compute_price_range_status
        from trading.models import BreakoutRange, AssetPriceStatus
        
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now,
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
        )
        
        # Price clearly above range high + min_breakout_distance
        AssetPriceStatus.objects.create(
            asset=self.asset,
            bid_price=Decimal('75.60'),  # 10 ticks above high
            ask_price=Decimal('75.65'),
        )
        
        status = compute_price_range_status(self.asset, 'ASIA_RANGE')
        
        self.assertEqual(status.status_code, 'BREAKOUT_LONG')
    
    def test_price_range_status_to_dict(self):
        """Test PriceRangeStatus serialization to dict."""
        from trading.services import PriceRangeStatus
        
        status = PriceRangeStatus(
            asset='OIL',
            phase='ASIA_RANGE',
            range_high=Decimal('75.50'),
            range_low=Decimal('74.50'),
            range_ticks=100,
            tick_size=Decimal('0.01'),
            current_bid=Decimal('75.00'),
            current_ask=Decimal('75.05'),
            distance_to_high_ticks=50,
            distance_to_low_ticks=55,
            min_breakout_distance_ticks=2,
            status_code='INSIDE_RANGE',
            status_text='INSIDE RANGE',
        )
        
        data = status.to_dict()
        
        self.assertEqual(data['asset'], 'OIL')
        self.assertEqual(data['phase'], 'ASIA_RANGE')
        self.assertEqual(data['range_high'], '75.50')
        self.assertEqual(data['range_low'], '74.50')
        self.assertEqual(data['status_code'], 'INSIDE_RANGE')
        self.assertEqual(data['badge_color'], 'green')


class PriceRangeStatusAPITest(TestCase):
    """Tests for Price vs Range - Live Status API endpoints."""
    
    def setUp(self):
        """Set up test data and authenticated client."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_api_price_range_status_requires_asset_id(self):
        """Test that asset_id is required."""
        response = self.client.get('/fiona/api/price-range-status/?phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('asset_id', data['error'])
    
    def test_api_price_range_status_requires_phase(self):
        """Test that phase is required."""
        response = self.client.get(f'/fiona/api/price-range-status/?asset_id={self.asset.id}')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('phase', data['error'])
    
    def test_api_price_range_status_validates_phase(self):
        """Test that invalid phase is rejected."""
        response = self.client.get(f'/fiona/api/price-range-status/?asset_id={self.asset.id}&phase=INVALID_PHASE')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid phase', data['error'])
    
    def test_api_price_range_status_success(self):
        """Test successful price range status response."""
        response = self.client.get(f'/fiona/api/price-range-status/?asset_id={self.asset.id}&phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)
        self.assertEqual(data['data']['asset'], 'OIL')
        self.assertEqual(data['data']['phase'], 'ASIA_RANGE')
        self.assertIn('status_code', data['data'])
    
    def test_htmx_price_range_status_returns_html(self):
        """Test that HTMX endpoint returns HTML partial."""
        response = self.client.get(f'/fiona/htmx/price-range-status/?asset_id={self.asset.id}&phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
    
    def test_htmx_price_range_status_no_asset(self):
        """Test HTMX endpoint handles missing asset."""
        response = self.client.get('/fiona/htmx/price-range-status/?phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 200)
        # Should show error message in HTML
        self.assertIn(b'Kein Asset', response.content)


# ============================================================================
# PriceSnapshot Model Tests
# ============================================================================

class PriceSnapshotModelTest(TestCase):
    """Tests for the PriceSnapshot model."""
    
    def setUp(self):
        """Set up test data."""
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_snapshot_creation(self):
        """Test basic price snapshot creation."""
        from .models import PriceSnapshot
        
        snapshot = PriceSnapshot.record_snapshot(
            asset=self.asset,
            price_mid=Decimal('75.50'),
            price_bid=Decimal('75.49'),
            price_ask=Decimal('75.51'),
        )
        
        self.assertEqual(snapshot.asset, self.asset)
        self.assertEqual(snapshot.price_mid, Decimal('75.50'))
        self.assertEqual(snapshot.price_bid, Decimal('75.49'))
        self.assertEqual(snapshot.price_ask, Decimal('75.51'))
        self.assertIsNotNone(snapshot.timestamp)
    
    def test_get_recent_for_asset(self):
        """Test retrieving recent snapshots for an asset."""
        from .models import PriceSnapshot
        
        # Create some snapshots
        for i in range(5):
            PriceSnapshot.record_snapshot(
                asset=self.asset,
                price_mid=Decimal(f'75.{50 + i}'),
            )
        
        recent = PriceSnapshot.get_recent_for_asset(self.asset, minutes=60)
        self.assertEqual(recent.count(), 5)
    
    def test_get_recent_excludes_old_snapshots(self):
        """Test that old snapshots are excluded."""
        from .models import PriceSnapshot
        
        now = timezone.now()
        
        # Create a recent snapshot
        PriceSnapshot.objects.create(
            asset=self.asset,
            timestamp=now,
            price_mid=Decimal('75.50'),
        )
        
        # Create an old snapshot
        PriceSnapshot.objects.create(
            asset=self.asset,
            timestamp=now - timedelta(hours=2),
            price_mid=Decimal('74.50'),
        )
        
        recent = PriceSnapshot.get_recent_for_asset(self.asset, minutes=60)
        self.assertEqual(recent.count(), 1)
        self.assertEqual(recent.first().price_mid, Decimal('75.50'))
    
    def test_cleanup_old_snapshots(self):
        """Test cleanup of old snapshots."""
        from .models import PriceSnapshot
        
        now = timezone.now()
        
        # Create recent snapshots
        PriceSnapshot.objects.create(
            asset=self.asset,
            timestamp=now,
            price_mid=Decimal('75.50'),
        )
        
        # Create old snapshots
        for i in range(3):
            PriceSnapshot.objects.create(
                asset=self.asset,
                timestamp=now - timedelta(hours=3 + i),
                price_mid=Decimal(f'74.{50 + i}'),
            )
        
        self.assertEqual(PriceSnapshot.objects.count(), 4)
        
        deleted = PriceSnapshot.cleanup_old_snapshots(hours=2)
        self.assertEqual(deleted, 3)
        self.assertEqual(PriceSnapshot.objects.count(), 1)
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        from .models import PriceSnapshot
        
        snapshot = PriceSnapshot.record_snapshot(
            asset=self.asset,
            price_mid=Decimal('75.50'),
            price_bid=Decimal('75.49'),
            price_ask=Decimal('75.51'),
        )
        
        data = snapshot.to_dict()
        
        self.assertIn('ts', data)
        self.assertEqual(data['price'], 75.50)
        self.assertEqual(data['bid'], 75.49)
        self.assertEqual(data['ask'], 75.51)


# ============================================================================
# Breakout Distance Chart Service Tests
# ============================================================================

class BreakoutDistanceChartServiceTest(TestCase):
    """Tests for the Breakout Distance Chart service."""
    
    def setUp(self):
        """Set up test data."""
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        AssetBreakoutConfig.objects.create(
            asset=self.asset,
            min_breakout_distance_ticks=2,
        )

        AssetSessionPhaseConfig.create_default_phases_for_asset(self.asset)

    def test_get_reference_phase_london_core(self):
        """Test reference phase mapping for LONDON_CORE."""
        from trading.services.breakout_distance_chart import get_reference_phase

        self.assertEqual(get_reference_phase(self.asset, 'LONDON_CORE'), 'ASIA_RANGE')

    def test_get_reference_phase_us_core_trading(self):
        """Test reference phase mapping for US_CORE_TRADING."""
        from trading.services.breakout_distance_chart import get_reference_phase

        self.assertEqual(get_reference_phase(self.asset, 'US_CORE_TRADING'), 'PRE_US_RANGE')

    def test_get_reference_phase_pre_us_uses_london_range(self):
        """PRE_US should reference the most recent range phase (London Core)."""
        from trading.services.breakout_distance_chart import get_reference_phase

        self.assertEqual(get_reference_phase(self.asset, 'PRE_US_RANGE'), 'LONDON_CORE')

    def test_get_reference_phase_invalid(self):
        """Test reference phase mapping for invalid phase."""
        from trading.services.breakout_distance_chart import get_reference_phase

        self.assertIsNone(get_reference_phase(self.asset, 'INVALID_PHASE'))
    
    def test_compute_trend_up(self):
        """Test trend computation when prices are up."""
        from trading.services.breakout_distance_chart import compute_trend
        
        prices = [
            {'price': 75.00},
            {'price': 75.10},
            {'price': 75.20},
            {'price': 75.30},
        ]
        
        trend = compute_trend(prices, Decimal('0.01'), threshold_ticks=10)
        self.assertEqual(trend, 'up')
    
    def test_compute_trend_down(self):
        """Test trend computation when prices are down."""
        from trading.services.breakout_distance_chart import compute_trend
        
        prices = [
            {'price': 75.30},
            {'price': 75.20},
            {'price': 75.10},
            {'price': 75.00},
        ]
        
        trend = compute_trend(prices, Decimal('0.01'), threshold_ticks=10)
        self.assertEqual(trend, 'down')
    
    def test_compute_trend_sideways(self):
        """Test trend computation when prices are sideways."""
        from trading.services.breakout_distance_chart import compute_trend
        
        prices = [
            {'price': 75.00},
            {'price': 75.05},
            {'price': 74.98},
            {'price': 75.03},
        ]
        
        trend = compute_trend(prices, Decimal('0.01'), threshold_ticks=10)
        self.assertEqual(trend, 'sideways')
    
    def test_compute_trend_empty_prices(self):
        """Test trend computation with empty prices."""
        from trading.services.breakout_distance_chart import compute_trend
        
        trend = compute_trend([], Decimal('0.01'))
        self.assertEqual(trend, 'sideways')
    
    def test_get_chart_data_no_reference_phase(self):
        """Test chart data when no reference phase available."""
        from trading.services.breakout_distance_chart import get_breakout_distance_chart_data
        
        data = get_breakout_distance_chart_data(self.asset, 'ASIA_RANGE')  # ASIA_RANGE has no reference
        
        self.assertIsNotNone(data.error)
        self.assertIn('No breakout distance chart available', data.error)
    
    def test_get_chart_data_no_range(self):
        """Test chart data when no range data available."""
        from trading.services.breakout_distance_chart import get_breakout_distance_chart_data
        
        data = get_breakout_distance_chart_data(self.asset, 'LONDON_CORE')
        
        self.assertIsNotNone(data.error)
        self.assertIn('No reference range available', data.error)
    
    def test_get_chart_data_success(self):
        """Test successful chart data retrieval."""
        from trading.services.breakout_distance_chart import get_breakout_distance_chart_data
        from .models import BreakoutRange, PriceSnapshot
        
        # Create reference range (Asia Range for LONDON_CORE)
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1),
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
        )
        
        # Create price history
        for i in range(10):
            PriceSnapshot.objects.create(
                asset=self.asset,
                timestamp=now - timedelta(minutes=50 - i * 5),
                price_mid=Decimal(f'75.{i:02d}'),
            )
        
        data = get_breakout_distance_chart_data(self.asset, 'LONDON_CORE')
        
        self.assertIsNone(data.error)
        self.assertEqual(data.asset, 'OIL')
        self.assertEqual(data.phase, 'LONDON_CORE')
        self.assertEqual(data.reference_phase, 'ASIA_RANGE')
        self.assertEqual(data.range_high, Decimal('75.50'))
        self.assertEqual(data.range_low, Decimal('74.50'))
        self.assertEqual(data.min_breakout_ticks, 2)
        self.assertEqual(data.breakout_long_level, Decimal('75.52'))  # 75.50 + 0.02
        self.assertEqual(data.breakout_short_level, Decimal('74.48'))  # 74.50 - 0.02
        self.assertEqual(len(data.prices), 10)
    
    def test_to_dict(self):
        """Test chart data to_dict method."""
        from trading.services.breakout_distance_chart import BreakoutDistanceChartData
        
        data = BreakoutDistanceChartData(
            asset='OIL',
            phase='LONDON_CORE',
            reference_phase='ASIA_RANGE',
            range_high=Decimal('75.50'),
            range_low=Decimal('74.50'),
            tick_size=Decimal('0.01'),
            min_breakout_ticks=2,
            breakout_long_level=Decimal('75.52'),
            breakout_short_level=Decimal('74.48'),
            trend='up',
            prices=[{'ts': '2025-01-01T00:00:00Z', 'price': 75.0}],
        )
        
        result = data.to_dict()
        
        self.assertEqual(result['asset'], 'OIL')
        self.assertEqual(result['phase'], 'LONDON_CORE')
        self.assertEqual(result['reference_phase'], 'ASIA_RANGE')
        self.assertEqual(result['range']['high'], 75.50)
        self.assertEqual(result['range']['low'], 74.50)
        self.assertEqual(result['range']['breakout_long_level'], 75.52)
        self.assertEqual(result['trend'], 'up')
        self.assertEqual(len(result['prices']), 1)


# ============================================================================
# Breakout Distance Chart API Tests
# ============================================================================

class BreakoutDistanceChartAPITest(TestCase):
    """Tests for the Breakout Distance Chart API endpoints."""
    
    def setUp(self):
        """Set up test data and authenticated client."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        AssetBreakoutConfig.objects.create(
            asset=self.asset,
            min_breakout_distance_ticks=2,
        )
    
    def test_api_requires_phase(self):
        """Test that phase parameter is required."""
        response = self.client.get('/fiona/api/assets/OIL/diagnostics/breakout-distance-chart')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('phase', data['error'])
    
    def test_api_invalid_phase(self):
        """Test that invalid phase is rejected."""
        response = self.client.get('/fiona/api/assets/OIL/diagnostics/breakout-distance-chart?phase=ASIA_RANGE')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_api_asset_not_found(self):
        """Test handling of non-existent asset."""
        response = self.client.get('/fiona/api/assets/NONEXISTENT/diagnostics/breakout-distance-chart?phase=LONDON_CORE')
        self.assertEqual(response.status_code, 404)  # Returns 404 for not found
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not found', data['error'])
    
    def test_api_no_range_data(self):
        """Test handling when no range data available."""
        response = self.client.get('/fiona/api/assets/OIL/diagnostics/breakout-distance-chart?phase=LONDON_CORE')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No reference range', data['error'])
    
    def test_api_by_id_success(self):
        """Test API endpoint by asset ID."""
        from .models import BreakoutRange, PriceSnapshot
        
        # Create range
        now = timezone.now()
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1),
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            height_ticks=100,
        )
        
        # Create price history
        for i in range(5):
            PriceSnapshot.objects.create(
                asset=self.asset,
                timestamp=now - timedelta(minutes=30 - i * 5),
                price_mid=Decimal(f'75.{i:02d}'),
            )
        
        response = self.client.get(f'/fiona/api/assets/{self.asset.id}/diagnostics/breakout-distance-chart/?phase=LONDON_CORE')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['asset'], 'OIL')
        self.assertEqual(data['phase'], 'LONDON_CORE')
        self.assertEqual(data['reference_phase'], 'ASIA_RANGE')
        self.assertEqual(len(data['prices']), 5)
    
    def test_api_requires_login(self):
        """Test that API requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/api/assets/OIL/diagnostics/breakout-distance-chart?phase=LONDON_CORE')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


# ============================================================================
# Chart API Tests
# ============================================================================

class ChartCandlesAPITest(TestCase):
    """Tests for the Chart Candles API endpoint."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_get_candles_success(self):
        """Test successful candle retrieval with price snapshot data."""
        from .models import PriceSnapshot

        # Create price snapshots for the last hour
        now = timezone.now()
        for i in range(60):  # 60 snapshots = 60 * 1 = 60 minutes
            PriceSnapshot.objects.create(
                asset=self.asset,
                timestamp=now - timedelta(minutes=59 - i),
                price_mid=Decimal(f'75.{i:02d}'),
            )

        response = self.client.get('/fiona/api/chart/OIL/candles?hours=1')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['asset'], 'OIL')
        self.assertEqual(data['timeframe'], '1m')
        self.assertEqual(data['hours'], 1)
        self.assertIn('candles', data)
        self.assertIn('candle_count', data)
        self.assertGreater(data['candle_count'], 0)
    
    def test_get_candles_no_data(self):
        """Test candle retrieval when no data is available."""
        response = self.client.get('/fiona/api/chart/OIL/candles?hours=1')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        # Should return error when no IG API or snapshots available
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
    def test_get_candles_invalid_hours(self):
        """Test candle retrieval with invalid hours parameter."""
        response = self.client.get('/fiona/api/chart/OIL/candles?hours=5')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid hours', data['error'])
    
    def test_get_candles_asset_not_found(self):
        """Test candle retrieval for non-existent asset."""
        response = self.client.get('/fiona/api/chart/NONEXISTENT/candles?hours=1')
        self.assertEqual(response.status_code, 404)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not found', data['error'])
    
    def test_get_candles_requires_login(self):
        """Test that candles API requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/api/chart/OIL/candles?hours=1')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


class ChartBreakoutContextAPITest(TestCase):
    """Tests for the Chart Breakout Context API endpoint."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        # Create breakout config
        AssetBreakoutConfig.objects.create(
            asset=self.asset,
            min_breakout_distance_ticks=3,
        )
        
        # Create a range
        now = timezone.now()
        from .models import BreakoutRange
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1),
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            is_valid=True,
        )
    
    def test_get_breakout_context_success(self):
        """Test successful breakout context retrieval."""
        response = self.client.get('/fiona/api/chart/OIL/breakout-context')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('phase', data)
        self.assertIn('tick_size', data)
    
    def test_get_breakout_context_asset_not_found(self):
        """Test breakout context for non-existent asset."""
        response = self.client.get('/fiona/api/chart/NONEXISTENT/breakout-context')
        self.assertEqual(response.status_code, 404)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not found', data['error'])
    
    def test_get_breakout_context_requires_login(self):
        """Test that breakout context API requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/api/chart/OIL/breakout-context')
        self.assertEqual(response.status_code, 302)


class ChartSessionRangesAPITest(TestCase):
    """Tests for the Chart Session Ranges API endpoint."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        # Create ranges for different phases
        now = timezone.now()
        from .models import BreakoutRange
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1),
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            is_valid=True,
        )
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=2),
            high=Decimal('76.00'),
            low=Decimal('75.00'),
            is_valid=True,
        )
    
    def test_get_session_ranges_success(self):
        """Test successful session ranges retrieval."""
        response = self.client.get('/fiona/api/chart/OIL/session-ranges?hours=24')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['asset'], 'OIL')
        self.assertIn('ranges', data)
        
        # Check that ranges are present
        ranges = data['ranges']
        self.assertIn('ASIA_RANGE', ranges)
        self.assertIn('LONDON_CORE', ranges)
    
    def test_get_session_ranges_asset_not_found(self):
        """Test session ranges for non-existent asset."""
        response = self.client.get('/fiona/api/chart/NONEXISTENT/session-ranges?hours=24')
        self.assertEqual(response.status_code, 404)
        
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_get_session_ranges_requires_login(self):
        """Test that session ranges API requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/api/chart/OIL/session-ranges')
        self.assertEqual(response.status_code, 302)


class BreakoutDistanceChartViewTest(TestCase):
    """Tests for the Breakout Distance Chart page view."""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
    
    def test_chart_view_renders(self):
        """Test that chart view renders successfully."""
        response = self.client.get('/fiona/chart/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Breakout Distance Chart')
        self.assertContains(response, 'lightweight-charts')
    
    def test_chart_view_with_asset_param(self):
        """Test chart view with asset parameter."""
        response = self.client.get('/fiona/chart/?asset=OIL&hours=6')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'OIL')
    
    def test_chart_view_requires_login(self):
        """Test that chart view requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/chart/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


class ChartServiceTest(TestCase):
    """Tests for the Chart Service functions."""
    
    def setUp(self):
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        # Create breakout config
        AssetBreakoutConfig.objects.create(
            asset=self.asset,
            min_breakout_distance_ticks=3,
        )
        
        # Create ranges
        now = timezone.now()
        from .models import BreakoutRange
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1),
            high=Decimal('75.50'),
            low=Decimal('74.50'),
            is_valid=True,
        )
    
    def test_get_asset_by_symbol(self):
        """Test getting asset by symbol."""
        from .services.chart_service import get_asset_by_symbol
        
        asset = get_asset_by_symbol('OIL')
        self.assertIsNotNone(asset)
        self.assertEqual(asset.symbol, 'OIL')
        
        # Test case insensitivity
        asset = get_asset_by_symbol('oil')
        self.assertIsNotNone(asset)
        
        # Test non-existent asset
        asset = get_asset_by_symbol('NONEXISTENT')
        self.assertIsNone(asset)
    
    def test_get_candles_for_asset(self):
        """Test getting candles for asset with price snapshot data."""
        from .services.chart_service import get_candles_for_asset
        from .models import PriceSnapshot

        # Create price snapshots for the last hour
        now = timezone.now()
        for i in range(60):  # 60 snapshots = 60 * 1 = 60 minutes
            PriceSnapshot.objects.create(
                asset=self.asset,
                timestamp=now - timedelta(minutes=59 - i),
                price_mid=Decimal(f'75.{i:02d}'),
            )

        result = get_candles_for_asset(self.asset, hours=1, timeframe='1m')

        self.assertEqual(result.asset, 'OIL')
        self.assertEqual(result.timeframe, '1m')
        self.assertEqual(result.hours, 1)
        self.assertIsNone(result.error)
        # Should have candles from snapshot data
        self.assertGreater(len(result.candles), 0)
    
    def test_get_candles_for_asset_no_data(self):
        """Test getting candles when no data is available."""
        from .services.chart_service import get_candles_for_asset

        result = get_candles_for_asset(self.asset, hours=1, timeframe='1m')

        self.assertEqual(result.asset, 'OIL')
        # Should have error message when no data available
        self.assertIsNotNone(result.error)
        self.assertEqual(len(result.candles), 0)
    
    def test_get_breakout_context_for_asset(self):
        """Test getting breakout context for asset."""
        from .services.chart_service import get_breakout_context_for_asset
        
        context = get_breakout_context_for_asset(self.asset)
        
        self.assertIsNotNone(context.phase)
        self.assertEqual(context.tick_size, 0.01)
    
    def test_get_session_ranges_for_asset(self):
        """Test getting session ranges for asset."""
        from .services.chart_service import get_session_ranges_for_asset
        
        result = get_session_ranges_for_asset(self.asset, hours=24)
        
        self.assertEqual(result.asset, 'OIL')
        self.assertIn('ASIA_RANGE', result.ranges)
        
        asia_range = result.ranges['ASIA_RANGE']
        self.assertTrue(asia_range.is_valid)
        self.assertEqual(asia_range.high, 75.50)


# ============================================================================
# Market Data Layer Tests
# ============================================================================

class CandleModelTest(TestCase):
    """Tests for the Candle data model."""
    
    def test_candle_creation(self):
        """Test basic candle creation."""
        from core.services.market_data import Candle
        
        candle = Candle(
            timestamp=1700000000,
            open=75.50,
            high=75.75,
            low=75.25,
            close=75.60,
            volume=1000.0,
            complete=True,
        )
        
        self.assertEqual(candle.timestamp, 1700000000)
        self.assertEqual(candle.open, 75.50)
        self.assertEqual(candle.high, 75.75)
        self.assertEqual(candle.low, 75.25)
        self.assertEqual(candle.close, 75.60)
        self.assertEqual(candle.volume, 1000.0)
        self.assertTrue(candle.complete)
    
    def test_candle_to_dict(self):
        """Test candle serialization to dict."""
        from core.services.market_data import Candle
        
        candle = Candle(
            timestamp=1700000000,
            open=75.50,
            high=75.75,
            low=75.25,
            close=75.60,
        )
        
        data = candle.to_dict()
        
        self.assertEqual(data['time'], 1700000000)
        self.assertEqual(data['open'], 75.5)
        self.assertEqual(data['high'], 75.75)
        self.assertEqual(data['low'], 75.25)
        self.assertEqual(data['close'], 75.6)
    
    def test_candle_from_dict(self):
        """Test candle deserialization from dict."""
        from core.services.market_data import Candle
        
        data = {
            'time': 1700000000,
            'open': 75.50,
            'high': 75.75,
            'low': 75.25,
            'close': 75.60,
            'volume': 1000.0,
        }
        
        candle = Candle.from_dict(data)
        
        self.assertEqual(candle.timestamp, 1700000000)
        self.assertEqual(candle.open, 75.50)
        self.assertEqual(candle.high, 75.75)
        self.assertEqual(candle.volume, 1000.0)


class MarketDataConfigTest(TestCase):
    """Tests for Market Data configuration."""
    
    def test_window_config_validation(self):
        """Test window config validation."""
        from core.services.market_data import WindowConfig
        
        config = WindowConfig()
        
        # Should snap to allowed values
        self.assertEqual(config.validate_hours(1), 1)
        self.assertEqual(config.validate_hours(6), 6)
        self.assertEqual(config.validate_hours(24), 24)
        
        # Should snap to nearest allowed value
        self.assertEqual(config.validate_hours(5), 6)
        self.assertEqual(config.validate_hours(7), 6)
        
        # Should clamp to max
        self.assertEqual(config.validate_hours(100), 72)
    
    def test_timeframe_config_validation(self):
        """Test timeframe config validation."""
        from core.services.market_data import TimeframeConfig
        
        config = TimeframeConfig()
        
        self.assertEqual(config.validate_timeframe('1m'), '1m')
        self.assertEqual(config.validate_timeframe('5m'), '5m')
        self.assertEqual(config.validate_timeframe('invalid'), '1m')  # default
    
    def test_timeframe_to_minutes(self):
        """Test timeframe to minutes conversion."""
        from core.services.market_data import TimeframeConfig
        
        self.assertEqual(TimeframeConfig.to_minutes('1m'), 1)
        self.assertEqual(TimeframeConfig.to_minutes('5m'), 5)
        self.assertEqual(TimeframeConfig.to_minutes('15m'), 15)
        self.assertEqual(TimeframeConfig.to_minutes('1h'), 60)
        self.assertEqual(TimeframeConfig.to_minutes('4h'), 240)
        self.assertEqual(TimeframeConfig.to_minutes('1d'), 1440)


class RedisCandleStoreTest(TestCase):
    """Tests for Redis candle store (using in-memory fallback)."""
    
    def setUp(self):
        """Set up test data."""
        from core.services.market_data import RedisCandleStore, reset_candle_store
        reset_candle_store()
        
        # Create a store that will use in-memory fallback
        self.store = RedisCandleStore()
        self.asset_id = 'TEST_OIL'
        self.timeframe = '1m'
    
    def tearDown(self):
        """Clean up."""
        from core.services.market_data import reset_candle_store
        reset_candle_store()
    
    def test_append_and_load_candle(self):
        """Test appending and loading a single candle."""
        from core.services.market_data import Candle
        
        candle = Candle(
            timestamp=1700000000,
            open=75.50,
            high=75.75,
            low=75.25,
            close=75.60,
        )
        
        # Append
        result = self.store.append_candle(self.asset_id, self.timeframe, candle)
        self.assertTrue(result)
        
        # Load
        candles = self.store.load_candles(self.asset_id, self.timeframe)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].timestamp, 1700000000)
    
    def test_append_multiple_candles(self):
        """Test appending multiple candles."""
        from core.services.market_data import Candle
        
        candles = [
            Candle(timestamp=1700000000 + i * 60, open=75.0 + i * 0.1, high=75.5, low=74.5, close=75.2)
            for i in range(10)
        ]
        
        count = self.store.append_candles(self.asset_id, self.timeframe, candles)
        self.assertEqual(count, 10)
        
        loaded = self.store.load_candles(self.asset_id, self.timeframe)
        self.assertEqual(len(loaded), 10)
    
    def test_get_latest_candle(self):
        """Test getting latest candle."""
        from core.services.market_data import Candle
        
        candles = [
            Candle(timestamp=1700000000 + i * 60, open=75.0, high=75.5, low=74.5, close=75.0 + i * 0.1)
            for i in range(5)
        ]
        self.store.append_candles(self.asset_id, self.timeframe, candles)
        
        latest = self.store.get_latest_candle(self.asset_id, self.timeframe)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.timestamp, 1700000000 + 4 * 60)
    
    def test_clear_candles(self):
        """Test clearing candles."""
        from core.services.market_data import Candle
        
        candle = Candle(timestamp=1700000000, open=75.0, high=75.5, low=74.5, close=75.2)
        self.store.append_candle(self.asset_id, self.timeframe, candle)
        
        self.assertEqual(self.store.get_candle_count(self.asset_id, self.timeframe), 1)
        
        self.store.clear(self.asset_id, self.timeframe)
        
        self.assertEqual(self.store.get_candle_count(self.asset_id, self.timeframe), 0)


class CandleStreamTest(TestCase):
    """Tests for the CandleStream class."""
    
    def setUp(self):
        """Set up test data."""
        from core.services.market_data import CandleStream, reset_candle_store
        reset_candle_store()
        
        self.stream = CandleStream(
            asset_id='TEST_OIL',
            timeframe='1m',
            broker='IG',
            max_candles=100,
        )
    
    def tearDown(self):
        """Clean up."""
        from core.services.market_data import reset_candle_store
        reset_candle_store()
    
    def test_append_candle(self):
        """Test appending a candle to the stream."""
        from core.services.market_data import Candle
        
        candle = Candle(
            timestamp=1700000000,
            open=75.50,
            high=75.75,
            low=75.25,
            close=75.60,
        )
        
        self.stream.append(candle)
        
        self.assertEqual(self.stream.get_count(), 1)
    
    def test_get_recent_candles(self):
        """Test getting recent candles."""
        from core.services.market_data import Candle
        from datetime import datetime, timezone
        
        now = int(datetime.now(timezone.utc).timestamp())
        
        # Add some candles
        for i in range(10):
            candle = Candle(
                timestamp=now - (10 - i) * 60,  # 10 minutes ago to now
                open=75.0 + i * 0.1,
                high=75.5,
                low=74.5,
                close=75.2,
            )
            self.stream.append(candle, persist=False)
        
        # Get all recent
        candles = self.stream.get_recent()
        self.assertEqual(len(candles), 10)
        
        # Get by count
        candles = self.stream.get_recent(count=5)
        self.assertEqual(len(candles), 5)
    
    def test_stream_status(self):
        """Test getting stream status."""
        status = self.stream.get_status()
        
        self.assertEqual(status.asset_id, 'TEST_OIL')
        self.assertEqual(status.timeframe, '1m')
        self.assertEqual(status.broker, 'IG')
        self.assertEqual(status.candle_count, 0)


class MarketDataStreamManagerTest(TestCase):
    """Tests for MarketDataStreamManager."""
    
    def setUp(self):
        """Set up test data."""
        from core.services.market_data import MarketDataStreamManager
        
        self.asset = TradingAsset.objects.create(
            name='Test Oil',
            symbol='TEST_OIL',
            epic='CC.D.CL.UNC.IP',
            category='commodity',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        # Reset singleton for clean test
        MarketDataStreamManager.reset_instance()
        self.manager = MarketDataStreamManager()
    
    def tearDown(self):
        """Clean up."""
        from core.services.market_data import MarketDataStreamManager
        MarketDataStreamManager.reset_instance()
    
    def test_get_or_create_stream(self):
        """Test stream creation."""
        stream = self.manager.get_or_create_stream('TEST_OIL', '1m', 'IG')
        
        self.assertIsNotNone(stream)
        self.assertEqual(stream.asset_id, 'TEST_OIL')
        self.assertEqual(stream.timeframe, '1m')
    
    def test_get_stream_status(self):
        """Test getting stream status."""
        self.manager.get_or_create_stream('TEST_OIL', '1m', 'IG')
        
        status = self.manager.get_stream_status('TEST_OIL', '1m')
        
        self.assertEqual(status.asset_id, 'TEST_OIL')
        self.assertEqual(status.timeframe, '1m')
    
    def test_get_all_stream_statuses(self):
        """Test getting all stream statuses."""
        self.manager.get_or_create_stream('TEST_OIL', '1m', 'IG')
        self.manager.get_or_create_stream('TEST_OIL', '5m', 'IG')

        statuses = self.manager.get_all_stream_statuses()

        self.assertEqual(len(statuses), 2)

    def test_ig_allowance_error_returns_cached_status(self):
        """Handle IG allowance errors with a friendly message and cached status."""
        from core.services.broker.broker_service import BrokerError
        from core.services.market_data.candle_models import Candle

        stream = self.manager.get_or_create_stream('TEST_OIL', '1m', 'IG')
        stream.append(Candle(timestamp=1, open=1.0, high=1.0, low=1.0, close=1.0))

        error = BrokerError(
            "IG API error [error.public-api.exceeded-account-historical-data-allowance]: {}",
            code='400',
        )

        with patch('core.services.broker.BrokerRegistry') as MockRegistry, \
                patch.object(self.manager, '_fetch_historical_prices', side_effect=error):
            MockRegistry.return_value.get_broker_for_asset.return_value = MagicMock()

            self.manager._fetch_candles_from_broker(self.asset, stream, '1m', 1)

        self.assertEqual(stream.status, 'CACHED')
        self.assertEqual(
            stream.error,
            'IG API-Limit für historische Daten erreicht. Bitte später erneut versuchen.',
        )

    def test_ig_historical_prices_caps_data_points(self):
        """Test that IG historical prices are capped to 50 points to conserve allowance."""
        from core.services.broker.ig_broker_service import IgBrokerService

        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.get_historical_prices.return_value = []

        # Request 360 points (6 hours * 60 minutes for 1m timeframe)
        self.manager._fetch_historical_prices(
            broker=mock_broker,
            symbol='TEST_OIL',
            epic='CC.D.CL.UNC.IP',
            timeframe='1m',
            num_points=360,
        )

        # Verify that the broker was called with max 50 points
        mock_broker.get_historical_prices.assert_called_once()
        call_kwargs = mock_broker.get_historical_prices.call_args[1]
        self.assertEqual(call_kwargs['num_points'], 50)
        self.assertEqual(call_kwargs['resolution'], 'MINUTE')
        self.assertEqual(call_kwargs['epic'], 'CC.D.CL.UNC.IP')


class BreakoutDistanceCandlesAPITest(TestCase):
    """Tests for the new breakout distance candles API endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        self.asset = TradingAsset.objects.create(
            name='Crude Oil',
            symbol='OIL',
            epic='CC.D.CL.UNC.IP',
            tick_size=Decimal('0.01'),
            is_active=True,
        )
        
        from core.services.market_data import MarketDataStreamManager
        MarketDataStreamManager.reset_instance()
    
    def tearDown(self):
        """Clean up."""
        from core.services.market_data import MarketDataStreamManager
        MarketDataStreamManager.reset_instance()
    
    def test_api_requires_asset_id(self):
        """Test that asset_id is required."""
        response = self.client.get('/fiona/api/breakout-distance-candles')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('asset_id', data['error'])
    
    def test_api_returns_response(self):
        """Test that API returns a valid response."""
        response = self.client.get(f'/fiona/api/breakout-distance-candles?asset_id={self.asset.id}')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['asset'], 'OIL')
        self.assertIn('timeframe', data)
        self.assertIn('window_hours', data)
        self.assertIn('candles', data)
        self.assertIn('status', data)
    
    def test_api_with_timeframe_param(self):
        """Test API with timeframe parameter."""
        response = self.client.get(f'/fiona/api/breakout-distance-candles?asset_id={self.asset.id}&timeframe=5m')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['timeframe'], '5m')
    
    def test_api_with_window_param(self):
        """Test API with window parameter."""
        response = self.client.get(f'/fiona/api/breakout-distance-candles?asset_id={self.asset.id}&window=12')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['window_hours'], 12.0)
    
    def test_api_asset_not_found(self):
        """Test API with non-existent asset."""
        response = self.client.get('/fiona/api/breakout-distance-candles?asset_id=99999')
        self.assertEqual(response.status_code, 404)
        
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_api_requires_login(self):
        """Test that API requires authentication."""
        self.client.logout()
        response = self.client.get(f'/fiona/api/breakout-distance-candles?asset_id={self.asset.id}')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_api_status_includes_data_source(self):
        """Test that status includes data source indicator."""
        response = self.client.get(f'/fiona/api/breakout-distance-candles?asset_id={self.asset.id}')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        status = data['status']
        
        self.assertIn('status', status)
        # Status should be one of the valid values
        self.assertIn(status['status'], ['LIVE', 'POLL', 'CACHED', 'OFFLINE'])


class MarketDataStatusAPITest(TestCase):
    """Tests for the market data status API endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.login(username='testuser', password='password')
        
        from core.services.market_data import MarketDataStreamManager
        MarketDataStreamManager.reset_instance()
    
    def tearDown(self):
        """Clean up."""
        from core.services.market_data import MarketDataStreamManager
        MarketDataStreamManager.reset_instance()
    
    def test_status_api_returns_empty_initially(self):
        """Test that status API returns empty initially."""
        response = self.client.get('/fiona/api/market-data/status/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_streams'], 0)
        self.assertEqual(len(data['streams']), 0)
    
    def test_status_api_requires_login(self):
        """Test that status API requires authentication."""
        self.client.logout()
        response = self.client.get('/fiona/api/market-data/status/')
        self.assertEqual(response.status_code, 302)


class BulkDeleteSignalsTest(TestCase):
    """Tests for bulk signal deletion functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        # Create test signals with different risk statuses
        self.signal_green = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='LONG',
            trigger_price=Decimal('78.50'),
            risk_status='GREEN',
            status='ACTIVE'
        )
        
        self.signal_yellow = Signal.objects.create(
            setup_type='BREAKOUT',
            session_phase='LONDON_CORE',
            instrument='CL',
            direction='SHORT',
            trigger_price=Decimal('77.50'),
            risk_status='YELLOW',
            status='ACTIVE'
        )
        
        self.signal_red_1 = Signal.objects.create(
            setup_type='EIA_REVERSION',
            session_phase='EIA_POST',
            instrument='CL',
            direction='LONG',
            trigger_price=Decimal('79.00'),
            risk_status='RED',
            status='ACTIVE'
        )
        
        self.signal_red_2 = Signal.objects.create(
            setup_type='EIA_TRENDDAY',
            session_phase='EIA_POST',
            instrument='CL',
            direction='SHORT',
            trigger_price=Decimal('76.00'),
            risk_status='RED',
            status='ACTIVE'
        )
    
    def test_delete_forbidden_signals(self):
        """Test deleting all forbidden (RED) signals."""
        response = self.client.post('/fiona/signals/delete-forbidden/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['deleted_count'], 2)
        
        # Verify RED signals are deleted
        self.assertFalse(Signal.objects.filter(id=self.signal_red_1.id).exists())
        self.assertFalse(Signal.objects.filter(id=self.signal_red_2.id).exists())
        
        # Verify other signals still exist
        self.assertTrue(Signal.objects.filter(id=self.signal_green.id).exists())
        self.assertTrue(Signal.objects.filter(id=self.signal_yellow.id).exists())
    
    def test_delete_selected_signals(self):
        """Test deleting selected signals."""
        signal_ids = [str(self.signal_green.id), str(self.signal_red_1.id)]
        response = self.client.post(
            '/fiona/signals/delete-selected/',
            data=json.dumps({'signal_ids': signal_ids}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['deleted_count'], 2)
        
        # Verify selected signals are deleted
        self.assertFalse(Signal.objects.filter(id=self.signal_green.id).exists())
        self.assertFalse(Signal.objects.filter(id=self.signal_red_1.id).exists())
        
        # Verify other signals still exist
        self.assertTrue(Signal.objects.filter(id=self.signal_yellow.id).exists())
        self.assertTrue(Signal.objects.filter(id=self.signal_red_2.id).exists())
    
    def test_delete_selected_signals_empty_list(self):
        """Test deleting with empty signal list."""
        response = self.client.post(
            '/fiona/signals/delete-selected/',
            data=json.dumps({'signal_ids': []}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_delete_selected_signals_invalid_json(self):
        """Test deleting with invalid JSON."""
        response = self.client.post(
            '/fiona/signals/delete-selected/',
            data='invalid json',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_delete_forbidden_requires_login(self):
        """Test that delete forbidden requires authentication."""
        self.client.logout()
        response = self.client.post('/fiona/signals/delete-forbidden/')
        self.assertEqual(response.status_code, 302)
    
    def test_delete_selected_requires_login(self):
        """Test that delete selected requires authentication."""
        self.client.logout()
        response = self.client.post('/fiona/signals/delete-selected/')
        self.assertEqual(response.status_code, 302)


class TimeSinceShortFilterTest(TestCase):
    """Tests for the timesince_short template filter."""
    
    def test_timesince_short_seconds(self):
        """Test timesince_short for seconds."""
        from trading.templatetags.trading_tags import timesince_short
        
        now = timezone.now()
        time_ago = now - timedelta(seconds=30)
        result = timesince_short(time_ago)
        self.assertIn('Sek.', result)
    
    def test_timesince_short_minutes(self):
        """Test timesince_short for minutes."""
        from trading.templatetags.trading_tags import timesince_short
        
        now = timezone.now()
        time_ago = now - timedelta(minutes=15)
        result = timesince_short(time_ago)
        self.assertIn('Min.', result)
    
    def test_timesince_short_hours(self):
        """Test timesince_short for hours."""
        from trading.templatetags.trading_tags import timesince_short
        
        now = timezone.now()
        time_ago = now - timedelta(hours=3)
        result = timesince_short(time_ago)
        self.assertIn('Std.', result)
    
    def test_timesince_short_days(self):
        """Test timesince_short for days."""
        from trading.templatetags.trading_tags import timesince_short
        
        now = timezone.now()
        time_ago = now - timedelta(days=5)
        result = timesince_short(time_ago)
        self.assertIn('Tag', result)
    
    def test_timesince_short_none(self):
        """Test timesince_short with None value."""
        from trading.templatetags.trading_tags import timesince_short
        
        result = timesince_short(None)
        self.assertEqual(result, '')
