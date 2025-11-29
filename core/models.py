from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Payee(models.Model):
    """
    Represents a payment recipient (Zahlungsempfänger) for bookings.
    Used for analysis and reporting by recipient.
    """
    name = models.CharField(max_length=200)
    note = models.TextField(blank=True, help_text='Optional description or alias')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Payee'
        verbose_name_plural = 'Payees'
    
    def __str__(self):
        return self.name


class Account(models.Model):
    """
    Represents a financial account (checking, credit card, trading, loan, etc.)
    """
    ACCOUNT_TYPES = [
        ('checking', 'Girokonto'),
        ('credit_card', 'Kreditkarte'),
        ('trading', 'Trading-Konto'),
        ('loan', 'Darlehen'),
        ('liability', 'Verbindlichkeit'),
        ('receivable', 'Forderung'),
        ('depot', 'Wertpapierdepot'),
        ('savings', 'Sparen'),
        ('insurance', 'Versicherungen'),
    ]
    
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=50, choices=ACCOUNT_TYPES)
    initial_balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00')
    )
    is_active = models.BooleanField(default=True)
    is_liquidity_relevant = models.BooleanField(
        default=True,
        help_text='Whether this account should be included in liquidity calculations (e.g., checking accounts: yes, loans/savings: no)'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Category(models.Model):
    """
    Represents a booking category for classification
    """
    CATEGORY_TYPES = [
        ('income', 'Einnahme'),
        ('expense', 'Ausgabe'),
        ('transfer', 'Umbuchung'),
    ]
    
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=50, choices=CATEGORY_TYPES, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'
    
    def __str__(self):
        return self.name


class Booking(models.Model):
    """
    Represents a financial booking (transaction)
    """
    STATUS_CHOICES = [
        ('POSTED', 'Gebucht'),
        ('PLANNED', 'Geplant'),
        ('CANCELLED', 'Storniert'),
    ]
    
    account = models.ForeignKey(
        Account, 
        on_delete=models.PROTECT, 
        related_name='bookings'
    )
    booking_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.ForeignKey(
        Category, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='bookings'
    )
    payee = models.ForeignKey(
        Payee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text='Optional payment recipient'
    )
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='POSTED')
    
    # Transfer/Umbuchung fields
    is_transfer = models.BooleanField(default=False)
    transfer_group_id = models.UUIDField(null=True, blank=True)
    transfer_partner_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_bookings'
    )
    
    # AI-Ready fields
    ai_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_suggested_bookings'
    )
    ai_category_confidence = models.FloatField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0.0)]
    )
    is_ai_category_confirmed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-booking_date', '-created_at']
    
    def __str__(self):
        return f"{self.booking_date} - {self.account.name} - {self.amount}€"


class RecurringBooking(models.Model):
    """
    Represents a recurring booking template (e.g., rent, salary, insurance)
    """
    FREQUENCY_CHOICES = [
        ('MONTHLY', 'Monatlich'),
    ]
    
    SOURCE_CHOICES = [
        ('MANUAL', 'Manuell'),
        ('AI', 'KI-Vorschlag'),
    ]
    
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='recurring_bookings'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_bookings'
    )
    payee = models.ForeignKey(
        Payee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_bookings',
        help_text='Optional payment recipient'
    )
    description = models.CharField(max_length=500, blank=True)
    
    # Recurrence settings
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='MONTHLY')
    interval = models.PositiveIntegerField(default=1)  # e.g., every 2 months
    day_of_month = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    
    is_active = models.BooleanField(default=True)
    
    # Transfer fields
    is_transfer = models.BooleanField(default=False)
    transfer_partner_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_transfer_bookings'
    )
    
    # AI fields
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='MANUAL')
    is_confirmed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_date', 'day_of_month']
    
    def __str__(self):
        return f"{self.description} - {self.amount}€ ({self.get_frequency_display()})"


class KIGateConfig(models.Model):
    """
    Configuration for KIGate AI service integration.
    Used for text-based AI functions (agents, auto-categorization, matching, forecasts, etc.)
    """
    name = models.CharField(max_length=200, help_text='Configuration name for identification')
    base_url = models.URLField(help_text='Base URL for KIGate API')
    api_key = models.CharField(max_length=500, help_text='API key for authentication')
    max_tokens = models.PositiveIntegerField(default=2000, help_text='Maximum tokens for responses')
    default_agent_name = models.CharField(max_length=200, blank=True, help_text='Default agent name to use')
    default_provider = models.CharField(max_length=100, blank=True, help_text='Default AI provider (e.g., openai, anthropic)')
    default_model = models.CharField(max_length=100, blank=True, help_text='Default model name')
    default_user_id = models.CharField(max_length=200, blank=True, help_text='Default user ID for requests')
    timeout_seconds = models.PositiveIntegerField(default=30, help_text='Request timeout in seconds')
    is_active = models.BooleanField(default=False, help_text='Whether this configuration is active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'KIGate Configuration'
        verbose_name_plural = 'KIGate Configurations'
    
    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name}"


class OpenAIConfig(models.Model):
    """
    Configuration for direct OpenAI API integration.
    Used for special use cases like vision/document recognition.
    """
    name = models.CharField(max_length=200, help_text='Configuration name for identification')
    api_key = models.CharField(max_length=500, help_text='OpenAI API key')
    base_url = models.URLField(default='https://api.openai.com/v1', help_text='OpenAI API base URL')
    default_model = models.CharField(max_length=100, default='gpt-4', help_text='Default text model')
    default_vision_model = models.CharField(max_length=100, default='gpt-4o', help_text='Default vision model')
    timeout_seconds = models.PositiveIntegerField(default=30, help_text='Request timeout in seconds')
    is_active = models.BooleanField(default=False, help_text='Whether this configuration is active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'OpenAI Configuration'
        verbose_name_plural = 'OpenAI Configurations'
    
    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name}"


class DocumentUpload(models.Model):
    """
    Represents an uploaded document (receipt/invoice) for AI-powered booking suggestion.
    """
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Hochgeladen"
        AI_PROCESSING = "AI_PROCESSING", "In Verarbeitung"
        AI_DONE = "AI_DONE", "Analyse abgeschlossen"
        REVIEW_PENDING = "REVIEW_PENDING", "Zur Prüfung"
        BOOKED = "BOOKED", "Verbucht"
        ERROR = "ERROR", "Fehler"

    file = models.FileField(upload_to="finoa_uploads/")
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.UPLOADED,
    )

    source = models.CharField(
        max_length=50,
        blank=True,
        help_text="z.B. 'web', 'mobile', 'api'.",
    )

    ai_result_openai = models.JSONField(null=True, blank=True)
    ai_result_kigate = models.JSONField(null=True, blank=True)

    extracted_text = models.TextField(blank=True)

    suggested_account = models.ForeignKey(
        "Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_suggested_account",
    )

    suggested_payee = models.ForeignKey(
        "Payee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_suggested_payee",
    )

    suggested_category = models.ForeignKey(
        "Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_suggested_category",
    )

    suggested_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    suggested_currency = models.CharField(
        max_length=8,
        blank=True,
        default="EUR",
    )

    suggested_date = models.DateField(
        null=True,
        blank=True,
        help_text="Beleg-/Buchungsdatum aus der Analyse.",
    )

    suggested_description = models.CharField(
        max_length=255,
        blank=True,
    )

    suggested_is_recurring = models.BooleanField(
        default=False,
        help_text="Wird in der KI-Antwort vorgeschlagen als wiederkehrende Zahlung.",
    )

    suggestion_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Gesamteinschätzung der KI (0–1).",
    )

    booking = models.ForeignKey(
        "Booking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_document",
    )

    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Document Upload'
        verbose_name_plural = 'Document Uploads'

    def __str__(self):
        return f"{self.original_filename} - {self.get_status_display()}"


class TimeEntry(models.Model):
    """
    Represents a billable time entry for side jobs and service work.
    Multiple entries can be billed together per payee.
    """
    payee = models.ForeignKey(
        Payee,
        on_delete=models.CASCADE,
        related_name='time_entries',
        help_text='Customer / Payment recipient'
    )
    date = models.DateField(help_text='Date of service')
    duration_hours = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        help_text='Duration in hours (e.g. 0.5, 1.0, 2.3)'
    )
    activity = models.CharField(max_length=255, help_text='Description of activity')
    hourly_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text='Hourly rate in €/hour'
    )
    billed = models.BooleanField(default=False, help_text='Whether this has been billed')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Time Entry'
        verbose_name_plural = 'Time Entries'
    
    @property
    def amount(self):
        """Calculate total amount for this time entry"""
        return self.duration_hours * self.hourly_rate
    
    def __str__(self):
        return f"{self.date} - {self.payee.name} - {self.duration_hours}h @ {self.hourly_rate}€/h"


class IgBrokerConfig(models.Model):
    """
    Configuration for IG Broker API integration.
    Used for trading operations via IG Web API.
    """
    ACCOUNT_TYPE_CHOICES = [
        ('DEMO', 'Demo'),
        ('LIVE', 'Live'),
    ]
    
    name = models.CharField(max_length=200, help_text='Configuration name for identification')
    api_key = models.CharField(max_length=500, help_text='IG API key')
    username = models.CharField(max_length=200, help_text='IG account username/identifier')
    password = models.CharField(max_length=500, help_text='IG account password')
    account_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='DEMO',
        help_text='Account type (Demo or Live)'
    )
    account_id = models.CharField(
        max_length=50,
        blank=True,
        help_text='Specific account ID (if multiple accounts)'
    )
    api_base_url = models.URLField(
        blank=True,
        help_text='Custom API base URL (optional, auto-detected based on account type)'
    )
    default_oil_epic = models.CharField(
        max_length=100,
        blank=True,
        help_text='Default EPIC for oil trading (e.g., CC.D.CL.UNC.IP for WTI Crude)'
    )
    timeout_seconds = models.PositiveIntegerField(
        default=30,
        help_text='Request timeout in seconds'
    )
    is_active = models.BooleanField(
        default=False,
        help_text='Whether this configuration is active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'IG Broker Configuration'
        verbose_name_plural = 'IG Broker Configurations'
    
    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name} ({self.get_account_type_display()})"


class MexcBrokerConfig(models.Model):
    """
    Configuration for MEXC Broker API integration.
    Used for trading operations via MEXC API (Spot & Futures).
    
    Note: MEXC only has Spot and Futures accounts. There is no separate
    Margin account - margin trading is done through the Futures API.
    """
    ACCOUNT_TYPE_CHOICES = [
        ('SPOT', 'Spot'),
        ('FUTURES', 'Futures'),
    ]
    
    name = models.CharField(
        max_length=200,
        help_text='Configuration name for identification'
    )
    api_key = models.CharField(
        max_length=500,
        help_text='MEXC API key'
    )
    api_secret = models.CharField(
        max_length=500,
        help_text='MEXC API secret'
    )
    account_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='SPOT',
        help_text='Account type (Spot or Futures)'
    )
    api_base_url = models.URLField(
        default='https://api.mexc.com',
        help_text='MEXC API base URL'
    )
    timeout_seconds = models.PositiveIntegerField(
        default=30,
        help_text='Request timeout in seconds'
    )
    is_active = models.BooleanField(
        default=False,
        help_text='Whether this configuration is active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'MEXC Broker Configuration'
        verbose_name_plural = 'MEXC Broker Configurations'
    
    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name} ({self.get_account_type_display()})"
