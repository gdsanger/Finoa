"""
Recurrence Engine - Generates virtual bookings from recurring templates

Handles the generation of virtual bookings for forecast calculations.
"""
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from core.models import RecurringBooking


def generate_virtual_bookings(account=None, start_date=None, end_date=None):
    """
    Generate virtual bookings from recurring booking templates.
    
    Args:
        account: Optional Account instance to filter by
        start_date: Start date for generation (default: today)
        end_date: End date for generation
    
    Returns:
        list: List of dicts representing virtual bookings with keys:
              date, amount, description, category, recurring_booking_id
    """
    if start_date is None:
        start_date = date.today()
    
    if end_date is None:
        end_date = start_date + relativedelta(months=6)
    
    # Get active recurring bookings
    recurring_bookings = RecurringBooking.objects.filter(is_active=True)
    
    if account:
        recurring_bookings = recurring_bookings.filter(account=account)
    
    virtual_bookings = []
    
    for recurring in recurring_bookings:
        # Generate virtual bookings for this recurring template
        virtual_bookings.extend(
            _generate_bookings_for_recurring(recurring, start_date, end_date)
        )
    
    # Sort by date
    virtual_bookings.sort(key=lambda x: x['date'])
    
    return virtual_bookings


def _generate_bookings_for_recurring(recurring, start_date, end_date):
    """
    Generate virtual bookings for a single recurring booking template.
    
    Args:
        recurring: RecurringBooking instance
        start_date: Start date for generation
        end_date: End date for generation
    
    Returns:
        list: List of virtual booking dicts
    """
    virtual_bookings = []
    
    # Determine the first occurrence date
    current_date = recurring.start_date
    
    # Skip to the first date that's >= start_date
    while current_date < start_date:
        current_date = _next_occurrence(current_date, recurring)
    
    # Generate occurrences
    while current_date <= end_date:
        # Check if we're past the end_date of the recurring booking
        if recurring.end_date and current_date > recurring.end_date:
            break
        
        virtual_bookings.append({
            'date': current_date,
            'amount': recurring.amount,
            'description': recurring.description,
            'category': recurring.category,
            'recurring_booking_id': recurring.id,
            'account': recurring.account,
            'is_transfer': recurring.is_transfer,
            'transfer_partner_account': recurring.transfer_partner_account,
        })
        
        current_date = _next_occurrence(current_date, recurring)
    
    return virtual_bookings


def _next_occurrence(current_date, recurring):
    """
    Calculate the next occurrence date for a recurring booking.
    
    Args:
        current_date: Current date
        recurring: RecurringBooking instance
    
    Returns:
        date: Next occurrence date
    """
    if recurring.frequency == 'MONTHLY':
        # Add interval months
        next_date = current_date + relativedelta(months=recurring.interval)
        
        # Ensure day_of_month is valid for the target month
        try:
            next_date = next_date.replace(day=recurring.day_of_month)
        except ValueError:
            # Handle cases like day 31 in February - use last day of month
            next_date = next_date + relativedelta(day=31)
        
        return next_date
    
    # Default fallback (should not happen with current model)
    return current_date + relativedelta(months=1)


def get_virtual_bookings_for_month(account, year, month):
    """
    Get all virtual bookings for a specific month and account.
    
    Args:
        account: Account instance
        year: Year (int)
        month: Month (int, 1-12)
    
    Returns:
        list: List of virtual booking dicts
    """
    start_date = date(year, month, 1)
    
    # Calculate last day of month
    if month == 12:
        end_date = date(year + 1, 1, 1) - relativedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - relativedelta(days=1)
    
    return generate_virtual_bookings(account, start_date, end_date)
