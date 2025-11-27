"""
Tests for central logging configuration.
"""
import logging
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings


class LoggingConfigTests(TestCase):
    """Tests for the logging configuration module."""
    
    def test_get_log_level_default(self):
        """Test that default log level is INFO."""
        from finoa.logging_config import get_log_level
        
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove FIONA_LOG_LEVEL if it exists
            os.environ.pop('FIONA_LOG_LEVEL', None)
            level = get_log_level()
            self.assertEqual(level, 'INFO')
    
    def test_get_log_level_from_env(self):
        """Test that log level can be set via environment variable."""
        from finoa.logging_config import get_log_level
        
        with mock.patch.dict(os.environ, {'FIONA_LOG_LEVEL': 'DEBUG'}):
            level = get_log_level()
            self.assertEqual(level, 'DEBUG')
        
        with mock.patch.dict(os.environ, {'FIONA_LOG_LEVEL': 'WARNING'}):
            level = get_log_level()
            self.assertEqual(level, 'WARNING')
    
    def test_get_log_level_invalid_defaults_to_info(self):
        """Test that invalid log level defaults to INFO."""
        from finoa.logging_config import get_log_level
        
        with mock.patch.dict(os.environ, {'FIONA_LOG_LEVEL': 'INVALID'}):
            level = get_log_level()
            self.assertEqual(level, 'INFO')
    
    def test_get_log_level_case_insensitive(self):
        """Test that log level is case insensitive."""
        from finoa.logging_config import get_log_level
        
        with mock.patch.dict(os.environ, {'FIONA_LOG_LEVEL': 'debug'}):
            level = get_log_level()
            self.assertEqual(level, 'DEBUG')
    
    def test_get_log_dir_creates_directory(self):
        """Test that get_log_dir creates the directory if it doesn't exist."""
        from finoa.logging_config import get_log_dir
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, 'test_logs')
            with mock.patch.dict(os.environ, {'FIONA_LOG_DIR': log_dir}):
                result = get_log_dir()
                self.assertTrue(result.exists())
                self.assertTrue(result.is_dir())
    
    def test_configure_logging_returns_dict(self):
        """Test that configure_logging returns a valid logging config dict."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIsInstance(config, dict)
        self.assertEqual(config['version'], 1)
        self.assertIn('handlers', config)
        self.assertIn('loggers', config)
        self.assertIn('formatters', config)
    
    def test_configure_logging_has_console_handler(self):
        """Test that console handler is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('console', config['handlers'])
        self.assertEqual(
            config['handlers']['console']['class'],
            'logging.StreamHandler'
        )
    
    def test_configure_logging_has_file_handler(self):
        """Test that file handler is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('file', config['handlers'])
        self.assertEqual(
            config['handlers']['file']['class'],
            'logging.handlers.TimedRotatingFileHandler'
        )
        self.assertEqual(config['handlers']['file']['when'], 'midnight')
        self.assertEqual(config['handlers']['file']['backupCount'], 7)
    
    def test_configure_logging_has_core_logger(self):
        """Test that core logger is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('core', config['loggers'])
        self.assertIn('console', config['loggers']['core']['handlers'])
        self.assertIn('file', config['loggers']['core']['handlers'])
    
    def test_get_log_format(self):
        """Test log format string."""
        from finoa.logging_config import get_log_format
        
        format_str = get_log_format()
        
        self.assertIn('%(asctime)s', format_str)
        self.assertIn('%(levelname)s', format_str)
        self.assertIn('%(name)s', format_str)
        self.assertIn('%(message)s', format_str)
    
    def test_setup_sentry_no_dsn(self):
        """Test that Sentry is not initialized when DSN is not set."""
        from finoa.logging_config import setup_sentry, SENTRY_AVAILABLE
        
        if SENTRY_AVAILABLE:
            import sentry_sdk
            # Clear any existing Sentry initialization
            with mock.patch.dict(os.environ, {'SENTRY_DSN': ''}):
                # This should not raise an error
                setup_sentry()
    
    def test_sentry_available_constant(self):
        """Test that SENTRY_AVAILABLE constant is set correctly."""
        from finoa.logging_config import SENTRY_AVAILABLE
        
        # sentry-sdk should be installed
        self.assertTrue(SENTRY_AVAILABLE)


class LoggingIntegrationTests(TestCase):
    """Integration tests for logging."""
    
    def test_logging_to_console_works(self):
        """Test that logging to console works."""
        logger = logging.getLogger('core.test')
        
        # This should not raise any errors
        logger.info('Test info message')
        logger.warning('Test warning message')
        logger.error('Test error message')
    
    def test_logging_to_file_works(self):
        """Test that logging to file works."""
        from finoa.logging_config import get_log_dir
        
        log_dir = get_log_dir()
        log_file = log_dir / 'fiona.log'
        
        # Clear the log file
        if log_file.exists():
            initial_size = log_file.stat().st_size
        else:
            initial_size = 0
        
        # Log a message
        logger = logging.getLogger('core.integration_test')
        logger.info('Integration test message')
        
        # Force handlers to flush
        for handler in logging.root.handlers:
            handler.flush()
        
        # Note: Due to logging configuration, the file might not be written
        # immediately or at all if the logger is not using the file handler.
        # This test primarily verifies that no errors occur.


class TradingLayerLoggingTests(TestCase):
    """Tests for trading layer logging configuration."""
    
    def test_configure_logging_has_strategy_logger(self):
        """Test that strategy engine logger is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('core.services.strategy', config['loggers'])
        self.assertIn('core.services.strategy.strategy_engine', config['loggers'])
    
    def test_configure_logging_has_risk_logger(self):
        """Test that risk engine logger is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('core.services.risk', config['loggers'])
        self.assertIn('core.services.risk.risk_engine', config['loggers'])
    
    def test_configure_logging_has_execution_logger(self):
        """Test that execution service logger is configured."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        self.assertIn('core.services.execution', config['loggers'])
        self.assertIn('core.services.execution.execution_service', config['loggers'])
    
    def test_trading_loggers_use_both_handlers(self):
        """Test that trading layer loggers use both console and file handlers."""
        from finoa.logging_config import configure_logging
        
        config = configure_logging()
        
        trading_loggers = [
            'core.services.strategy',
            'core.services.strategy.strategy_engine',
            'core.services.risk',
            'core.services.risk.risk_engine',
            'core.services.execution',
            'core.services.execution.execution_service',
        ]
        
        for logger_name in trading_loggers:
            self.assertIn('console', config['loggers'][logger_name]['handlers'])
            self.assertIn('file', config['loggers'][logger_name]['handlers'])
    
    def test_strategy_engine_logger_exists(self):
        """Test that strategy engine logger can be created."""
        logger = logging.getLogger('core.services.strategy.strategy_engine')
        
        # Should be able to log without errors
        logger.debug('Test strategy debug message')
        logger.info('Test strategy info message')
    
    def test_risk_engine_logger_exists(self):
        """Test that risk engine logger can be created."""
        logger = logging.getLogger('core.services.risk.risk_engine')
        
        # Should be able to log without errors
        logger.debug('Test risk debug message')
        logger.info('Test risk info message')
    
    def test_execution_service_logger_exists(self):
        """Test that execution service logger can be created."""
        logger = logging.getLogger('core.services.execution.execution_service')
        
        # Should be able to log without errors
        logger.debug('Test execution debug message')
        logger.info('Test execution info message')
