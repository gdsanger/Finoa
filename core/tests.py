from django.test import TestCase
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta

from .models import Account, Category, Booking, RecurringBooking
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


class ViewTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test Account',
            type='checking',
            initial_balance=Decimal('1000.00')
        )

    def test_dashboard_view(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')

    def test_accounts_view(self):
        response = self.client.get('/accounts/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Account')

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
