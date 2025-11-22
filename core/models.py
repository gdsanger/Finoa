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
