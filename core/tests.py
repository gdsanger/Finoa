from django.test import TestCase
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
import tempfile
import os

import fitz  # PyMuPDF

from .models import Account, Category, Booking, RecurringBooking, Payee, KIGateConfig, OpenAIConfig, DocumentUpload, TimeEntry
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


class OverdueUpcomingBookingsTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(name='Test Category')
    
    def test_overdue_bookings_sum_empty(self):
        """Test that overdue bookings sum is zero when no overdue bookings exist"""
        from .services import get_overdue_bookings_sum
        
        overdue_sum = get_overdue_bookings_sum()
        self.assertEqual(overdue_sum, Decimal('0.00'))
    
    def test_overdue_bookings_sum_with_overdue(self):
        """Test that overdue bookings are correctly summed"""
        from .services import get_overdue_bookings_sum
        from datetime import timedelta
        
        # Create overdue bookings
        yesterday = date.today() - timedelta(days=1)
        three_days_ago = date.today() - timedelta(days=3)
        
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday,
            amount=Decimal('-100.00'),
            status='PLANNED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=three_days_ago,
            amount=Decimal('-50.00'),
            status='PLANNED'
        )
        
        overdue_sum = get_overdue_bookings_sum()
        self.assertEqual(overdue_sum, Decimal('-150.00'))
    
    def test_overdue_bookings_sum_excludes_posted(self):
        """Test that posted bookings are not included in overdue sum"""
        from .services import get_overdue_bookings_sum
        from datetime import timedelta
        
        yesterday = date.today() - timedelta(days=1)
        
        # Create posted booking in the past
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday,
            amount=Decimal('-100.00'),
            status='POSTED'
        )
        
        overdue_sum = get_overdue_bookings_sum()
        self.assertEqual(overdue_sum, Decimal('0.00'))
    
    def test_overdue_bookings_sum_excludes_today_and_future(self):
        """Test that bookings from today or future are not included"""
        from .services import get_overdue_bookings_sum
        from datetime import timedelta
        
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        Booking.objects.create(
            account=self.account,
            booking_date=today,
            amount=Decimal('-100.00'),
            status='PLANNED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=tomorrow,
            amount=Decimal('-50.00'),
            status='PLANNED'
        )
        
        overdue_sum = get_overdue_bookings_sum()
        self.assertEqual(overdue_sum, Decimal('0.00'))
    
    def test_upcoming_bookings_sum_empty(self):
        """Test that upcoming bookings sum is zero when no upcoming bookings exist"""
        from .services import get_upcoming_bookings_sum
        
        upcoming_sum = get_upcoming_bookings_sum(days=7)
        self.assertEqual(upcoming_sum, Decimal('0.00'))
    
    def test_upcoming_bookings_sum_with_upcoming(self):
        """Test that upcoming bookings are correctly summed"""
        from .services import get_upcoming_bookings_sum
        from datetime import timedelta
        
        today = date.today()
        in_three_days = today + timedelta(days=3)
        in_five_days = today + timedelta(days=5)
        
        Booking.objects.create(
            account=self.account,
            booking_date=today,
            amount=Decimal('-100.00'),
            status='PLANNED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=in_three_days,
            amount=Decimal('-75.00'),
            status='PLANNED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=in_five_days,
            amount=Decimal('-25.00'),
            status='PLANNED'
        )
        
        upcoming_sum = get_upcoming_bookings_sum(days=7)
        self.assertEqual(upcoming_sum, Decimal('-200.00'))
    
    def test_upcoming_bookings_sum_excludes_beyond_window(self):
        """Test that bookings beyond the time window are not included"""
        from .services import get_upcoming_bookings_sum
        from datetime import timedelta
        
        today = date.today()
        in_ten_days = today + timedelta(days=10)
        
        Booking.objects.create(
            account=self.account,
            booking_date=in_ten_days,
            amount=Decimal('-100.00'),
            status='PLANNED'
        )
        
        upcoming_sum = get_upcoming_bookings_sum(days=7)
        self.assertEqual(upcoming_sum, Decimal('0.00'))
    
    def test_upcoming_bookings_sum_excludes_past(self):
        """Test that past bookings are not included in upcoming sum"""
        from .services import get_upcoming_bookings_sum
        from datetime import timedelta
        
        yesterday = date.today() - timedelta(days=1)
        
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday,
            amount=Decimal('-100.00'),
            status='PLANNED'
        )
        
        upcoming_sum = get_upcoming_bookings_sum(days=7)
        self.assertEqual(upcoming_sum, Decimal('0.00'))
    
    def test_upcoming_bookings_sum_excludes_posted(self):
        """Test that posted bookings are not included in upcoming sum"""
        from .services import get_upcoming_bookings_sum
        from datetime import timedelta
        
        tomorrow = date.today() + timedelta(days=1)
        
        Booking.objects.create(
            account=self.account,
            booking_date=tomorrow,
            amount=Decimal('-100.00'),
            status='POSTED'
        )
        
        upcoming_sum = get_upcoming_bookings_sum(days=7)
        self.assertEqual(upcoming_sum, Decimal('0.00'))


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
    
    def test_document_review_detail_amount_is_inverted(self):
        """Test that amount is inverted (made negative) when creating booking from document"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='invoice.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('99.99'),
            suggested_date=date.today()
        )
        
        # Submit with positive amount
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '99.99',
            'booking_date': date.today().isoformat(),
            'description': 'Test invoice'
        })
        
        self.assertEqual(response.status_code, 302)
        doc.refresh_from_db()
        
        # Amount should be inverted (negative)
        self.assertIsNotNone(doc.booking)
        self.assertEqual(doc.booking.amount, Decimal('-99.99'))
    
    def test_document_review_detail_default_status_is_planned(self):
        """Test that bookings are created with PLANNED status by default"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('50.00'),
            suggested_date=date.today()
        )
        
        # Submit without explicit status (should default to PLANNED)
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '50.00',
            'booking_date': date.today().isoformat(),
            'description': 'Test booking'
        })
        
        self.assertEqual(response.status_code, 302)
        doc.refresh_from_db()
        
        # Status should be PLANNED by default
        self.assertIsNotNone(doc.booking)
        self.assertEqual(doc.booking.status, 'PLANNED')
    
    def test_document_review_detail_status_can_be_set_to_posted(self):
        """Test that status can be explicitly set to POSTED"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('50.00'),
            suggested_date=date.today()
        )
        
        # Submit with explicit POSTED status
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '50.00',
            'booking_date': date.today().isoformat(),
            'description': 'Test booking',
            'status': 'POSTED'
        })
        
        self.assertEqual(response.status_code, 302)
        doc.refresh_from_db()
        
        # Status should be POSTED as specified
        self.assertIsNotNone(doc.booking)
        self.assertEqual(doc.booking.status, 'POSTED')
    
    def test_document_review_detail_recurring_booking_amount_inverted(self):
        """Test that recurring booking amount is also inverted"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='subscription.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('29.99'),
            suggested_date=date.today(),
            suggested_is_recurring=True
        )
        
        # Create with recurring option
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '29.99',
            'booking_date': date.today().isoformat(),
            'description': 'Monthly subscription',
            'create_recurring': 'on',
            'status': 'PLANNED'
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Check that both booking and recurring booking were created with inverted amount
        doc.refresh_from_db()
        self.assertIsNotNone(doc.booking)
        self.assertEqual(doc.booking.amount, Decimal('-29.99'))
        
        from .models import RecurringBooking
        recurring = RecurringBooking.objects.filter(
            account=self.account,
            description='Monthly subscription'
        ).first()
        
        self.assertIsNotNone(recurring)
        self.assertEqual(recurring.amount, Decimal('-29.99'))
    
    def test_document_review_detail_invalid_date_format(self):
        """Test that invalid date format is handled gracefully"""
        from .models import DocumentUpload
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        file_content = b'test'
        uploaded_file = SimpleUploadedFile('test.pdf', file_content)
        
        doc = DocumentUpload.objects.create(
            file=uploaded_file,
            original_filename='test.pdf',
            status='REVIEW_PENDING',
            suggested_amount=Decimal('50.00'),
            suggested_date=date.today()
        )
        
        # Submit with invalid date format
        response = self.client.post(f'/documents/review/{doc.id}/', {
            'account': self.account.id,
            'amount': '50.00',
            'booking_date': '2024-13-45',  # Invalid date
            'description': 'Test booking',
            'status': 'PLANNED'
        })
        
        # Should redirect back to the review page (not to list)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/documents/review/{doc.id}/', response.url)
        
        # No booking should be created
        doc.refresh_from_db()
        self.assertIsNone(doc.booking)


class DashboardDeficitCalculationTest(TestCase):
    """Test cases for dashboard deficit calculations"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00'),
            is_liquidity_relevant=True
        )
    
    def test_dashboard_overdue_deficit_with_expenses(self):
        """Test that overdue expenses correctly reduce liquidity deficit"""
        from datetime import timedelta
        
        # Create overdue expense bookings
        yesterday = date.today() - timedelta(days=1)
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday,
            amount=Decimal('-100.00'),  # Expense
            status='PLANNED'
        )
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday - timedelta(days=1),
            amount=Decimal('-50.00'),  # Expense
            status='PLANNED'
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Verify overdue_sum is correctly summed
        self.assertEqual(response.context['overdue_sum'], Decimal('-150.00'))
        
        # Verify deficit: liquidity_actual + overdue_sum
        # 1000 + (-150) = 850 (remaining after paying)
        expected_deficit = Decimal('850.00')
        self.assertEqual(response.context['overdue_deficit'], expected_deficit)
    
    def test_dashboard_overdue_deficit_with_income(self):
        """Test that overdue income correctly increases liquidity deficit"""
        from datetime import timedelta
        
        # Create overdue income booking
        yesterday = date.today() - timedelta(days=1)
        Booking.objects.create(
            account=self.account,
            booking_date=yesterday,
            amount=Decimal('500.00'),  # Income
            status='PLANNED'
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Verify overdue_sum
        self.assertEqual(response.context['overdue_sum'], Decimal('500.00'))
        
        # Verify deficit: liquidity_actual + overdue_sum
        # 1000 + 500 = 1500 (total after receiving income)
        expected_deficit = Decimal('1500.00')
        self.assertEqual(response.context['overdue_deficit'], expected_deficit)
    
    def test_dashboard_upcoming_deficit_with_expenses(self):
        """Test that upcoming expenses correctly reduce liquidity deficit"""
        from datetime import timedelta
        
        # Create upcoming expense bookings
        in_three_days = date.today() + timedelta(days=3)
        Booking.objects.create(
            account=self.account,
            booking_date=in_three_days,
            amount=Decimal('-200.00'),  # Expense
            status='PLANNED'
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Verify upcoming_sum
        self.assertEqual(response.context['upcoming_sum'], Decimal('-200.00'))
        
        # Verify deficit: liquidity_actual + upcoming_sum
        # 1000 + (-200) = 800 (remaining after paying)
        expected_deficit = Decimal('800.00')
        self.assertEqual(response.context['upcoming_deficit'], expected_deficit)
    
    def test_dashboard_upcoming_deficit_with_income(self):
        """Test that upcoming income correctly increases liquidity deficit"""
        from datetime import timedelta
        
        # Create upcoming income booking
        tomorrow = date.today() + timedelta(days=1)
        Booking.objects.create(
            account=self.account,
            booking_date=tomorrow,
            amount=Decimal('300.00'),  # Income
            status='PLANNED'
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Verify upcoming_sum
        self.assertEqual(response.context['upcoming_sum'], Decimal('300.00'))
        
        # Verify deficit: liquidity_actual + upcoming_sum
        # 1000 + 300 = 1300 (total after receiving income)
        expected_deficit = Decimal('1300.00')
        self.assertEqual(response.context['upcoming_deficit'], expected_deficit)


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


class ReconcileBalanceViewTest(TestCase):
    """Tests for balance reconciliation feature"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.account = Account.objects.create(
            name='Test Giro',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        
        # Create reconciliation categories
        self.cat_correction = Category.objects.create(name='Korrektur')
        self.cat_unrealized = Category.objects.create(name='Unrealisierte Gewinne/Verluste')
        self.cat_roundup = Category.objects.create(name='RoundUp')
        self.cat_saveback = Category.objects.create(name='SaveBack')
    
    def test_reconcile_balance_view_get_requires_login(self):
        """Test that reconciliation view requires login"""
        self.client.logout()
        response = self.client.get(f'/accounts/{self.account.id}/reconcile/')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_reconcile_balance_view_get_shows_form(self):
        """Test that GET request shows reconciliation form"""
        response = self.client.get(f'/accounts/{self.account.id}/reconcile/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Aktueller Finoa-Saldo')
        # Balance could be formatted as "1000.00" or "1.000,00" or similar
        self.assertContains(response, '1000')
        self.assertContains(response, 'Neuer externer Saldo')
    
    def test_reconcile_balance_creates_positive_difference_booking(self):
        """Test creating a reconciliation booking with positive difference"""
        # Add a booking to increase balance
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('500.00'),
            status='POSTED'
        )
        
        # Current balance should be 1500.00
        current_balance = calculate_actual_balance(self.account)
        self.assertEqual(current_balance, Decimal('1500.00'))
        
        # Reconcile to 2000.00 (difference +500)
        response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
            'new_balance': '2000.00',
            'date': date.today().isoformat(),
            'diff_type': 'correction',
            'category_id': self.cat_correction.id,
        })
        
        # Should redirect back to account detail
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/accounts/{self.account.id}/', response.url)
        
        # Check that reconciliation booking was created
        reconciliation_booking = Booking.objects.filter(
            account=self.account,
            description__contains='Saldenabgleich'
        ).first()
        
        self.assertIsNotNone(reconciliation_booking)
        self.assertEqual(reconciliation_booking.amount, Decimal('500.00'))
        self.assertEqual(reconciliation_booking.category, self.cat_correction)
        self.assertEqual(reconciliation_booking.status, 'POSTED')
        
        # Verify final balance
        final_balance = calculate_actual_balance(self.account)
        self.assertEqual(final_balance, Decimal('2000.00'))
    
    def test_reconcile_balance_creates_negative_difference_booking(self):
        """Test creating a reconciliation booking with negative difference"""
        # Add a booking
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('500.00'),
            status='POSTED'
        )
        
        # Current balance: 1500.00
        # Reconcile to 1200.00 (difference -300)
        response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
            'new_balance': '1200.00',
            'date': date.today().isoformat(),
            'diff_type': 'correction',
            'category_id': self.cat_correction.id,
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Check reconciliation booking
        reconciliation_booking = Booking.objects.filter(
            account=self.account,
            description__contains='Saldenabgleich'
        ).first()
        
        self.assertIsNotNone(reconciliation_booking)
        self.assertEqual(reconciliation_booking.amount, Decimal('-300.00'))
        
        # Verify final balance
        final_balance = calculate_actual_balance(self.account)
        self.assertEqual(final_balance, Decimal('1200.00'))
    
    def test_reconcile_balance_no_difference_no_booking(self):
        """Test that no booking is created when there's no difference"""
        # Current balance is 1000.00
        # Reconcile to same balance
        initial_booking_count = Booking.objects.filter(account=self.account).count()
        
        response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
            'new_balance': '1000.00',
            'date': date.today().isoformat(),
            'diff_type': 'correction',
            'category_id': self.cat_correction.id,
        })
        
        self.assertEqual(response.status_code, 302)
        
        # No new booking should be created
        final_booking_count = Booking.objects.filter(account=self.account).count()
        self.assertEqual(initial_booking_count, final_booking_count)
    
    def test_reconcile_balance_different_diff_types(self):
        """Test reconciliation with different difference types"""
        diff_types_and_categories = [
            ('unrealized', self.cat_unrealized, 'Unrealisierte Gewinne/Verluste'),
            ('roundup', self.cat_roundup, 'RoundUp'),
            ('saveback', self.cat_saveback, 'SaveBack'),
        ]
        
        for diff_type, category, expected_desc_part in diff_types_and_categories:
            # Reset account for each test
            Booking.objects.filter(account=self.account).delete()
            
            response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
                'new_balance': '1100.00',
                'date': date.today().isoformat(),
                'diff_type': diff_type,
                'category_id': category.id,
            })
            
            self.assertEqual(response.status_code, 302)
            
            booking = Booking.objects.filter(
                account=self.account,
                description__contains=expected_desc_part
            ).first()
            
            self.assertIsNotNone(booking, f"No booking found for {diff_type}")
            self.assertEqual(booking.category, category)
            self.assertEqual(booking.amount, Decimal('100.00'))
    
    def test_reconcile_balance_with_decimal_input(self):
        """Test reconciliation with decimal values"""
        response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
            'new_balance': '1234.56',
            'date': date.today().isoformat(),
            'diff_type': 'correction',
            'category_id': self.cat_correction.id,
        })
        
        self.assertEqual(response.status_code, 302)
        
        booking = Booking.objects.filter(
            account=self.account,
            description__contains='Saldenabgleich'
        ).first()
        
        self.assertIsNotNone(booking)
        self.assertEqual(booking.amount, Decimal('234.56'))
    
    def test_reconcile_balance_invalid_input(self):
        """Test reconciliation with invalid input"""
        response = self.client.post(f'/accounts/{self.account.id}/reconcile/', {
            'new_balance': '',  # Empty balance
            'date': date.today().isoformat(),
            'diff_type': 'correction',
            'category_id': self.cat_correction.id,
        })
        
        # Should redirect with error message
        self.assertEqual(response.status_code, 302)
        
        # No booking should be created
        booking = Booking.objects.filter(
            account=self.account,
            description__contains='Saldenabgleich'
        ).first()
        self.assertIsNone(booking)


class TimeEntryModelTest(TestCase):
    """Tests for TimeEntry model"""
    
    def setUp(self):
        self.payee = Payee.objects.create(name='Test Customer', is_active=True)
    
    def test_time_entry_creation(self):
        """Test basic TimeEntry creation"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.5'),
            activity='Gartenarbeit',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        
        self.assertEqual(entry.payee, self.payee)
        self.assertEqual(entry.duration_hours, Decimal('2.5'))
        self.assertEqual(entry.hourly_rate, Decimal('25.00'))
        self.assertFalse(entry.billed)
    
    def test_time_entry_amount_calculation(self):
        """Test that amount property correctly calculates total"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('3.5'),
            activity='Reparatur',
            hourly_rate=Decimal('30.00'),
            billed=False
        )
        
        expected_amount = Decimal('3.5') * Decimal('30.00')
        self.assertEqual(entry.amount, expected_amount)
    
    def test_time_entry_str_representation(self):
        """Test string representation"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date(2025, 1, 15),
            duration_hours=Decimal('2.0'),
            activity='Test Activity',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        
        str_repr = str(entry)
        self.assertIn('2025-01-15', str_repr)
        self.assertIn('Test Customer', str_repr)
        self.assertIn('2.0', str_repr)


class TimeTrackingViewTest(TestCase):
    """Tests for time tracking views"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.payee = Payee.objects.create(name='Test Customer', is_active=True)
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(
            name='Dienstleistungseinnahmen',
            type='income'
        )
    
    def test_time_tracking_view_accessible(self):
        """Test that time tracking view is accessible"""
        response = self.client.get('/time-tracking/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Zeiterfassung')
    
    def test_create_time_entry(self):
        """Test creating a new time entry"""
        response = self.client.post('/time-tracking/create/', {
            'payee': self.payee.id,
            'date': date.today().isoformat(),
            'duration_hours': '2.5',
            'activity': 'Gartenarbeit',
            'hourly_rate': '25.00'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect
        
        entry = TimeEntry.objects.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.payee, self.payee)
        self.assertEqual(entry.duration_hours, Decimal('2.5'))
        self.assertFalse(entry.billed)
    
    def test_update_time_entry(self):
        """Test updating an existing time entry"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Original Activity',
            hourly_rate=Decimal('20.00'),
            billed=False
        )
        
        response = self.client.post(f'/time-tracking/{entry.id}/update/', {
            'payee': self.payee.id,
            'date': date.today().isoformat(),
            'duration_hours': '3.0',
            'activity': 'Updated Activity',
            'hourly_rate': '30.00'
        })
        
        self.assertEqual(response.status_code, 302)
        
        entry.refresh_from_db()
        self.assertEqual(entry.duration_hours, Decimal('3.0'))
        self.assertEqual(entry.activity, 'Updated Activity')
        self.assertEqual(entry.hourly_rate, Decimal('30.00'))
    
    def test_cannot_update_billed_entry(self):
        """Test that billed entries cannot be updated"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Billed Activity',
            hourly_rate=Decimal('20.00'),
            billed=True
        )
        
        response = self.client.post(f'/time-tracking/{entry.id}/update/', {
            'payee': self.payee.id,
            'date': date.today().isoformat(),
            'duration_hours': '3.0',
            'activity': 'Updated Activity',
            'hourly_rate': '30.00'
        })
        
        entry.refresh_from_db()
        self.assertEqual(entry.duration_hours, Decimal('2.0'))  # Should not change
    
    def test_delete_time_entry(self):
        """Test deleting a time entry"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='To Delete',
            hourly_rate=Decimal('20.00'),
            billed=False
        )
        
        response = self.client.post(f'/time-tracking/{entry.id}/delete/')
        self.assertEqual(response.status_code, 302)
        
        self.assertFalse(TimeEntry.objects.filter(id=entry.id).exists())
    
    def test_cannot_delete_billed_entry(self):
        """Test that billed entries cannot be deleted"""
        entry = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Billed Activity',
            hourly_rate=Decimal('20.00'),
            billed=True
        )
        
        response = self.client.post(f'/time-tracking/{entry.id}/delete/')
        
        # Entry should still exist
        self.assertTrue(TimeEntry.objects.filter(id=entry.id).exists())


class TimeEntryBulkBillingTest(TestCase):
    """Tests for bulk billing functionality"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.payee = Payee.objects.create(name='Test Customer', is_active=True)
        self.payee2 = Payee.objects.create(name='Another Customer', is_active=True)
        
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )
        self.category = Category.objects.create(
            name='Dienstleistungseinnahmen',
            type='income'
        )
        
        # Create test entries
        self.entry1 = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today() - relativedelta(days=5),
            duration_hours=Decimal('2.0'),
            activity='Activity 1',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        self.entry2 = TimeEntry.objects.create(
            payee=self.payee,
            date=date.today() - relativedelta(days=3),
            duration_hours=Decimal('3.0'),
            activity='Activity 2',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
    
    def test_billing_form_loads(self):
        """Test that billing form loads with selected entries"""
        response = self.client.get('/time-tracking/billing/', {
            'entries': [self.entry1.id, self.entry2.id]
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sammelabrechnung')
        self.assertContains(response, 'Test Customer')
    
    def test_bulk_billing_creates_booking(self):
        """Test that bulk billing creates a booking and marks entries as billed"""
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [self.entry1.id, self.entry2.id],
            'account': self.account.id,
            'category': self.category.id,
            'billing_date': date.today().isoformat()
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Check booking was created
        booking = Booking.objects.filter(
            account=self.account,
            payee=self.payee
        ).first()
        
        self.assertIsNotNone(booking)
        self.assertEqual(booking.amount, Decimal('125.00'))  # 2*25 + 3*25
        self.assertEqual(booking.category, self.category)
        self.assertEqual(booking.status, 'POSTED')
        
        # Check entries are marked as billed
        self.entry1.refresh_from_db()
        self.entry2.refresh_from_db()
        self.assertTrue(self.entry1.billed)
        self.assertTrue(self.entry2.billed)
    
    def test_billing_requires_same_payee(self):
        """Test that billing fails if entries have different payees"""
        entry3 = TimeEntry.objects.create(
            payee=self.payee2,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Different Payee',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [self.entry1.id, entry3.id],
            'account': self.account.id,
            'category': self.category.id,
            'billing_date': date.today().isoformat()
        })
        
        # Should redirect with error
        self.assertEqual(response.status_code, 302)
        
        # No booking should be created
        booking = Booking.objects.filter(account=self.account).first()
        self.assertIsNone(booking)
        
        # Entries should not be marked as billed
        self.entry1.refresh_from_db()
        self.assertFalse(self.entry1.billed)
    
    def test_billing_requires_unbilled_entries(self):
        """Test that billing only processes unbilled entries"""
        self.entry1.billed = True
        self.entry1.save()
        
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [self.entry1.id, self.entry2.id],
            'account': self.account.id,
            'category': self.category.id,
            'billing_date': date.today().isoformat()
        })
        
        # Should only process unbilled entry
        booking = Booking.objects.filter(account=self.account).first()
        if booking:
            # If booking was created, it should only include entry2
            self.assertEqual(booking.amount, Decimal('75.00'))  # 3*25
    
    def test_billing_requires_category(self):
        """Test that billing requires a category (mandatory field)"""
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [self.entry1.id, self.entry2.id],
            'account': self.account.id,
            'billing_date': date.today().isoformat()
            # No category provided
        })
        
        # Should fail validation
        # No booking should be created
        booking = Booking.objects.filter(account=self.account).first()
        self.assertIsNone(booking)
    
    def test_billing_description_single_date(self):
        """Test billing description when all entries on same date"""
        today = date.today()
        entry_a = TimeEntry.objects.create(
            payee=self.payee,
            date=today,
            duration_hours=Decimal('2.0'),
            activity='Activity A',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        entry_b = TimeEntry.objects.create(
            payee=self.payee,
            date=today,
            duration_hours=Decimal('1.0'),
            activity='Activity B',
            hourly_rate=Decimal('25.00'),
            billed=False
        )
        
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [entry_a.id, entry_b.id],
            'account': self.account.id,
            'category': self.category.id,
            'billing_date': date.today().isoformat()
        })
        
        booking = Booking.objects.filter(account=self.account).first()
        self.assertIsNotNone(booking)
        
        # Description should mention single date
        self.assertIn('vom', booking.description)
        self.assertNotIn('bis', booking.description)
    
    def test_billing_description_date_range(self):
        """Test billing description with date range"""
        response = self.client.post('/time-tracking/billing/', {
            'selected_entries': [self.entry1.id, self.entry2.id],
            'account': self.account.id,
            'category': self.category.id,
            'billing_date': date.today().isoformat()
        })
        
        booking = Booking.objects.filter(account=self.account).first()
        self.assertIsNotNone(booking)
        
        # Description should mention date range
        self.assertIn('vom', booking.description)
        self.assertIn('bis', booking.description)
        self.assertIn('Test Customer', booking.description)


class DashboardUnbilledTimeSumTest(TestCase):
    """Tests for dashboard unbilled time entries sum display"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.payee = Payee.objects.create(name='Test Customer', is_active=True)
    
    def test_dashboard_includes_unbilled_time_sum(self):
        """Test that dashboard includes unbilled time entries sum in context"""
        # Create some unbilled time entries
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('5.0'),
            activity='Test Work',
            hourly_rate=Decimal('50.00'),
            billed=False
        )
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('3.0'),
            activity='More Work',
            hourly_rate=Decimal('60.00'),
            billed=False
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Verify unbilled_time_sum is in context
        self.assertIn('unbilled_time_sum', response.context)
        
        # Verify correct calculation: 5*50 + 3*60 = 250 + 180 = 430
        expected_sum = Decimal('430.00')
        self.assertEqual(response.context['unbilled_time_sum'], expected_sum)
    
    def test_dashboard_unbilled_time_sum_excludes_billed(self):
        """Test that dashboard unbilled sum excludes billed entries"""
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Unbilled Work',
            hourly_rate=Decimal('50.00'),
            billed=False
        )
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('10.0'),
            activity='Billed Work',
            hourly_rate=Decimal('100.00'),
            billed=True
        )
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        
        # Should only include unbilled: 2*50 = 100
        expected_sum = Decimal('100.00')
        self.assertEqual(response.context['unbilled_time_sum'], expected_sum)


class UnbilledTimeEntriesSumTest(TestCase):
    """Tests for get_unbilled_time_entries_sum service function"""
    
    def setUp(self):
        from .services import get_unbilled_time_entries_sum
        self.get_unbilled_time_entries_sum = get_unbilled_time_entries_sum
        self.payee = Payee.objects.create(name='Test Customer', is_active=True)
    
    def test_unbilled_sum_with_no_entries(self):
        """Test that sum is 0 when there are no time entries"""
        sum_value = self.get_unbilled_time_entries_sum()
        self.assertEqual(sum_value, Decimal('0.00'))
    
    def test_unbilled_sum_with_only_unbilled_entries(self):
        """Test sum calculation with only unbilled entries"""
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.5'),
            activity='Test 1',
            hourly_rate=Decimal('50.00'),
            billed=False
        )
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('3.0'),
            activity='Test 2',
            hourly_rate=Decimal('60.00'),
            billed=False
        )
        
        sum_value = self.get_unbilled_time_entries_sum()
        expected = Decimal('2.5') * Decimal('50.00') + Decimal('3.0') * Decimal('60.00')
        self.assertEqual(sum_value, expected)  # 125 + 180 = 305
    
    def test_unbilled_sum_excludes_billed_entries(self):
        """Test that sum excludes billed entries"""
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('2.0'),
            activity='Unbilled',
            hourly_rate=Decimal('50.00'),
            billed=False
        )
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('5.0'),
            activity='Billed',
            hourly_rate=Decimal('50.00'),
            billed=True
        )
        
        sum_value = self.get_unbilled_time_entries_sum()
        expected = Decimal('2.0') * Decimal('50.00')
        self.assertEqual(sum_value, expected)  # Only unbilled: 100
    
    def test_unbilled_sum_with_decimal_hours(self):
        """Test sum calculation with decimal hours"""
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('0.5'),
            activity='Half hour',
            hourly_rate=Decimal('100.00'),
            billed=False
        )
        TimeEntry.objects.create(
            payee=self.payee,
            date=date.today(),
            duration_hours=Decimal('1.5'),
            activity='1.5 hours',
            hourly_rate=Decimal('40.00'),
            billed=False
        )
        
        sum_value = self.get_unbilled_time_entries_sum()
        expected = Decimal('110.00')
        self.assertEqual(sum_value, expected)  # 50 + 60 = 110


class FinancialInsightsEngineTest(TestCase):
    """Tests for Financial Insights Engine"""
    
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00'),
            is_liquidity_relevant=True
        )
        self.income_category = Category.objects.create(name='Gehalt', type='income')
        self.expense_category1 = Category.objects.create(name='Miete', type='expense')
        self.expense_category2 = Category.objects.create(name='Freizeit', type='expense')
        
        # Create payees for test bookings
        self.employer_payee = Payee.objects.create(name='Employer')
        self.landlord_payee = Payee.objects.create(name='Landlord')
        self.leisure_payee = Payee.objects.create(name='Leisure Co')
        
        # Create some test bookings
        for i in range(3):
            # Create monthly income
            Booking.objects.create(
                account=self.account,
                booking_date=date.today() - relativedelta(months=i),
                amount=Decimal('3000.00'),
                category=self.income_category,
                payee=self.employer_payee,
                status='POSTED'
            )
            # Create monthly rent
            Booking.objects.create(
                account=self.account,
                booking_date=date.today() - relativedelta(months=i),
                amount=Decimal('-1000.00'),
                category=self.expense_category1,
                payee=self.landlord_payee,
                status='POSTED'
            )
            # Create variable leisure spending
            Booking.objects.create(
                account=self.account,
                booking_date=date.today() - relativedelta(months=i),
                amount=Decimal('-200.00') * (i + 1),  # Increasing trend
                category=self.expense_category2,
                payee=self.leisure_payee,
                status='POSTED'
            )
    
    def test_aggregate_monthly_liquidity(self):
        """Test monthly liquidity aggregation"""
        from core.services.financial_insights_engine import aggregate_monthly_liquidity
        
        result = aggregate_monthly_liquidity(months=3)
        
        # Should have 3 months of data
        self.assertEqual(len(result), 3)
        
        # Each entry should have month and ist keys
        for entry in result:
            self.assertIn('month', entry)
            self.assertIn('ist', entry)
            self.assertIsInstance(entry['ist'], float)
    
    def test_aggregate_category_summaries(self):
        """Test category summaries aggregation"""
        from core.services.financial_insights_engine import aggregate_category_summaries
        
        result = aggregate_category_summaries(months=3)
        
        # Should have categories
        self.assertGreater(len(result), 0)
        
        # Find Miete category
        miete_data = next((cat for cat in result if cat['name'] == 'Miete'), None)
        self.assertIsNotNone(miete_data)
        
        # Miete should have total and monthly data
        self.assertIn('total', miete_data)
        self.assertIn('monthly', miete_data)
        self.assertIsInstance(miete_data['total'], float)
        
        # Should have 3 months of data
        self.assertEqual(len(miete_data['monthly']), 3)
    
    def test_aggregate_booking_entries(self):
        """Test booking entries aggregation"""
        from core.services.financial_insights_engine import aggregate_booking_entries
        
        result = aggregate_booking_entries(months=3, limit=10)
        
        # Should have some entries
        self.assertGreater(len(result), 0)
        
        # Each entry should have required fields
        for entry in result:
            self.assertIn('date', entry)
            self.assertIn('amount', entry)
            self.assertIn('category', entry)
    
    def test_build_analysis_dataset(self):
        """Test complete dataset building"""
        from core.services.financial_insights_engine import build_analysis_dataset
        
        dataset = build_analysis_dataset(months=3)
        
        # Should have all required keys
        self.assertIn('period_months', dataset)
        self.assertIn('monthly_liquidity', dataset)
        self.assertIn('categories', dataset)
        self.assertIn('entries', dataset)
        
        # Verify period
        self.assertEqual(dataset['period_months'], 3)
    
    def test_create_agent_prompt(self):
        """Test agent prompt creation"""
        from core.services.financial_insights_engine import create_agent_prompt
        
        dataset = {
            'period_months': 3,
            'monthly_liquidity': [{'month': '2025-01', 'ist': 1000.0}],
            'categories': [{'name': 'Test', 'total': 100.0, 'monthly': []}],
            'entries': []
        }
        
        prompt = create_agent_prompt(dataset)
        
        # Prompt should contain key instructions
        self.assertIn('Analysiere', prompt)
        self.assertIn('Klassifiziere', prompt)
        self.assertIn('MUSS', prompt)
        self.assertIn('NICE_TO_HAVE', prompt)
        self.assertIn('UNSINN', prompt)
    
    def test_parse_agent_response_valid(self):
        """Test parsing valid agent response"""
        from core.services.financial_insights_engine import parse_agent_response
        import json
        
        valid_response = {
            'result': json.dumps({
                'classification': {
                    'MUSS': ['Miete'],
                    'NICE_TO_HAVE': ['Freizeit'],
                    'UNSINN': []
                },
                'trends': {
                    'liquidity': {
                        'direction': 'stable',
                        'avg_change': 0.0,
                        'comment': 'Test'
                    }
                },
                'forecast': {
                    '6_months': 'Test forecast',
                    '12_months': 'Test forecast',
                    '24_months': 'Test forecast'
                },
                'recommendations': ['Test recommendation']
            })
        }
        
        result = parse_agent_response(valid_response)
        
        self.assertIsNotNone(result)
        self.assertIn('classification', result)
        self.assertIn('trends', result)
        self.assertIn('forecast', result)
        self.assertIn('recommendations', result)
    
    def test_parse_agent_response_invalid(self):
        """Test parsing invalid agent response"""
        from core.services.financial_insights_engine import parse_agent_response
        
        invalid_response = {'result': 'not valid json'}
        
        result = parse_agent_response(invalid_response)
        
        self.assertIsNone(result)
    
    def test_aggregate_booking_entries_excludes_no_category(self):
        """Test that bookings without category are excluded"""
        from core.services.financial_insights_engine import aggregate_booking_entries
        
        payee = Payee.objects.create(name='Test Payee')
        
        # Create booking without category but with payee
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            category=None,  # No category
            payee=payee,
            status='POSTED'
        )
        
        result = aggregate_booking_entries(months=1, limit=10)
        
        # Should not include the booking without category
        self.assertEqual(len([e for e in result if e.get('payee') == 'Test Payee']), 0)
    
    def test_aggregate_booking_entries_excludes_no_payee(self):
        """Test that bookings without payee are excluded"""
        from core.services.financial_insights_engine import aggregate_booking_entries
        
        # Create booking with category but without payee
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            category=self.expense_category1,
            payee=None,  # No payee
            status='POSTED'
        )
        
        result = aggregate_booking_entries(months=1, limit=10)
        
        # Count bookings for the expense category
        expense_bookings = [e for e in result if e.get('category') == 'Miete' and e.get('payee') is None]
        
        # Should not include the booking without payee
        self.assertEqual(len(expense_bookings), 0)
    
    def test_aggregate_booking_entries_includes_valid(self):
        """Test that bookings with both category and payee are included"""
        from core.services.financial_insights_engine import aggregate_booking_entries
        
        payee = Payee.objects.create(name='Valid Payee')
        
        # Create valid booking with both category and payee
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-100.00'),
            category=self.expense_category1,
            payee=payee,
            status='POSTED'
        )
        
        result = aggregate_booking_entries(months=1, limit=10)
        
        # Should include the valid booking
        valid_bookings = [e for e in result if e.get('payee') == 'Valid Payee']
        self.assertEqual(len(valid_bookings), 1)
        self.assertEqual(valid_bookings[0]['category'], 'Miete')
    
    def test_aggregate_category_summaries_excludes_no_category(self):
        """Test that category summaries exclude bookings without category"""
        from core.services.financial_insights_engine import aggregate_category_summaries
        
        payee = Payee.objects.create(name='Test Payee')
        
        # Create booking without category
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-500.00'),
            category=None,
            payee=payee,
            status='POSTED'
        )
        
        result = aggregate_category_summaries(months=1)
        
        # Should not have "Ohne Kategorie" in results
        categories = [cat['name'] for cat in result]
        self.assertNotIn('Ohne Kategorie', categories)
    
    def test_aggregate_category_summaries_excludes_no_payee(self):
        """Test that category summaries exclude bookings without payee"""
        from core.services.financial_insights_engine import aggregate_category_summaries
        
        # Get initial total for Miete category
        initial_result = aggregate_category_summaries(months=3)
        initial_miete = next((cat for cat in initial_result if cat['name'] == 'Miete'), None)
        initial_total = initial_miete['total'] if initial_miete else 0.0
        
        # Create booking with category but without payee
        Booking.objects.create(
            account=self.account,
            booking_date=date.today(),
            amount=Decimal('-500.00'),
            category=self.expense_category1,
            payee=None,
            status='POSTED'
        )
        
        result = aggregate_category_summaries(months=3)
        miete_data = next((cat for cat in result if cat['name'] == 'Miete'), None)
        
        # Total should not have increased by 500
        self.assertIsNotNone(miete_data)
        self.assertAlmostEqual(miete_data['total'], initial_total, places=2)
    
    def test_aggregate_recurring_bookings(self):
        """Test recurring bookings aggregation"""
        from core.services.financial_insights_engine import aggregate_recurring_bookings
        
        payee = Payee.objects.create(name='Landlord')
        
        # Create a recurring booking
        RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-1200.00'),
            category=self.expense_category1,
            payee=payee,
            description='Monthly Rent',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            interval=1,
            day_of_month=1,
            is_active=True
        )
        
        result = aggregate_recurring_bookings()
        
        # Should have one recurring booking
        self.assertEqual(len(result), 1)
        
        # Check fields
        self.assertEqual(result[0]['amount'], -1200.0)
        self.assertEqual(result[0]['category'], 'Miete')
        self.assertEqual(result[0]['payee'], 'Landlord')
        self.assertEqual(result[0]['frequency'], 'Monatlich')
        self.assertEqual(result[0]['interval'], 1)
    
    def test_aggregate_recurring_bookings_excludes_transfers(self):
        """Test that recurring transfers are excluded"""
        from core.services.financial_insights_engine import aggregate_recurring_bookings
        
        account2 = Account.objects.create(
            name='Savings',
            type='checking',
            initial_balance=Decimal('0.00')
        )
        
        # Create a recurring transfer
        RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-200.00'),
            description='Monthly Savings',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            interval=1,
            day_of_month=1,
            is_active=True,
            is_transfer=True,
            transfer_partner_account=account2
        )
        
        result = aggregate_recurring_bookings()
        
        # Should not include transfers
        self.assertEqual(len(result), 0)
    
    def test_aggregate_recurring_bookings_excludes_no_category(self):
        """Test that recurring bookings without category are excluded"""
        from core.services.financial_insights_engine import aggregate_recurring_bookings
        
        payee = Payee.objects.create(name='Test Payee')
        
        # Create recurring booking without category
        RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-100.00'),
            category=None,
            payee=payee,
            description='No category recurring',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            interval=1,
            day_of_month=1,
            is_active=True
        )
        
        result = aggregate_recurring_bookings()
        
        # Should not include recurring booking without category
        no_cat_recurring = [r for r in result if r.get('payee') == 'Test Payee']
        self.assertEqual(len(no_cat_recurring), 0)
    
    def test_aggregate_recurring_bookings_excludes_no_payee(self):
        """Test that recurring bookings without payee are excluded"""
        from core.services.financial_insights_engine import aggregate_recurring_bookings
        
        # Create recurring booking without payee
        RecurringBooking.objects.create(
            account=self.account,
            amount=Decimal('-100.00'),
            category=self.expense_category1,
            payee=None,
            description='No payee recurring',
            start_date=date(2025, 1, 1),
            frequency='MONTHLY',
            interval=1,
            day_of_month=1,
            is_active=True
        )
        
        result = aggregate_recurring_bookings()
        
        # Should not include recurring booking without payee
        no_payee_recurring = [r for r in result if r.get('category') == 'Miete' and r.get('payee') is None]
        self.assertEqual(len(no_payee_recurring), 0)
    
    def test_aggregate_planned_bookings(self):
        """Test planned future bookings aggregation"""
        from core.services.financial_insights_engine import aggregate_planned_bookings
        
        payee = Payee.objects.create(name='Insurance Co')
        
        # Create planned future booking
        future_date = date.today() + relativedelta(months=1)
        Booking.objects.create(
            account=self.account,
            booking_date=future_date,
            amount=Decimal('-500.00'),
            category=self.expense_category1,
            payee=payee,
            description='Insurance payment',
            status='PLANNED'
        )
        
        result = aggregate_planned_bookings()
        
        # Should have one planned booking
        self.assertEqual(len(result), 1)
        
        # Check fields
        self.assertEqual(result[0]['amount'], -500.0)
        self.assertEqual(result[0]['category'], 'Miete')
        self.assertEqual(result[0]['payee'], 'Insurance Co')
        self.assertTrue(result[0]['is_one_time'])
    
    def test_aggregate_planned_bookings_excludes_past(self):
        """Test that planned bookings in the past are excluded"""
        from core.services.financial_insights_engine import aggregate_planned_bookings
        
        payee = Payee.objects.create(name='Past Payee')
        
        # Create planned booking in the past
        past_date = date.today() - relativedelta(months=1)
        Booking.objects.create(
            account=self.account,
            booking_date=past_date,
            amount=Decimal('-100.00'),
            category=self.expense_category1,
            payee=payee,
            status='PLANNED'
        )
        
        result = aggregate_planned_bookings()
        
        # Should not include past bookings
        past_bookings = [b for b in result if b['payee'] == 'Past Payee']
        self.assertEqual(len(past_bookings), 0)
    
    def test_aggregate_planned_bookings_excludes_no_category(self):
        """Test that planned bookings without category are excluded"""
        from core.services.financial_insights_engine import aggregate_planned_bookings
        
        payee = Payee.objects.create(name='Test Payee')
        
        # Create planned booking without category
        future_date = date.today() + relativedelta(months=1)
        Booking.objects.create(
            account=self.account,
            booking_date=future_date,
            amount=Decimal('-100.00'),
            category=None,
            payee=payee,
            status='PLANNED'
        )
        
        result = aggregate_planned_bookings()
        
        # Should not include booking without category
        no_cat_bookings = [b for b in result if b['payee'] == 'Test Payee']
        self.assertEqual(len(no_cat_bookings), 0)
    
    def test_aggregate_planned_bookings_excludes_no_payee(self):
        """Test that planned bookings without payee are excluded"""
        from core.services.financial_insights_engine import aggregate_planned_bookings
        
        # Create planned booking without payee
        future_date = date.today() + relativedelta(months=1)
        Booking.objects.create(
            account=self.account,
            booking_date=future_date,
            amount=Decimal('-100.00'),
            category=self.expense_category1,
            payee=None,
            status='PLANNED'
        )
        
        result = aggregate_planned_bookings()
        
        # Should not include booking without payee
        no_payee_bookings = [b for b in result if b.get('category') == 'Miete' and b.get('payee') is None]
        self.assertEqual(len(no_payee_bookings), 0)
    
    def test_build_analysis_dataset_includes_new_sections(self):
        """Test that dataset includes recurring_bookings and planned_bookings"""
        from core.services.financial_insights_engine import build_analysis_dataset
        
        dataset = build_analysis_dataset(months=3)
        
        # Should have new keys
        self.assertIn('recurring_bookings', dataset)
        self.assertIn('planned_bookings', dataset)
        
        # Should be lists
        self.assertIsInstance(dataset['recurring_bookings'], list)
        self.assertIsInstance(dataset['planned_bookings'], list)
    
    def test_create_agent_prompt_mentions_new_sections(self):
        """Test that prompt explains the new data sections"""
        from core.services.financial_insights_engine import create_agent_prompt
        
        dataset = {
            'period_months': 3,
            'monthly_liquidity': [],
            'categories': [],
            'entries': [],
            'recurring_bookings': [],
            'planned_bookings': []
        }
        
        prompt = create_agent_prompt(dataset)
        
        # Prompt should mention the new sections
        self.assertIn('recurring_bookings', prompt)
        self.assertIn('planned_bookings', prompt)
        self.assertIn('wiederkehrende', prompt.lower())
        self.assertIn('einmalige', prompt.lower())


class AIAnalysisViewTest(TestCase):
    """Tests for AI Analysis view"""
    
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00'),
            is_liquidity_relevant=True
        )
    
    def test_ai_analysis_view_accessible(self):
        """Test that AI analysis view is accessible"""
        response = self.client.get('/analytics/ai-analysis/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KI-Finanzanalyse')
    
    def test_ai_analysis_view_requires_login(self):
        """Test that AI analysis view requires login"""
        self.client.logout()
        response = self.client.get('/analytics/ai-analysis/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
    
    def test_ai_analysis_view_initial_state(self):
        """Test initial state without analysis"""
        response = self.client.get('/analytics/ai-analysis/')
        self.assertEqual(response.status_code, 200)
        
        # Should show period selection
        self.assertContains(response, 'Analysezeitraum')
        self.assertContains(response, '3 Monate')
        self.assertContains(response, '6 Monate')
        self.assertContains(response, '12 Monate')
        self.assertContains(response, '24 Monate')
    
    def test_ai_analysis_view_with_insufficient_data(self):
        """Test behavior with insufficient data"""
        # Try to analyze with no bookings
        response = self.client.get('/analytics/ai-analysis/?analyze=1&months=6')
        self.assertEqual(response.status_code, 200)
        
        # Should show error message
        self.assertContains(response, 'Nicht genügend Daten')
    
    def test_ai_analysis_view_period_validation(self):
        """Test that invalid period is corrected"""
        # Try with invalid period
        response = self.client.get('/analytics/ai-analysis/?months=999')
        self.assertEqual(response.status_code, 200)
        
        # Should default to 6 months
        self.assertEqual(response.context['selected_months'], 6)
