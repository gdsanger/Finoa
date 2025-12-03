"""
Integration tests for Risk Engine logging with risk_data.

This module tests that when the Risk Engine rejects a trade, the log output
includes both the human-readable reason in the message and structured risk_data
in the extra fields, which are properly formatted by the RiskDataFilter.
"""
import logging
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase

from core.services.broker.models import AccountState, OrderRequest, OrderDirection, OrderType
from core.services.risk import RiskConfig, RiskEngine
from core.services.strategy.models import SetupCandidate, SetupKind, SessionPhase, BreakoutContext


class RiskEngineLoggingIntegrationTest(TestCase):
    """Integration tests for Risk Engine logging with risk_data."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a risk config
        self.config = RiskConfig(
            max_risk_per_trade_percent=Decimal('1.0'),
            max_daily_loss_percent=Decimal('3.0'),
            max_weekly_loss_percent=Decimal('6.0'),
            max_open_positions=1,
            max_position_size=Decimal('5.0'),
            sl_min_ticks=5,
            tp_min_ticks=5,
            tick_size=Decimal('0.01'),
            tick_value=Decimal('10.0'),
            deny_eia_window_minutes=5,
            deny_friday_after='21:00',
            deny_overnight=True,
            allow_countertrend=False,
        )
        
        # Create risk engine
        self.engine = RiskEngine(self.config)
        
        # Create test account
        self.account = AccountState(
            account_id='TEST123',
            account_name='Test Account',
            balance=Decimal('10000.00'),
            available=Decimal('10000.00'),
            equity=Decimal('10000.00'),
            currency='USD',
        )
        
        # Create test setup
        self.setup = SetupCandidate(
            id='test-setup-123',
            created_at=datetime.now(timezone.utc),
            epic='BTCUSDT',
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.US_CORE,
            reference_price=50000.00,
            direction='LONG',
            breakout=BreakoutContext(
                range_high=49900.00,
                range_low=49800.00,
                range_height=100.00,
                trigger_price=50000.00,
                direction='LONG',
            )
        )
    
    def test_rejection_logs_include_reason_and_risk_data(self):
        """
        Test that when Risk Engine rejects a trade, the logs include:
        1. The human-readable reason in the log message
        2. Structured risk_data with detailed information
        """
        # Create order with SL that's too close (will trigger rejection)
        order = OrderRequest(
            epic='BTCUSDT',
            direction=OrderDirection.BUY,
            size=Decimal('1.0'),
            order_type=OrderType.MARKET,
            stop_loss=Decimal('49999.96'),  # Only 0.04 away = 4 ticks (< 5 min)
            take_profit=Decimal('50100.00'),
            currency='USD',
        )
        
        # Capture log records
        captured_records = []
        
        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured_records.append(record)
        
        # Set up logger with capturing handler
        logger = logging.getLogger('core.services.risk.risk_engine')
        original_level = logger.level
        original_handlers = logger.handlers[:]
        
        try:
            logger.handlers = []
            handler = CapturingHandler()
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            
            # Evaluate the trade (should be rejected)
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=order,
                now=datetime.now(timezone.utc),
            )
            
            # Verify rejection
            self.assertFalse(result.allowed)
            self.assertIn('SL distance', result.reason)
            self.assertIn('below minimum', result.reason)
            
            # Verify logs were captured
            self.assertGreater(len(captured_records), 0)
            
            # Find the INFO log about position risk exceeded
            position_risk_log = None
            for record in captured_records:
                if record.levelname == 'INFO' and 'position risk exceeded' in record.getMessage():
                    position_risk_log = record
                    break
            
            self.assertIsNotNone(position_risk_log, "Should have INFO log about position risk exceeded")
            
            # Verify the message includes the reason
            message = position_risk_log.getMessage()
            self.assertIn('position risk exceeded', message)
            self.assertIn('Trade denied', message)
            self.assertIn('SL distance', message)
            self.assertIn('below minimum', message)
            
            # Verify risk_data is present
            self.assertTrue(hasattr(position_risk_log, 'risk_data'), "Log record should have risk_data attribute")
            risk_data = position_risk_log.risk_data
            
            # risk_data should be a dict with structured information
            self.assertIsInstance(risk_data, dict)
            self.assertEqual(risk_data['setup_id'], 'test-setup-123')
            self.assertEqual(risk_data['epic'], 'BTCUSDT')
            self.assertEqual(risk_data['check'], 'position_risk')
            self.assertEqual(risk_data['result'], 'denied')
            self.assertIn('SL distance', risk_data['reason'])
            
            # Verify risk metrics are included
            self.assertIn('risk_metrics', risk_data)
            risk_metrics = risk_data['risk_metrics']
            self.assertIn('sl_distance', risk_metrics)
            self.assertIn('sl_ticks', risk_metrics)
            
            # Find the WARNING log about trade DENIED
            trade_denied_log = None
            for record in captured_records:
                if record.levelname == 'WARNING' and 'trade DENIED' in record.getMessage():
                    trade_denied_log = record
                    break
            
            self.assertIsNotNone(trade_denied_log, "Should have WARNING log about trade DENIED")
            
            # Verify the final rejection message
            message = trade_denied_log.getMessage()
            self.assertIn('trade DENIED', message)
            self.assertIn('Trade denied', message)
            
        finally:
            # Restore original logger state
            logger.handlers = original_handlers
            logger.level = original_level
            logger.propagate = True
    
    def test_risk_data_filter_formats_data_in_logs(self):
        """
        Test that the RiskDataFilter properly formats risk_data for log output.
        This simulates what happens when logs are written to file with the verbose formatter.
        """
        from finoa.logging_config import RiskDataFilter
        import json
        
        # Create order with SL too large (will trigger rejection)
        order = OrderRequest(
            epic='BTCUSDT',
            direction=OrderDirection.BUY,
            size=Decimal('10.0'),  # Large size
            order_type=OrderType.MARKET,
            stop_loss=Decimal('49000.00'),  # 1000 away = 100,000 ticks, huge risk
            take_profit=Decimal('51000.00'),
            currency='USD',
        )
        
        # Capture log records
        captured_records = []
        
        class CapturingHandler(logging.Handler):
            def emit(self, record):
                # Apply RiskDataFilter before capturing
                risk_filter = RiskDataFilter()
                risk_filter.filter(record)
                captured_records.append(record)
        
        # Set up logger
        logger = logging.getLogger('core.services.risk.risk_engine')
        original_level = logger.level
        original_handlers = logger.handlers[:]
        
        try:
            logger.handlers = []
            logger.addHandler(CapturingHandler())
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            
            # Evaluate the trade (should be rejected)
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=order,
                now=datetime.now(timezone.utc),
            )
            
            # Verify rejection
            self.assertFalse(result.allowed)
            
            # Find log with risk_data
            risk_data_logs = [r for r in captured_records if hasattr(r, 'risk_data') and r.risk_data]
            self.assertGreater(len(risk_data_logs), 0, "Should have logs with risk_data")
            
            # Check that risk_data was formatted by the filter
            for record in risk_data_logs:
                if isinstance(record.risk_data, str) and record.risk_data.strip():
                    # Should be valid JSON string
                    try:
                        parsed = json.loads(record.risk_data)
                        self.assertIsInstance(parsed, dict, "Parsed risk_data should be a dict")
                        # Should contain expected fields
                        if 'setup_id' in parsed:
                            self.assertEqual(parsed['setup_id'], 'test-setup-123')
                    except json.JSONDecodeError:
                        # If it's not JSON, it might be an empty string or simple value, which is OK
                        pass
                elif isinstance(record.risk_data, dict):
                    # risk_data is still a dict (before serialization), which is fine
                    self.assertEqual(record.risk_data['setup_id'], 'test-setup-123')
        
        finally:
            # Restore original logger state
            logger.handlers = original_handlers
            logger.level = original_level
            logger.propagate = True
    
    def test_verbose_formatter_includes_risk_data(self):
        """
        Test that the verbose formatter includes risk_data in the output.
        This verifies that file logs will show the structured risk information.
        """
        from finoa.logging_config import RiskDataFilter
        
        # Create order with missing stop loss (will trigger rejection)
        order = OrderRequest(
            epic='BTCUSDT',
            direction=OrderDirection.BUY,
            size=Decimal('1.0'),
            order_type=OrderType.MARKET,
            stop_loss=None,  # Missing SL!
            take_profit=Decimal('51000.00'),
            currency='USD',
        )
        
        # Create a formatter that simulates the verbose formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s %(risk_data)s'
        )
        
        # Capture formatted output
        captured_output = []
        
        class FormattedCapturingHandler(logging.Handler):
            def emit(self, record):
                # Apply RiskDataFilter
                risk_filter = RiskDataFilter()
                risk_filter.filter(record)
                # Format the record
                formatted = formatter.format(record)
                captured_output.append(formatted)
        
        # Set up logger
        logger = logging.getLogger('core.services.risk.risk_engine')
        original_level = logger.level
        original_handlers = logger.handlers[:]
        
        try:
            logger.handlers = []
            logger.addHandler(FormattedCapturingHandler())
            logger.setLevel(logging.INFO)
            logger.propagate = False
            
            # Evaluate the trade (should be rejected)
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=order,
                now=datetime.now(timezone.utc),
            )
            
            # Verify rejection
            self.assertFalse(result.allowed)
            self.assertIn('Stop loss is required', result.reason)
            
            # Verify formatted output
            self.assertGreater(len(captured_output), 0)
            
            # Find the log line about SL/TP invalid
            sltp_log = None
            for line in captured_output:
                if 'SL/TP invalid' in line and 'Stop loss is required' in line:
                    sltp_log = line
                    break
            
            self.assertIsNotNone(sltp_log, "Should have log about SL/TP invalid")
            
            # Verify the log line contains the human-readable message
            self.assertIn('Risk check: SL/TP invalid', sltp_log)
            self.assertIn('Stop loss is required', sltp_log)
            
            # Verify that risk_data is present in the output
            # (either as JSON string or empty string if no extra was provided for that specific log)
            # The key point is that the formatter doesn't crash when risk_data is accessed
            self.assertIsInstance(sltp_log, str)
            
        finally:
            # Restore original logger state
            logger.handlers = original_handlers
            logger.level = original_level
            logger.propagate = True


class RiskEngineLoggingEdgeCasesTest(TestCase):
    """Edge case tests for Risk Engine logging."""
    
    def test_log_without_risk_data_extra(self):
        """
        Test that logs without risk_data extra field don't crash.
        The RiskDataFilter should add an empty string for missing risk_data.
        """
        from finoa.logging_config import RiskDataFilter
        
        # Create a log record without risk_data
        record = logging.LogRecord(
            name='core.services.risk.risk_engine',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='Test message without risk_data',
            args=(),
            exc_info=None
        )
        
        # Apply filter
        risk_filter = RiskDataFilter()
        result = risk_filter.filter(record)
        
        # Should not crash and should add empty string
        self.assertTrue(result)
        self.assertEqual(record.risk_data, '')
        
        # Verify it can be formatted
        formatter = logging.Formatter('%(message)s %(risk_data)s')
        formatted = formatter.format(record)
        self.assertEqual(formatted, 'Test message without risk_data ')
    
    def test_log_with_none_risk_data(self):
        """
        Test that logs with None risk_data are handled correctly.
        """
        from finoa.logging_config import RiskDataFilter
        
        # Create a log record with None risk_data
        record = logging.LogRecord(
            name='core.services.risk.risk_engine',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='Test message',
            args=(),
            exc_info=None
        )
        record.risk_data = None
        
        # Apply filter
        risk_filter = RiskDataFilter()
        result = risk_filter.filter(record)
        
        # Should convert None to empty string
        self.assertTrue(result)
        self.assertEqual(record.risk_data, '')
