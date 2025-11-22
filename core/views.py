from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from .models import Account, Booking, Category, RecurringBooking
from .services import (
    calculate_actual_balance,
    calculate_forecast_balance,
    build_account_timeline,
    create_transfer,
    generate_virtual_bookings,
    get_virtual_bookings_for_month,
    get_total_liquidity,
)


def dashboard(request):
    """
    Dashboard view showing:
    - Total liquidity (actual & forecast)
    - Summary of all accounts
    - 6-month forecast chart
    """
    accounts = Account.objects.filter(is_active=True)
    
    # Calculate total liquidity
    total_actual = get_total_liquidity(include_forecast=False)
    total_forecast = get_total_liquidity(include_forecast=True)
    
    # Prepare account summaries
    account_summaries = []
    for account in accounts:
        actual_balance = calculate_actual_balance(account)
        forecast_balance = calculate_forecast_balance(account)
        
        account_summaries.append({
            'account': account,
            'actual_balance': actual_balance,
            'forecast_balance': forecast_balance,
        })
    
    # Build timeline for chart (6 months)
    # Use first account for demo, or aggregate in future
    timeline_data = None
    if accounts.exists():
        # For simplicity, show timeline of total liquidity
        timeline_months = []
        timeline_actual = []
        timeline_forecast = []
        
        for month_offset in range(6):
            target_date = date.today() + relativedelta(months=month_offset)
            end_of_month = (target_date.replace(day=1) + relativedelta(months=1)) - relativedelta(days=1)
            
            actual = get_total_liquidity(as_of_date=end_of_month, include_forecast=False)
            forecast = get_total_liquidity(as_of_date=end_of_month, include_forecast=True)
            
            timeline_months.append(end_of_month.strftime('%b %Y'))
            timeline_actual.append(float(actual))
            timeline_forecast.append(float(forecast))
        
        timeline_data = {
            'months': timeline_months,
            'actual': timeline_actual,
            'forecast': timeline_forecast,
        }
    
    context = {
        'total_actual': total_actual,
        'total_forecast': total_forecast,
        'account_summaries': account_summaries,
        'timeline_data': timeline_data,
    }
    
    return render(request, 'core/dashboard.html', context)


def accounts(request):
    """
    Accounts overview showing all accounts with balances
    """
    accounts = Account.objects.filter(is_active=True)
    
    account_list = []
    for account in accounts:
        actual_balance = calculate_actual_balance(account)
        forecast_balance = calculate_forecast_balance(account)
        
        account_list.append({
            'account': account,
            'actual_balance': actual_balance,
            'forecast_balance': forecast_balance,
        })
    
    context = {
        'account_list': account_list,
    }
    
    return render(request, 'core/accounts.html', context)


def monthly_view(request):
    """
    Monthly view showing bookings for a specific month and account
    """
    # Get current year and month
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))
    account_id = request.GET.get('account_id')
    
    # Get all accounts for dropdown
    accounts = Account.objects.filter(is_active=True)
    
    # Select account
    selected_account = None
    if account_id:
        selected_account = get_object_or_404(Account, id=account_id, is_active=True)
    elif accounts.exists():
        selected_account = accounts.first()
    
    # Get bookings for the month
    bookings = []
    virtual_bookings = []
    running_balance = Decimal('0.00')
    
    if selected_account:
        # Calculate starting balance (balance at end of previous month)
        start_of_month = date(year, month, 1)
        previous_month_end = start_of_month - relativedelta(days=1)
        running_balance = calculate_actual_balance(selected_account, previous_month_end)
        
        # Get actual bookings (POSTED + PLANNED)
        end_of_month = (start_of_month + relativedelta(months=1)) - relativedelta(days=1)
        
        bookings = Booking.objects.filter(
            account=selected_account,
            booking_date__gte=start_of_month,
            booking_date__lte=end_of_month
        ).exclude(status='CANCELLED').order_by('booking_date')
        
        # Get virtual bookings from recurring
        virtual_bookings = get_virtual_bookings_for_month(selected_account, year, month)
    
    # Prepare navigation (prev/next month)
    prev_month_date = date(year, month, 1) - relativedelta(months=1)
    next_month_date = date(year, month, 1) + relativedelta(months=1)
    
    context = {
        'accounts': accounts,
        'selected_account': selected_account,
        'year': year,
        'month': month,
        'month_name': date(year, month, 1).strftime('%B %Y'),
        'bookings': bookings,
        'virtual_bookings': virtual_bookings,
        'running_balance': running_balance,
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
        'categories': Category.objects.all(),
    }
    
    return render(request, 'core/monthly_view.html', context)
