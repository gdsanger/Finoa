from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
import uuid

from .models import Signal, Trade, WorkerStatus


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
        """Test breakout range diagnostics when no worker data exists."""
        response = self.client.get('/fiona/api/debug/breakout-range/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
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

