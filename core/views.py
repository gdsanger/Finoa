from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import json
import os

from .models import Account, Booking, Category, RecurringBooking, Payee, DocumentUpload, TimeEntry
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
    get_overdue_bookings_sum,
    get_upcoming_bookings_sum,
)
from .services.document_processor import get_mime_type


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
    
    # Get overdue and upcoming bookings sums
    overdue_sum = get_overdue_bookings_sum()
    upcoming_sum = get_upcoming_bookings_sum(days=7)
    
    # Calculate deficit/surplus relative to liquidity actual
    # Add the sums (which are negative for expenses) to get remaining liquidity
    overdue_deficit = liquidity_actual + overdue_sum
    upcoming_deficit = liquidity_actual + upcoming_sum
    
    context = {
        'liquidity_actual': liquidity_actual,
        'liquidity_forecast': liquidity_forecast,
        'assets_actual': assets_actual,
        'assets_forecast': assets_forecast,
        'account_summaries': account_summaries,
        'liquidity_timeline_data': liquidity_timeline_data,
        'assets_timeline_data': assets_timeline_data,
        'overdue_sum': overdue_sum,
        'upcoming_sum': upcoming_sum,
        'overdue_deficit': overdue_deficit,
        'upcoming_deficit': upcoming_deficit,
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
        'today': date.today(),
        'reconciliation_category_ids': _get_reconciliation_category_ids(),
    }
    
    return render(request, 'core/account_detail.html', context)


def _get_reconciliation_category_ids():
    """Helper function to get category IDs for reconciliation types."""
    category_names = {
        'correction': 'Korrektur',
        'unrealized': 'Unrealisierte Gewinne/Verluste',
        'roundup': 'RoundUp',
        'saveback': 'SaveBack',
    }
    
    result = {}
    for key, name in category_names.items():
        try:
            cat = Category.objects.get(name=name)
            result[key] = cat.id
        except Category.DoesNotExist:
            result[key] = None
    
    return result


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


@login_required
def document_list(request):
    """
    Document upload and listing view.
    Allows users to upload documents and see the list of recent uploads.
    """
    if request.method == 'POST' and request.FILES.get('document'):
        # Handle file upload
        uploaded_file = request.FILES['document']
        
        # Validate file type using file extension
        allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        # Get file extension safely
        _, file_ext = os.path.splitext(uploaded_file.name.lower())
        
        if not file_ext or file_ext not in allowed_extensions:
            messages.error(request, 'Ungültiger Dateityp. Erlaubt sind: PDF, JPG, JPEG, PNG, GIF, BMP, WEBP')
        else:
            # Validate file size (max 10MB)
            max_size = 10 * 1024 * 1024  # 10MB
            if uploaded_file.size > max_size:
                messages.error(request, 'Datei zu groß. Maximale Größe: 10 MB')
            else:
                # Create DocumentUpload
                document = DocumentUpload.objects.create(
                    file=uploaded_file,
                    original_filename=uploaded_file.name,
                    mime_type=get_mime_type(uploaded_file.name),
                    file_size=uploaded_file.size,
                    source='web',
                    status=DocumentUpload.Status.UPLOADED
                )
                messages.success(request, f'Dokument "{uploaded_file.name}" erfolgreich hochgeladen!')
                return redirect('document_list')
    
    # Get all documents ordered by upload date
    documents = DocumentUpload.objects.all().order_by('-uploaded_at')
    
    # Count by status
    status_counts = {
        'uploaded': documents.filter(status=DocumentUpload.Status.UPLOADED).count(),
        'processing': documents.filter(status=DocumentUpload.Status.AI_PROCESSING).count(),
        'review': documents.filter(status=DocumentUpload.Status.REVIEW_PENDING).count(),
        'booked': documents.filter(status=DocumentUpload.Status.BOOKED).count(),
        'error': documents.filter(status=DocumentUpload.Status.ERROR).count(),
    }
    
    context = {
        'documents': documents,
        'status_counts': status_counts,
    }
    
    return render(request, 'core/document_list.html', context)


@login_required
def document_review_list(request):
    """
    List all documents pending review (status = REVIEW_PENDING).
    """
    documents = DocumentUpload.objects.filter(
        status=DocumentUpload.Status.REVIEW_PENDING
    ).order_by('-uploaded_at')
    
    context = {
        'documents': documents,
    }
    
    return render(request, 'core/document_review_list.html', context)

def debug_view(request):
    from django.http import JsonResponse
    return JsonResponse(dict(request.headers))

@login_required
def document_review_detail(request, document_id):
    """
    Detail view for reviewing a document and creating a booking.
    """
    document = get_object_or_404(DocumentUpload, id=document_id)
    
    if request.method == 'POST':
        # Handle booking creation
        try:
            account_id = request.POST.get('account')
            amount = request.POST.get('amount')
            booking_date = request.POST.get('booking_date')
            description = request.POST.get('description', '')
            category_id = request.POST.get('category')
            payee_id = request.POST.get('payee')
            create_recurring = request.POST.get('create_recurring') == 'on'
            
            # Validate required fields
            if not account_id or not amount or not booking_date:
                messages.error(request, 'Konto, Betrag und Datum sind erforderlich.')
                return redirect('document_review_detail', document_id=document_id)
            
            # Get account
            account = get_object_or_404(Account, id=account_id, is_active=True)
            
            # Get category and payee (optional)
            category = None
            if category_id:
                category = get_object_or_404(Category, id=category_id)
            
            payee = None
            if payee_id:
                payee = get_object_or_404(Payee, id=payee_id, is_active=True)
            
            # Create booking
            booking = Booking.objects.create(
                account=account,
                amount=Decimal(amount),
                booking_date=booking_date,
                description=description,
                category=category,
                payee=payee,
                status='POSTED'
            )
            
            # Update document
            document.booking = booking
            document.status = DocumentUpload.Status.BOOKED
            document.save()
            
            # Create recurring booking if requested
            if create_recurring and document.suggested_is_recurring:
                # Create recurring booking
                recurring = RecurringBooking.objects.create(
                    account=account,
                    amount=Decimal(amount),
                    description=description,
                    category=category,
                    payee=payee,
                    start_date=booking_date,
                    frequency='MONTHLY',
                    interval=1,
                    day_of_month=booking.booking_date.day,
                    is_active=True,
                    source='AI',
                    is_confirmed=False
                )
                messages.success(request, f'Buchung und wiederkehrende Buchung erstellt!')
            else:
                messages.success(request, 'Buchung erfolgreich erstellt!')
            
            return redirect('document_review_list')
            
        except Exception as e:
            messages.error(request, f'Fehler beim Erstellen der Buchung: {str(e)}')
            return redirect('document_review_detail', document_id=document_id)
    
    # Get all accounts, categories, and payees for form
    accounts = Account.objects.filter(is_active=True).order_by('name')
    categories = Category.objects.all().order_by('name')
    payees = Payee.objects.filter(is_active=True).order_by('name')
    
    context = {
        'document': document,
        'accounts': accounts,
        'categories': categories,
        'payees': payees,
    }
    
    return render(request, 'core/document_review_detail.html', context)


@login_required
def due_bookings(request):
    """
    Due bookings overview showing:
    - Overdue bookings (status=PLANNED, date < today)
    - Upcoming bookings (status=PLANNED, today <= date <= today+7)
    """
    today = date.today()
    window_end = today + timedelta(days=7)
    
    # Get overdue bookings
    overdue_bookings = Booking.objects.filter(
        status='PLANNED',
        booking_date__lt=today
    ).select_related('account', 'category', 'payee').order_by('booking_date')
    
    # Get upcoming bookings (due within 7 days)
    upcoming_bookings = Booking.objects.filter(
        status='PLANNED',
        booking_date__gte=today,
        booking_date__lte=window_end
    ).select_related('account', 'category', 'payee').order_by('booking_date')
    
    context = {
        'overdue_bookings': overdue_bookings,
        'upcoming_bookings': upcoming_bookings,
        'today': today,
    }
    
    return render(request, 'core/due_bookings.html', context)


@login_required
@require_http_methods(['POST'])
def mark_booking_as_booked(request, booking_id):
    """
    Mark a planned booking as booked via HTMX.
    Returns empty response so HTMX can remove the row via outerHTML swap.
    """
    booking = get_object_or_404(Booking, id=booking_id)
    
    if booking.status == 'PLANNED':
        booking.status = 'POSTED'
        booking.save()
        # Return empty response for HTMX to swap (removes the row)
        return HttpResponse('')
    
    # Return error status for non-planned bookings
    return HttpResponse('Booking is not planned', status=400)


@login_required
def reconcile_balance(request, account_id):
    """
    Balance reconciliation view for aligning Finoa balance with external balance.
    
    GET: Displays reconciliation form with current balance
    POST: Creates a booking to reconcile the difference
    
    The user provides:
    - New external balance
    - Date for the reconciliation booking
    - Difference type (correction, unrealized, roundup, saveback)
    - Category (pre-filled based on difference type, but changeable)
    """
    account = get_object_or_404(Account, pk=account_id, is_active=True)
    current_balance = calculate_actual_balance(account)
    
    # Define default categories for each difference type
    diff_type_defaults = {
        'correction': 'Korrektur',
        'unrealized': 'Unrealisierte Gewinne/Verluste',
        'roundup': 'RoundUp',
        'saveback': 'SaveBack',
    }
    
    # Define descriptions for each difference type
    diff_type_descriptions = {
        'correction': 'Saldenabgleich (Korrektur)',
        'unrealized': 'Saldenabgleich (Unrealisierte Gewinne/Verluste)',
        'roundup': 'Saldenabgleich (RoundUp)',
        'saveback': 'Saldenabgleich (SaveBack)',
    }
    
    if request.method == 'POST':
        try:
            # Parse form data
            new_balance_str = request.POST.get('new_balance', '').strip()
            if not new_balance_str:
                messages.error(request, 'Bitte geben Sie den neuen Saldo ein.')
                return redirect('account_detail', account_id=account.id)
            
            # Parse decimal value - replace comma with dot for German locale compatibility
            # HTML5 number input sends values with dot separator, but handle both
            new_balance_str = new_balance_str.replace(',', '.')
            new_balance = Decimal(new_balance_str)
            
            booking_date_str = request.POST.get('date', '').strip()
            if booking_date_str:
                booking_date = date.fromisoformat(booking_date_str)
            else:
                booking_date = date.today()
            
            diff_type = request.POST.get('diff_type', 'correction')
            category_id = request.POST.get('category_id')
            
            # Calculate difference
            diff = new_balance - current_balance
            
            # Only create booking if there's a difference
            if diff != 0:
                # Get category
                category = None
                if category_id:
                    try:
                        category = Category.objects.get(pk=category_id)
                    except Category.DoesNotExist:
                        pass
                
                # Get description based on diff type
                description = diff_type_descriptions.get(diff_type, 'Saldenabgleich')
                
                # Create the reconciliation booking
                Booking.objects.create(
                    account=account,
                    amount=diff,
                    booking_date=booking_date,
                    status='POSTED',
                    category=category,
                    description=description,
                )
                
                messages.success(
                    request, 
                    f'Saldenabgleich erfolgreich durchgeführt. Differenz: {diff:+.2f} €'
                )
            else:
                messages.info(
                    request,
                    'Keine Differenz gefunden. Finoa-Saldo stimmt bereits mit externem Saldo überein.'
                )
            
            # Redirect back to account detail
            return redirect('account_detail', account_id=account.id)
            
        except (ValueError, TypeError) as e:
            messages.error(request, f'Ungültige Eingabe: {str(e)}')
            return redirect('account_detail', account_id=account.id)
    
    # GET request: Show form
    # Get all categories for dropdown
    categories = Category.objects.all().order_by('name')
    
    # Prepare default category IDs for each diff type
    default_category_ids = {}
    for diff_type_key, cat_name in diff_type_defaults.items():
        try:
            cat = Category.objects.get(name=cat_name)
            default_category_ids[diff_type_key] = cat.id
        except Category.DoesNotExist:
            default_category_ids[diff_type_key] = None
    
    context = {
        'account': account,
        'current_balance': current_balance,
        'categories': categories,
        'default_category_ids': default_category_ids,
        'today': date.today().isoformat(),
    }
    
    return render(request, 'core/reconcile_balance_modal.html', context)


@login_required
def time_tracking(request):
    """
    Time tracking overview showing all time entries with filtering options.
    """
    # Get filter parameters
    filter_status = request.GET.get('status', 'all')  # 'all', 'billed', 'unbilled'
    filter_payee_id = request.GET.get('payee')
    filter_year = request.GET.get('year')
    filter_month = request.GET.get('month')
    
    # Start with all time entries
    entries = TimeEntry.objects.select_related('payee').all()
    
    # Apply filters
    if filter_status == 'billed':
        entries = entries.filter(billed=True)
    elif filter_status == 'unbilled':
        entries = entries.filter(billed=False)
    
    if filter_payee_id:
        entries = entries.filter(payee_id=filter_payee_id)
    
    if filter_year and filter_month:
        try:
            year = int(filter_year)
            month = int(filter_month)
            entries = entries.filter(date__year=year, date__month=month)
        except ValueError:
            pass
    
    # Get all active payees for filter dropdown
    payees = Payee.objects.filter(is_active=True).order_by('name')
    
    # Calculate total for filtered entries using database aggregation
    from django.db.models import F, Sum, DecimalField, ExpressionWrapper
    total_amount = entries.aggregate(
        total=Sum(ExpressionWrapper(F('duration_hours') * F('hourly_rate'), output_field=DecimalField()))
    )['total'] or Decimal('0.00')
    
    context = {
        'entries': entries,
        'payees': payees,
        'filter_status': filter_status,
        'filter_payee_id': filter_payee_id,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'total_amount': total_amount,
        'today': date.today(),
    }
    
    return render(request, 'core/time_tracking.html', context)


@login_required
@require_http_methods(['POST'])
def time_entry_create(request):
    """
    Create a new time entry via HTMX.
    """
    try:
        payee_id = request.POST.get('payee')
        entry_date = request.POST.get('date')
        duration = request.POST.get('duration_hours')
        activity = request.POST.get('activity')
        hourly_rate = request.POST.get('hourly_rate')
        
        # Validate required fields
        if not all([payee_id, entry_date, duration, activity, hourly_rate]):
            messages.error(request, 'Alle Felder sind erforderlich.')
            return redirect('time_tracking')
        
        # Get payee
        payee = get_object_or_404(Payee, id=payee_id, is_active=True)
        
        # Parse and validate date
        parsed_date = date.fromisoformat(entry_date)
        
        # Create time entry
        TimeEntry.objects.create(
            payee=payee,
            date=parsed_date,
            duration_hours=Decimal(duration),
            activity=activity,
            hourly_rate=Decimal(hourly_rate),
            billed=False
        )
        
        messages.success(request, 'Zeiteintrag erfolgreich erstellt.')
        return redirect('time_tracking')
        
    except Exception as e:
        messages.error(request, f'Fehler beim Erstellen: {str(e)}')
        return redirect('time_tracking')


@login_required
@require_http_methods(['POST'])
def time_entry_update(request, entry_id):
    """
    Update an existing time entry via HTMX.
    """
    entry = get_object_or_404(TimeEntry, id=entry_id)
    
    # Don't allow editing billed entries
    if entry.billed:
        messages.error(request, 'Abgerechnete Einträge können nicht bearbeitet werden.')
        return redirect('time_tracking')
    
    try:
        payee_id = request.POST.get('payee')
        entry_date = request.POST.get('date')
        duration = request.POST.get('duration_hours')
        activity = request.POST.get('activity')
        hourly_rate = request.POST.get('hourly_rate')
        
        # Validate required fields
        if not all([payee_id, entry_date, duration, activity, hourly_rate]):
            messages.error(request, 'Alle Felder sind erforderlich.')
            return redirect('time_tracking')
        
        # Get payee
        payee = get_object_or_404(Payee, id=payee_id, is_active=True)
        
        # Parse and validate date
        parsed_date = date.fromisoformat(entry_date)
        
        # Update time entry
        entry.payee = payee
        entry.date = parsed_date
        entry.duration_hours = Decimal(duration)
        entry.activity = activity
        entry.hourly_rate = Decimal(hourly_rate)
        entry.save()
        
        messages.success(request, 'Zeiteintrag erfolgreich aktualisiert.')
        return redirect('time_tracking')
        
    except Exception as e:
        messages.error(request, f'Fehler beim Aktualisieren: {str(e)}')
        return redirect('time_tracking')


@login_required
@require_http_methods(['POST'])
def time_entry_delete(request, entry_id):
    """
    Delete a time entry via HTMX.
    """
    entry = get_object_or_404(TimeEntry, id=entry_id)
    
    # Don't allow deleting billed entries
    if entry.billed:
        messages.error(request, 'Abgerechnete Einträge können nicht gelöscht werden.')
        return redirect('time_tracking')
    
    entry.delete()
    messages.success(request, 'Zeiteintrag erfolgreich gelöscht.')
    return redirect('time_tracking')


@login_required
def time_entry_bulk_billing(request):
    """
    Bulk billing view for creating a collective booking from selected time entries.
    
    GET: Show billing form with selected entries
    POST: Create booking and mark entries as billed
    """
    if request.method == 'POST':
        from django.db import transaction
        
        try:
            # Get selected entry IDs
            selected_ids = request.POST.getlist('selected_entries')
            if not selected_ids:
                messages.error(request, 'Keine Einträge ausgewählt.')
                return redirect('time_tracking')
            
            # Get entries
            entries = TimeEntry.objects.filter(id__in=selected_ids, billed=False).select_related('payee')
            
            if not entries.exists():
                messages.error(request, 'Keine gültigen Einträge gefunden.')
                return redirect('time_tracking')
            
            # Validate: all entries must have same payee
            payee_ids = entries.values_list('payee_id', flat=True).distinct()
            if payee_ids.count() != 1:
                messages.error(request, 'Sammelabrechnung ist nur für Einträge mit demselben Kunden (Payee) möglich.')
                return redirect('time_tracking')
            
            payee = entries.first().payee
            
            # Get form data
            account_id = request.POST.get('account')
            category_id = request.POST.get('category')
            billing_date_str = request.POST.get('billing_date')
            
            # Validate required fields
            if not account_id or not category_id or not billing_date_str:
                messages.error(request, 'Konto, Kategorie und Datum sind Pflichtfelder.')
                # Return to form with data
                return _show_billing_form(request, selected_ids)
            
            # Get account and category
            account = get_object_or_404(Account, id=account_id, is_active=True)
            category = get_object_or_404(Category, id=category_id)
            billing_date = date.fromisoformat(billing_date_str)
            
            # Calculate totals and dates in a single iteration
            total_amount = Decimal('0.00')
            dates = []
            for entry in entries:
                total_amount += entry.amount
                dates.append(entry.date)
            start_date = min(dates)
            end_date = max(dates)
            
            # Generate description
            if start_date == end_date:
                description = f"Stundenabrechnung vom {start_date.strftime('%d.%m.%Y')} bei {payee.name}"
            else:
                description = f"Stundenabrechnung vom {start_date.strftime('%d.%m.%Y')} bis {end_date.strftime('%d.%m.%Y')} bei {payee.name}"
            
            # Create booking and mark entries as billed in a transaction
            with transaction.atomic():
                booking = Booking.objects.create(
                    account=account,
                    amount=total_amount,
                    booking_date=billing_date,
                    status='POSTED',
                    category=category,
                    payee=payee,
                    description=description
                )
                
                # Mark all entries as billed
                entries.update(billed=True)
            
            messages.success(
                request,
                f'Sammelabrechnung erfolgreich erstellt. {entries.count()} Einträge abgerechnet. Summe: {total_amount:.2f} €'
            )
            return redirect('time_tracking')
            
        except Exception as e:
            messages.error(request, f'Fehler beim Erstellen der Sammelabrechnung: {str(e)}')
            return redirect('time_tracking')
    
    # GET request: Show form
    selected_ids = request.GET.getlist('entries')
    return _show_billing_form(request, selected_ids)


def _show_billing_form(request, selected_ids):
    """
    Helper function to show the billing form.
    """
    if not selected_ids:
        messages.error(request, 'Keine Einträge ausgewählt.')
        return redirect('time_tracking')
    
    # Get entries
    entries = TimeEntry.objects.filter(id__in=selected_ids, billed=False).select_related('payee')
    
    if not entries.exists():
        messages.error(request, 'Keine gültigen Einträge gefunden.')
        return redirect('time_tracking')
    
    # Validate: all entries must have same payee
    payee_ids = entries.values_list('payee_id', flat=True).distinct()
    if payee_ids.count() != 1:
        messages.error(request, 'Sammelabrechnung ist nur für Einträge mit demselben Kunden (Payee) und Status "nicht abgerechnet" möglich.')
        return redirect('time_tracking')
    
    payee = entries.first().payee
    
    # Calculate totals and dates in a single iteration
    total_amount = Decimal('0.00')
    dates = []
    for entry in entries:
        total_amount += entry.amount
        dates.append(entry.date)
    start_date = min(dates)
    end_date = max(dates)
    
    # Generate default description
    if start_date == end_date:
        default_description = f"Stundenabrechnung vom {start_date.strftime('%d.%m.%Y')} bei {payee.name}"
    else:
        default_description = f"Stundenabrechnung vom {start_date.strftime('%d.%m.%Y')} bis {end_date.strftime('%d.%m.%Y')} bei {payee.name}"
    
    # Get accounts and categories
    accounts = Account.objects.filter(is_active=True).order_by('name')
    categories = Category.objects.all().order_by('name')
    
    context = {
        'entries': entries,
        'payee': payee,
        'total_amount': total_amount,
        'start_date': start_date,
        'end_date': end_date,
        'default_description': default_description,
        'accounts': accounts,
        'categories': categories,
        'today': date.today(),
        'selected_ids': selected_ids,
    }
    
    return render(request, 'core/time_entry_billing.html', context)
