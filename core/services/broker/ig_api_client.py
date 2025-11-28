"""
IG API Client for REST API communication.

Handles low-level communication with IG Web API including:
- Session management (login/logout)
- Authentication header management
- REST API calls for accounts, positions, and markets
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List
import requests

from .broker_service import BrokerError, AuthenticationError


logger = logging.getLogger(__name__)


# API version headers
API_VERSION_SESSION = "3"
API_VERSION_ACCOUNTS = "1"
API_VERSION_POSITIONS = "2"
API_VERSION_MARKETS = "3"
API_VERSION_ORDERS = "2"


@dataclass
class IgSession:
    """Holds session information for IG API."""
    cst: str
    security_token: str
    account_id: str
    client_id: str
    timezone_offset: int = 0
    created_at: datetime = None
    is_oauth: bool = False  # Track if session was authenticated via OAuth

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class IgApiClient:
    """
    Low-level client for IG Web API (REST).
    
    Handles authentication, session management, and REST API calls.
    This class should not contain business logic - it's a thin wrapper
    around the IG REST API.
    """

    # IG API endpoints
    DEMO_BASE_URL = "https://demo-api.ig.com/gateway/deal"
    LIVE_BASE_URL = "https://api.ig.com/gateway/deal"

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        account_type: str = "DEMO",
        account_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the IG API client.
        
        Args:
            api_key: IG API key.
            username: IG account username/identifier.
            password: IG account password.
            account_type: "DEMO" or "LIVE".
            account_id: Specific account ID to use (if multiple accounts).
            base_url: Override the base URL (optional).
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.username = username
        self.password = password
        self.account_type = account_type.upper()
        self.account_id = account_id
        self.timeout = timeout
        
        # Set base URL based on account type
        if base_url:
            self.base_url = base_url.rstrip('/')
        elif self.account_type == "LIVE":
            self.base_url = self.LIVE_BASE_URL
        else:
            self.base_url = self.DEMO_BASE_URL
        
        self._session: Optional[IgSession] = None
        logger.info(f"IgApiClient initialized for {self.account_type} account")

    @property
    def is_authenticated(self) -> bool:
        """Check if client has a valid session."""
        return self._session is not None

    def _get_auth_headers(self, version: str = "1") -> Dict[str, str]:
        """
        Get headers for authenticated requests.
        
        Uses different headers based on authentication method:
        - OAuth: Authorization: Bearer <access_token> + IG-ACCOUNT-ID
        - Traditional: CST + X-SECURITY-TOKEN headers
        
        Args:
            version: API version for the request.
        
        Returns:
            Dict with required headers.
        """
        if not self._session:
            raise AuthenticationError("Not authenticated - call login() first")
        
        headers = {
            "X-IG-API-KEY": self.api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json; charset=UTF-8",
            "VERSION": version,
        }
        
        if self._session.is_oauth:
            # OAuth authentication uses Bearer token
            headers["Authorization"] = f"Bearer {self._session.cst}"
            if self._session.account_id:
                headers["IG-ACCOUNT-ID"] = self._session.account_id
        else:
            # Traditional authentication uses CST and X-SECURITY-TOKEN
            headers["CST"] = self._session.cst
            headers["X-SECURITY-TOKEN"] = self._session.security_token
        
        return headers

    def _get_login_headers(self, version: str = "3") -> Dict[str, str]:
        """Get headers for login request."""
        return {
            "X-IG-API-KEY": self.api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json; charset=UTF-8",
            "VERSION": version,
        }

    # Token-related error codes that indicate the need to re-authenticate
    TOKEN_INVALID_ERRORS = frozenset([
        "error.security.client-token-invalid",
        "error.security.oauth-token-invalid",
    ])

    def _make_request(
        self,
        method: str,
        endpoint: str,
        headers: Dict[str, str],
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry_on_token_error: bool = True
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the IG API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint (without base URL).
            headers: Request headers.
            data: Request body (for POST/PUT).
            params: Query parameters.
            retry_on_token_error: If True, automatically re-authenticate and retry
                when a token-invalid error is received.
        
        Returns:
            Parsed JSON response.
        
        Raises:
            BrokerError: If the request fails.
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=self.timeout
            )
            
            # Log request (without sensitive data)
            logger.debug(f"IG API {method} {endpoint} -> {response.status_code}")
            
            # Handle responses
            if response.status_code in [200, 201]:
                return response.json() if response.text else {}
            
            # Handle errors
            error_msg = f"IG API error: {response.status_code}"
            error_code = None
            try:
                error_data = response.json()
                error_code = error_data.get('errorCode', 'UNKNOWN')
                error_msg = f"IG API error [{error_code}]: {response.text}"
            except (ValueError, TypeError):
                pass
            
            if response.status_code == 401:
                # Check if this is a token-invalid error that we can retry
                if retry_on_token_error and error_code in self.TOKEN_INVALID_ERRORS:
                    logger.info(f"Token invalid ({error_code}), attempting to re-authenticate...")
                    return self._retry_with_fresh_session(
                        method, endpoint, headers, data, params
                    )
                raise AuthenticationError(error_msg, code=error_code)
            
            raise BrokerError(error_msg, code=str(response.status_code))
            
        except requests.Timeout:
            raise BrokerError(f"Request timeout after {self.timeout}s")
        except requests.RequestException as e:
            raise BrokerError(f"Request failed: {str(e)}")

    def _retry_with_fresh_session(
        self,
        method: str,
        endpoint: str,
        headers: Dict[str, str],
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Refresh the session and retry the request.
        
        This is called when a token-invalid error is received to automatically
        re-authenticate and retry the original request once.
        
        For OAuth sessions, tries to refresh the token first. If that fails,
        falls back to full re-login.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint (without base URL).
            headers: Original request headers (tokens will be updated).
            data: Request body (for POST/PUT).
            params: Query parameters.
        
        Returns:
            Parsed JSON response.
        
        Raises:
            AuthenticationError: If re-authentication fails.
            BrokerError: If the retried request fails.
        """
        try:
            # For OAuth sessions, try to refresh the token first
            if self._session and self._session.is_oauth and self._session.security_token:
                try:
                    self._refresh_oauth_token()
                except AuthenticationError:
                    # If refresh fails, fall back to full re-login
                    logger.info("OAuth token refresh failed, falling back to full login")
                    self.login()
            else:
                # For traditional sessions, just re-login
                self.login()
            
            # Verify session was established with valid tokens
            # Note: For both OAuth and traditional sessions, the access/auth token is stored in `cst`
            # For OAuth: cst = access_token, security_token = refresh_token
            # For traditional: cst = CST header value, security_token = X-SECURITY-TOKEN header value
            if not self._session or not self._session.cst:
                raise AuthenticationError("Re-authentication did not establish a valid session")
            
            # For non-OAuth sessions, also verify security_token
            if not self._session.is_oauth and not self._session.security_token:
                raise AuthenticationError("Re-authentication did not establish a valid session")
            
            logger.info("Re-authentication successful, retrying request...")
            
            # Get fresh auth headers for the retry
            version = headers.get("VERSION", "1")
            new_headers = self._get_auth_headers(version)
            
            # Retry the request without allowing another retry to prevent infinite loops
            return self._make_request(
                method, endpoint, new_headers, data, params,
                retry_on_token_error=False
            )
        except AuthenticationError:
            logger.error("Re-authentication failed")
            raise

    def _refresh_oauth_token(self) -> None:
        """
        Refresh OAuth access token using the refresh token.
        
        Updates the session with new tokens.
        
        Raises:
            AuthenticationError: If token refresh fails.
        """
        if not self._session or not self._session.security_token:
            raise AuthenticationError("No refresh token available")
        
        logger.info("Refreshing OAuth token...")
        
        data = {
            "refresh_token": self._session.security_token,
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/session/refresh-token",
                headers={
                    "X-IG-API-KEY": self.api_key,
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json; charset=UTF-8",
                    "VERSION": API_VERSION_SESSION,
                },
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                error_msg = f"Token refresh failed: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = f"Token refresh failed: {error_data.get('errorCode', response.text)}"
                except (ValueError, TypeError):
                    pass
                raise AuthenticationError(error_msg)
            
            body = response.json()
            
            # Extract new tokens
            access_token = body.get("access_token")
            # IG API may not return a new refresh_token on every refresh.
            # Per OAuth 2.0 spec, if no new refresh_token is provided, the existing one remains valid.
            refresh_token = body.get("refresh_token", self._session.security_token)
            
            if not access_token:
                raise AuthenticationError("Token refresh response missing access_token")
            
            # Update session with new tokens
            self._session = IgSession(
                cst=access_token,
                security_token=refresh_token,
                account_id=self._session.account_id,
                client_id=self._session.client_id,
                timezone_offset=self._session.timezone_offset,
                is_oauth=True,
            )
            
            logger.info("OAuth token refreshed successfully")
            
        except requests.RequestException as e:
            raise AuthenticationError(f"Token refresh request failed: {str(e)}")

    def login(self) -> IgSession:
        """
        Authenticate with IG and create a session.
        
        Returns:
            IgSession with authentication tokens.
        
        Raises:
            AuthenticationError: If login fails.
        """
        logger.info("Logging in to IG API...")
        
        data = {
            "identifier": self.username,
            "password": self.password,
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/session",
                headers=self._get_login_headers(API_VERSION_SESSION),
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                error_msg = f"Login failed: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = f"Login failed: {error_data.get('errorCode', response.text)}"
                except (ValueError, TypeError):
                    pass
                raise AuthenticationError(error_msg)
            
            # Parse response body first (needed for both header and body token extraction)
            body = response.json()
            
            # Extract session tokens from headers (primary method)
            cst = response.headers.get("CST")
            security_token = response.headers.get("X-SECURITY-TOKEN")
            
            # If BOTH tokens are missing from headers, try to get from response body (OAuth tokens)
            # IG API V3 can return oauthToken in body for OAuth flow
            # Note: If headers have partial tokens (one present, one missing), we don't fallback to OAuth
            is_oauth = False
            if not cst and not security_token:
                oauth_token = body.get("oauthToken", {})
                if oauth_token:
                    cst = oauth_token.get("access_token")
                    security_token = oauth_token.get("refresh_token")
                    is_oauth = True
            
            if not cst or not security_token:
                raise AuthenticationError("Login response missing session tokens")
            
            account_id = self.account_id or body.get("currentAccountId")
            client_id = body.get("clientId")
            timezone_offset = body.get("timezoneOffset", 0)
            
            self._session = IgSession(
                cst=cst,
                security_token=security_token,
                account_id=account_id,
                client_id=client_id,
                timezone_offset=timezone_offset,
                is_oauth=is_oauth,
            )
            
            auth_method = "OAuth" if is_oauth else "traditional"
            logger.info(f"Successfully logged in via {auth_method}. Account: {account_id}")
            return self._session
            
        except requests.RequestException as e:
            raise AuthenticationError(f"Login request failed: {str(e)}")

    def logout(self) -> None:
        """
        End the current session.
        
        For traditional sessions, makes a DELETE request to /session.
        For OAuth sessions, simply discards the tokens (no server-side logout needed).
        
        Raises:
            BrokerError: If logout fails (only for traditional sessions).
        """
        if not self._session:
            logger.warning("Logout called but no active session")
            return
        
        try:
            if self._session.is_oauth:
                # For OAuth sessions, just discard the tokens
                # OAuth tokens expire on their own and don't need server-side logout
                logger.info("OAuth session - discarding tokens")
            else:
                # For traditional sessions, make a logout request
                self._make_request(
                    "DELETE",
                    "/session",
                    self._get_auth_headers(API_VERSION_SESSION),
                    retry_on_token_error=False  # Don't retry logout on token error
                )
                logger.info("Successfully logged out")
        except BrokerError as e:
            logger.warning(f"Logout failed: {e}")
        finally:
            self._session = None

    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        Get list of all accounts.
        
        Returns:
            List of account dictionaries.
        """
        response = self._make_request(
            "GET",
            "/accounts",
            self._get_auth_headers(API_VERSION_ACCOUNTS)
        )
        return response.get("accounts", [])

    def get_account_details(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get details for a specific account.
        
        Args:
            account_id: Account ID (uses session account if not provided).
        
        Returns:
            Account details dictionary.
        """
        account_id = account_id or (self._session.account_id if self._session else None)
        if not account_id:
            raise BrokerError("No account ID available")
        
        accounts = self.get_accounts()
        for account in accounts:
            if account.get("accountId") == account_id:
                return account
        
        raise BrokerError(f"Account {account_id} not found")

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions.
        
        Returns:
            List of position dictionaries.
        """
        response = self._make_request(
            "GET",
            "/positions",
            self._get_auth_headers(API_VERSION_POSITIONS)
        )
        return response.get("positions", [])

    def get_position(self, deal_id: str) -> Dict[str, Any]:
        """
        Get details for a specific position.
        
        Args:
            deal_id: Deal ID of the position.
        
        Returns:
            Position details dictionary.
        """
        response = self._make_request(
            "GET",
            f"/positions/{deal_id}",
            self._get_auth_headers(API_VERSION_POSITIONS)
        )
        return response

    def get_market(self, epic: str) -> Dict[str, Any]:
        """
        Get market details and current prices.
        
        Args:
            epic: Market EPIC code.
        
        Returns:
            Market details dictionary.
        """
        response = self._make_request(
            "GET",
            f"/markets/{epic}",
            self._get_auth_headers(API_VERSION_MARKETS)
        )
        return response

    def search_markets(self, search_term: str) -> List[Dict[str, Any]]:
        """
        Search for markets.
        
        Args:
            search_term: Search term (e.g., "oil", "crude").
        
        Returns:
            List of matching markets.
        """
        response = self._make_request(
            "GET",
            "/markets",
            self._get_auth_headers(API_VERSION_MARKETS),
            params={"searchTerm": search_term}
        )
        return response.get("markets", [])

    def create_position(
        self,
        epic: str,
        direction: str,
        size: Decimal,
        order_type: str = "MARKET",
        currency_code: str = "EUR",
        stop_level: Optional[Decimal] = None,
        stop_distance: Optional[Decimal] = None,
        limit_level: Optional[Decimal] = None,
        limit_distance: Optional[Decimal] = None,
        guaranteed_stop: bool = False,
        force_open: bool = True,
        level: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Create a new position (place order).
        
        Args:
            epic: Market EPIC code.
            direction: "BUY" or "SELL".
            size: Position size.
            order_type: "MARKET" or "LIMIT".
            currency_code: Currency code.
            stop_level: Absolute stop loss level.
            stop_distance: Stop loss distance in points.
            limit_level: Absolute take profit level.
            limit_distance: Take profit distance in points.
            guaranteed_stop: Whether stop is guaranteed.
            force_open: Force open a new position.
            level: Price level for LIMIT orders.
        
        Returns:
            Dictionary with deal reference.
        """
        data = {
            "epic": epic,
            "direction": direction,
            "size": str(size),
            "orderType": order_type,
            "currencyCode": currency_code,
            "guaranteedStop": guaranteed_stop,
            "forceOpen": force_open,
        }
        
        # Add optional fields
        if stop_level is not None:
            data["stopLevel"] = str(stop_level)
        if stop_distance is not None:
            data["stopDistance"] = str(stop_distance)
        if limit_level is not None:
            data["limitLevel"] = str(limit_level)
        if limit_distance is not None:
            data["limitDistance"] = str(limit_distance)
        if level is not None:
            data["level"] = str(level)
        
        response = self._make_request(
            "POST",
            "/positions/otc",
            self._get_auth_headers(API_VERSION_ORDERS),
            data=data
        )
        return response

    def close_position(
        self,
        deal_id: str,
        direction: str,
        size: Decimal,
        order_type: str = "MARKET",
        level: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Close an existing position.
        
        Args:
            deal_id: Deal ID of the position to close.
            direction: Opposite to the position direction.
            size: Size to close (may be partial).
            order_type: "MARKET" or "LIMIT".
            level: Price level for LIMIT orders.
        
        Returns:
            Dictionary with deal reference.
        """
        data = {
            "dealId": deal_id,
            "direction": direction,
            "size": str(size),
            "orderType": order_type,
        }
        
        if level is not None:
            data["level"] = str(level)
        
        # IG requires DELETE method with body, use _method header trick
        headers = self._get_auth_headers(API_VERSION_ORDERS)
        headers["_method"] = "DELETE"
        
        response = self._make_request(
            "POST",
            "/positions/otc",
            headers,
            data=data
        )
        return response

    def confirm_deal(self, deal_reference: str) -> Dict[str, Any]:
        """
        Confirm a deal was executed.
        
        Args:
            deal_reference: Deal reference from create/close position.
        
        Returns:
            Deal confirmation details.
        """
        response = self._make_request(
            "GET",
            f"/confirms/{deal_reference}",
            self._get_auth_headers(API_VERSION_ORDERS)
        )
        return response

    def get_prices(
        self,
        epic: str,
        resolution: str = "MINUTE_5",
        num_points: int = 144,
    ) -> Dict[str, Any]:
        """
        Get historical price data (candles) for a market.
        
        Uses the IG REST API /prices/{epic} endpoint to fetch historical
        OHLC candlestick data.
        
        Args:
            epic: Market EPIC code (e.g., 'CC.D.CL.UNC.IP').
            resolution: Price resolution. One of:
                - 'SECOND' (not recommended)
                - 'MINUTE', 'MINUTE_2', 'MINUTE_3', 'MINUTE_5', 
                  'MINUTE_10', 'MINUTE_15', 'MINUTE_30'
                - 'HOUR', 'HOUR_2', 'HOUR_3', 'HOUR_4'
                - 'DAY', 'WEEK', 'MONTH'
            num_points: Number of data points to retrieve (max varies by resolution).
                For MINUTE_5: max ~10000 points (about 35 days).
        
        Returns:
            Dictionary containing:
                - instrumentType: Type of instrument
                - prices: List of price data points, each containing:
                    - snapshotTime: Timestamp string
                    - snapshotTimeUTC: UTC timestamp string
                    - openPrice: {bid, ask, lastTraded}
                    - closePrice: {bid, ask, lastTraded}
                    - highPrice: {bid, ask, lastTraded}
                    - lowPrice: {bid, ask, lastTraded}
                    - lastTradedVolume: Volume
                - allowance: API allowance info
        
        Raises:
            BrokerError: If the API request fails.
        """
        response = self._make_request(
            "GET",
            f"/prices/{epic}",
            self._get_auth_headers(API_VERSION_MARKETS),
            params={
                "resolution": resolution,
                "max": num_points,
                "pageSize": 0,  # Return all in one response
            }
        )
        return response
