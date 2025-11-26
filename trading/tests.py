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

