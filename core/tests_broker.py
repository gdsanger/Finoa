"""
Tests for the Broker Service module.

These tests cover the data models, abstract interface, and IG implementation
without requiring actual IG API credentials.
"""
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, MagicMock, Mock
from django.test import TestCase
from django.core.exceptions import ImproperlyConfigured

from core.models import IgBrokerConfig
from core.services.broker import (
    AccountState,
    Position,
    OrderRequest,
    OrderResult,
    SymbolPrice,
    OrderType,
    OrderDirection,
    PositionDirection,
    Direction,
    OrderStatus,
    BrokerService,
    BrokerError,
    AuthenticationError,
    IgApiClient,
    IgBrokerService,
    get_active_ig_broker_config,
    create_ig_broker_service,
    BrokerErrorData,
)


class BrokerModelsTest(TestCase):
    """Tests for broker data models."""

    def test_account_state_creation(self):
        """Test AccountState dataclass creation."""
        state = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10500.00"),
            margin_used=Decimal("2000.00"),
            margin_available=Decimal("8000.00"),
            unrealized_pnl=Decimal("500.00"),
            currency="EUR",
        )
        
        self.assertEqual(state.account_id, "TEST123")
        self.assertEqual(state.balance, Decimal("10000.00"))
        self.assertEqual(state.currency, "EUR")
        self.assertIsNotNone(state.timestamp)

    def test_account_state_decimal_conversion(self):
        """Test that AccountState converts numeric values to Decimal."""
        state = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=10000,  # int
            available="8000.00",  # string
            equity=10500.50,  # float
        )
        
        self.assertIsInstance(state.balance, Decimal)
        self.assertIsInstance(state.available, Decimal)
        self.assertIsInstance(state.equity, Decimal)

    def test_position_creation(self):
        """Test Position dataclass creation."""
        position = Position(
            position_id="POS123",
            deal_id="DEAL123",
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            open_price=Decimal("75.50"),
            current_price=Decimal("76.00"),
            unrealized_pnl=Decimal("50.00"),
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        
        self.assertEqual(position.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(position.direction, OrderDirection.BUY)
        self.assertEqual(position.unrealized_pnl, Decimal("50.00"))

    def test_position_direction_from_string(self):
        """Test that Position converts string direction to enum."""
        position = Position(
            position_id="POS123",
            deal_id="DEAL123",
            epic="TEST",
            market_name="Test",
            direction="BUY",  # string
            size=1.0,
            open_price=100,
            current_price=101,
            unrealized_pnl=10,
        )
        
        self.assertEqual(position.direction, OrderDirection.BUY)

    def test_order_request_creation(self):
        """Test OrderRequest dataclass creation."""
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        
        self.assertEqual(order.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(order.order_type, OrderType.MARKET)
        self.assertFalse(order.guaranteed_stop)

    def test_order_request_limit_order(self):
        """Test OrderRequest for limit order."""
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.SELL,
            size=Decimal("2.0"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("77.00"),
        )
        
        self.assertEqual(order.order_type, OrderType.LIMIT)
        self.assertEqual(order.limit_price, Decimal("77.00"))

    def test_order_result_success(self):
        """Test OrderResult for successful order."""
        result = OrderResult(
            success=True,
            deal_id="DEAL456",
            deal_reference="REF123",
            status=OrderStatus.OPEN,
            affected_deals=["DEAL456"],
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.status, OrderStatus.OPEN)

    def test_order_result_failure(self):
        """Test OrderResult for failed order."""
        result = OrderResult(
            success=False,
            status=OrderStatus.REJECTED,
            reason="Insufficient margin",
        )
        
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "Insufficient margin")

    def test_symbol_price_creation(self):
        """Test SymbolPrice dataclass creation."""
        price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
            high=Decimal("76.00"),
            low=Decimal("74.50"),
            change=Decimal("0.75"),
            change_percent=Decimal("1.00"),
        )
        
        self.assertEqual(price.bid, Decimal("75.45"))
        self.assertEqual(price.spread, Decimal("0.05"))
        self.assertIsNotNone(price.timestamp)

    def test_symbol_price_mid_price(self):
        """Test SymbolPrice mid_price calculation."""
        price = SymbolPrice(
            epic="TEST",
            market_name="Test",
            bid=Decimal("100.00"),
            ask=Decimal("100.10"),
            spread=Decimal("0.10"),
        )
        
        self.assertEqual(price.mid_price, Decimal("100.05"))

    def test_order_type_enum(self):
        """Test OrderType enum values."""
        self.assertEqual(OrderType.MARKET.value, "MARKET")
        self.assertEqual(OrderType.LIMIT.value, "LIMIT")
        self.assertEqual(OrderType.STOP.value, "STOP")
        self.assertEqual(OrderType.BUY_STOP.value, "BUY_STOP")
        self.assertEqual(OrderType.SELL_STOP.value, "SELL_STOP")

    def test_order_direction_enum(self):
        """Test OrderDirection enum values."""
        self.assertEqual(OrderDirection.BUY.value, "BUY")
        self.assertEqual(OrderDirection.SELL.value, "SELL")

    def test_order_status_enum(self):
        """Test OrderStatus enum values."""
        self.assertEqual(OrderStatus.OPEN.value, "OPEN")
        self.assertEqual(OrderStatus.CLOSED.value, "CLOSED")
        self.assertEqual(OrderStatus.REJECTED.value, "REJECTED")


class IgBrokerConfigModelTest(TestCase):
    """Tests for IgBrokerConfig Django model."""

    def test_ig_broker_config_creation(self):
        """Test basic IgBrokerConfig creation."""
        config = IgBrokerConfig.objects.create(
            name="Test IG Config",
            api_key="test-api-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
            is_active=True,
        )
        
        self.assertEqual(config.name, "Test IG Config")
        self.assertEqual(config.account_type, "DEMO")
        self.assertTrue(config.is_active)

    def test_ig_broker_config_str_active(self):
        """Test string representation for active config."""
        config = IgBrokerConfig.objects.create(
            name="Active Config",
            api_key="key",
            username="user",
            password="pass",
            account_type="DEMO",
            is_active=True,
        )
        
        self.assertIn("✓", str(config))
        self.assertIn("Active Config", str(config))
        self.assertIn("Demo", str(config))

    def test_ig_broker_config_str_inactive(self):
        """Test string representation for inactive config."""
        config = IgBrokerConfig.objects.create(
            name="Inactive Config",
            api_key="key",
            username="user",
            password="pass",
            is_active=False,
        )
        
        self.assertIn("✗", str(config))

    def test_ig_broker_config_live_account(self):
        """Test config with LIVE account type."""
        config = IgBrokerConfig.objects.create(
            name="Live Config",
            api_key="key",
            username="user",
            password="pass",
            account_type="LIVE",
            is_active=False,
        )
        
        self.assertEqual(config.account_type, "LIVE")
        self.assertIn("Live", str(config))

    def test_ig_broker_config_ordering(self):
        """Test that active configs appear first."""
        inactive = IgBrokerConfig.objects.create(
            name="Inactive",
            api_key="key1",
            username="user1",
            password="pass1",
            is_active=False,
        )
        active = IgBrokerConfig.objects.create(
            name="Active",
            api_key="key2",
            username="user2",
            password="pass2",
            is_active=True,
        )
        
        configs = list(IgBrokerConfig.objects.all())
        self.assertEqual(configs[0], active)
        self.assertEqual(configs[1], inactive)


class GetActiveIgBrokerConfigTest(TestCase):
    """Tests for get_active_ig_broker_config function."""

    def test_get_active_config_success(self):
        """Test retrieving active configuration."""
        IgBrokerConfig.objects.create(
            name="Test Config",
            api_key="key",
            username="user",
            password="pass",
            is_active=True,
        )
        
        config = get_active_ig_broker_config()
        self.assertEqual(config.name, "Test Config")

    def test_get_active_config_no_active(self):
        """Test error when no active configuration exists."""
        IgBrokerConfig.objects.create(
            name="Inactive Config",
            api_key="key",
            username="user",
            password="pass",
            is_active=False,
        )
        
        with self.assertRaises(ImproperlyConfigured):
            get_active_ig_broker_config()


class IgApiClientTest(TestCase):
    """Tests for IgApiClient."""

    def test_client_initialization_demo(self):
        """Test client initialization with DEMO account."""
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
        )
        
        self.assertEqual(client.base_url, IgApiClient.DEMO_BASE_URL)
        self.assertFalse(client.is_authenticated)

    def test_client_initialization_live(self):
        """Test client initialization with LIVE account."""
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
            account_type="LIVE",
        )
        
        self.assertEqual(client.base_url, IgApiClient.LIVE_BASE_URL)

    def test_client_initialization_custom_url(self):
        """Test client initialization with custom base URL."""
        custom_url = "https://custom-api.example.com"
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
            base_url=custom_url,
        )
        
        self.assertEqual(client.base_url, custom_url)

    def test_auth_headers_not_authenticated(self):
        """Test that auth headers raise error when not authenticated."""
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        with self.assertRaises(AuthenticationError):
            client._get_auth_headers()

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_login_success(self, mock_post):
        """Test successful login."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
            "timezoneOffset": 0,
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        session = client.login()
        
        self.assertEqual(session.cst, "test-cst-token")
        self.assertEqual(session.account_id, "ACC123")
        self.assertTrue(client.is_authenticated)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_login_failure(self, mock_post):
        """Test failed login."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "errorCode": "INVALID_CREDENTIALS"
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="wrong-pass",
        )
        
        with self.assertRaises(AuthenticationError):
            client.login()

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_login_success_with_oauth_tokens(self, mock_post):
        """Test successful login with OAuth tokens in response body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}  # No tokens in headers
        mock_response.json.return_value = {
            "currentAccountId": "ACC456",
            "clientId": "CLIENT456",
            "timezoneOffset": 1,
            "oauthToken": {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "token_type": "Bearer",
                "expires_in": "60",
            }
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        session = client.login()
        
        self.assertEqual(session.cst, "oauth-access-token")
        self.assertEqual(session.security_token, "oauth-refresh-token")
        self.assertEqual(session.account_id, "ACC456")
        self.assertTrue(session.is_oauth)
        self.assertTrue(client.is_authenticated)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_oauth_auth_headers_use_bearer_token(self, mock_post):
        """Test that OAuth sessions use Authorization: Bearer header."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}  # No tokens in headers = OAuth flow
        mock_response.json.return_value = {
            "currentAccountId": "ACC456",
            "clientId": "CLIENT456",
            "oauthToken": {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
            }
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        headers = client._get_auth_headers()
        
        self.assertEqual(headers["Authorization"], "Bearer oauth-access-token")
        self.assertEqual(headers["IG-ACCOUNT-ID"], "ACC456")
        self.assertNotIn("CST", headers)
        self.assertNotIn("X-SECURITY-TOKEN", headers)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_traditional_auth_headers_use_cst_token(self, mock_post):
        """Test that traditional sessions use CST and X-SECURITY-TOKEN headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        headers = client._get_auth_headers()
        
        self.assertEqual(headers["CST"], "test-cst-token")
        self.assertEqual(headers["X-SECURITY-TOKEN"], "test-security-token")
        self.assertNotIn("Authorization", headers)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_oauth_logout_does_not_make_api_call(self, mock_post):
        """Test that OAuth sessions don't make logout API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "currentAccountId": "ACC456",
            "clientId": "CLIENT456",
            "oauthToken": {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
            }
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # Reset mock to track logout calls
        with patch('core.services.broker.ig_api_client.requests.request') as mock_request:
            client.logout()
            # No request should be made for OAuth logout
            mock_request.assert_not_called()
        
        # Session should be cleared
        self.assertFalse(client.is_authenticated)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_oauth_token_refresh_success(self, mock_post):
        """Test OAuth token refresh updates session with new tokens."""
        # Initial login
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {}
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC456",
            "clientId": "CLIENT456",
            "oauthToken": {
                "access_token": "old-access-token",
                "refresh_token": "refresh-token",
            }
        }
        
        # Token refresh response
        mock_refresh_response = MagicMock()
        mock_refresh_response.status_code = 200
        mock_refresh_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
        }
        
        mock_post.side_effect = [mock_login_response, mock_refresh_response]
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # Refresh the token
        client._refresh_oauth_token()
        
        # Session should have new tokens
        self.assertEqual(client._session.cst, "new-access-token")
        self.assertEqual(client._session.security_token, "new-refresh-token")
        self.assertTrue(client._session.is_oauth)

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_login_missing_tokens(self, mock_post):
        """Test login fails when no tokens in headers or body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}  # No tokens in headers
        mock_response.json.return_value = {
            "currentAccountId": "ACC789",
            "clientId": "CLIENT789",
            # No oauthToken in body either
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        with self.assertRaises(AuthenticationError) as context:
            client.login()
        
        self.assertIn("session tokens", str(context.exception))

    @patch('core.services.broker.ig_api_client.requests.post')
    def test_login_partial_header_tokens_fails(self, mock_post):
        """Test login fails when only one token is in headers (doesn't fallback to OAuth)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "CST": "header-cst-token",  # Only CST, no X-SECURITY-TOKEN
        }
        mock_response.json.return_value = {
            "currentAccountId": "ACC999",
            "clientId": "CLIENT999",
            "oauthToken": {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
            }
        }
        mock_post.return_value = mock_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        # Should fail because headers have partial tokens (CST but not X-SECURITY-TOKEN)
        # and OAuth should not be used as a fallback in this case
        with self.assertRaises(AuthenticationError) as context:
            client.login()
        
        self.assertIn("session tokens", str(context.exception))

    @patch('core.services.broker.ig_api_client.requests.request')
    @patch('core.services.broker.ig_api_client.requests.post')
    def test_token_invalid_triggers_reauth_and_retry(self, mock_post, mock_request):
        """Test that token-invalid error triggers re-authentication and retry."""
        # First login succeeds
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
            "timezoneOffset": 0,
        }
        
        # Re-login response (after re-auth)
        mock_relogin_response = MagicMock()
        mock_relogin_response.status_code = 200
        mock_relogin_response.headers = {
            "CST": "new-cst-token",
            "X-SECURITY-TOKEN": "new-security-token",
        }
        mock_relogin_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
            "timezoneOffset": 0,
        }
        
        mock_post.side_effect = [mock_login_response, mock_relogin_response]
        
        # First request fails with token-invalid
        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.text = '{"errorCode":"error.security.client-token-invalid"}'
        mock_error_response.json.return_value = {
            "errorCode": "error.security.client-token-invalid"
        }
        
        # Retry succeeds
        mock_success_response = MagicMock()
        mock_success_response.status_code = 200
        mock_success_response.text = '{"accounts": []}'
        mock_success_response.json.return_value = {"accounts": []}
        
        mock_request.side_effect = [mock_error_response, mock_success_response]
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # This should trigger re-auth and retry
        result = client.get_accounts()
        
        self.assertEqual(result, [])
        # Verify re-auth was called (login called twice)
        self.assertEqual(mock_post.call_count, 2)
        # Verify original request and retry were called
        self.assertEqual(mock_request.call_count, 2)

    @patch('core.services.broker.ig_api_client.requests.request')
    @patch('core.services.broker.ig_api_client.requests.post')
    def test_token_invalid_oauth_triggers_reauth(self, mock_post, mock_request):
        """Test that oauth-token-invalid error triggers token refresh and retry."""
        # First login succeeds with OAuth tokens
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {}
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
            "oauthToken": {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
            }
        }
        
        # Token refresh succeeds
        mock_refresh_response = MagicMock()
        mock_refresh_response.status_code = 200
        mock_refresh_response.json.return_value = {
            "access_token": "new-oauth-access-token",
            "refresh_token": "oauth-refresh-token",
        }
        
        mock_post.side_effect = [mock_login_response, mock_refresh_response]
        
        # First request fails with oauth-token-invalid
        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.text = '{"errorCode":"error.security.oauth-token-invalid"}'
        mock_error_response.json.return_value = {
            "errorCode": "error.security.oauth-token-invalid"
        }
        
        # Retry succeeds
        mock_success_response = MagicMock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {"accounts": []}
        
        mock_request.side_effect = [mock_error_response, mock_success_response]
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # This should trigger token refresh and retry
        result = client.get_accounts()
        
        self.assertEqual(result, [])
        # First login + token refresh
        self.assertEqual(mock_post.call_count, 2)

    @patch('core.services.broker.ig_api_client.requests.request')
    @patch('core.services.broker.ig_api_client.requests.post')
    def test_token_invalid_reauth_fails_raises_error(self, mock_post, mock_request):
        """Test that when re-authentication fails, the error is raised."""
        # First login succeeds
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
        }
        
        # Re-login fails
        mock_relogin_fail = MagicMock()
        mock_relogin_fail.status_code = 401
        mock_relogin_fail.json.return_value = {
            "errorCode": "INVALID_CREDENTIALS"
        }
        
        mock_post.side_effect = [mock_login_response, mock_relogin_fail]
        
        # Request fails with token-invalid
        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.text = '{"errorCode":"error.security.client-token-invalid"}'
        mock_error_response.json.return_value = {
            "errorCode": "error.security.client-token-invalid"
        }
        
        mock_request.return_value = mock_error_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # This should fail after re-auth fails
        with self.assertRaises(AuthenticationError):
            client.get_accounts()

    @patch('core.services.broker.ig_api_client.requests.request')
    @patch('core.services.broker.ig_api_client.requests.post')
    def test_other_401_errors_not_retried(self, mock_post, mock_request):
        """Test that other 401 errors (not token-invalid) are not retried."""
        # Login succeeds
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
        }
        mock_post.return_value = mock_login_response
        
        # Request fails with different 401 error
        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.text = '{"errorCode":"error.security.forbidden"}'
        mock_error_response.json.return_value = {
            "errorCode": "error.security.forbidden"
        }
        
        mock_request.return_value = mock_error_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # This should fail without retrying (only login called once)
        with self.assertRaises(AuthenticationError):
            client.get_accounts()
        
        # Verify no re-auth attempt was made
        self.assertEqual(mock_post.call_count, 1)

    @patch('core.services.broker.ig_api_client.requests.request')
    @patch('core.services.broker.ig_api_client.requests.post')
    def test_reauth_invalid_session_raises_error(self, mock_post, mock_request):
        """Test that re-auth with invalid session tokens raises error."""
        # First login succeeds normally
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.headers = {
            "CST": "test-cst-token",
            "X-SECURITY-TOKEN": "test-security-token",
        }
        mock_login_response.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
        }
        
        # Re-login returns success but with no tokens (edge case)
        mock_relogin_empty = MagicMock()
        mock_relogin_empty.status_code = 200
        mock_relogin_empty.headers = {}  # No tokens
        mock_relogin_empty.json.return_value = {
            "currentAccountId": "ACC123",
            "clientId": "CLIENT123",
            # No oauthToken either
        }
        
        mock_post.side_effect = [mock_login_response, mock_relogin_empty]
        
        # Request fails with token-invalid
        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.text = '{"errorCode":"error.security.client-token-invalid"}'
        mock_error_response.json.return_value = {
            "errorCode": "error.security.client-token-invalid"
        }
        
        mock_request.return_value = mock_error_response
        
        client = IgApiClient(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        client.login()
        
        # This should fail with "session tokens" error from the re-auth login
        with self.assertRaises(AuthenticationError):
            client.get_accounts()


class IgBrokerServiceTest(TestCase):
    """Tests for IgBrokerService."""

    def test_service_initialization(self):
        """Test service initialization."""
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
        )
        
        self.assertFalse(service.is_connected())

    def test_service_from_config(self):
        """Test creating service from config model."""
        config = IgBrokerConfig.objects.create(
            name="Test Config",
            api_key="test-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
            timeout_seconds=45,
            is_active=True,
        )
        
        service = IgBrokerService.from_config(config)
        
        self.assertIsInstance(service, IgBrokerService)
        self.assertFalse(service.is_connected())

    def test_ensure_connected_raises_when_not_connected(self):
        """Test that operations raise error when not connected."""
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        with self.assertRaises(ConnectionError):
            service.get_account_state()

    @patch.object(IgApiClient, 'login')
    def test_connect_success(self, mock_login):
        """Test successful connection."""
        mock_session = MagicMock(
            cst="test-cst",
            security_token="test-token",
            account_id="ACC123",
        )
        mock_login.return_value = mock_session
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        service.connect()
        # The _connected flag should be set to True
        self.assertTrue(service._connected)
        mock_login.assert_called_once()

    @patch.object(IgApiClient, 'login')
    def test_connect_auth_failure(self, mock_login):
        """Test connection with authentication failure."""
        mock_login.side_effect = AuthenticationError("Invalid credentials")
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="wrong-pass",
        )
        
        with self.assertRaises(AuthenticationError):
            service.connect()
        
        self.assertFalse(service._connected)

    @patch.object(IgApiClient, 'logout')
    @patch.object(IgApiClient, 'login')
    def test_disconnect(self, mock_login, mock_logout):
        """Test disconnection."""
        mock_session = MagicMock()
        mock_login.return_value = mock_session
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        
        service.connect()
        self.assertTrue(service._connected)
        
        service.disconnect()
        self.assertFalse(service._connected)
        mock_logout.assert_called_once()

    @patch.object(IgApiClient, 'get_account_details')
    @patch.object(IgApiClient, 'login')
    def test_get_account_state(self, mock_login, mock_get_account):
        """Test getting account state."""
        mock_session = MagicMock()
        mock_login.return_value = mock_session
        mock_get_account.return_value = {
            "accountId": "ACC123",
            "accountName": "Test Account",
            "currency": "EUR",
            "balance": {
                "balance": 10000.00,
                "available": 8000.00,
                "deposit": 2000.00,
                "profitLoss": 500.00,
            }
        }
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        service.connect()
        # Manually set _session on client for is_authenticated to work
        service._client._session = mock_session
        
        state = service.get_account_state()
        
        self.assertEqual(state.account_id, "ACC123")
        self.assertEqual(state.balance, Decimal("10000"))
        self.assertEqual(state.available, Decimal("8000"))
        self.assertEqual(state.currency, "EUR")

    @patch.object(IgApiClient, 'get_positions')
    @patch.object(IgApiClient, 'login')
    def test_get_open_positions_empty(self, mock_login, mock_get_positions):
        """Test getting open positions when empty."""
        mock_session = MagicMock()
        mock_login.return_value = mock_session
        mock_get_positions.return_value = []
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        service.connect()
        service._client._session = mock_session
        
        positions = service.get_open_positions()
        
        self.assertEqual(positions, [])

    @patch.object(IgApiClient, 'get_positions')
    @patch.object(IgApiClient, 'login')
    def test_get_open_positions_with_data(self, mock_login, mock_get_positions):
        """Test getting open positions with data."""
        mock_session = MagicMock()
        mock_login.return_value = mock_session
        mock_get_positions.return_value = [
            {
                "position": {
                    "dealId": "DEAL123",
                    "direction": "BUY",
                    "size": 1.0,
                    "level": 75.50,
                    "profit": 50.00,
                    "currency": "EUR",
                },
                "market": {
                    "epic": "CC.D.CL.UNC.IP",
                    "instrumentName": "WTI Crude",
                    "bid": 76.00,
                    "offer": 76.05,
                }
            }
        ]
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        service.connect()
        service._client._session = mock_session
        
        positions = service.get_open_positions()
        
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].deal_id, "DEAL123")
        self.assertEqual(positions[0].direction, OrderDirection.BUY)
        self.assertEqual(positions[0].epic, "CC.D.CL.UNC.IP")

    @patch.object(IgApiClient, 'get_market')
    @patch.object(IgApiClient, 'login')
    def test_get_symbol_price(self, mock_login, mock_get_market):
        """Test getting symbol price."""
        mock_session = MagicMock()
        mock_login.return_value = mock_session
        mock_get_market.return_value = {
            "instrument": {
                "name": "WTI Crude Oil"
            },
            "snapshot": {
                "bid": 75.45,
                "offer": 75.50,
                "high": 76.00,
                "low": 74.50,
                "netChange": 0.75,
                "percentageChange": 1.00,
            }
        }
        
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        service.connect()
        service._client._session = mock_session
        
        price = service.get_symbol_price("CC.D.CL.UNC.IP")
        
        self.assertEqual(price.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(price.bid, Decimal("75.45"))
        self.assertEqual(price.ask, Decimal("75.50"))
        self.assertEqual(price.spread, Decimal("0.05"))

    def test_get_symbol_price_empty_epic(self):
        """Test get_symbol_price with empty epic raises error."""
        service = IgBrokerService(
            api_key="test-key",
            username="test-user",
            password="test-pass",
        )
        # Mock connection
        service._connected = True
        service._client._session = MagicMock()
        
        with self.assertRaises(ValueError):
            service.get_symbol_price("")


class BrokerErrorTest(TestCase):
    """Tests for broker exceptions."""

    def test_broker_error_creation(self):
        """Test BrokerError creation."""
        error = BrokerError("Test error", code="TEST_CODE", details={"key": "value"})
        
        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.code, "TEST_CODE")
        self.assertEqual(error.details, {"key": "value"})

    def test_authentication_error_is_broker_error(self):
        """Test that AuthenticationError is a BrokerError."""
        error = AuthenticationError("Auth failed")
        
        self.assertIsInstance(error, BrokerError)


class CreateIgBrokerServiceTest(TestCase):
    """Tests for create_ig_broker_service function."""

    def test_create_service_success(self):
        """Test creating service from active config."""
        IgBrokerConfig.objects.create(
            name="Test Config",
            api_key="test-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
            is_active=True,
        )
        
        service = create_ig_broker_service()
        
        self.assertIsInstance(service, IgBrokerService)

    def test_create_service_no_active_config(self):
        """Test error when no active config."""
        with self.assertRaises(ImproperlyConfigured):
            create_ig_broker_service()


class DirectionEnumTest(TestCase):
    """Tests for Direction and PositionDirection enums."""

    def test_direction_enum_values(self):
        """Test Direction enum has all required values."""
        self.assertEqual(Direction.BUY.value, "BUY")
        self.assertEqual(Direction.SELL.value, "SELL")
        self.assertEqual(Direction.LONG.value, "LONG")
        self.assertEqual(Direction.SHORT.value, "SHORT")

    def test_direction_is_order_direction(self):
        """Test is_order_direction method."""
        self.assertTrue(Direction.BUY.is_order_direction())
        self.assertTrue(Direction.SELL.is_order_direction())
        self.assertFalse(Direction.LONG.is_order_direction())
        self.assertFalse(Direction.SHORT.is_order_direction())

    def test_direction_is_position_direction(self):
        """Test is_position_direction method."""
        self.assertFalse(Direction.BUY.is_position_direction())
        self.assertFalse(Direction.SELL.is_position_direction())
        self.assertTrue(Direction.LONG.is_position_direction())
        self.assertTrue(Direction.SHORT.is_position_direction())

    def test_direction_to_order_direction(self):
        """Test conversion to OrderDirection."""
        self.assertEqual(Direction.BUY.to_order_direction(), OrderDirection.BUY)
        self.assertEqual(Direction.SELL.to_order_direction(), OrderDirection.SELL)
        self.assertEqual(Direction.LONG.to_order_direction(), OrderDirection.BUY)
        self.assertEqual(Direction.SHORT.to_order_direction(), OrderDirection.SELL)

    def test_direction_to_position_direction(self):
        """Test conversion to PositionDirection."""
        self.assertEqual(Direction.BUY.to_position_direction(), PositionDirection.LONG)
        self.assertEqual(Direction.SELL.to_position_direction(), PositionDirection.SHORT)
        self.assertEqual(Direction.LONG.to_position_direction(), PositionDirection.LONG)
        self.assertEqual(Direction.SHORT.to_position_direction(), PositionDirection.SHORT)

    def test_direction_is_string_subclass(self):
        """Test that Direction is a string subclass for JSON serialization."""
        self.assertIsInstance(Direction.BUY, str)
        # Direction.value gives the raw string value for serialization
        self.assertEqual(Direction.BUY.value, "BUY")

    def test_position_direction_enum_values(self):
        """Test PositionDirection enum values."""
        self.assertEqual(PositionDirection.LONG.value, "LONG")
        self.assertEqual(PositionDirection.SHORT.value, "SHORT")

    def test_position_direction_from_order_direction(self):
        """Test converting OrderDirection to PositionDirection."""
        self.assertEqual(
            PositionDirection.from_order_direction(OrderDirection.BUY),
            PositionDirection.LONG
        )
        self.assertEqual(
            PositionDirection.from_order_direction(OrderDirection.SELL),
            PositionDirection.SHORT
        )


class SerializationTest(TestCase):
    """Tests for to_dict() serialization methods."""

    def test_account_state_to_dict(self):
        """Test AccountState to_dict serialization."""
        state = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10500.00"),
            margin_used=Decimal("2000.00"),
            margin_available=Decimal("8000.00"),
            unrealized_pnl=Decimal("500.00"),
            currency="EUR",
        )
        
        data = state.to_dict()
        
        self.assertEqual(data['account_id'], "TEST123")
        self.assertEqual(data['balance'], 10000.00)
        self.assertEqual(data['available'], 8000.00)
        self.assertEqual(data['currency'], "EUR")
        self.assertIsInstance(data['balance'], float)
        self.assertIn('timestamp', data)

    def test_position_to_dict(self):
        """Test Position to_dict serialization."""
        position = Position(
            position_id="POS123",
            deal_id="DEAL123",
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            open_price=Decimal("75.50"),
            current_price=Decimal("76.00"),
            unrealized_pnl=Decimal("50.00"),
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        
        data = position.to_dict()
        
        self.assertEqual(data['position_id'], "POS123")
        self.assertEqual(data['epic'], "CC.D.CL.UNC.IP")
        self.assertEqual(data['direction'], "BUY")
        self.assertEqual(data['size'], 1.0)
        self.assertEqual(data['stop_loss'], 74.00)
        self.assertIsInstance(data['open_price'], float)

    def test_order_request_to_dict(self):
        """Test OrderRequest to_dict serialization."""
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        
        data = order.to_dict()
        
        self.assertEqual(data['epic'], "CC.D.CL.UNC.IP")
        self.assertEqual(data['direction'], "BUY")
        self.assertEqual(data['order_type'], "MARKET")
        self.assertEqual(data['size'], 1.0)
        self.assertIsNone(data['limit_price'])

    def test_order_result_to_dict(self):
        """Test OrderResult to_dict serialization."""
        result = OrderResult(
            success=True,
            deal_id="DEAL456",
            deal_reference="REF123",
            status=OrderStatus.OPEN,
            affected_deals=["DEAL456"],
        )
        
        data = result.to_dict()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['deal_id'], "DEAL456")
        self.assertEqual(data['status'], "OPEN")
        self.assertEqual(data['affected_deals'], ["DEAL456"])

    def test_symbol_price_to_dict(self):
        """Test SymbolPrice to_dict serialization."""
        price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
            high=Decimal("76.00"),
            low=Decimal("74.50"),
        )
        
        data = price.to_dict()
        
        self.assertEqual(data['epic'], "CC.D.CL.UNC.IP")
        self.assertEqual(data['bid'], 75.45)
        self.assertEqual(data['ask'], 75.50)
        self.assertEqual(data['mid_price'], 75.475)
        self.assertIn('timestamp', data)

    def test_symbol_price_to_dict_optional_fields(self):
        """Test SymbolPrice to_dict with None optional fields."""
        price = SymbolPrice(
            epic="TEST",
            market_name="Test",
            bid=Decimal("100.00"),
            ask=Decimal("100.10"),
            spread=Decimal("0.10"),
        )
        
        data = price.to_dict()
        
        self.assertIsNone(data['high'])
        self.assertIsNone(data['low'])
        self.assertIsNone(data['change'])


class BrokerErrorDataTest(TestCase):
    """Tests for BrokerErrorData dataclass."""

    def test_broker_error_data_creation(self):
        """Test BrokerErrorData dataclass creation."""
        error = BrokerErrorData(
            error_code="TEST_CODE",
            message="Test error message",
            raw={"key": "value"}
        )
        
        self.assertEqual(error.error_code, "TEST_CODE")
        self.assertEqual(error.message, "Test error message")
        self.assertEqual(error.raw, {"key": "value"})

    def test_broker_error_data_to_dict(self):
        """Test BrokerErrorData to_dict serialization."""
        error = BrokerErrorData(
            error_code="INSUFFICIENT_MARGIN",
            message="Not enough margin",
            raw={"balance": 100, "required": 200}
        )
        
        data = error.to_dict()
        
        self.assertEqual(data['error_code'], "INSUFFICIENT_MARGIN")
        self.assertEqual(data['message'], "Not enough margin")
        self.assertEqual(data['raw'], {"balance": 100, "required": 200})

    def test_broker_error_data_optional_raw(self):
        """Test BrokerErrorData with None raw field."""
        error = BrokerErrorData(
            error_code="UNKNOWN",
            message="Unknown error"
        )
        
        data = error.to_dict()
        
        self.assertIsNone(data['raw'])


class IGMarketStateProviderTest(TestCase):
    """Tests for IGMarketStateProvider functionality."""

    def setUp(self):
        """Set up test fixtures."""
        from trading.models import TradingAsset
        from decimal import Decimal
        
        # Create a test trading asset
        self.asset = TradingAsset.objects.create(
            name="Test Oil",
            symbol="CL",
            epic="CC.D.CL.UNC.IP",
            category="commodity",
            tick_size=Decimal("0.01"),
            is_active=True,
        )
        
        # Create mock broker service
        self.mock_broker = MagicMock()

    def tearDown(self):
        """Clean up test data."""
        from trading.models import TradingAsset, BreakoutRange
        BreakoutRange.objects.all().delete()
        TradingAsset.objects.all().delete()

    def test_set_current_asset(self):
        """Test setting current asset for range persistence."""
        from core.services.broker import IGMarketStateProvider
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Initially no asset set
        self.assertIsNone(provider._current_asset)
        
        # Set asset
        provider.set_current_asset(self.asset)
        self.assertEqual(provider._current_asset, self.asset)
        
        # Clear asset
        provider.clear_current_asset()
        self.assertIsNone(provider._current_asset)

    def test_set_asia_range_persists_to_database(self):
        """Test that set_asia_range persists range to database when asset is set."""
        from core.services.broker import IGMarketStateProvider
        from trading.models import BreakoutRange
        from datetime import datetime, timezone
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        now = datetime.now(timezone.utc)
        
        # Set a range
        provider.set_asia_range(
            epic="CC.D.CL.UNC.IP",
            high=75.50,
            low=74.00,
            start_time=now,
            end_time=now,
            candle_count=10,
            atr=0.50,
        )
        
        # Verify it's persisted
        range_obj = BreakoutRange.objects.filter(
            asset=self.asset,
            phase='ASIA_RANGE',
        ).first()
        
        self.assertIsNotNone(range_obj)
        self.assertEqual(float(range_obj.high), 75.50)
        self.assertEqual(float(range_obj.low), 74.00)
        self.assertEqual(range_obj.candle_count, 10)

    def test_set_asia_range_without_asset_not_persisted(self):
        """Test that set_asia_range does NOT persist when no asset is set."""
        from core.services.broker import IGMarketStateProvider
        from trading.models import BreakoutRange
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        # Explicitly do NOT set current asset
        
        # Set a range
        provider.set_asia_range(
            epic="CC.D.CL.UNC.IP",
            high=75.50,
            low=74.00,
        )
        
        # Verify cache is still updated
        cached = provider.get_asia_range("CC.D.CL.UNC.IP")
        self.assertIsNotNone(cached)
        self.assertEqual(cached, (75.50, 74.00))
        
        # Verify it's NOT persisted to database
        count = BreakoutRange.objects.count()
        self.assertEqual(count, 0)

    def test_set_london_core_range_persists_to_database(self):
        """Test that set_london_core_range persists range to database when asset is set."""
        from core.services.broker import IGMarketStateProvider
        from trading.models import BreakoutRange
        from datetime import datetime, timezone
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        now = datetime.now(timezone.utc)
        
        # Set a range
        provider.set_london_core_range(
            epic="CC.D.CL.UNC.IP",
            high=76.00,
            low=75.00,
            start_time=now,
            end_time=now,
            candle_count=15,
        )
        
        # Verify it's persisted
        range_obj = BreakoutRange.objects.filter(
            asset=self.asset,
            phase='LONDON_CORE',
        ).first()
        
        self.assertIsNotNone(range_obj)
        self.assertEqual(float(range_obj.high), 76.00)
        self.assertEqual(float(range_obj.low), 75.00)

    def test_set_pre_us_range_persists_to_database(self):
        """Test that set_pre_us_range persists range to database when asset is set."""
        from core.services.broker import IGMarketStateProvider
        from trading.models import BreakoutRange
        from datetime import datetime, timezone
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        now = datetime.now(timezone.utc)
        
        # Set a range
        provider.set_pre_us_range(
            epic="CC.D.CL.UNC.IP",
            high=77.00,
            low=76.50,
            start_time=now,
            end_time=now,
        )
        
        # Verify it's persisted
        range_obj = BreakoutRange.objects.filter(
            asset=self.asset,
            phase='PRE_US_RANGE',
        ).first()
        
        self.assertIsNotNone(range_obj)
        self.assertEqual(float(range_obj.high), 77.00)
        self.assertEqual(float(range_obj.low), 76.50)

    def test_range_not_persisted_for_mismatched_epic(self):
        """Test that range is NOT persisted when epic doesn't match asset."""
        from core.services.broker import IGMarketStateProvider
        from trading.models import BreakoutRange
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        # Set a range with wrong epic
        provider.set_asia_range(
            epic="WRONG.EPIC",  # Different from asset's epic
            high=75.50,
            low=74.00,
        )
        
        # Verify it's NOT persisted to database
        count = BreakoutRange.objects.count()
        self.assertEqual(count, 0)

    def test_candle_count_tracking(self):
        """Test that candle counts are tracked per epic."""
        from core.services.broker import IGMarketStateProvider
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Initially 0
        self.assertEqual(provider.get_candle_count_for_epic("CC.D.CL.UNC.IP"), 0)
        
        # Manually increment (normally done by get_recent_candles)
        provider._candle_counts["CC.D.CL.UNC.IP"] = 10
        
        self.assertEqual(provider.get_candle_count_for_epic("CC.D.CL.UNC.IP"), 10)

    def test_check_no_data_warning(self):
        """Test the sanity check for no data warning."""
        from core.services.broker import IGMarketStateProvider
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # With 0 candles, should trigger warning
        result = provider.check_no_data_warning("CC.D.CL.UNC.IP")
        self.assertTrue(result)
        
        # With some candles, should NOT trigger warning
        provider._candle_counts["CC.D.CL.UNC.IP"] = 10
        result = provider.check_no_data_warning("CC.D.CL.UNC.IP")
        self.assertFalse(result)

    def test_clear_session_caches_resets_counts(self):
        """Test that clear_session_caches also resets candle counts."""
        from core.services.broker import IGMarketStateProvider
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Set some counts
        provider._candle_counts["CC.D.CL.UNC.IP"] = 10
        provider._asia_range_cache["CC.D.CL.UNC.IP"] = (75.50, 74.00)
        
        # Clear caches
        provider.clear_session_caches()
        
        # Verify everything is cleared
        self.assertEqual(len(provider._candle_counts), 0)
        self.assertEqual(len(provider._asia_range_cache), 0)

    def test_broker_registry_used_for_mexc_asset(self):
        """Test that broker registry is used to get correct broker for MEXC assets."""
        from core.services.broker import IGMarketStateProvider
        from core.services.broker.config import BrokerRegistry
        from trading.models import TradingAsset
        from decimal import Decimal
        
        # Create a MEXC crypto asset
        mexc_asset = TradingAsset.objects.create(
            name="ETH/USDT",
            symbol="ETHUSDT",
            epic="ETHUSDT",
            broker="MEXC",
            broker_symbol="ETHUSDT",
            category="crypto",
            is_crypto=True,
            tick_size=Decimal("0.01"),
            is_active=True,
        )
        
        # Create mocks
        mock_ig_broker = MagicMock()
        mock_mexc_broker = MagicMock()
        mock_registry = MagicMock(spec=BrokerRegistry)
        mock_registry.get_broker_for_asset.return_value = mock_mexc_broker
        
        # Set up mock price response
        mock_price = MagicMock()
        mock_price.mid_price = Decimal("3000.50")
        mock_price.high = Decimal("3100.00")
        mock_price.low = Decimal("2950.00")
        mock_mexc_broker.get_symbol_price.return_value = mock_price
        
        # Create provider with registry
        provider = IGMarketStateProvider(
            broker_service=mock_ig_broker,
            broker_registry=mock_registry,
        )
        provider.set_current_asset(mexc_asset)
        
        # Call get_daily_high_low - should use MEXC broker, not IG
        result = provider.get_daily_high_low("ETHUSDT")
        
        # Verify registry was used to get broker for asset
        mock_registry.get_broker_for_asset.assert_called_once_with(mexc_asset)
        
        # Verify MEXC broker was called with correct symbol
        mock_mexc_broker.get_symbol_price.assert_called_once_with("ETHUSDT")
        
        # Verify IG broker was NOT called
        mock_ig_broker.get_symbol_price.assert_not_called()
        
        # Verify result
        self.assertEqual(result, (3100.00, 2950.00))
        
        # Clean up
        mexc_asset.delete()

    def test_broker_registry_used_for_get_recent_candles(self):
        """Test that broker registry is used for get_recent_candles with MEXC assets."""
        from core.services.broker import IGMarketStateProvider
        from core.services.broker.config import BrokerRegistry
        from trading.models import TradingAsset
        from decimal import Decimal
        
        # Create a MEXC crypto asset
        mexc_asset = TradingAsset.objects.create(
            name="SOL/USDT",
            symbol="SOLUSDT",
            epic="SOLUSDT",
            broker="MEXC",
            broker_symbol="SOLUSDT",
            category="crypto",
            is_crypto=True,
            tick_size=Decimal("0.1"),
            is_active=True,
        )
        
        # Create mocks
        mock_ig_broker = MagicMock()
        mock_mexc_broker = MagicMock()
        mock_registry = MagicMock(spec=BrokerRegistry)
        mock_registry.get_broker_for_asset.return_value = mock_mexc_broker
        
        # Set up mock price response
        mock_price = MagicMock()
        mock_price.mid_price = Decimal("150.50")
        mock_price.high = Decimal("155.00")
        mock_price.low = Decimal("148.00")
        mock_mexc_broker.get_symbol_price.return_value = mock_price
        
        # Create provider with registry
        provider = IGMarketStateProvider(
            broker_service=mock_ig_broker,
            broker_registry=mock_registry,
        )
        provider.set_current_asset(mexc_asset)
        
        # Call get_recent_candles - should use MEXC broker, not IG
        candles = provider.get_recent_candles("SOLUSDT", "1m", 5)
        
        # Verify registry was used to get broker for asset
        mock_registry.get_broker_for_asset.assert_called_once_with(mexc_asset)
        
        # Verify MEXC broker was called with correct symbol
        mock_mexc_broker.get_symbol_price.assert_called_once_with("SOLUSDT")
        
        # Verify IG broker was NOT called
        mock_ig_broker.get_symbol_price.assert_not_called()
        
        # Verify candles were returned
        self.assertGreater(len(candles), 0)
        self.assertEqual(candles[-1].close, 150.50)
        
        # Clean up
        mexc_asset.delete()

    def test_fallback_to_default_broker_without_registry(self):
        """Test that default broker is used when no registry is available."""
        from core.services.broker import IGMarketStateProvider
        from decimal import Decimal
        
        # Create mocks - only default broker, no registry
        mock_ig_broker = MagicMock()
        
        # Set up mock price response
        mock_price = MagicMock()
        mock_price.mid_price = Decimal("75.50")
        mock_price.high = Decimal("76.00")
        mock_price.low = Decimal("74.50")
        mock_ig_broker.get_symbol_price.return_value = mock_price
        
        # Create provider WITHOUT registry
        provider = IGMarketStateProvider(
            broker_service=mock_ig_broker,
            broker_registry=None,  # No registry
        )
        
        # Call get_daily_high_low without setting asset
        result = provider.get_daily_high_low("CC.D.CL.UNC.IP")
        
        # Verify default IG broker was called
        mock_ig_broker.get_symbol_price.assert_called_once_with("CC.D.CL.UNC.IP")
        
        # Verify result
        self.assertEqual(result, (76.00, 74.50))


class KrakenBrokerConfigTest(TestCase):
    """Tests for Kraken Broker configuration and integration."""

    def test_get_active_kraken_broker_config_success(self):
        """Test retrieving active Kraken broker configuration."""
        from core.models import KrakenBrokerConfig
        from core.services.broker.config import get_active_kraken_broker_config
        
        # Create an active Kraken config
        KrakenBrokerConfig.objects.create(
            name="Test Kraken Config",
            api_key="test-kraken-key",
            api_secret="test-kraken-secret",
            default_symbol="PF_ADAUSD",
            account_type="DEMO",
            is_active=True,
        )
        
        config = get_active_kraken_broker_config()
        self.assertEqual(config.name, "Test Kraken Config")
        self.assertEqual(config.api_key, "test-kraken-key")
        self.assertEqual(config.default_symbol, "PF_ADAUSD")

    def test_get_active_kraken_broker_config_no_active(self):
        """Test error when no active Kraken configuration exists."""
        from core.models import KrakenBrokerConfig
        from core.services.broker.config import get_active_kraken_broker_config
        
        # Create an inactive config
        KrakenBrokerConfig.objects.create(
            name="Inactive Kraken Config",
            api_key="test-key",
            api_secret="test-secret",
            is_active=False,
        )
        
        with self.assertRaises(ImproperlyConfigured) as context:
            get_active_kraken_broker_config()
        
        self.assertIn("No active Kraken Broker configuration", str(context.exception))

    @patch('core.services.broker.config.KrakenBrokerService')
    def test_create_kraken_broker_service(self, mock_kraken_service_class):
        """Test creating Kraken broker service from configuration."""
        from core.models import KrakenBrokerConfig
        from core.services.broker.config import create_kraken_broker_service
        
        # Create active config
        config = KrakenBrokerConfig.objects.create(
            name="Test Kraken",
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PF_ADAUSD",
            account_type="DEMO",
            is_active=True,
        )
        
        # Mock the from_config method
        mock_service = MagicMock()
        mock_kraken_service_class.from_config.return_value = mock_service
        
        # Create service
        service = create_kraken_broker_service()
        
        # Verify from_config was called with the config
        mock_kraken_service_class.from_config.assert_called_once()
        call_args = mock_kraken_service_class.from_config.call_args[0][0]
        self.assertEqual(call_args.name, "Test Kraken")
        
        # Verify service returned
        self.assertEqual(service, mock_service)

    @patch('core.services.broker.config.create_kraken_broker_service')
    def test_broker_registry_get_kraken_broker(self, mock_create_kraken):
        """Test BrokerRegistry.get_kraken_broker() method."""
        from core.services.broker.config import BrokerRegistry
        
        # Reset registry for clean test
        BrokerRegistry.reset_instance()
        
        # Mock broker service
        mock_broker = MagicMock()
        mock_create_kraken.return_value = mock_broker
        
        # Get registry instance and kraken broker
        registry = BrokerRegistry.get_instance()
        broker = registry.get_kraken_broker()
        
        # Verify broker was created and connected
        mock_create_kraken.assert_called_once()
        mock_broker.connect.assert_called_once()
        self.assertEqual(broker, mock_broker)
        
        # Call again - should return cached broker without creating new one
        broker2 = registry.get_kraken_broker()
        self.assertEqual(broker2, mock_broker)
        # Still only one call to create
        mock_create_kraken.assert_called_once()

    @patch('core.services.broker.config.create_kraken_broker_service')
    def test_broker_registry_get_broker_for_kraken_asset(self, mock_create_kraken):
        """Test BrokerRegistry.get_broker_for_asset() with KRAKEN asset."""
        from core.services.broker.config import BrokerRegistry
        from trading.models import TradingAsset
        
        # Reset registry for clean test
        BrokerRegistry.reset_instance()
        
        # Create a Kraken asset
        asset = TradingAsset.objects.create(
            name="ADA/USD",
            symbol="ADAUSD",
            epic="PF_ADAUSD",
            broker=TradingAsset.BrokerKind.KRAKEN,
            broker_symbol="PF_ADAUSD",
            category="crypto",
            tick_size="0.0001",
            is_active=True,
        )
        
        # Mock broker service
        mock_broker = MagicMock()
        mock_create_kraken.return_value = mock_broker
        
        # Get broker for asset
        registry = BrokerRegistry.get_instance()
        broker = registry.get_broker_for_asset(asset)
        
        # Verify broker was created and connected
        mock_create_kraken.assert_called_once()
        mock_broker.connect.assert_called_once()
        self.assertEqual(broker, mock_broker)

    @patch('core.services.broker.config.create_kraken_broker_service')
    def test_get_broker_service_for_kraken_asset(self, mock_create_kraken):
        """Test get_broker_service_for_asset() function with KRAKEN asset."""
        from core.services.broker.config import get_broker_service_for_asset
        from trading.models import TradingAsset
        
        # Create a Kraken asset
        asset = TradingAsset.objects.create(
            name="ETH/USD",
            symbol="ETHUSD",
            epic="PF_ETHUSD",
            broker=TradingAsset.BrokerKind.KRAKEN,
            broker_symbol="PF_ETHUSD",
            category="crypto",
            tick_size="0.01",
            is_active=True,
        )
        
        # Mock broker service
        mock_broker = MagicMock()
        mock_create_kraken.return_value = mock_broker
        
        # Get broker service
        broker = get_broker_service_for_asset(asset)
        
        # Verify broker was created
        mock_create_kraken.assert_called_once()
        self.assertEqual(broker, mock_broker)

    def test_unsupported_broker_type_still_raises_error(self):
        """Test that unsupported broker types still raise ValueError."""
        from core.services.broker.config import BrokerRegistry
        from trading.models import TradingAsset
        
        # Reset registry for clean test
        BrokerRegistry.reset_instance()
        
        # Create an asset with an invalid broker type
        asset = TradingAsset.objects.create(
            name="Test Asset",
            symbol="TEST",
            epic="TEST",
            broker="INVALID_BROKER",  # Not a valid BrokerKind
            category="other",
            tick_size="0.01",
            is_active=True,
        )
        
        # Try to get broker for asset
        registry = BrokerRegistry.get_instance()
        with self.assertRaises(ValueError) as context:
            registry.get_broker_for_asset(asset)
        
        self.assertIn("Unsupported broker type", str(context.exception))

    def test_kraken_get_historical_prices(self):
        """Test that KrakenBrokerService.get_historical_prices returns aggregated candles."""
        from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig, Candle1m
        from datetime import datetime, timezone
        
        # Create a mock config
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        # Create service
        service = KrakenBrokerService(config)
        service._connected = True  # Mock connection
        service._session = MagicMock()  # Mock session
        
        # Add some mock candles to the cache
        mock_candles = [
            Candle1m(
                symbol="PI_XBTUSD",
                time=datetime(2023, 12, 6, 10, 0, 0, tzinfo=timezone.utc),
                open=42000.0,
                high=42100.0,
                low=41900.0,
                close=42050.0,
                volume=100.5,
            ),
            Candle1m(
                symbol="PI_XBTUSD",
                time=datetime(2023, 12, 6, 10, 1, 0, tzinfo=timezone.utc),
                open=42050.0,
                high=42200.0,
                low=42000.0,
                close=42150.0,
                volume=150.3,
            ),
        ]
        service._candle_cache["PI_XBTUSD"] = mock_candles
        
        # Call get_historical_prices
        prices = service.get_historical_prices(symbol="PI_XBTUSD", num_points=120)
        
        # Verify the return format
        self.assertEqual(len(prices), 2)
        
        # Check first candle
        self.assertIsInstance(prices[0]["time"], int)  # Unix timestamp
        self.assertEqual(prices[0]["open"], 42000.0)
        self.assertEqual(prices[0]["high"], 42100.0)
        self.assertEqual(prices[0]["low"], 41900.0)
        self.assertEqual(prices[0]["close"], 42050.0)
        self.assertEqual(prices[0]["volume"], 100.5)
        
        # Check second candle
        self.assertIsInstance(prices[1]["time"], int)
        self.assertEqual(prices[1]["close"], 42150.0)
        
        # Verify timestamps are 60 seconds apart (1 minute)
        self.assertEqual(prices[1]["time"] - prices[0]["time"], 60)

    def test_kraken_get_historical_prices_with_epic(self):
        """Test that get_historical_prices accepts epic parameter for compatibility."""
        from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig
        
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        service = KrakenBrokerService(config)
        service._connected = True
        service._session = MagicMock()
        service._candle_cache["PI_ETHUSD"] = []
        
        # Call with epic instead of symbol - should work without error
        prices = service.get_historical_prices(epic="PI_ETHUSD", num_points=60)
        
        # Should return empty list since cache is empty
        self.assertEqual(prices, [])

    def test_kraken_trade_count_tracking(self):
        """Test that trade_count is properly tracked in 1m candles."""
        from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig
        from datetime import datetime, timezone, timedelta
        from django.utils import timezone as dj_timezone
        
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        service = KrakenBrokerService(config)
        service._connected = True
        service._session = MagicMock()
        
        # Use current time to avoid being filtered out as too old
        base_time = dj_timezone.now().astimezone(timezone.utc).replace(second=30, microsecond=0)
        
        # Trade 1: First trade in the minute
        service._update_candle("PI_XBTUSD", 42000.0, 1.5, base_time)
        
        # Trade 2: Second trade in same minute
        service._update_candle("PI_XBTUSD", 42050.0, 2.0, base_time.replace(second=35))
        
        # Trade 3: Third trade in same minute
        service._update_candle("PI_XBTUSD", 41990.0, 1.0, base_time.replace(second=45))
        
        # Verify the current candle has correct trade_count
        current_candle = service._current_candle.get("PI_XBTUSD")
        self.assertIsNotNone(current_candle)
        self.assertEqual(current_candle["trade_count"], 3)
        self.assertEqual(current_candle["open"], 42000.0)
        self.assertEqual(current_candle["high"], 42050.0)
        self.assertEqual(current_candle["low"], 41990.0)
        self.assertEqual(current_candle["close"], 41990.0)
        self.assertEqual(current_candle["volume"], 4.5)
        
        # Get candles including the current forming one
        candles = service.get_live_candles_1m(symbol="PI_XBTUSD")
        
        # Verify the candle has trade_count
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].trade_count, 3)
        self.assertEqual(candles[0].open, 42000.0)
        self.assertEqual(candles[0].high, 42050.0)
        self.assertEqual(candles[0].low, 41990.0)
        self.assertEqual(candles[0].close, 41990.0)
        self.assertEqual(candles[0].volume, 4.5)

    def test_kraken_start_price_stream_symbol_change_restart(self):
        """Test that start_price_stream restarts when symbols change."""
        from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig
        from unittest.mock import MagicMock, patch
        import threading
        
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        service = KrakenBrokerService(config)
        service._connected = True
        service._session = MagicMock()
        service._candle_store_enabled = False
        
        # Mock WebSocket and thread
        mock_ws = MagicMock()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        service._ws = mock_ws
        service._ws_thread = mock_thread
        service._config.symbols = ["PI_XBTUSD"]
        
        # Mock the _stop_price_stream method to verify it's called
        with patch.object(service, '_stop_price_stream') as mock_stop:
            # Simulate starting stream with same symbols - should not restart
            service.start_price_stream(["PI_XBTUSD"])
            mock_stop.assert_not_called()
            
            # Reset the mock
            mock_stop.reset_mock()
            
            # Simulate starting stream with different symbols - should restart
            with patch('core.services.broker.kraken_broker_service.WebSocketApp') as mock_ws_app, \
                 patch('core.services.broker.kraken_broker_service.threading.Thread') as mock_thread_class:
                
                # Configure mocks
                mock_ws_instance = MagicMock()
                mock_ws_app.return_value = mock_ws_instance
                mock_new_thread = MagicMock()
                mock_thread_class.return_value = mock_new_thread
                
                # Call with new symbols
                new_symbols = ["PI_XBTUSD", "PF_ETHUSD", "PF_LTCUSD"]
                service.start_price_stream(new_symbols)
                
                # Verify stop was called
                mock_stop.assert_called_once()
                
                # Verify config was updated with new symbols
                self.assertEqual(set(service._config.symbols), set(new_symbols))
                
                # Verify new WebSocket was created
                mock_ws_app.assert_called_once()
                
                # Verify new thread was started
                mock_new_thread.start.assert_called_once()

    def test_kraken_load_persisted_candles_for_new_symbols(self):
        """Test that persisted candles are loaded for new symbols when stream starts."""
        from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig
        from unittest.mock import MagicMock, patch
        from datetime import datetime, timezone
        
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        service = KrakenBrokerService(config)
        service._connected = True
        service._session = MagicMock()
        
        # Mock candle store
        mock_candle_store = MagicMock()
        service._candle_store = mock_candle_store
        service._candle_store_enabled = True
        
        # Mock get_range to return some test candles
        mock_candle = MagicMock()
        mock_candle.timestamp = datetime.now(timezone.utc).timestamp()
        mock_candle.open = 42000.0
        mock_candle.high = 42100.0
        mock_candle.low = 41900.0
        mock_candle.close = 42050.0
        mock_candle.volume = 100.0
        mock_candle.trade_count = 10
        mock_candle_store.get_range.return_value = [mock_candle]
        
        # Mock WebSocket and thread creation
        with patch('core.services.broker.kraken_broker_service.WebSocketApp') as mock_ws_app, \
             patch('core.services.broker.kraken_broker_service.threading.Thread') as mock_thread_class:
            
            mock_ws_instance = MagicMock()
            mock_ws_app.return_value = mock_ws_instance
            mock_new_thread = MagicMock()
            mock_thread_class.return_value = mock_new_thread
            
            # Start stream with multiple symbols
            symbols = ["PF_LTCUSD", "PF_ETHUSD", "PF_ADAUSD"]
            service.start_price_stream(symbols)
            
            # Verify get_range was called for each symbol
            self.assertEqual(mock_candle_store.get_range.call_count, len(symbols))
            
            # Verify candles were loaded into cache for each symbol
            for symbol in symbols:
                self.assertIn(symbol, service._candle_cache)
                self.assertEqual(len(service._candle_cache[symbol]), 1)
