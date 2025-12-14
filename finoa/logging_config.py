"""
Central Logging Configuration for Fiona.

Provides unified logging setup for both the Django web application
and the background worker. Supports:
- Sentry integration for error tracking (ERROR level only)
- Local logfiles with daily rotation and 7-day retention
- Console logging for development
- Environment-based configuration
"""
import json
import logging
import os
from pathlib import Path

# Check if Sentry SDK is available
try:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


def get_log_level() -> str:
    """
    Get the log level from environment variable.
    
    Returns:
        str: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
             Defaults to INFO if not set or invalid.
    """
    level = os.environ.get('FIONA_LOG_LEVEL', 'INFO').upper()
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if level not in valid_levels:
        level = 'DEBUG'
    return level


def get_log_dir() -> Path:
    """
    Get the logs directory path and ensure it exists.
    
    Returns:
        Path: Path to the logs directory.
    """
    # Use FIONA_LOG_DIR if set, otherwise default to ./logs relative to BASE_DIR
    log_dir_env = os.environ.get('FIONA_LOG_DIR')
    if log_dir_env:
        log_dir = Path(log_dir_env)
    else:
        # Default to project root / logs
        base_dir = Path(__file__).resolve().parent.parent
        log_dir = base_dir / 'logs'
    
    # Create directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_sentry() -> None:
    """
    Initialize Sentry SDK if configured.
    
    Sentry is only initialized if:
    - SENTRY_DSN environment variable is set
    - sentry-sdk package is installed
    
    Only errors (ERROR level and above) are sent to Sentry.
    """
    if not SENTRY_AVAILABLE:
        logging.getLogger(__name__).debug(
            "Sentry SDK not installed, skipping Sentry initialization"
        )
        return
    
    sentry_dsn = os.environ.get('SENTRY_DSN', '')
    if not sentry_dsn:
        logging.getLogger(__name__).debug(
            "SENTRY_DSN not set, skipping Sentry initialization"
        )
        return
    
    # Environment name for Sentry
    environment = os.environ.get('FIONA_ENVIRONMENT', 'development')
    
    # Configure Sentry logging integration to only capture ERROR and above
    sentry_logging = LoggingIntegration(
        level=logging.ERROR,  # Only capture ERROR and above
        event_level=logging.ERROR,  # Send events for ERROR and above
    )
    
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            DjangoIntegration(),
            sentry_logging,
        ],
        environment=environment,
        # Capture 100% of errors
        traces_sample_rate=0.0,  # Disable performance tracing by default
        # Set to 1.0 to enable performance tracing
        send_default_pii=False,  # Don't send personally identifiable information
    )
    
    logging.getLogger(__name__).info(
        f"Sentry initialized for environment: {environment}"
    )


def get_log_format() -> str:
    """
    Get the log format string.
    
    Returns:
        str: Log format string with timestamp, level, logger name, and message.
    """
    return '%(asctime)s [%(levelname)s] %(name)s: %(message)s'


def get_date_format() -> str:
    """
    Get the date format string for log timestamps.
    
    Returns:
        str: Date format string.
    """
    return '%Y-%m-%d %H:%M:%S'


class StructuredDataFilter(logging.Filter):
    """Ensure a structured data attribute exists on log records.
    
    This generic filter ensures the specified attribute exists on log records
    and formats it appropriately. Any mapping or list is serialized to JSON for
    readability; other types are converted to strings. Empty values render as an
    empty string so the formatter doesn't produce extra spaces.
    
    Args:
        attribute_name: The name of the attribute to ensure exists (e.g., 'strategy_data', 'risk_data').
    """

    def __init__(self, attribute_name: str):
        """Initialize the filter with the attribute name to handle."""
        super().__init__()
        self.attribute_name = attribute_name

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if not hasattr(record, self.attribute_name) or getattr(record, self.attribute_name) is None:
            setattr(record, self.attribute_name, "")
            return True

        value = getattr(record, self.attribute_name)
        
        # Format the value appropriately
        if isinstance(value, (dict, list)):
            try:
                formatted = json.dumps(value, default=str)
            except (TypeError, ValueError):  # Catch JSON serialization errors
                # Fallback to string representation if JSON serialization fails
                formatted = str(value)
        else:
            formatted = str(value)
        
        # Prepend space for better readability when data is present
        setattr(record, self.attribute_name, " " + formatted if formatted else "")
        
        return True


class StrategyDataFilter(StructuredDataFilter):
    """Ensure ``strategy_data`` exists on log records.

    The verbose formatter includes ``%(strategy_data)s`` so we need to guarantee
    the attribute is present to avoid ``KeyError`` when log calls don't supply
    extra strategy data.
    """

    def __init__(self):
        """Initialize the filter for strategy_data."""
        super().__init__('strategy_data')


class RiskDataFilter(StructuredDataFilter):
    """Ensure ``risk_data`` exists on log records.

    The verbose formatter includes ``%(risk_data)s`` so we need to guarantee
    the attribute is present to avoid ``KeyError`` when log calls don't supply
    extra risk data.
    """

    def __init__(self):
        """Initialize the filter for risk_data."""
        super().__init__('risk_data')


def configure_logging() -> dict:
    """
    Configure logging for the application.
    
    This function sets up:
    - Console handler for stdout output
    - File handler with daily rotation (rotates at midnight)
    - 7-day retention (older log files are automatically deleted)
    
    Log files are named 'fiona.log' with rotated files having date suffixes
    like 'fiona.log.2025-11-26'.
    
    Returns:
        dict: Django LOGGING configuration dictionary.
    """
    log_level = get_log_level()
    log_dir = get_log_dir()
    log_format = get_log_format()
    date_format = get_date_format()
    
    # Determine if we're in debug mode
    debug_mode = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
    
    # Console log level - more verbose in debug mode
    console_level = 'DEBUG' if debug_mode else 'INFO'
    
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'filters': {
            'strategy_data': {
                '()': 'finoa.logging_config.StrategyDataFilter',
            },
            'risk_data': {
                '()': 'finoa.logging_config.RiskDataFilter',
            },
        },
        'formatters': {
            'standard': {
                'format': log_format,
                'datefmt': date_format,
            },
            'verbose': {
                'format': '%(asctime)s [%(levelname)s] %(name)s (%(process)d:%(thread)d): %(message)s%(strategy_data)s%(risk_data)s',
                'datefmt': date_format,
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'level': console_level,
            },
            'file': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'fiona.log'),
                'when': 'midnight',
                'interval': 1,
                'backupCount': 7,
                'encoding': 'utf-8',
                'formatter': 'verbose',
                'level': log_level,
                'filters': ['strategy_data', 'risk_data'],
            },
        },
        'loggers': {
            '': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': True,
            },
            'django': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
            'django.request': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
            'django.db.backends': {
                'handlers': ['console', 'file'],
                'level': 'WARNING',  # Reduce SQL query noise
                'propagate': False,
            },
            'core': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            # Strategy Engine logging
            'core.services.strategy': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'core.services.strategy.strategy_engine': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            # Risk Engine logging
            'core.services.risk': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'core.services.risk.risk_engine': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            # Execution Layer logging
            'core.services.execution': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'core.services.execution.execution_service': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'trading': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
            'fiona': {
                'handlers': ['console', 'file'],
                'level': log_level,
                'propagate': False,
            },
        },
    }
    
    return logging_config


def setup_logging() -> None:
    """
    Set up the complete logging configuration.
    
    This function:
    1. Creates the logs directory if needed
    2. Configures Python logging with the appropriate handlers
    3. Initializes Sentry if configured
    
    Call this function at application startup (before Django loads).
    """
    import logging.config
    
    # Ensure log directory exists
    log_dir = get_log_dir()
    
    # Configure logging
    config = configure_logging()
    logging.config.dictConfig(config)
    
    # Initialize Sentry
    setup_sentry()
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured. Level: {get_log_level()}, Directory: {log_dir}")
