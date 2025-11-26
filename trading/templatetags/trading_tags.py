"""
Template tags for the trading app.
"""
from django import template

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
