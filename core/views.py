from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import json

from .models import Account, Booking, Category, RecurringBooking
from .services import (
    calculate_actual_balance,
    calculate_forecast_balance,
    build_account_timeline,
    create_transfer,
    generate_virtual_bookings,
    get_virtual_bookings_for_month,
    get_total_liquidity,
    get_category_analysis,
    get_top_categories,
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
    Accounts overview showing all accounts with balances and forecast charts
    """
    accounts = Account.objects.filter(is_active=True)
    
    account_list = []
    for account in accounts:
        actual_balance = calculate_actual_balance(account)
        forecast_balance = calculate_forecast_balance(account)
        
        # Build 6-month timeline for this account
        timeline = build_account_timeline(account, months=6, include_forecast=True)
        
        timeline_data = {
            'months': [t['date'].strftime('%b %Y') for t in timeline],
            'actual': [float(t['actual_balance']) for t in timeline],
            'forecast': [float(t['forecast_balance']) for t in timeline],
        }
        
        account_list.append({
            'account': account,
            'actual_balance': actual_balance,
            'forecast_balance': forecast_balance,
            'timeline_data': timeline_data,
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


def category_analytics(request):
    """
    Category analytics view showing income/expense analysis by category.
    Supports filtering by time period and account.
    """
    # Get filter parameters
    filter_type = request.GET.get('filter', 'month')  # 'month' or 'custom'
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))
    account_id = request.GET.get('account_id')
    
    # Calculate date range based on filter type
    if filter_type == 'custom':
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if start_date_str and end_date_str:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        else:
            # Fallback to current month
            start_date = date(year, month, 1)
            end_date = (start_date + relativedelta(months=1)) - relativedelta(days=1)
    else:
        # Default: current/selected month
        start_date = date(year, month, 1)
        end_date = (start_date + relativedelta(months=1)) - relativedelta(days=1)
    
    # Get selected account if any
    selected_account = None
    if account_id:
        selected_account = get_object_or_404(Account, id=account_id, is_active=True)
    
    # Get all accounts for dropdown
    accounts = Account.objects.filter(is_active=True)
    
    # Get category analysis
    analysis = get_category_analysis(
        start_date=start_date,
        end_date=end_date,
        account=selected_account,
        status='POSTED'
    )
    
    # Prepare data for charts
    # Donut chart: Expenses by category
    expense_labels = []
    expense_data = []
    for category, amount in analysis['sorted_expenses']:
        if amount > 0:  # Only include categories with expenses
            expense_labels.append(category)
            expense_data.append(float(amount))
    
    # Bar chart: Top 10 categories
    top_categories = analysis['sorted_expenses'][:10]
    top_labels = [cat[0] for cat in top_categories]
    top_data = [float(cat[1]) for cat in top_categories]
    
    # Prepare table data
    category_table = []
    all_categories = set(analysis['expenses_by_category'].keys()) | set(analysis['income_by_category'].keys())
    for category in sorted(all_categories):
        category_table.append({
            'name': category,
            'expenses': analysis['expenses_by_category'].get(category, Decimal('0.00')),
            'income': analysis['income_by_category'].get(category, Decimal('0.00')),
            'net': analysis['net_by_category'].get(category, Decimal('0.00')),
        })
    
    # Sort by expenses (highest first)
    category_table.sort(key=lambda x: x['expenses'], reverse=True)
    
    # Navigation for month filter
    prev_month_date = date(year, month, 1) - relativedelta(months=1)
    next_month_date = date(year, month, 1) + relativedelta(months=1)
    
    context = {
        'filter_type': filter_type,
        'year': year,
        'month': month,
        'month_name': date(year, month, 1).strftime('%B %Y'),
        'start_date': start_date,
        'end_date': end_date,
        'selected_account': selected_account,
        'accounts': accounts,
        'analysis': analysis,
        'category_table': category_table,
        'expense_labels': json.dumps(expense_labels),
        'expense_data': json.dumps(expense_data),
        'top_labels': json.dumps(top_labels),
        'top_data': json.dumps(top_data),
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
    }
    
    # Return partial template for HTMX requests
    if request.headers.get('HX-Request'):
        return render(request, 'core/partials/category_analytics_content.html', context)
    
    return render(request, 'core/category_analytics.html', context)
