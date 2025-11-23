"""
Finance Engine - Core calculation logic for Finoa

Handles balance calculations, forecasts, and transfer operations.
"""
from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
import uuid

from core.models import Account, Booking


def calculate_actual_balance(account, as_of_date=None):
    """
    Calculate the actual (posted) balance of an account.
    
    Formula: initial_balance + sum of all POSTED bookings up to as_of_date
    
    Args:
        account: Account instance
        as_of_date: Date to calculate balance for (default: today)
    
    Returns:
        Decimal: The actual balance
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    posted_sum = account.bookings.filter(
        status='POSTED',
        booking_date__lte=as_of_date
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return account.initial_balance + posted_sum


def calculate_forecast_balance(account, as_of_date=None, include_recurring=True):
    """
    Calculate the forecast balance of an account.
    
    Formula: actual_balance + PLANNED bookings + virtual recurring bookings
    
    Args:
        account: Account instance
        as_of_date: Date to forecast to (default: today)
        include_recurring: Whether to include virtual recurring bookings
    
    Returns:
        Decimal: The forecast balance
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    # Start with actual balance
    balance = calculate_actual_balance(account, as_of_date)
    
    # Add planned bookings
    planned_sum = account.bookings.filter(
        status='PLANNED',
        booking_date__lte=as_of_date
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    balance += planned_sum
    
    # Add virtual recurring bookings if requested
    if include_recurring:
        from .recurrence_engine import generate_virtual_bookings
        
        # Get all virtual bookings up to as_of_date
        virtual_bookings = generate_virtual_bookings(
            account=account,
            start_date=date.today(),
            end_date=as_of_date
        )
        
        virtual_sum = sum(booking['amount'] for booking in virtual_bookings)
        balance += Decimal(str(virtual_sum))
    
    return balance


def build_account_timeline(account, start_date=None, months=6, include_forecast=True):
    """
    Build a timeline of balances for an account.
    
    Returns both actual and forecast balances for each month.
    
    Args:
        account: Account instance
        start_date: Starting date (default: today)
        months: Number of months to project
        include_forecast: Whether to include forecast data
    
    Returns:
        list: List of dicts with keys: date, actual_balance, forecast_balance
    """
    if start_date is None:
        start_date = date.today()
    
    timeline = []
    current_date = start_date
    
    for _ in range(months):
        # Calculate end of month
        end_of_month = (current_date + relativedelta(months=1)) - timedelta(days=1)
        
        actual_balance = calculate_actual_balance(account, end_of_month)
        
        forecast_balance = None
        if include_forecast:
            forecast_balance = calculate_forecast_balance(
                account, 
                end_of_month, 
                include_recurring=True
            )
        
        timeline.append({
            'date': end_of_month,
            'month': end_of_month.strftime('%Y-%m'),
            'actual_balance': actual_balance,
            'forecast_balance': forecast_balance,
        })
        
        current_date = current_date + relativedelta(months=1)
    
    return timeline


def create_transfer(from_account, to_account, amount, booking_date, description='', category=None):
    """
    Create a transfer (Umbuchung) between two accounts.
    
    Creates two linked bookings:
    - One negative booking in the source account
    - One positive booking in the target account
    
    Args:
        from_account: Source Account instance
        to_account: Target Account instance
        amount: Amount to transfer (positive value)
        booking_date: Date of the transfer
        description: Optional description
        category: Optional Category instance
    
    Returns:
        tuple: (from_booking, to_booking)
    """
    if amount <= 0:
        raise ValueError("Transfer amount must be positive")
    
    # Generate a unique transfer group ID
    transfer_group_id = uuid.uuid4()
    
    # Create the outgoing booking
    from_booking = Booking.objects.create(
        account=from_account,
        booking_date=booking_date,
        amount=-abs(Decimal(str(amount))),
        category=category,
        description=description,
        status='POSTED',
        is_transfer=True,
        transfer_group_id=transfer_group_id,
        transfer_partner_account=to_account
    )
    
    # Create the incoming booking
    to_booking = Booking.objects.create(
        account=to_account,
        booking_date=booking_date,
        amount=abs(Decimal(str(amount))),
        category=category,
        description=description,
        status='POSTED',
        is_transfer=True,
        transfer_group_id=transfer_group_id,
        transfer_partner_account=from_account
    )
    
    return from_booking, to_booking


def get_total_liquidity(as_of_date=None, include_forecast=False, liquidity_relevant_only=False):
    """
    Calculate total liquidity across all active accounts.
    
    Args:
        as_of_date: Date to calculate for (default: today)
        include_forecast: Whether to use forecast or actual balances
        liquidity_relevant_only: Whether to only include liquidity-relevant accounts
    
    Returns:
        Decimal: Total liquidity
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    active_accounts = Account.objects.filter(is_active=True)
    
    if liquidity_relevant_only:
        active_accounts = active_accounts.filter(is_liquidity_relevant=True)
    
    total = Decimal('0.00')
    for account in active_accounts:
        if include_forecast:
            balance = calculate_forecast_balance(account, as_of_date)
        else:
            balance = calculate_actual_balance(account, as_of_date)
        total += balance
    
    return total


def get_overdue_bookings_sum():
    """
    Calculate the sum of all overdue planned bookings.
    
    Overdue bookings are those with status='PLANNED' and booking_date < today.
    
    Returns:
        Decimal: Sum of amounts for overdue bookings
    """
    today = date.today()
    
    overdue_sum = Booking.objects.filter(
        status='PLANNED',
        booking_date__lt=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return overdue_sum


def get_upcoming_bookings_sum(days=7):
    """
    Calculate the sum of all planned bookings due within the specified number of days.
    
    Args:
        days: Number of days to look ahead (default: 7)
    
    Returns:
        Decimal: Sum of amounts for upcoming bookings
    """
    today = date.today()
    window_end = today + timedelta(days=days)
    
    upcoming_sum = Booking.objects.filter(
        status='PLANNED',
        booking_date__gte=today,
        booking_date__lte=window_end
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return upcoming_sum
