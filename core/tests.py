from django.test import TestCase
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta

from .models import Account, Category, Booking, RecurringBooking, Payee
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
