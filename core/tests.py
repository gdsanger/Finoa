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
