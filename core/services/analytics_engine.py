"""
Analytics Engine - Category analysis and reporting

Handles aggregation and analysis of bookings by category.
"""
from decimal import Decimal
from datetime import date
from django.db.models import Sum, Q
from collections import defaultdict

from core.models import Booking, Category


def get_category_analysis(start_date, end_date, account=None, status='POSTED'):
    """
    Analyze bookings by category for a given period.
    
    Args:
        start_date: Start date of the period
        end_date: End date of the period
        account: Optional Account instance to filter by
        status: Booking status to include (default: 'POSTED' for actual analysis)
    
    Returns:
        dict: Analysis results with expenses, income, and net by category
    """
    # Build base query
    query = Q(
        booking_date__gte=start_date,
        booking_date__lte=end_date,
        status=status
    )
    
    if account:
        query &= Q(account=account)
    
    bookings = Booking.objects.filter(query).select_related('category')
    
    # Aggregate by category
    expenses_by_category = defaultdict(lambda: Decimal('0.00'))
    income_by_category = defaultdict(lambda: Decimal('0.00'))
    category_names = {}
    
    for booking in bookings:
        category_name = booking.category.name if booking.category else 'Ohne Kategorie'
        category_id = booking.category.id if booking.category else None
        
        category_names[category_name] = category_id
        
        if booking.amount < 0:
            expenses_by_category[category_name] += abs(booking.amount)
        else:
            income_by_category[category_name] += booking.amount
    
    # Calculate net per category
    all_categories = set(expenses_by_category.keys()) | set(income_by_category.keys())
    net_by_category = {}
    
    for category in all_categories:
        net = income_by_category[category] - expenses_by_category[category]
        net_by_category[category] = net
    
    # Sort categories by expense (for charts)
    sorted_expenses = sorted(
        expenses_by_category.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # Calculate totals
    total_expenses = sum(expenses_by_category.values())
    total_income = sum(income_by_category.values())
    total_net = total_income - total_expenses
    
    return {
        'expenses_by_category': dict(expenses_by_category),
        'income_by_category': dict(income_by_category),
        'net_by_category': net_by_category,
        'sorted_expenses': sorted_expenses,
        'category_names': category_names,
        'total_expenses': total_expenses,
        'total_income': total_income,
        'total_net': total_net,
        'period': {
            'start': start_date,
            'end': end_date,
        }
    }


def get_top_categories(start_date, end_date, account=None, status='POSTED', limit=10, by='expenses'):
    """
    Get top N categories by expenses or income.
    
    Args:
        start_date: Start date of the period
        end_date: End date of the period
        account: Optional Account instance to filter by
        status: Booking status to include
        limit: Number of top categories to return
        by: 'expenses' or 'income'
    
    Returns:
        list: List of tuples (category_name, amount)
    """
    analysis = get_category_analysis(start_date, end_date, account, status)
    
    if by == 'expenses':
        data = analysis['sorted_expenses']
    else:
        data = sorted(
            analysis['income_by_category'].items(),
            key=lambda x: x[1],
            reverse=True
        )
    
    return data[:limit]
