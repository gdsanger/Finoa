"""
Template tags for the trading app.
"""
from django import template
from django.utils import timezone
from datetime import timedelta

register = template.Library()


@register.simple_tag
def get_phase_configs(asset):
    """
    Get all session phase configurations for an asset.
    
    Usage:
        {% load trading_tags %}
        {% get_phase_configs asset as phase_configs %}
        {% for pc in phase_configs %}
            {{ pc.get_phase_display }}
        {% endfor %}
    """
    from trading.models import AssetSessionPhaseConfig
    return AssetSessionPhaseConfig.get_phases_for_asset(asset)


@register.simple_tag
def get_enabled_phase_configs(asset):
    """
    Get only enabled session phase configurations for an asset.
    
    Usage:
        {% load trading_tags %}
        {% get_enabled_phase_configs asset as phase_configs %}
    """
    from trading.models import AssetSessionPhaseConfig
    return AssetSessionPhaseConfig.get_enabled_phases_for_asset(asset)


@register.filter
def timesince_short(value):
    """
    Return a human-readable short time difference.
    
    Examples:
        - "vor 2 Min."
        - "vor 1 Std."
        - "vor 3 Tagen"
    
    Usage:
        {{ signal.created_at|timesince_short }}
    """
    if not value:
        return ''
    
    now = timezone.now()
    if value > now:
        return 'in der Zukunft'
    
    diff = now - value
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return f'vor {int(seconds)} Sek.'
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f'vor {minutes} Min.'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'vor {hours} Std.'
    else:
        days = int(seconds / 86400)
        return f'vor {days} Tag{"en" if days != 1 else ""}'
