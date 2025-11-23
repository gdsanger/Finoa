from django.test import TestCase
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
import tempfile
import os

import fitz  # PyMuPDF

from .models import Account, Category, Booking, RecurringBooking, Payee, KIGateConfig, OpenAIConfig, DocumentUpload
from .services import (
    calculate_actual_balance,
    calculate_forecast_balance,
    create_transfer,
    generate_virtual_bookings,
)


class AccountModelTest(TestCase):
    def test_account_creation(self):
        account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.assertEqual(account.name, 'Test Account')
        self.assertEqual(account.initial_balance, Decimal('1000.00'))
        self.assertTrue(account.is_active)


class FinanceEngineTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(name='Test Category')

    def test_actual_balance_calculation(self):
        # Initially, balance should equal initial_balance
        balance = calculate_actual_balance(self.account)
        self.assertEqual(balance, Decimal('1000.00'))

        # Add a posted booking
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('500.00'),
            status='POSTED'
        )

        balance = calculate_actual_balance(self.account)
        self.assertEqual(balance, Decimal('1500.00'))

    def test_planned_bookings_excluded_from_actual(self):
        # Add a planned booking
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('500.00'),
            status='PLANNED'
        )

        # Actual balance should not include planned bookings
        balance = calculate_actual_balance(self.account)
        self.assertEqual(balance, Decimal('1000.00'))

    def test_forecast_balance_includes_planned(self):
        # Add posted and planned bookings
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('500.00'),
            status='POSTED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=date.today() + relativedelta(days=5),
            amount=Decimal('200.00'),
            status='PLANNED'
        )

        # Forecast should include both when forecasting to future date
        future_date = date.today() + relativedelta(days=10)
        balance = calculate_forecast_balance(self.account, as_of_date=future_date, include_recurring=False)
        self.assertEqual(balance, Decimal('1700.00'))

    def test_transfer_creation(self):
        account2 = Account.objects.create(
            name='Account 2',
            type='checking',
            initial_balance=Decimal('500.00')
        )

        from_booking, to_booking = create_transfer(
            from_account=self.account,
            to_account=account2,
            amount=100,
            booking_date=date.today(),
            description='Test Transfer'
        )

        # Check bookings are created correctly
        self.assertEqual(from_booking.amount, Decimal('-100.00'))
        self.assertEqual(to_booking.amount, Decimal('100.00'))
        self.assertTrue(from_booking.is_transfer)
        self.assertTrue(to_booking.is_transfer)
        self.assertEqual(from_booking.transfer_group_id, to_booking.transfer_group_id)

        # Check balances
        balance1 = calculate_actual_balance(self.account)
        balance2 = calculate_actual_balance(account2)
        self.assertEqual(balance1, Decimal('900.00'))
        self.assertEqual(balance2, Decimal('600.00'))


class RecurringBookingTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(name='Salary')

    def test_virtual_booking_generation(self):
        # Create a monthly recurring booking
        recurring = RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('3000.00'),
            category=self.category,
            description='Monthly Salary',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            interval=1,
            day_of_month=1,
            is_active=True
        )

        # Generate virtual bookings for 3 months
        start = date(2025, 1, 1)
        end = date(2025, 3, 31)
        virtual_bookings = generate_virtual_bookings(
            account=self.account,
            start_date=start,
            end_date=end
        )

        # Should have 3 monthly occurrences
        self.assertEqual(len(virtual_bookings), 3)
        self.assertEqual(virtual_bookings[0]['amount'], Decimal('3000.00'))

    def test_recurring_transfer_virtual_bookings(self):
        # Create a second account for transfer target
        account2 = Account.objects.create(
            name='Savings Account',
            type='checking',
            initial_balance=Decimal('500.00')
        )

        # Create a recurring transfer booking
        recurring = RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-200.00'),  # Negative amount represents outflow from source account
            category=self.category,
            description='Monthly Savings Transfer',
            start_date=date(2025, 1, 15),
            frequency='MONTHLY',
            interval=1,
            day_of_month=15,
            is_active=True,
            is_transfer=True,
            transfer_partner_account=account2
        )

        # Generate virtual bookings for both accounts
        start = date(2025, 1, 1)
        end = date(2025, 3, 31)
        
        # Get virtual bookings for source account
        virtual_bookings_from = generate_virtual_bookings(
            account=self.account,
            start_date=start,
            end_date=end
        )
        
        # Get virtual bookings for target account
        virtual_bookings_to = generate_virtual_bookings(
            account=account2,
            start_date=start,
            end_date=end
        )

        # Should have 3 monthly occurrences in source account
        self.assertEqual(len(virtual_bookings_from), 3)
        self.assertEqual(virtual_bookings_from[0]['amount'], Decimal('-200.00'))
        self.assertTrue(virtual_bookings_from[0]['is_transfer'])
        self.assertEqual(virtual_bookings_from[0]['transfer_partner_account'], account2)

        # Should also have 3 monthly occurrences in target account (counter-bookings)
        self.assertEqual(len(virtual_bookings_to), 3)
        self.assertEqual(virtual_bookings_to[0]['amount'], Decimal('200.00'))
        self.assertTrue(virtual_bookings_to[0]['is_transfer'])
        self.assertEqual(virtual_bookings_to[0]['transfer_partner_account'], self.account)

        # Verify dates match
        for i in range(3):
            self.assertEqual(virtual_bookings_from[i]['date'], virtual_bookings_to[i]['date'])

    def test_recurring_transfer_forecast_balance(self):
        # Create a second account for transfer target
        account2 = Account.objects.create(
            name='Savings Account',
            type='checking',
            initial_balance=Decimal('500.00')
        )

        # Use today's date as reference
        today = date.today()
        next_month = today + relativedelta(months=1)
        three_months_later = today + relativedelta(months=3)

        # Create a recurring transfer booking: 200 from account1 to account2 monthly
        recurring = RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-200.00'),  # Negative amount represents outflow from source account
            category=self.category,
            description='Monthly Savings Transfer',
            start_date=next_month,
            frequency='MONTHLY',
            interval=1,
            day_of_month=15,
            is_active=True,
            is_transfer=True,
            transfer_partner_account=account2
        )

        # Calculate forecast balance for both accounts after 3 months
        forecast_date = three_months_later
        
        balance1 = calculate_forecast_balance(self.account, as_of_date=forecast_date, include_recurring=True)
        balance2 = calculate_forecast_balance(account2, as_of_date=forecast_date, include_recurring=True)

        # account1 should have: 1000 (initial) - 600 (3x200) = 400
        self.assertEqual(balance1, Decimal('400.00'))
        
        # account2 should have: 500 (initial) + 600 (3x200) = 1100
        self.assertEqual(balance2, Decimal('1100.00'))


class ViewTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.client.login(username='testuser', password='testpass123')

    def test_dashboard_view(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')

    def test_dashboard_view_requires_login(self):
        self.client.logout()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    def test_accounts_view(self):
        response = self.client.get('/accounts/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Account')

    def test_accounts_view_requires_login(self):
        self.client.logout()
        response = self.client.get('/accounts/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    def test_monthly_view(self):
        response = self.client.get('/monthly/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Monatsansicht')

    def test_category_analytics_view(self):
        response = self.client.get('/analytics/categories/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kategorien-Auswertung')
        self.assertContains(response, 'Gesamtausgaben')
        self.assertContains(response, 'Gesamteinnahmen')

    def test_payees_view(self):
        response = self.client.get('/payees/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Zahlungsempfänger')
        self.assertContains(response, 'Neuer Zahlungsempfänger')


class AnalyticsEngineTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.income_category = Category.objects.create(name='Salary', type='income')
        self.expense_category = Category.objects.create(name='Groceries', type='expense')

    def test_category_analysis_basic(self):
        from .services import get_category_analysis
        
        # Create bookings
        Booking.objects.create(
            account=self.account,
            booking_date=date(2025, 11, 1),
            amount=Decimal('3000.00'),
            category=self.income_category,
            status='POSTED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=date(2025, 11, 15),
            amount=Decimal('-500.00'),
            category=self.expense_category,
            status='POSTED'
        )

        # Analyze
        analysis = get_category_analysis(
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 30)
        )

        self.assertEqual(analysis['total_income'], Decimal('3000.00'))
        self.assertEqual(analysis['total_expenses'], Decimal('500.00'))
        self.assertEqual(analysis['total_net'], Decimal('2500.00'))
        self.assertIn('Salary', analysis['income_by_category'])
        self.assertIn('Groceries', analysis['expenses_by_category'])

    def test_category_analysis_with_account_filter(self):
        from .services import get_category_analysis
        
        account2 = Account.objects.create(
            name='Account 2',
            type='checking',
            initial_balance=Decimal('500.00')
        )

        # Create bookings on different accounts
        Booking.objects.create(
            account=self.account,
            booking_date=date(2025, 11, 1),
            amount=Decimal('-100.00'),
            category=self.expense_category,
            status='POSTED'
        )
        Booking.objects.create(
            account=account2,
            booking_date=date(2025, 11, 1),
            amount=Decimal('-200.00'),
            category=self.expense_category,
            status='POSTED'
        )

        # Analyze only first account
        analysis = get_category_analysis(
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 30),
            account=self.account
        )

        # Should only include bookings from first account
        self.assertEqual(analysis['total_expenses'], Decimal('100.00'))

    def test_category_analysis_excludes_planned(self):
        from .services import get_category_analysis
        
        # Create posted and planned bookings
        Booking.objects.create(
            account=self.account,
            booking_date=date(2025, 11, 1),
            amount=Decimal('-100.00'),
            category=self.expense_category,
            status='POSTED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=date(2025, 11, 15),
            amount=Decimal('-200.00'),
            category=self.expense_category,
            status='PLANNED'
        )

        # Analyze with POSTED status (default)
        analysis = get_category_analysis(
            start_date=date(2025, 11, 1),
            end_date=date(2025, 11, 30),
            status='POSTED'
        )

        # Should only include posted bookings
        self.assertEqual(analysis['total_expenses'], Decimal('100.00'))


class PayeeModelTest(TestCase):
    def test_payee_creation(self):
        """Test basic payee creation"""
        payee = Payee.objects.create(
            name='Amazon',
            note='Online shopping'
        )
        self.assertEqual(payee.name, 'Amazon')
        self.assertEqual(payee.note, 'Online shopping')
        self.assertTrue(payee.is_active)
        self.assertEqual(str(payee), 'Amazon')

    def test_payee_in_booking(self):
        """Test that a booking can have a payee"""
        account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        payee = Payee.objects.create(name='Netflix')
        category = Category.objects.create(name='Entertainment')
        
        booking = Booking.objects.create(
            account=account,
            booking_date=date.today(),
            amount=Decimal('-15.99'),
            category=category,
            payee=payee,
            description='Monthly subscription',
            status='POSTED'
        )
        
        self.assertEqual(booking.payee, payee)
        self.assertEqual(booking.payee.name, 'Netflix')

    def test_payee_in_recurring_booking(self):
        """Test that a recurring booking can have a payee"""
        account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        payee = Payee.objects.create(name='Landlord')
        category = Category.objects.create(name='Rent')
        
        recurring = RecurringBooking.objects.create(
            account=account,
            amount=Decimal('-1200.00'),
            category=category,
            payee=payee,
            description='Monthly rent',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            day_of_month=1,
            is_active=True
        )
        
        self.assertEqual(recurring.payee, payee)
        self.assertEqual(recurring.payee.name, 'Landlord')

    def test_payee_in_virtual_bookings(self):
        """Test that virtual bookings from recurring bookings include payee"""
        account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        payee = Payee.objects.create(name='Gym')
        category = Category.objects.create(name='Health')
        
        recurring = RecurringBooking.objects.create(
            account=account,
            amount=Decimal('-50.00'),
            category=category,
            payee=payee,
            description='Gym membership',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            day_of_month=1,
            is_active=True
        )
        
        # Generate virtual bookings
        start = date(2025, 1, 1)
        end = date(2025, 3, 31)
        virtual_bookings = generate_virtual_bookings(
            account=account,
            start_date=start,
            end_date=end
        )
        
        # Check that virtual bookings have the payee
        self.assertEqual(len(virtual_bookings), 3)
        for vb in virtual_bookings:
            self.assertEqual(vb['payee'], payee)

    def test_payee_deletion_sets_null(self):
        """Test that deleting a payee sets booking.payee to NULL"""
        account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        payee = Payee.objects.create(name='Test Payee')
        
        booking = Booking.objects.create(
            account=account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            payee=payee,
            status='POSTED'
        )
        
        # Delete payee
        payee.delete()
        
        # Reload booking
        booking.refresh_from_db()
        self.assertIsNone(booking.payee)


class AccountLiquidityRelevanceTest(TestCase):
    def test_account_liquidity_relevance_default(self):
        """Test that accounts are liquidity-relevant by default"""
        account = Account.objects.create(
            name='Checking Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.assertTrue(account.is_liquidity_relevant)

    def test_account_liquidity_relevance_false(self):
        """Test setting account as not liquidity-relevant"""
        account = Account.objects.create(
            name='Savings Account',
            type='loan',
            initial_balance=Decimal('5000.00'),
            is_liquidity_relevant=False
        )
        self.assertFalse(account.is_liquidity_relevant)

    def test_total_liquidity_with_filter(self):
        """Test that get_total_liquidity can filter by liquidity relevance"""
        from .services import get_total_liquidity
        
        # Create liquidity-relevant account
        checking = Account.objects.create(
            name='Checking',
            type='checking',
            initial_balance=Decimal('1000.00'),
            is_liquidity_relevant=True
        )
        
        # Create non-liquidity-relevant account (e.g., loan)
        loan = Account.objects.create(
            name='Loan',
            type='loan',
            initial_balance=Decimal('-5000.00'),
            is_liquidity_relevant=False
        )
        
        # Test without filter - should include both
        total_all = get_total_liquidity(liquidity_relevant_only=False)
        self.assertEqual(total_all, Decimal('-4000.00'))
        
        # Test with filter - should only include checking account
        total_liquid = get_total_liquidity(liquidity_relevant_only=True)
        self.assertEqual(total_liquid, Decimal('1000.00'))


class KIGateConfigModelTest(TestCase):
    """Tests for KIGateConfig model."""
    
    def test_kigate_config_creation(self):
        """Test basic KIGate configuration creation"""
        config = KIGateConfig.objects.create(
            name='Test KIGate',
            base_url='https://kigate.example.com',
            api_key='test-api-key-123',
            max_tokens=2000,
            default_agent_name='test-agent',
            default_provider='openai',
            default_model='gpt-4',
            default_user_id='user123',
            timeout_seconds=30,
            is_active=True
        )
        self.assertEqual(config.name, 'Test KIGate')
        self.assertEqual(config.base_url, 'https://kigate.example.com')
        self.assertTrue(config.is_active)
        self.assertEqual(config.max_tokens, 2000)
        self.assertEqual(config.timeout_seconds, 30)
        
    def test_kigate_config_str_active(self):
        """Test string representation for active config"""
        config = KIGateConfig.objects.create(
            name='Production KIGate',
            base_url='https://kigate.example.com',
            api_key='key',
            is_active=True
        )
        self.assertEqual(str(config), '✓ Production KIGate')
        
    def test_kigate_config_str_inactive(self):
        """Test string representation for inactive config"""
        config = KIGateConfig.objects.create(
            name='Inactive KIGate',
            base_url='https://kigate.example.com',
            api_key='key',
            is_active=False
        )
        self.assertEqual(str(config), '✗ Inactive KIGate')
        
    def test_kigate_config_ordering(self):
        """Test that active configs appear first"""
        inactive = KIGateConfig.objects.create(
            name='Inactive',
            base_url='https://kigate1.example.com',
            api_key='key1',
            is_active=False
        )
        active = KIGateConfig.objects.create(
            name='Active',
            base_url='https://kigate2.example.com',
            api_key='key2',
            is_active=True
        )
        
        configs = list(KIGateConfig.objects.all())
        self.assertEqual(configs[0], active)
        self.assertEqual(configs[1], inactive)


class OpenAIConfigModelTest(TestCase):
    """Tests for OpenAIConfig model."""
    
    def test_openai_config_creation(self):
        """Test basic OpenAI configuration creation"""
        config = OpenAIConfig.objects.create(
            name='Test OpenAI',
            api_key='sk-test-key-123',
            base_url='https://api.openai.com/v1',
            default_model='gpt-4',
            default_vision_model='gpt-4o',
            timeout_seconds=30,
            is_active=True
        )
        self.assertEqual(config.name, 'Test OpenAI')
        self.assertEqual(config.default_model, 'gpt-4')
        self.assertTrue(config.is_active)
        
    def test_openai_config_defaults(self):
        """Test that default values are set correctly"""
        config = OpenAIConfig.objects.create(
            name='OpenAI',
            api_key='sk-key',
        )
        self.assertEqual(config.base_url, 'https://api.openai.com/v1')
        self.assertEqual(config.default_model, 'gpt-4')
        self.assertEqual(config.default_vision_model, 'gpt-4o')
        self.assertEqual(config.timeout_seconds, 30)
        self.assertFalse(config.is_active)
        
    def test_openai_config_str_active(self):
        """Test string representation for active config"""
        config = OpenAIConfig.objects.create(
            name='Production OpenAI',
            api_key='sk-key',
            is_active=True
        )
        self.assertEqual(str(config), '✓ Production OpenAI')
        
    def test_openai_config_str_inactive(self):
        """Test string representation for inactive config"""
        config = OpenAIConfig.objects.create(
            name='Inactive OpenAI',
            api_key='sk-key',
            is_active=False
        )
        self.assertEqual(str(config), '✗ Inactive OpenAI')


class KIGateClientTest(TestCase):
    """Tests for KIGate client functions."""
    
    def setUp(self):
        """Create test configuration"""
        self.config = KIGateConfig.objects.create(
            name='Test Config',
            base_url='https://kigate.test.com',
            api_key='test-key',
            default_agent_name='test-agent',
            default_provider='openai',
            default_model='gpt-4',
            default_user_id='test-user',
            max_tokens=1000,
            timeout_seconds=30,
            is_active=True
        )
    
    def test_get_active_kigate_config_success(self):
        """Test retrieving active configuration"""
        from .services import get_active_kigate_config
        config = get_active_kigate_config()
        self.assertEqual(config.name, 'Test Config')
        self.assertTrue(config.is_active)
    
    def test_get_active_kigate_config_no_active(self):
        """Test error when no active configuration exists"""
        from .services import get_active_kigate_config
        from django.core.exceptions import ImproperlyConfigured
        
        # Deactivate the config
        self.config.is_active = False
        self.config.save()
        
        with self.assertRaises(ImproperlyConfigured):
            get_active_kigate_config()
    
    def test_execute_agent_no_config(self):
        """Test execute_agent returns error when no active config"""
        from .services import execute_agent
        
        # Deactivate the config
        self.config.is_active = False
        self.config.save()
        
        response = execute_agent("test prompt")
        self.assertFalse(response.success)
        self.assertIn("No active KIGate configuration", response.error)
    
    def test_execute_agent_payload_format(self):
        """Test that execute_agent constructs payload with correct API schema"""
        from .services.kigate_client import execute_agent
        from unittest.mock import patch, MagicMock
        
        # Mock the requests.post method
        with patch('core.services.kigate_client.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'result': 'success'}
            mock_post.return_value = mock_response
            
            # Call execute_agent
            execute_agent(
                prompt="Test message",
                agent_name="test-agent",
                provider="test-provider",
                model="test-model",
                user_id="test-user",
                max_tokens=1500,
                temperature=0.5
            )
            
            # Verify the payload structure
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args.kwargs['json']
            
            # Verify payload has correct fields according to API schema
            self.assertIn('message', payload)  # Should be 'message', not 'prompt'
            self.assertNotIn('prompt', payload)  # Should not contain 'prompt'
            self.assertEqual(payload['message'], 'Test message')
            self.assertEqual(payload['agent_name'], 'test-agent')
            self.assertEqual(payload['provider'], 'test-provider')
            self.assertEqual(payload['model'], 'test-model')
            self.assertEqual(payload['user_id'], 'test-user')
            self.assertEqual(payload['max_tokens'], 1500)
            self.assertEqual(payload['temperature'], 0.5)
    
    def test_execute_agent_empty_user_id_fallback(self):
        """Test that empty user_id gets replaced with default value"""
        from .services.kigate_client import execute_agent
        from unittest.mock import patch, MagicMock
        
        # Update config to have empty user_id
        self.config.default_user_id = ''
        self.config.save()
        
        # Mock the requests.post method
        with patch('core.services.kigate_client.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'result': 'success'}
            mock_post.return_value = mock_response
            
            # Call execute_agent without user_id
            execute_agent(prompt="Test message")
            
            # Verify the payload has non-empty user_id
            call_args = mock_post.call_args
            payload = call_args.kwargs['json']
            self.assertIn('user_id', payload)
            self.assertNotEqual(payload['user_id'], '')
            self.assertEqual(payload['user_id'], 'default')
    
    def test_execute_agent_explicit_empty_user_id(self):
        """Test that explicitly passing empty user_id gets replaced with default"""
        from .services.kigate_client import execute_agent
        from unittest.mock import patch, MagicMock
        
        # Mock the requests.post method
        with patch('core.services.kigate_client.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'result': 'success'}
            mock_post.return_value = mock_response
            
            # Call execute_agent with explicitly empty user_id
            execute_agent(prompt="Test message", user_id="")
            
            # Verify the payload has non-empty user_id (should fallback to config or default)
            call_args = mock_post.call_args
            payload = call_args.kwargs['json']
            self.assertIn('user_id', payload)
            self.assertNotEqual(payload['user_id'], '')
            # Should use config default or fallback to 'default'
            self.assertIn(payload['user_id'], ['test-user', 'default'])


class OpenAIClientTest(TestCase):
    """Tests for OpenAI client functions."""
    
    def setUp(self):
        """Create test configuration"""
        self.config = OpenAIConfig.objects.create(
            name='Test Config',
            api_key='sk-test-key',
            base_url='https://api.openai.com/v1',
            default_model='gpt-4',
            timeout_seconds=30,
            is_active=True
        )
    
    def test_get_active_openai_config_success(self):
        """Test retrieving active configuration"""
        from .services import get_active_openai_config
        config = get_active_openai_config()
        self.assertEqual(config.name, 'Test Config')
        self.assertTrue(config.is_active)
    
    def test_get_active_openai_config_no_active(self):
        """Test error when no active configuration exists"""
        from .services import get_active_openai_config
        from django.core.exceptions import ImproperlyConfigured
        
        # Deactivate the config
        self.config.is_active = False
        self.config.save()
        
        with self.assertRaises(ImproperlyConfigured):
            get_active_openai_config()
    
    def test_call_openai_chat_no_config(self):
        """Test call_openai_chat returns error when no active config"""
        from .services import call_openai_chat
        
        # Deactivate the config
        self.config.is_active = False
        self.config.save()
        
        messages = [{"role": "user", "content": "Hello"}]
        response = call_openai_chat(messages)
        self.assertFalse(response.success)
        self.assertIn("No active OpenAI configuration", response.error)


class DocumentUploadModelTest(TestCase):
    """Test cases for DocumentUpload model"""
    
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.payee = Payee.objects.create(name='Test Payee')
        self.category = Category.objects.create(name='Test Category')
    
    def test_document_upload_creation(self):
        """Test basic document upload creation"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test file content'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content, content_type='application/pdf')
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            mime_type='application/pdf',
            file_size=len(file_content),
            source='web',
            status='UPLOADED'
        )
        
        self.assertEqual(doc.original_filename, 'test.pdf')
        self.assertEqual(doc.status, 'UPLOADED')
        self.assertEqual(doc.source, 'web')
        self.assertIsNotNone(doc.file)
    
    def test_document_upload_with_suggestions(self):
        """Test document upload with AI suggestions"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test file content'
        uploaded_file = SimpleUploadedFile('invoice.pdf', file_content, content_type='application/pdf')
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='invoice.pdf',
            mime_type='application/pdf',
            file_size=len(file_content),
            status='REVIEW_PENDING',
            suggested_account=self.account,
            suggested_payee=self.payee,
            suggested_category=self.category,
            suggested_amount=Decimal('99.99'),
            suggested_currency='EUR',
            suggested_date=date.today(),
            suggested_description='Test invoice',
            suggestion_confidence=0.95
        )
        
        self.assertEqual(doc.suggested_account, self.account)
        self.assertEqual(doc.suggested_payee, self.payee)
        self.assertEqual(doc.suggested_category, self.category)
        self.assertEqual(doc.suggested_amount, Decimal('99.99'))
        self.assertEqual(doc.suggestion_confidence, 0.95)


class DocumentProcessorTest(TestCase):
    """Test cases for document processor service"""
    
    def test_get_mime_type(self):
        """Test MIME type detection from filename"""
        from .services.document_processor import get_mime_type
        
        self.assertEqual(get_mime_type('test.pdf'), 'application/pdf')
        self.assertEqual(get_mime_type('test.jpg'), 'image/jpeg')
        self.assertEqual(get_mime_type('test.jpeg'), 'image/jpeg')
        self.assertEqual(get_mime_type('test.png'), 'image/png')
    
    def test_is_image_mime_type(self):
        """Test image MIME type detection"""
        from .services.document_processor import is_image_mime_type
        
        # Test image types
        self.assertTrue(is_image_mime_type('image/jpeg'))
        self.assertTrue(is_image_mime_type('image/png'))
        self.assertTrue(is_image_mime_type('image/gif'))
        self.assertTrue(is_image_mime_type('image/webp'))
        
        # Test non-image types
        self.assertFalse(is_image_mime_type('application/pdf'))
        self.assertFalse(is_image_mime_type('text/plain'))
        self.assertFalse(is_image_mime_type('application/json'))
    
    def test_extract_text_from_pdf(self):
        """Test PDF text extraction"""
        from .services.document_processor import extract_text_from_pdf
        
        # Create a temporary PDF with some text
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            
        try:
            # Create a simple PDF with PyMuPDF using context manager
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((50, 50), "Test Invoice\nAmount: 99.99 EUR\nDate: 2024-01-15")
                doc.save(tmp_path)
            
            # Extract text
            extracted_text = extract_text_from_pdf(tmp_path)
            
            # Verify text extraction
            self.assertIn("Test Invoice", extracted_text)
            self.assertIn("99.99", extracted_text)
            self.assertIn("2024-01-15", extracted_text)
        finally:
            os.unlink(tmp_path)
    
    def test_extract_text_from_pdf_with_length_limit(self):
        """Test PDF text extraction respects character limit"""
        from .services.document_processor import extract_text_from_pdf
        
        # Create a temporary PDF with longer text
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            
        try:
            # Create a PDF with repeated text
            with fitz.open() as doc:
                page = doc.new_page()
                long_text = "A" * 1000  # 1000 characters
                page.insert_text((50, 50), long_text)
                doc.save(tmp_path)
            
            # Extract text with a small limit
            extracted_text = extract_text_from_pdf(tmp_path, max_chars=500)
            
            # Verify text is truncated
            self.assertLessEqual(len(extracted_text), 500)
            self.assertTrue(extracted_text.startswith("A"))
        finally:
            os.unlink(tmp_path)
    
    def test_sanitize_extracted_text(self):
        """Test text sanitization removes control characters"""
        from .services.document_processor import sanitize_extracted_text
        
        # Test with control characters and excessive whitespace
        dirty_text = "Hello\x00World\n\n\n   Spaced  Out   \n\nEnd"
        clean_text = sanitize_extracted_text(dirty_text)
        
        # Verify control characters are removed
        self.assertNotIn('\x00', clean_text)
        # Verify excessive whitespace is reduced
        self.assertNotIn('\n\n\n', clean_text)
        # Verify content is preserved
        self.assertIn('Hello', clean_text)
        self.assertIn('World', clean_text)
    
    def test_map_to_database_objects_basic(self):
        """Test mapping extracted data to database objects"""
        from .services.document_processor import map_to_database_objects
        
        account = Account.objects.create(name='Girokonto', type='checking')
        payee = Payee.objects.create(name='REWE', is_active=True)
        category = Category.objects.create(name='Lebensmittel')
        
        extracted_data = {
            'payee_name': 'REWE',
            'account_name': 'Girokonto',
            'category_name': 'Lebensmittel',
            'amount': 42.50,
            'currency': 'EUR',
            'date': '2024-01-15',
            'description': 'Grocery shopping',
            'is_recurring': False,
            'confidence': 0.9,
            'extracted_text': 'Some text'
        }
        
        result = map_to_database_objects(extracted_data)
        
        self.assertEqual(result['suggested_account'], account)
        self.assertEqual(result['suggested_payee'], payee)
        self.assertEqual(result['suggested_category'], category)
        self.assertEqual(result['suggested_amount'], Decimal('42.50'))
    
    def test_process_document_with_kigate_parses_german_format(self):
        """Test parsing German-formatted KIGate response"""
        from .services.document_processor import process_document_with_kigate
        from unittest.mock import patch, MagicMock
        
        # Create a temporary PDF for testing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_path = tmp_file.name
        
        try:
            # Create a simple PDF
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((50, 50), "Test Invoice")
                doc.save(tmp_path)
            
            # Mock the KIGate response with German format
            mock_kigate_response = MagicMock()
            mock_kigate_response.success = True
            mock_kigate_response.data = {
                'job_id': 'test-job-123',
                'result': '''{
                    "Belegnummer": "DE52E6ZDABEY",
                    "Absender": "Amazon Business EU S.à r.l.",
                    "Betrag": "27,03 €",
                    "Fällig": "13. Dezember 2025",
                    "Info": "Schlitzer Neutralalkohol"
                }'''
            }
            
            with patch('core.services.document_processor.execute_agent', return_value=mock_kigate_response):
                result = process_document_with_kigate(tmp_path, 'application/pdf')
            
            # Verify success
            self.assertTrue(result['success'])
            
            # Verify data extraction
            data = result['data']
            self.assertEqual(data['payee_name'], 'Amazon Business EU S.à r.l.')
            self.assertAlmostEqual(data['amount'], 27.03, places=2)
            self.assertEqual(data['currency'], 'EUR')
            self.assertEqual(data['date'], '2025-12-13')
            self.assertEqual(data['description'], 'DE52E6ZDABEY Schlitzer Neutralalkohol')
            
        finally:
            os.unlink(tmp_path)


class DocumentViewTest(TestCase):
    """Test cases for document views"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
    
    def test_document_list_view_get(self):
        """Test document list view GET request"""
        response = self.client.get('/documents/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dokumente')
    
    def test_document_list_view_requires_login(self):
        """Test that document list requires login"""
        self.client.logout()
        response = self.client.get('/documents/')
        self.assertEqual(response.status_code, 302)
    
    def test_document_review_detail_create_booking(self):
        """Test creating a booking from document review"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('99.99'),
            suggested_date=date.today()
        )
        
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '99.99',
            'booking_date': date.today().isoformat(),
            'description': 'Test booking'
        })
        
        self.assertEqual(response.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'BOOKED')
        self.assertIsNotNone(doc.booking)
    
    def test_document_review_detail_amount_field_renders_correctly(self):
        """Test that the amount field in review detail renders with correct format for HTML input"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        # Test with a decimal amount
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('42.50'),
            suggested_currency='EUR',
            suggested_date=date.today()
        )
        
        response = self.client.get(f'/documents/review/{doc.id}/')
        self.assertEqual(response.status_code, 200)
        
        # The amount should be rendered with a period (.) not a comma (,) for HTML number inputs
        # Check that the input field contains the correct value format
        self.assertContains(response, 'value="42.50"')
        # Ensure it doesn't contain the localized comma format
        self.assertNotContains(response, 'value="42,50"')


class DueBookingsViewTest(TestCase):
    """Test cases for due bookings overview"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(name='Test Category')
    
    def test_due_bookings_view_requires_login(self):
        """Test that due bookings view requires login"""
        self.client.logout()
        response = self.client.get('/due-bookings/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_due_bookings_view_shows_overdue(self):
        """Test that overdue bookings are shown"""
        from datetime import timedelta
        
        # Create an overdue booking
        overdue_date = date.today() - timedelta(days=5)
        booking = Booking.objects.create(
            account=self.account,
            booking_date=overdue_date,
            amount=Decimal('-100.00'),
            description='Overdue payment',
            status='PLANNED'
        )
        
        response = self.client.get('/due-bookings/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Overdue payment')
        self.assertContains(response, 'Überfällige Rechnungen')
    
    def test_due_bookings_view_shows_upcoming(self):
        """Test that upcoming bookings are shown"""
        from datetime import timedelta
        
        # Create an upcoming booking (3 days from now)
        upcoming_date = date.today() + timedelta(days=3)
        booking = Booking.objects.create(
            account=self.account,
            booking_date=upcoming_date,
            amount=Decimal('-200.00'),
            description='Upcoming payment',
            status='PLANNED'
        )
        
        response = self.client.get('/due-bookings/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upcoming payment')
        self.assertContains(response, 'Fällig innerhalb der nächsten 7 Tage')
    
    def test_due_bookings_view_excludes_posted(self):
        """Test that posted bookings are not shown"""
        from datetime import timedelta
        
        # Create a posted booking
        booking = Booking.objects.create(
            account=self.account,
            booking_date=date.today() - timedelta(days=2),
            amount=Decimal('-100.00'),
            description='Posted payment',
            status='POSTED'
        )
        
        response = self.client.get('/due-bookings/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Posted payment')
    
    def test_due_bookings_view_excludes_far_future(self):
        """Test that bookings more than 7 days in future are not shown"""
        from datetime import timedelta
        
        # Create a booking 10 days from now
        far_future_date = date.today() + timedelta(days=10)
        booking = Booking.objects.create(
            account=self.account,
            booking_date=far_future_date,
            amount=Decimal('-100.00'),
            description='Far future payment',
            status='PLANNED'
        )
        
        response = self.client.get('/due-bookings/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Far future payment')
    
    def test_mark_booking_as_booked_success(self):
        """Test marking a planned booking as booked"""
        booking = Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            description='Test payment',
            status='PLANNED'
        )
        
        response = self.client.post(f'/bookings/{booking.id}/mark-booked/')
        self.assertEqual(response.status_code, 200)
        
        # Response should be empty (for HTMX to remove the row)
        self.assertEqual(response.content, b'')
        
        # Verify booking status changed
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'POSTED')
    
    def test_mark_booking_as_booked_already_posted(self):
        """Test marking an already posted booking returns error"""
        booking = Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            description='Test payment',
            status='POSTED'
        )
        
        response = self.client.post(f'/bookings/{booking.id}/mark-booked/')
        self.assertEqual(response.status_code, 400)
        
        # Response should contain error message
        self.assertIn(b'not planned', response.content)
    
    def test_mark_booking_as_booked_requires_login(self):
        """Test that marking booking as booked requires login"""
        booking = Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            description='Test payment',
            status='PLANNED'
        )
        
        self.client.logout()
        response = self.client.post(f'/bookings/{booking.id}/mark-booked/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_mark_booking_as_booked_only_post(self):
        """Test that marking booking only accepts POST requests"""
        booking = Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            description='Test payment',
            status='PLANNED'
        )
        
        response = self.client.get(f'/bookings/{booking.id}/mark-booked/')
        self.assertEqual(response.status_code, 405)  # Method Not Allowed
