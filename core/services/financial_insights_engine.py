"""
Financial Insights Engine - AI-based financial analysis and forecasting

Aggregates historical booking data and prepares it for AI analysis via KIGate.
Provides classification, trend analysis, and forecasting capabilities.
"""
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional
from django.db.models import Sum, Count, Q

from core.models import Booking, Category, Account


def aggregate_monthly_liquidity(months: int = 6) -> List[Dict[str, Any]]:
    """
    Aggregate monthly liquidity (end-of-month balances) for specified period.
    
    Args:
        months: Number of months to look back from today
        
    Returns:
        List of dicts with month and ist (actual balance)
    """
    from core.services import get_total_liquidity
    
    monthly_data = []
    today = date.today()
    
    for month_offset in range(months, 0, -1):  # Go backwards from oldest to newest
        target_date = today - relativedelta(months=month_offset)
        end_of_month = (target_date.replace(day=1) + relativedelta(months=1)) - relativedelta(days=1)
        
        # Only include months up to today
        if end_of_month > today:
            end_of_month = today
        
        # Get liquidity at end of month (actual posted bookings only)
        balance = get_total_liquidity(
            as_of_date=end_of_month,
            include_forecast=False,
            liquidity_relevant_only=True
        )
        
        monthly_data.append({
            'month': end_of_month.strftime('%Y-%m'),
            'ist': float(balance)
        })
    
    return monthly_data


def aggregate_category_summaries(months: int = 6) -> List[Dict[str, Any]]:
    """
    Aggregate expenses and income by category for specified period.
    
    Args:
        months: Number of months to look back from today
        
    Returns:
        List of category summaries with totals and monthly breakdowns
    """
    today = date.today()
    start_date = today - relativedelta(months=months)
    
    # Get all posted bookings in the period
    bookings = Booking.objects.filter(
        booking_date__gte=start_date,
        booking_date__lte=today,
        status='POSTED'
    ).exclude(
        is_transfer=True  # Exclude transfers
    ).select_related('category')
    
    # Aggregate by category
    category_data = defaultdict(lambda: {
        'total': Decimal('0.00'),
        'monthly': defaultdict(lambda: Decimal('0.00'))
    })
    
    for booking in bookings:
        category_name = booking.category.name if booking.category else 'Ohne Kategorie'
        month_key = booking.booking_date.strftime('%Y-%m')
        
        category_data[category_name]['total'] += booking.amount
        category_data[category_name]['monthly'][month_key] += booking.amount
    
    # Format output
    result = []
    for category_name, data in sorted(category_data.items()):
        # Build monthly list
        monthly_list = []
        for month_offset in range(months, 0, -1):
            target_date = today - relativedelta(months=month_offset)
            month_key = target_date.strftime('%Y-%m')
            amount = data['monthly'].get(month_key, Decimal('0.00'))
            monthly_list.append({
                'month': month_key,
                'amount': float(amount)
            })
        
        result.append({
            'name': category_name,
            'total': float(data['total']),
            'monthly': monthly_list
        })
    
    return result


def aggregate_booking_entries(months: int = 6, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get abstract representation of individual bookings for AI analysis.
    Limited to most significant bookings to reduce token usage.
    
    Args:
        months: Number of months to look back from today
        limit: Maximum number of bookings to return
        
    Returns:
        List of booking entries (date, amount, category, payee, description)
    """
    today = date.today()
    start_date = today - relativedelta(months=months)
    
    # Get posted bookings, exclude transfers
    bookings = Booking.objects.filter(
        booking_date__gte=start_date,
        booking_date__lte=today,
        status='POSTED'
    ).exclude(
        is_transfer=True
    ).select_related('category', 'payee').order_by('-booking_date')[:limit]
    
    entries = []
    for booking in bookings:
        entries.append({
            'date': booking.booking_date.strftime('%Y-%m-%d'),
            'amount': float(booking.amount),
            'category': booking.category.name if booking.category else 'Ohne Kategorie',
            'payee': booking.payee.name if booking.payee else None,
            'description': booking.description[:100] if booking.description else None
        })
    
    return entries


def build_analysis_dataset(months: int = 6) -> Dict[str, Any]:
    """
    Build complete dataset for AI analysis.
    
    Args:
        months: Number of months to analyze
        
    Returns:
        Complete dataset with liquidity, categories, and entries
    """
    return {
        'period_months': months,
        'monthly_liquidity': aggregate_monthly_liquidity(months),
        'categories': aggregate_category_summaries(months),
        'entries': aggregate_booking_entries(months, limit=100)
    }


def create_agent_prompt(dataset: Dict[str, Any]) -> str:
    """
    Create the prompt for the financial-insights-de agent.
    
    Args:
        dataset: The aggregated financial data
        
    Returns:
        Formatted prompt string
    """
    import json
    
    prompt = f"""Analysiere die folgenden Finanzdaten und erstelle eine strukturierte Analyse.

**Zeitraum:** {dataset['period_months']} Monate

**Daten:**
```json
{json.dumps(dataset, indent=2, ensure_ascii=False)}
```

**Aufgabe:**
1. Klassifiziere die Kategorien in:
   - "MUSS" (Fixkosten, zwingende Ausgaben wie Miete, Versicherungen)
   - "NICE_TO_HAVE" (Freizeit, Komfort, Hobby)
   - "UNSINN" (Impulskäufe, unnötige Ausgaben)

2. Erstelle eine Trendanalyse:
   - Liquiditätsentwicklung (steigend/fallend)
   - Top 3 Kategorien mit steigendem Trend
   - Top 3 Kategorien mit fallendem Trend
   - Besondere Ausreißer oder Muster

3. Erstelle vorsichtige Prognosen für 6, 12 und 24 Monate.

4. Gib konkrete Empfehlungen zur Optimierung.

**Ausgabeformat (strikt als JSON):**
```json
{{
  "classification": {{
    "MUSS": ["Kategorie1", "Kategorie2"],
    "NICE_TO_HAVE": ["Kategorie3"],
    "UNSINN": ["Kategorie4"]
  }},
  "trends": {{
    "liquidity": {{
      "direction": "increasing|stable|decreasing",
      "avg_change": 123.45,
      "comment": "Kurze Beschreibung"
    }},
    "top_growth_categories": [
      {{"name": "Kategorie", "trend": "+15%"}}
    ],
    "top_saving_categories": [
      {{"name": "Kategorie", "trend": "-10%"}}
    ],
    "anomalies": ["Beschreibung von Ausreißern"]
  }},
  "forecast": {{
    "6_months": "Prognose für 6 Monate",
    "12_months": "Prognose für 12 Monate",
    "24_months": "Prognose für 24 Monate"
  }},
  "recommendations": [
    "Konkrete Handlungsempfehlung 1",
    "Konkrete Handlungsempfehlung 2"
  ]
}}
```

Antworte NUR mit dem JSON-Objekt, ohne zusätzlichen Text."""
    
    return prompt


def parse_agent_response(response_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse and validate the agent response.
    
    Args:
        response_data: Raw response from KIGate
        
    Returns:
        Parsed analysis result or None if invalid
    """
    import json
    import re
    
    try:
        # Extract result from response
        if 'result' in response_data:
            result_text = response_data['result']
        elif 'response' in response_data:
            result_text = response_data['response']
        else:
            result_text = str(response_data)
        
        # Try to extract JSON from the response (in case there's extra text)
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            result_text = json_match.group(0)
        
        # Parse JSON
        analysis = json.loads(result_text)
        
        # Validate structure
        required_keys = ['classification', 'trends', 'forecast', 'recommendations']
        if not all(key in analysis for key in required_keys):
            return None
        
        return analysis
        
    except (json.JSONDecodeError, ValueError, KeyError):
        return None
