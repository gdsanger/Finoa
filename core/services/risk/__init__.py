"""
Risk Engine module for Fiona trading system.

The Risk Engine v1.0 evaluates trades and determines whether they are
allowed based on configurable risk limits. It does not decide which trades
to enter - only whether a proposed trade meets risk requirements.
"""
from .models import RiskConfig, RiskEvaluationResult
from .risk_engine import RiskEngine

__all__ = [
    'RiskConfig',
    'RiskEvaluationResult',
    'RiskEngine',
]
