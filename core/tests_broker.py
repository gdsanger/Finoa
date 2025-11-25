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
