"""
API views (endpoints) for the Fiona Backend API Layer.

Provides HTTP/JSON endpoints for:
- GET /api/signals - List active signals
- GET /api/signals/{id} - Signal details
- POST /api/trade/live - Execute live trade
- POST /api/trade/shadow - Execute shadow trade
- POST /api/trade/reject - Reject signal
- GET /api/trades - Trade history
"""
import json
from functools import wraps
from typing import Callable, Any

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .services import SignalService, TradeService
from .dtos import TradeRequestDTO


# ============================================================================
# Service Instances
# ============================================================================

# Global service instances (can be replaced with dependency injection)
_signal_service: SignalService | None = None
_trade_service: TradeService | None = None


def get_signal_service() -> SignalService:
    """Get the global SignalService instance."""
    global _signal_service
    if _signal_service is None:
        _signal_service = SignalService()
    return _signal_service


def get_trade_service() -> TradeService:
    """Get the global TradeService instance."""
    global _trade_service
    if _trade_service is None:
        _trade_service = TradeService()
    return _trade_service


def set_signal_service(service: SignalService) -> None:
    """Set the global SignalService instance (for testing)."""
    global _signal_service
    _signal_service = service


def set_trade_service(service: TradeService) -> None:
    """Set the global TradeService instance (for testing)."""
    global _trade_service
    _trade_service = service


# ============================================================================
# Helper Functions
# ============================================================================

def json_response(data: dict, status: int = 200) -> JsonResponse:
    """Create a JSON response with proper content type."""
    return JsonResponse(data, status=status)


def error_response(message: str, status: int = 400) -> JsonResponse:
    """Create an error JSON response."""
    return JsonResponse({'error': message}, status=status)


def parse_json_body(request: HttpRequest) -> dict:
    """Parse JSON body from request."""
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ============================================================================
# Signal Endpoints
# ============================================================================

@csrf_exempt
@require_http_methods(['GET'])
def api_list_signals(request: HttpRequest) -> JsonResponse:
    """
    GET /api/signals
    
    List all active signals with KI and risk info.
    
    Query Parameters:
        include_dropped (bool): Include dropped signals (default: false)
        include_exited (bool): Include exited signals (default: false)
    
    Response:
        {
            "signals": [
                {
                    "id": "signal-uuid",
                    "epic": "OIL",
                    "setupKind": "BREAKOUT",
                    "phase": "LONDON_CORE",
                    "createdAt": "2025-05-01T12:34:56Z",
                    "direction": "LONG",
                    "referencePrice": 84.12,
                    "ki": {
                        "finalDirection": "LONG",
                        "finalSl": 83.70,
                        "finalTp": 85.40,
                        "finalSize": 1.0,
                        "confidence": 86.5
                    },
                    "risk": {
                        "allowed": true,
                        "reason": "Risk < 1% equity"
                    }
                }
            ]
        }
    """
    signal_service = get_signal_service()
    
    # Parse query parameters
    include_dropped = request.GET.get('include_dropped', 'false').lower() == 'true'
    include_exited = request.GET.get('include_exited', 'false').lower() == 'true'
    
    try:
        signals = signal_service.list_signals(
            include_dropped=include_dropped,
            include_exited=include_exited,
        )
        
        return json_response({
            'signals': [s.to_dict() for s in signals]
        })
    except Exception as e:
        return error_response(f"Failed to list signals: {str(e)}", status=500)


@csrf_exempt
@require_http_methods(['GET'])
def api_get_signal(request: HttpRequest, signal_id: str) -> JsonResponse:
    """
    GET /api/signals/{id}
    
    Get full details for a specific signal.
    
    Path Parameters:
        signal_id: UUID of the signal
    
    Response:
        {
            "id": "signal-uuid",
            "epic": "OIL",
            "setupKind": "BREAKOUT",
            "phase": "LONDON_CORE",
            "createdAt": "2025-05-01T12:34:56Z",
            "setup": { /* SetupCandidate data */ },
            "kiEvaluation": { /* KiEvaluationResult data */ },
            "riskEvaluation": {
                "allowed": true,
                "reason": "Risk < 1%",
                "adjustedOrder": { /* optional */ }
            },
            "executionState": {
                "status": "WAITING_FOR_USER",
                "executionSessionId": "session-uuid"
            }
        }
    """
    signal_service = get_signal_service()
    
    try:
        detail = signal_service.get_signal_detail(signal_id)
        
        if detail is None:
            return error_response("Signal not found", status=404)
        
        return json_response(detail.to_dict())
    except Exception as e:
        return error_response(f"Failed to get signal: {str(e)}", status=500)


# ============================================================================
# Trade Action Endpoints
# ============================================================================

@csrf_exempt
@require_http_methods(['POST'])
def api_execute_live_trade(request: HttpRequest) -> JsonResponse:
    """
    POST /api/trade/live
    
    Execute a live trade for a signal.
    
    Request Body:
        {
            "signalId": "signal-uuid"
        }
    
    Response (success):
        {
            "success": true,
            "tradeId": "trade-uuid",
            "message": "Live trade opened successfully."
        }
    
    Response (error):
        {
            "success": false,
            "error": "Trade not allowed by Risk Engine."
        }
    """
    trade_service = get_trade_service()
    
    try:
        body = parse_json_body(request)
        trade_request = TradeRequestDTO.from_dict(body)
        
        if not trade_request.signalId:
            return error_response("signalId is required", status=400)
        
        result = trade_service.execute_live_trade(trade_request.signalId)
        
        status_code = 200 if result.success else 400
        return json_response(result.to_dict(), status=status_code)
    except Exception as e:
        return error_response(f"Failed to execute trade: {str(e)}", status=500)


@csrf_exempt
@require_http_methods(['POST'])
def api_execute_shadow_trade(request: HttpRequest) -> JsonResponse:
    """
    POST /api/trade/shadow
    
    Execute a shadow trade for a signal.
    
    Request Body:
        {
            "signalId": "signal-uuid"
        }
    
    Response (success):
        {
            "success": true,
            "shadowTradeId": "shadow-uuid"
        }
    
    Response (error):
        {
            "success": false,
            "error": "..."
        }
    """
    trade_service = get_trade_service()
    
    try:
        body = parse_json_body(request)
        trade_request = TradeRequestDTO.from_dict(body)
        
        if not trade_request.signalId:
            return error_response("signalId is required", status=400)
        
        result = trade_service.execute_shadow_trade(trade_request.signalId)
        
        status_code = 200 if result.success else 400
        return json_response(result.to_dict(), status=status_code)
    except Exception as e:
        return error_response(f"Failed to execute shadow trade: {str(e)}", status=500)


@csrf_exempt
@require_http_methods(['POST'])
def api_reject_signal(request: HttpRequest) -> JsonResponse:
    """
    POST /api/trade/reject
    
    Reject/dismiss a signal.
    
    Request Body:
        {
            "signalId": "signal-uuid",
            "reason": "User rejected signal."  // optional
        }
    
    Response:
        {
            "success": true
        }
    """
    trade_service = get_trade_service()
    
    try:
        body = parse_json_body(request)
        trade_request = TradeRequestDTO.from_dict(body)
        
        if not trade_request.signalId:
            return error_response("signalId is required", status=400)
        
        result = trade_service.reject_signal(
            trade_request.signalId,
            reason=trade_request.reason,
        )
        
        status_code = 200 if result.success else 400
        return json_response(result.to_dict(), status=status_code)
    except Exception as e:
        return error_response(f"Failed to reject signal: {str(e)}", status=500)


# ============================================================================
# Trade History Endpoints
# ============================================================================

@csrf_exempt
@require_http_methods(['GET'])
def api_list_trades(request: HttpRequest) -> JsonResponse:
    """
    GET /api/trades
    
    Get trade history (live + shadow trades).
    
    Query Parameters:
        type (str): Filter by type ('live', 'shadow', 'all'). Default: 'all'
        limit (int): Maximum number of results. Default: 50
    
    Response:
        [
            {
                "id": "trade-uuid",
                "epic": "OIL",
                "direction": "LONG",
                "size": 1.0,
                "entryPrice": 84.10,
                "exitPrice": 84.90,
                "openedAt": "2025-05-01T12:35:12Z",
                "closedAt": "2025-05-01T13:05:44Z",
                "realizedPnl": 80.0,
                "isShadow": false,
                "exitReason": "TP_HIT"
            }
        ]
    """
    trade_service = get_trade_service()
    
    try:
        # Parse query parameters
        trade_type = request.GET.get('type', 'all')
        if trade_type not in ('live', 'shadow', 'all'):
            trade_type = 'all'
        
        try:
            limit = int(request.GET.get('limit', '50'))
            limit = max(1, min(limit, 100))  # Clamp between 1 and 100
        except ValueError:
            limit = 50
        
        trades = trade_service.get_trade_history(
            trade_type=trade_type,  # type: ignore
            limit=limit,
        )
        
        return JsonResponse([t.to_dict() for t in trades], safe=False)
    except Exception as e:
        return error_response(f"Failed to list trades: {str(e)}", status=500)
