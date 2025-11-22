from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import json

from .models import Account, Booking, Category, RecurringBooking, Payee
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


def _build_total_liquidity_timeline(months=6, liquidity_relevant_only=False):
    """
    Helper function to build timeline data for total liquidity or assets.
    
    Args:
        months: Number of months to project
        liquidity_relevant_only: Whether to include only liquidity-relevant accounts
    
    Returns:
        dict: Timeline data with months, actual, and forecast arrays
    """
    timeline_months = []
    timeline_actual = []
    timeline_forecast = []
    
    for month_offset in range(months):
        target_date = date.today() + relativedelta(months=month_offset)
        end_of_month = (target_date.replace(day=1) + relativedelta(months=1)) - relativedelta(days=1)
        
        actual = get_total_liquidity(as_of_date=end_of_month, include_forecast=False, liquidity_relevant_only=liquidity_relevant_only)
        forecast = get_total_liquidity(as_of_date=end_of_month, include_forecast=True, liquidity_relevant_only=liquidity_relevant_only)
        
        timeline_months.append(end_of_month.strftime('%b %Y'))
        timeline_actual.append(float(actual))
        timeline_forecast.append(float(forecast))
    
    return {
        'months': timeline_months,
        'actual': timeline_actual,
        'forecast': timeline_forecast,
    }


@login_required
def dashboard(request):
    """
    Dashboard view showing:
    - Total liquidity (actual & forecast) - only liquidity-relevant accounts
    - Total assets (actual & forecast) - all accounts
    - Summary of all accounts with end-of-month forecast
    - 6-month forecast charts (liquidity and assets)
    """
    accounts = Account.objects.filter(is_active=True)
    
    # Calculate total liquidity (liquidity-relevant accounts only)
    liquidity_actual = get_total_liquidity(include_forecast=False, liquidity_relevant_only=True)
    liquidity_forecast = get_total_liquidity(include_forecast=True, liquidity_relevant_only=True)
    
    # Calculate total assets (all accounts)
    assets_actual = get_total_liquidity(include_forecast=False, liquidity_relevant_only=False)
    assets_forecast = get_total_liquidity(include_forecast=True, liquidity_relevant_only=False)
    
    # Prepare account summaries with end-of-month forecast
    account_summaries = []
    today = date.today()
    end_of_current_month = (today.replace(day=1) + relativedelta(months=1)) - relativedelta(days=1)
    
    for account in accounts:
        actual_balance = calculate_actual_balance(account)
        forecast_balance_today = calculate_forecast_balance(account, as_of_date=today)
        forecast_balance_eom = calculate_forecast_balance(account, as_of_date=end_of_current_month)
        
        account_summaries.append({
            'account': account,
            'actual_balance': actual_balance,
            'forecast_balance_today': forecast_balance_today,
            'forecast_balance_eom': forecast_balance_eom,
        })
    
    # Build timeline for liquidity chart (6 months)
    liquidity_timeline_data = None
    if accounts.exists():
        liquidity_timeline_data = _build_total_liquidity_timeline(months=6, liquidity_relevant_only=True)
    
    # Build timeline for assets chart (6 months)
    assets_timeline_data = None
    if accounts.exists():
        assets_timeline_data = _build_total_liquidity_timeline(months=6, liquidity_relevant_only=False)
    
    context = {
        'liquidity_actual': liquidity_actual,
        'liquidity_forecast': liquidity_forecast,
        'assets_actual': assets_actual,
        'assets_forecast': assets_forecast,
        'account_summaries': account_summaries,
        'liquidity_timeline_data': liquidity_timeline_data,
        'assets_timeline_data': assets_timeline_data,
    }
    
    return render(request, 'core/dashboard.html', context)


@login_required
def accounts(request):
    """
    Accounts overview showing all accounts with balances (without forecast charts)
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


@login_required
def account_detail(request, account_id):
    """
    Account detail view showing:
    - Account summary with booking counts
    - Current and forecast balances
    - 6-month forecast chart
    - Bookings for selected month (posted, planned, and virtual from recurring)
    - Recurring bookings management (links to admin interface for CRUD)
    
    Note: Full CRUD operations within this view are planned for future implementation with HTMX.
    Currently provides read access and links to admin interface for create/update/delete operations.
    """
    account = get_object_or_404(Account, id=account_id, is_active=True)
    
    # Get current year and month
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))
    
    # Calculate balances
    actual_balance = calculate_actual_balance(account)
    forecast_balance = calculate_forecast_balance(account)
    
    # Build 6-month timeline for this account
    timeline = build_account_timeline(account, months=6, include_forecast=True)
    
    timeline_data = {
        'months': [t['date'].strftime('%b %Y') for t in timeline],
        'actual': [float(t['actual_balance']) for t in timeline],
        'forecast': [float(t['forecast_balance']) for t in timeline],
    }
    
    # Get bookings for the current/selected month
    start_of_month = date(year, month, 1)
    end_of_month = (start_of_month + relativedelta(months=1)) - relativedelta(days=1)
    
    posted_bookings = Booking.objects.filter(
        account=account,
        booking_date__gte=start_of_month,
        booking_date__lte=end_of_month,
        status='POSTED'
    ).order_by('-booking_date')
    
    planned_bookings = Booking.objects.filter(
        account=account,
        booking_date__gte=start_of_month,
        booking_date__lte=end_of_month,
        status='PLANNED'
    ).order_by('-booking_date')
    
    # Get virtual bookings from recurring
    virtual_bookings = get_virtual_bookings_for_month(account, year, month)
    
    # Get all recurring bookings for this account
    recurring_bookings = RecurringBooking.objects.filter(
        account=account,
        is_active=True
    ).order_by('day_of_month')
    
    # Count bookings
    posted_count = posted_bookings.count()
    planned_count = planned_bookings.count()
    recurring_count = recurring_bookings.count()
    
    # Prepare navigation (prev/next month)
    prev_month_date = date(year, month, 1) - relativedelta(months=1)
    next_month_date = date(year, month, 1) + relativedelta(months=1)
    
    context = {
        'account': account,
        'actual_balance': actual_balance,
        'forecast_balance': forecast_balance,
        'timeline_data': timeline_data,
        'year': year,
        'month': month,
        'month_name': date(year, month, 1).strftime('%B %Y'),
        'posted_bookings': posted_bookings,
        'planned_bookings': planned_bookings,
        'virtual_bookings': virtual_bookings,
        'recurring_bookings': recurring_bookings,
        'posted_count': posted_count,
        'planned_count': planned_count,
        'recurring_count': recurring_count,
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
        'categories': Category.objects.all(),
        'all_accounts': Account.objects.filter(is_active=True),
        'payees': Payee.objects.filter(is_active=True),
    }
    
    return render(request, 'core/account_detail.html', context)


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


@login_required
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


@login_required
def payees(request):
    """
    Payee management view showing all payees with booking counts
    """
    payees_list = Payee.objects.annotate(
        booking_count=Count('bookings'),
        recurring_booking_count=Count('recurring_bookings')
    ).order_by('-is_active', 'name')
    
    context = {
        'payees': payees_list,
    }
    
    return render(request, 'core/payees.html', context)
