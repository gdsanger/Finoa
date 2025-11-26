from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
import uuid

from .models import Signal, Trade, WorkerStatus, TradingAsset, AssetBreakoutConfig, AssetEventConfig


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



class WorkerStatusDiagnosticsTest(TestCase):
    """Tests for WorkerStatus diagnostic criteria and countdown."""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
    
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
