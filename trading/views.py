from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from decimal import Decimal
import uuid

from .models import Signal, Trade


def get_mock_signals():
    """
    Generate mock signals for development and testing.
    Returns a list of Signal-like dictionaries.
    """
    return [
        {
            'id': str(uuid.uuid4()),
            'setup_type': 'BREAKOUT',
            'setup_type_display': 'Breakout',
            'session_phase': 'LONDON_CORE',
            'session_phase_display': 'London Core',
            'instrument': 'CL',
            'range_high': Decimal('78.50'),
            'range_low': Decimal('77.20'),
            'trigger_price': Decimal('78.55'),
            'direction': 'LONG',
            'stop_loss': Decimal('77.80'),
            'take_profit': Decimal('79.50'),
            'position_size': Decimal('2.00'),
            'ki_reasoning': 'Starker Ausbruch über Widerstandsniveau. Volume-Bestätigung vorhanden.',
            'gpt_confidence': Decimal('85.00'),
            'gpt_reasoning': 'Technische Analyse bestätigt bullisches Setup. Marktstruktur intakt. EIA-Daten neutral, keine negativen Überraschungen erwartet.',
            'gpt_corrected_sl': Decimal('77.60'),
            'gpt_corrected_tp': Decimal('79.80'),
            'gpt_corrected_size': Decimal('1.50'),
            'risk_status': 'GREEN',
            'risk_allowed_size': Decimal('3.00'),
            'risk_percentage': Decimal('1.20'),
            'risk_reasoning': 'Position Size innerhalb der Limits. Max Drawdown nicht überschritten.',
            'status': 'ACTIVE',
            'can_execute_live': True,
            'is_active': True,
            'created_at': timezone.now(),
        },
        {
            'id': str(uuid.uuid4()),
            'setup_type': 'EIA_REVERSION',
            'setup_type_display': 'EIA-Reversion',
            'session_phase': 'EIA_POST',
            'session_phase_display': 'EIA Post',
            'instrument': 'CL',
            'range_high': Decimal('79.00'),
            'range_low': Decimal('76.50'),
            'trigger_price': Decimal('76.80'),
            'direction': 'SHORT',
            'stop_loss': Decimal('77.40'),
            'take_profit': Decimal('75.50'),
            'position_size': Decimal('1.50'),
            'ki_reasoning': 'Übertriebene Reaktion auf EIA-Daten. Mean-Reversion erwartet.',
            'gpt_confidence': Decimal('72.00'),
            'gpt_reasoning': 'EIA-Daten waren leicht bearish, aber Markt hat überreagiert. Reversion zu VWAP wahrscheinlich.',
            'gpt_corrected_sl': Decimal('77.60'),
            'gpt_corrected_tp': Decimal('75.80'),
            'gpt_corrected_size': Decimal('1.00'),
            'risk_status': 'YELLOW',
            'risk_allowed_size': Decimal('2.00'),
            'risk_percentage': Decimal('2.50'),
            'risk_reasoning': 'Erhöhtes Risiko wegen Volatilität nach EIA. Position Size reduzieren empfohlen.',
            'status': 'ACTIVE',
            'can_execute_live': True,
            'is_active': True,
            'created_at': timezone.now(),
        },
        {
            'id': str(uuid.uuid4()),
            'setup_type': 'EIA_TRENDDAY',
            'setup_type_display': 'EIA-TrendDay',
            'session_phase': 'US_CORE',
            'session_phase_display': 'US Core',
            'instrument': 'CL',
            'range_high': Decimal('80.20'),
            'range_low': Decimal('78.80'),
            'trigger_price': Decimal('80.25'),
            'direction': 'LONG',
            'stop_loss': Decimal('79.50'),
            'take_profit': Decimal('82.00'),
            'position_size': Decimal('3.00'),
            'ki_reasoning': 'Klarer Trendtag nach bullischen EIA-Daten. Momentum stark.',
            'gpt_confidence': Decimal('55.00'),
            'gpt_reasoning': 'Trend ist stark, aber späte Einstiegszeit. Risiko einer Korrektur erhöht.',
            'gpt_corrected_sl': Decimal('79.80'),
            'gpt_corrected_tp': Decimal('81.50'),
            'gpt_corrected_size': Decimal('1.00'),
            'risk_status': 'RED',
            'risk_allowed_size': Decimal('0.00'),
            'risk_percentage': Decimal('4.50'),
            'risk_reasoning': 'Max Tageslimit erreicht. Nur Shadow Trade möglich.',
            'status': 'ACTIVE',
            'can_execute_live': False,
            'is_active': True,
            'created_at': timezone.now(),
        },
    ]


@login_required
def signal_dashboard(request):
    """
    Signal Dashboard - Main view showing all active trading signals.
    """
    # Try to get signals from database, fall back to mock data
    signals = list(Signal.objects.filter(status='ACTIVE'))
    
    if not signals:
        # Use mock data for development
        signals = get_mock_signals()
    
    # Count signals by status
    active_count = len([s for s in signals if (isinstance(s, dict) and s.get('status') == 'ACTIVE') or (hasattr(s, 'status') and s.status == 'ACTIVE')])
    
    context = {
        'signals': signals,
        'active_count': active_count,
    }
    
    return render(request, 'trading/signal_dashboard.html', context)


@login_required
def signal_detail(request, signal_id):
    """
    Trade Detail Panel - Detailed view of a specific signal.
    """
    # Try to get from database first
    try:
        signal = Signal.objects.get(id=signal_id)
    except (Signal.DoesNotExist, ValueError):
        # Fall back to mock data
        mock_signals = get_mock_signals()
        signal = next((s for s in mock_signals if str(s['id']) == str(signal_id)), None)
        
        if not signal:
            # If still not found, use first mock signal
            signal = mock_signals[0] if mock_signals else None
    
    if not signal:
        return redirect('signal_dashboard')
    
    context = {
        'signal': signal,
    }
    
    return render(request, 'trading/signal_detail.html', context)


@login_required
@require_http_methods(['POST'])
def execute_live_trade(request, signal_id):
    """
    Execute a live trade for a signal.
    """
    # Try database first
    try:
        signal = Signal.objects.get(id=signal_id)
        
        if not signal.can_execute_live:
            return JsonResponse({
                'success': False,
                'error': 'Live Trade nicht erlaubt basierend auf Risk Engine Status.'
            }, status=400)
        
        # Create the trade
        trade = Trade.objects.create(
            signal=signal,
            trade_type='LIVE',
            entry_price=signal.trigger_price,
            stop_loss=signal.gpt_corrected_sl or signal.stop_loss,
            take_profit=signal.gpt_corrected_tp or signal.take_profit,
            position_size=signal.gpt_corrected_size or signal.position_size,
        )
        
        # Update signal status
        signal.status = 'EXECUTED'
        signal.executed_at = timezone.now()
        signal.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Live Trade erfolgreich ausgeführt!',
            'trade_id': str(trade.id)
        })
        
    except Signal.DoesNotExist:
        # Mock response for development
        return JsonResponse({
            'success': True,
            'message': 'Live Trade erfolgreich ausgeführt! (Mock)',
            'trade_id': str(uuid.uuid4())
        })


@login_required
@require_http_methods(['POST'])
def execute_shadow_trade(request, signal_id):
    """
    Execute a shadow trade for a signal.
    """
    # Try database first
    try:
        signal = Signal.objects.get(id=signal_id)
        
        # Create the shadow trade
        trade = Trade.objects.create(
            signal=signal,
            trade_type='SHADOW',
            entry_price=signal.trigger_price,
            stop_loss=signal.gpt_corrected_sl or signal.stop_loss,
            take_profit=signal.gpt_corrected_tp or signal.take_profit,
            position_size=signal.gpt_corrected_size or signal.position_size,
        )
        
        # Update signal status
        signal.status = 'SHADOW'
        signal.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Shadow Trade erfolgreich gestartet!',
            'trade_id': str(trade.id)
        })
        
    except Signal.DoesNotExist:
        # Mock response for development
        return JsonResponse({
            'success': True,
            'message': 'Shadow Trade erfolgreich gestartet! (Mock)',
            'trade_id': str(uuid.uuid4())
        })


@login_required
@require_http_methods(['POST'])
def reject_signal(request, signal_id):
    """
    Reject/dismiss a signal.
    """
    # Try database first
    try:
        signal = Signal.objects.get(id=signal_id)
        signal.status = 'REJECTED'
        signal.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Signal verworfen.'
        })
        
    except Signal.DoesNotExist:
        # Mock response for development
        return JsonResponse({
            'success': True,
            'message': 'Signal verworfen. (Mock)'
        })


@login_required
def trade_history(request):
    """
    Trade history view - Shows executed and shadow trades.
    """
    trades = Trade.objects.select_related('signal').all()[:50]
    
    # Generate mock trades if empty
    if not trades:
        mock_trades = [
            {
                'id': str(uuid.uuid4()),
                'trade_type': 'LIVE',
                'trade_type_display': 'Live Trade',
                'status': 'CLOSED',
                'status_display': 'Geschlossen',
                'signal': {
                    'setup_type': 'BREAKOUT',
                    'direction': 'LONG',
                    'instrument': 'CL',
                },
                'entry_price': Decimal('77.50'),
                'exit_price': Decimal('78.20'),
                'stop_loss': Decimal('77.00'),
                'take_profit': Decimal('78.50'),
                'position_size': Decimal('2.00'),
                'realized_pnl': Decimal('1400.00'),
                'opened_at': timezone.now(),
                'closed_at': timezone.now(),
            },
            {
                'id': str(uuid.uuid4()),
                'trade_type': 'SHADOW',
                'trade_type_display': 'Shadow Trade',
                'status': 'OPEN',
                'status_display': 'Offen',
                'signal': {
                    'setup_type': 'EIA_REVERSION',
                    'direction': 'SHORT',
                    'instrument': 'CL',
                },
                'entry_price': Decimal('79.00'),
                'exit_price': None,
                'stop_loss': Decimal('79.50'),
                'take_profit': Decimal('78.00'),
                'position_size': Decimal('1.00'),
                'realized_pnl': None,
                'opened_at': timezone.now(),
                'closed_at': None,
            },
        ]
        trades = mock_trades
    
    context = {
        'trades': trades,
    }
    
    return render(request, 'trading/trade_history.html', context)


# API Endpoints for HTMX/AJAX integration

@login_required
def api_signals(request):
    """
    GET /api/signals - Return list of active signals as JSON.
    """
    signals = list(Signal.objects.filter(status='ACTIVE').values())
    
    if not signals:
        # Return mock data
        mock_signals = get_mock_signals()
        signals = [{
            'id': str(s['id']),
            'setup_type': s['setup_type'],
            'session_phase': s['session_phase'],
            'direction': s['direction'],
            'trigger_price': str(s['trigger_price']),
            'gpt_confidence': str(s['gpt_confidence']),
            'risk_status': s['risk_status'],
            'status': s['status'],
        } for s in mock_signals]
    
    return JsonResponse({'signals': signals})


@login_required
def api_signal_detail(request, signal_id):
    """
    GET /api/trade/{id} - Return signal details as JSON.
    """
    try:
        signal = Signal.objects.get(id=signal_id)
        data = {
            'id': str(signal.id),
            'setup_type': signal.setup_type,
            'session_phase': signal.session_phase,
            'direction': signal.direction,
            'trigger_price': str(signal.trigger_price),
            'range_high': str(signal.range_high),
            'range_low': str(signal.range_low),
            'stop_loss': str(signal.stop_loss),
            'take_profit': str(signal.take_profit),
            'position_size': str(signal.position_size),
            'ki_reasoning': signal.ki_reasoning,
            'gpt_confidence': str(signal.gpt_confidence),
            'gpt_reasoning': signal.gpt_reasoning,
            'risk_status': signal.risk_status,
            'risk_reasoning': signal.risk_reasoning,
            'status': signal.status,
            'can_execute_live': signal.can_execute_live,
        }
    except Signal.DoesNotExist:
        # Return first mock signal
        mock_signals = get_mock_signals()
        s = mock_signals[0]
        data = {
            'id': str(s['id']),
            'setup_type': s['setup_type'],
            'session_phase': s['session_phase'],
            'direction': s['direction'],
            'trigger_price': str(s['trigger_price']),
            'range_high': str(s['range_high']),
            'range_low': str(s['range_low']),
            'stop_loss': str(s['stop_loss']),
            'take_profit': str(s['take_profit']),
            'position_size': str(s['position_size']),
            'ki_reasoning': s['ki_reasoning'],
            'gpt_confidence': str(s['gpt_confidence']),
            'gpt_reasoning': s['gpt_reasoning'],
            'risk_status': s['risk_status'],
            'risk_reasoning': s['risk_reasoning'],
            'status': s['status'],
            'can_execute_live': s['can_execute_live'],
        }
    
    return JsonResponse(data)
