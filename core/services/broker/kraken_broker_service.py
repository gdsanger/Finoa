# core/services/kraken_broker_service.py

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from urllib.parse import urlencode
import requests
from websocket import WebSocketApp  # websocket-client

from django.utils import timezone

from core.models import KrakenBrokerConfig as KrakenBrokerConfigModel
from core.services.market_data.candle_models import Candle
from .broker_service import BrokerService, BrokerError, AuthenticationError
from .models import (
    AccountState,
    Position,
    OrderRequest,
    OrderResult,
    SymbolPrice,
    OrderDirection,
    OrderStatus,
    OrderType,
    Candle1m,
)

logger = logging.getLogger("core.services.kraken_broker_service")

# Long-lived singleton instance for Kraken to avoid reconnecting per request
_kraken_service: "KrakenBrokerService" | None = None
_kraken_service_lock = threading.Lock()

# Charts API v1 response format constant
# Charts API returns candles as: [timestamp, open, high, low, close, volume]
CHARTS_API_EXPECTED_CANDLE_FIELDS = 6


# =============================================================================
# Domain-Modelle für Lumina v2 – brokerneutral, aber Kraken-optimiert
# =============================================================================


# =============================================================================
# Fehlerklassen
# =============================================================================


class KrakenBrokerError(BrokerError):
    """Allgemeiner Fehler im KrakenBrokerService."""


class KrakenAuthenticationError(KrakenBrokerError, AuthenticationError):
    """Auth-/API-Key-bezogene Fehler."""


# =============================================================================
# Konfiguration
# =============================================================================


@dataclass
class KrakenBrokerConfig:
    """
    Konfiguration des Kraken-Broker-Adapters.
    Diese Struktur kann 1:1 aus dem Broker-Objekt befüllt werden.
    """
    api_key: str
    api_secret: str

    # Nur Host, ohne Pfad
    rest_base_url: str = "https://futures.kraken.com/derivatives"
    ws_public_url: str = "wss://futures.kraken.com/ws/v1"
    charts_base_url: str = "https://futures.kraken.com/api/charts/v1"

    default_symbol: str = "PI_XBTUSD"
    symbols: Optional[List[str]] = None
    use_demo: bool = False

    def apply_demo(self) -> None:
        if self.use_demo:
            self.rest_base_url = "https://demo-futures.kraken.com/derivatives"
            self.ws_public_url = "wss://demo-futures.kraken.com/ws/v1"
            self.charts_base_url = "https://demo-futures.kraken.com/api/charts/v1"


def get_active_kraken_broker_config() -> KrakenBrokerConfig:
    """Build a :class:`KrakenBrokerConfig` from the active Kraken broker record."""

    try:
        config_model = KrakenBrokerConfigModel.objects.get(is_active=True)
    except KrakenBrokerConfigModel.DoesNotExist as exc:
        raise KrakenBrokerError("No active Kraken broker configured") from exc
    except KrakenBrokerConfigModel.MultipleObjectsReturned as exc:
        raise KrakenBrokerError(
            "Multiple active Kraken brokers configured; expected exactly one",
        ) from exc

    if not config_model.api_key or not config_model.api_secret:
        raise KrakenAuthenticationError(
            "Kraken broker API credentials are not configured",
        )

    # Build the config dataclass from the model
    config = KrakenBrokerConfig(
        api_key=config_model.api_key,
        api_secret=config_model.api_secret,
        default_symbol=config_model.default_symbol,
        use_demo=(config_model.account_type == 'DEMO'),
    )

    # Override URLs if specified in the model
    if config_model.rest_base_url:
        config.rest_base_url = config_model.rest_base_url

    if config_model.charts_base_url:
        config.charts_base_url = config_model.charts_base_url

    if config_model.websocket_url:
        config.ws_public_url = config_model.websocket_url

    return config


def get_kraken_service() -> "KrakenBrokerService":
    """Return a singleton :class:`KrakenBrokerService` instance and ensure it is connected."""

    global _kraken_service

    with _kraken_service_lock:
        if _kraken_service is None:
            cfg = get_active_kraken_broker_config()
            _kraken_service = KrakenBrokerService(cfg)

        service = _kraken_service

    service.connect()
    return service


# =============================================================================
# KrakenBrokerService – Kernklasse für Lumina v2
# =============================================================================


class KrakenBrokerService(BrokerService):
    """
    Voll funktionsfähiger Broker-Adapter für Kraken Futures / Kraken Pro.

    Features:
    - REST v3:
      - /accounts → AccountState
      - /openpositions → offene Positionen
      - /tickers → Marktpreise
      - /sendorder → Order platzieren/schließen
    - Charts API:
      - /trade/<symbol>/1m → 1m-Candles der letzten X Stunden
    - WebSocket v1:
      - ticker_lite → Live-Preise
      - trade → Candle-Aggregation (1m) in Echtzeit

    Nutzung (Beispiel):

        cfg = KrakenBrokerConfig(
            api_key="...",
            api_secret="...",
            default_symbol="PI_XBTUSD",
            symbols=["PI_XBTUSD", "PI_ETHUSD"],
            use_demo=True,
        )
        svc = KrakenBrokerService(cfg)
        svc.connect()
        account = svc.get_account_state()
        price = svc.get_symbol_price("PI_XBTUSD")
        candles = svc.get_live_candles_1m("PI_XBTUSD")
    """

    def __init__(self, config: KrakenBrokerConfig, candle_store=None) -> None:
        self._config = config
        self._config.apply_demo()

        self._session: Optional[requests.Session] = None
        self._connected: bool = False

        # WebSocket
        self._ws: Optional[WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop_event = threading.Event()

        # Caches
        self._price_cache: Dict[str, SymbolPrice] = {}
        self._candle_cache: Dict[str, List[Candle1m]] = {}
        self._current_candle: Dict[str, Dict[str, Any]] = {}
        self._account_state_cache: Optional[AccountState] = None
        self._account_state_cache_ts: Optional[float] = None
        self._account_state_cache_ttl = 5.0  # seconds

        # Candle persistence (lazy initialization to avoid import cycles)
        self._candle_store = candle_store
        self._candle_store_enabled = False

        self._lock = threading.Lock()

        logger.info(
            "KrakenBrokerService created (demo=%s, rest=%s)",
            self._config.use_demo,
            self._config.rest_base_url,
        )

    @classmethod
    def from_config(cls, config_model: KrakenBrokerConfigModel) -> 'KrakenBrokerService':
        """
        Create service from a KrakenBrokerConfig model instance.
        
        Args:
            config_model: KrakenBrokerConfig model instance.
        
        Returns:
            KrakenBrokerService instance.
        """
        # Build the config dataclass from the model
        config = KrakenBrokerConfig(
            api_key=config_model.api_key,
            api_secret=config_model.api_secret,
            default_symbol=config_model.default_symbol,
            use_demo=(config_model.account_type == 'DEMO'),
        )

        # Override URLs if specified in the model
        if config_model.rest_base_url:
            config.rest_base_url = config_model.rest_base_url

        if config_model.websocket_url:
            config.ws_public_url = config_model.websocket_url

        return cls(config)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def _load_persisted_candles_for_symbol(self, symbol: str) -> None:
        """Load persisted candles for a specific symbol from the candle store."""
        if not self._candle_store_enabled:
            return
        
        # Check if already loaded (with lock to prevent race condition)
        with self._lock:
            if symbol in self._candle_cache:
                return
        
        try:
            # Load last 6 hours of candles
            from_time = timezone.now() - timedelta(hours=6)
            candles = self._candle_store.get_range(
                asset_id=symbol,
                timeframe='1m',
                start_time=from_time,
                end_time=timezone.now()
            )
            if candles:
                # Convert to Candle1m format
                candle_objs = []
                for c in candles:
                    candle_objs.append(
                        Candle1m(
                            symbol=symbol,
                            time=datetime.fromtimestamp(c.timestamp, tz=dt_timezone.utc),
                            open=float(c.open),
                            high=float(c.high),
                            low=float(c.low),
                            close=float(c.close),
                            volume=float(c.volume) if c.volume else 0.0,
                            trade_count=int(c.trade_count) if c.trade_count else 0,
                        )
                    )
                with self._lock:
                    # Double-check in case another thread loaded it while we were loading
                    if symbol not in self._candle_cache:
                        self._candle_cache[symbol] = candle_objs
                        logger.info(f"Loaded {len(candle_objs)} persisted candles for {symbol}")
        except Exception as e:
            logger.warning(f"Could not load persisted candles for {symbol}: {e}")

    def _init_candle_store(self) -> None:
        """Initialize candle store and load persisted candles."""
        if self._candle_store is None:
            try:
                from core.services.market_data.redis_candle_store import get_candle_store
                self._candle_store = get_candle_store()
                self._candle_store_enabled = True
                logger.info("Candle persistence enabled via Redis")
            except Exception as e:
                logger.warning(f"Could not initialize candle store: {e}. Candles will not be persisted.")
                self._candle_store_enabled = False
                return
        
        # Load persisted candles for configured symbols
        if self._candle_store_enabled:
            symbols = self._config.symbols or [self._config.default_symbol]
            for symbol in symbols:
                self._load_persisted_candles_for_symbol(symbol)

    def connect(self) -> None:
        """
        Baut REST-Session auf und überprüft API-Key via /api/v3/accounts.
        Startet optional den WebSocket-Stream für Ticker & Trades.
        """
        if self._connected:
            return

        if not self._config.api_key or not self._config.api_secret:
            raise KrakenAuthenticationError("Kraken API key/secret not configured")

        self._session = requests.Session()
        logger.info("Connecting to Kraken Futures (REST v3)...")

        try:
            _ = self._request("GET", "/api/v3/accounts", auth_required=True)
        except KrakenAuthenticationError as exc:
            logger.warning(
                "Kraken authentication failed (check API key/secret and live/demo setting): %s",
                exc,
            )
            raise
        except Exception as ex:
            logger.exception("Error connecting to Kraken Futures")
            raise KrakenBrokerError(f"Error connecting to Kraken Futures: {ex}") from ex

        self._connected = True
        logger.info("Successfully connected to Kraken Futures (REST v3)")

        # Initialize candle store and load persisted candles
        self._init_candle_store()

        symbols = self._config.symbols or [self._config.default_symbol]
        try:
            self.start_price_stream(symbols)
        except Exception:
            logger.exception("Failed to start Kraken WebSocket price stream")


    def disconnect(self) -> None:
        """
        Schließt WebSocket und REST-Session.
        """
        self._connected = False

        # Stop the price stream
        self._stop_price_stream()

        if self._session:
            try:
                self._session.close()
            except Exception:
                logger.exception("Error while closing Kraken REST session")
            self._session = None

        self._account_state_cache = None
        self._account_state_cache_ts = None

        logger.info("KrakenBrokerService disconnected")

    def is_connected(self) -> bool:
        """
        Check if service is connected.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected or self._session is None:
            raise KrakenBrokerError("KrakenBrokerService is not connected")

    # -------------------------------------------------------------------------
    # REST Helper
    # -------------------------------------------------------------------------

    def _sign_request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        nonce: Optional[str] = None,
    ) -> Dict[str, str]:
        if nonce is None:
            nonce = str(int(time.time() * 1000))

        post_data_str = ""
        if params:
            post_data_str = urlencode(params, doseq=True)
        elif body:
            post_data_str = urlencode(body, doseq=True)

        # WICHTIG: path ist jetzt sowas wie "/api/v3/accounts"
        message = f"{post_data_str}{nonce}{path}"


        sha256_hash = hashlib.sha256(message.encode("utf-8")).digest()
        secret_bytes = base64.b64decode(self._config.api_secret)

        signature = hmac.new(secret_bytes, sha256_hash, hashlib.sha512).digest()
        authent = base64.b64encode(signature).decode("utf-8")

        headers = {
            "APIKey": self._config.api_key,
            "Authent": authent,
            "Nonce": nonce,
            "Content-Type": "application/json",
        }

        return headers


    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        *,
        auth_required: bool = False,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        base_url = self._config.rest_base_url
        url = f"{base_url}{path}"

        if self._session is None:
            self._session = requests.Session()

        headers: Dict[str, str] = {}
        data: Optional[str] = None

        if auth_required:
            nonce = str(int(time.time() * 1000))
            if params is None:
                params = {}

            headers = self._sign_request(
                method=method,
                path=path,
                body=body,
                params=params,
                nonce=nonce,
            )
        else:
            headers["Content-Type"] = "application/json"

        if body:
            data = json.dumps(body)

        resp = self._session.request(
            method=method.upper(),
            url=url,
            headers=headers,
            data=data,
            params=params,
            timeout=timeout,
        )

        if resp.status_code == 401:
            raise KrakenAuthenticationError(f"Unauthorized (401) for {path}")

        if resp.status_code >= 400:
            raise KrakenBrokerError(
                f"Kraken REST error HTTP {resp.status_code} for {path}: {resp.text}"
            )

        try:
            payload = resp.json()
        except Exception as ex:
            raise KrakenBrokerError(
                f"Invalid JSON response from Kraken: {ex}"
            ) from ex

        error_msg = payload.get("error")
        if error_msg:
            msg = str(error_msg)
            if "auth" in msg.lower():
                raise KrakenAuthenticationError(
                    f"Kraken v3 authentication error for {path}: {msg}"
                )
            raise KrakenBrokerError(f"Kraken v3 error for {path}: {msg}")

        return payload

    # -------------------------------------------------------------------------
    # Account / Margin
    # -------------------------------------------------------------------------

    def get_account_state(self) -> AccountState:
        """
        Liest den Kraken-Futures-Account-Status aus /api/v3/accounts.

        - nutzt primär den FLEX-Account (multiCollateralMarginAccount)
        - Werte sind bereits in USD bewertet
        """
        self._ensure_connected()

        now = time.time()
        with self._lock:
            if (
                self._account_state_cache
                and self._account_state_cache_ts
                and now - self._account_state_cache_ts < self._account_state_cache_ttl
            ):
                return self._account_state_cache

        payload = self._request("GET", "/api/v3/accounts", auth_required=True)
        accounts = payload.get("accounts")
        if not isinstance(accounts, dict):
            raise KrakenBrokerError("Unexpected structure in /accounts (expected dict)")

        flex = accounts.get("flex")
        if not flex:
            raise KrakenBrokerError("No 'flex' account found in /accounts")

        # --- Zahlen direkt aus FLEX nehmen ---
        balance_value = float(flex.get("balanceValue", 0.0))        # Gesamtwert (USD)
        portfolio_value = float(flex.get("portfolioValue", 0.0))    # praktisch gleich
        collateral_value = float(flex.get("collateralValue", 0.0))  # als Margin nutzbar
        available_margin = float(flex.get("availableMargin", 0.0))
        initial_margin = float(flex.get("initialMargin", 0.0))
        pnl = float(flex.get("pnl", 0.0))

        # Währung aus currencies ableiten (USDC, USDT, ...), sonst "usd"
        currencies = flex.get("currencies") or {}
        if currencies:
            first_code = next(iter(currencies.keys()))
            currency = first_code.upper()  # "USDC"
        else:
            currency = "USD"

        # serverTime parsen
        server_time = payload.get("serverTime")
        try:
            ts = datetime.fromisoformat(server_time.replace("Z", "+00:00"))
        except Exception:
            ts = timezone.now()

        # Für Lumina:
        # - balance = balanceValue (Gesamtwert)
        # - equity  = portfolioValue
        # - margin_used = initialMargin
        # - margin_available = availableMargin
        account_state = AccountState(
            account_id='KRAKEN_FLEX',
            account_name='Kraken Futures',
            balance=balance_value,
            available=available_margin,
            equity=portfolio_value,
            margin_used=initial_margin,
            margin_available=available_margin,
            unrealized_pnl=pnl,
            currency=currency,
            timestamp=ts,
        )

        with self._lock:
            self._account_state_cache = account_state
            self._account_state_cache_ts = time.time()

        return account_state

    # -------------------------------------------------------------------------
    # Symbol Prices (Realtime + Fallback)
    # -------------------------------------------------------------------------

    def get_symbol_price(self, epic: str) -> SymbolPrice:
        """
        Get current price information for a market/symbol.
        
        Args:
            epic: Market symbol (e.g., 'PI_XBTUSD').
        
        Returns:
            SymbolPrice with current bid/ask and other price data.
        """
        self._ensure_connected()
        
        symbol = epic or self._config.default_symbol

        with self._lock:
            sp = self._price_cache.get(symbol)
            if sp is not None:
                return sp

        # REST-Fallback
        params = {"symbol": symbol}
        payload = self._request(
            "GET",
            "/api/v3/tickers",
            params=params,
            auth_required=False,
        )

        tickers = payload.get("tickers") or payload.get("tickers", [])
        if isinstance(tickers, dict):
            ticker = tickers.get(symbol)
        else:
            ticker = next((t for t in tickers if t.get("symbol") == symbol), None)

        if not ticker:
            raise KrakenBrokerError(f"No ticker found for symbol {symbol}")

        bid = Decimal(str(ticker.get("bid", 0.0)))
        ask = Decimal(str(ticker.get("ask", 0.0)))
        spread = ask - bid
        mark = ticker.get("markPrice")
        
        # Get 24h stats if available
        high = Decimal(str(ticker.get("high24h"))) if ticker.get("high24h") else None
        low = Decimal(str(ticker.get("low24h"))) if ticker.get("low24h") else None
        change = Decimal(str(ticker.get("change24h"))) if ticker.get("change24h") else None
        change_percent = Decimal(str(ticker.get("changePercent24h"))) if ticker.get("changePercent24h") else None

        ts = timezone.now()
        sp = SymbolPrice(
            epic=symbol,
            market_name=symbol,
            bid=bid,
            ask=ask,
            spread=spread,
            high=high,
            low=low,
            change=change,
            change_percent=change_percent,
            timestamp=ts,
        )

        with self._lock:
            self._price_cache[symbol] = sp

        return sp

    # -------------------------------------------------------------------------
    # WebSocket – Ticker & Trades
    # -------------------------------------------------------------------------

    def _stop_price_stream(self) -> None:
        """
        Stop the WebSocket price stream.
        Internal helper method used when restarting with different symbols.
        """
        if self._ws:
            try:
                self._ws_stop_event.set()
                sock = getattr(self._ws, "sock", None)
                if sock and getattr(sock, "connected", False):
                    self._ws.close()
                else:
                    self._ws.keep_running = False
            except Exception:
                logger.exception("Error while closing Kraken WebSocket")
            self._ws = None

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5.0)
            self._ws_thread = None
        
        logger.debug("Price stream stopped")

    def start_price_stream(self, symbols: Optional[List[str]] = None) -> None:
        """
        Startet öffentlichen WebSocket-Feed für:
        - ticker_lite → Live-Bid/Ask
        - trade → Candle-Aggregation (1m)
        
        If symbols are provided and differ from currently streaming symbols,
        the stream will be restarted with the new symbol list.
        """
        # Determine the target symbols
        target_symbols = symbols if symbols else (self._config.symbols or [self._config.default_symbol])
        
        # If stream is already running, check if we need to restart with different symbols
        if self._ws_thread and self._ws_thread.is_alive():
            current_symbols = self._config.symbols or [self._config.default_symbol]
            # Compare as sets to ignore order differences
            if set(target_symbols) == set(current_symbols):
                logger.debug("Price stream already running with same symbols, no restart needed")
                return
            
            # Symbols changed - need to restart the stream
            logger.info("Restarting price stream with updated symbols: %s -> %s", current_symbols, target_symbols)
            self._stop_price_stream()

        # Update config with new symbols
        if symbols:
            self._config.symbols = symbols

        active_symbols = self._config.symbols or [self._config.default_symbol]
        
        # Load persisted candles for any new symbols
        if self._candle_store_enabled:
            for symbol in active_symbols:
                self._load_persisted_candles_for_symbol(symbol)
        
        self._ws_stop_event.clear()

        def _on_open(wsapp: WebSocketApp) -> None:
            logger.info("Kraken WebSocket connected (%s)", self._config.ws_public_url)
            sub_ticker = {
                "event": "subscribe",
                "feed": "ticker_lite",
                "product_ids": active_symbols,
            }
            wsapp.send(json.dumps(sub_ticker))

            sub_trade = {
                "event": "subscribe",
                "feed": "trade",
                "product_ids": active_symbols,
            }
            wsapp.send(json.dumps(sub_trade))

        def _on_message(wsapp: WebSocketApp, message: str) -> None:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("Received non-JSON WS message: %s", message)
                return

            feed = data.get("feed")
            if feed == "heartbeat":
                return

            if feed in ("ticker", "ticker_lite"):
                self._handle_ticker_message(data)
            elif feed in ("trade", "trade_snapshot"):
                # trade_snapshot enthält beim Subscribe initiale Trades – identische Struktur
                self._handle_trade_message(data)
            else:
                logger.debug("Unhandled WS feed=%s msg=%s", feed, data)

        def _on_error(wsapp: WebSocketApp, error: Any) -> None:
            if self._ws_stop_event.is_set():
                logger.info("Kraken WebSocket stopped: %s", error)
                return

            logger.error("Kraken WebSocket error: %s", error)

        def _on_close(wsapp: WebSocketApp, status_code: Any, msg: Any) -> None:
            logger.info("Kraken WebSocket closed: code=%s msg=%s", status_code, msg)

        self._ws = WebSocketApp(
            self._config.ws_public_url,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        def _run_ws() -> None:
            while not self._ws_stop_event.is_set():
                try:
                    self._ws.run_forever(ping_interval=30, ping_timeout=10)
                except Exception as ex:
                    logger.exception("Exception in Kraken WS thread: %s", ex)
                if not self._ws_stop_event.is_set():
                    logger.info("Kraken WS reconnect in 5s...")
                    time.sleep(5)

        self._ws_thread = threading.Thread(
            target=_run_ws,
            name="KrakenWS",
            daemon=True,
        )
        self._ws_thread.start()

        logger.info("Kraken WebSocket stream started for symbols=%s", active_symbols)

    def _handle_ticker_message(self, data: Dict[str, Any]) -> None:
        product_id = data.get("product_id") or data.get("symbol")
        if not product_id:
            return

        bid = Decimal(str(data.get("bid", 0.0)))
        ask = Decimal(str(data.get("ask", 0.0)))
        spread = ask - bid

        ts_raw = data.get("time") or data.get("timestamp")
        ts = self._parse_ws_timestamp(ts_raw)

        sp = SymbolPrice(
            epic=product_id,
            market_name=product_id,
            bid=bid,
            ask=ask,
            spread=spread,
            timestamp=ts,
        )

        with self._lock:
            self._price_cache[product_id] = sp

    def _handle_trade_message(self, data: Dict[str, Any]) -> None:
        product_id = data.get("product_id")
        if not product_id:
            return

        trades = data.get("trades") or []
        for trade in trades:
            price = float(trade.get("price", 0.0))
            qty = float(trade.get("qty", 0.0))
            ts_raw = trade.get("time") or trade.get("timestamp") or data.get("time")
            ts = self._parse_ws_timestamp(ts_raw)
            self._update_candle(product_id, price, qty, ts)

    @staticmethod
    def _parse_ws_timestamp(ts_raw: Any) -> datetime:
        if isinstance(ts_raw, (int, float)):
            if ts_raw > 10_000_000_000:  # ms
                return datetime.fromtimestamp(ts_raw / 1000.0, tz=dt_timezone.utc)
            return datetime.fromtimestamp(ts_raw, tz=dt_timezone.utc)
        if isinstance(ts_raw, str):
            try:
                if ts_raw.endswith("Z"):
                    ts_raw = ts_raw[:-1] + "+00:00"
                return datetime.fromisoformat(ts_raw)
            except Exception:
                pass
        return timezone.now()

    # -------------------------------------------------------------------------
    # Candle-Aggregation (1m)
    # -------------------------------------------------------------------------

    def _update_candle(
        self,
        symbol: str,
        price: float,
        volume: float,
        ts: datetime,
    ) -> None:
        minute_bucket = ts.replace(second=0, microsecond=0, tzinfo=dt_timezone.utc)
        bucket_key = int(minute_bucket.timestamp())

        with self._lock:
            cur = self._current_candle.get(symbol)
            if cur is None or cur.get("bucket_key") != bucket_key:
                if cur is not None:
                    self._append_candle_from_raw(symbol, cur)
                cur = {
                    "bucket_key": bucket_key,
                    "time": minute_bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "trade_count": 1,
                }
                self._current_candle[symbol] = cur
            else:
                cur["high"] = max(cur["high"], price)
                cur["low"] = min(cur["low"], price)
                cur["close"] = price
                cur["volume"] += volume
                cur["trade_count"] += 1

    def _append_candle_from_raw(self, symbol: str, candle: Dict[str, Any]) -> None:
        candle_obj = Candle1m(
            symbol=symbol,
            time=candle["time"],
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
            volume=float(candle["volume"]),
            trade_count=int(candle.get("trade_count", 0)),
        )
        
        candles = self._candle_cache.setdefault(symbol, [])
        candles.append(candle_obj)

        # Persist to Redis if enabled
        if self._candle_store_enabled and self._candle_store:
            try:
                # Convert to Candle model for Redis storage
                redis_candle = Candle(
                    timestamp=int(candle_obj.time.timestamp()),
                    open=float(candle_obj.open),
                    high=float(candle_obj.high),
                    low=float(candle_obj.low),
                    close=float(candle_obj.close),
                    volume=float(candle_obj.volume),
                    trade_count=int(candle_obj.trade_count),
                    complete=True,
                )
                self._candle_store.append_candle(
                    asset_id=symbol,
                    timeframe='1m',
                    candle=redis_candle,
                )
            except Exception as e:
                logger.warning(f"Failed to persist candle to Redis: {e}")

        six_hours_ago = timezone.now() - timedelta(hours=6)
        self._candle_cache[symbol] = [
            c for c in candles if c.time >= six_hours_ago
        ]

    def flush_open_candles(self) -> None:
        """Persist candles whose minute has completed even if no new trade arrived."""

        cutoff = timezone.now().astimezone(dt_timezone.utc)
        cutoff_minute = cutoff.replace(second=0, microsecond=0)

        with self._lock:
            stale_symbols: List[str] = []
            for symbol, candle in list(self._current_candle.items()):
                bucket_time: datetime = candle.get("time")
                if bucket_time <= cutoff_minute - timedelta(minutes=1):
                    self._append_candle_from_raw(symbol, candle)
                    stale_symbols.append(symbol)

            for symbol in stale_symbols:
                self._current_candle.pop(symbol, None)

    def _fill_candle_gaps(self, candles: List[Candle1m], symbol: str) -> List[Candle1m]:
        """
        Fill gaps in candle data with zero-volume candles.
        
        For minutes without trades, creates candles with:
        - open = close = high = low = last known close price
        - volume = 0
        - trade_count = 0
        
        This prevents gaps in charts.
        
        Args:
            candles: List of existing candles (sorted by time).
            symbol: Market symbol.
        
        Returns:
            List of candles with gaps filled.
        """
        if not candles:
            return candles
        
        filled = []
        
        for i, candle in enumerate(candles):
            filled.append(candle)
            
            # Check if there's a next candle
            if i + 1 < len(candles):
                next_candle = candles[i + 1]
                current_time = candle.time
                next_time = next_candle.time
                
                # Calculate expected time difference (should be 1 minute)
                expected_next = current_time + timedelta(minutes=1)
                
                # Fill gaps between current and next candle
                fill_time = expected_next
                last_close = candle.close
                
                while fill_time < next_time:
                    # Create a zero-volume candle with last known close price
                    gap_candle = Candle1m(
                        symbol=symbol,
                        time=fill_time,
                        open=last_close,
                        high=last_close,
                        low=last_close,
                        close=last_close,
                        volume=0.0,
                        trade_count=0,
                    )
                    filled.append(gap_candle)
                    
                    # Persist to Redis if enabled
                    if self._candle_store_enabled and self._candle_store:
                        try:
                            redis_candle = Candle(
                                timestamp=int(gap_candle.time.timestamp()),
                                open=float(gap_candle.open),
                                high=float(gap_candle.high),
                                low=float(gap_candle.low),
                                close=float(gap_candle.close),
                                volume=0.0,
                                trade_count=0,
                                complete=True,
                            )
                            self._candle_store.append_candle(
                                asset_id=symbol,
                                timeframe='1m',
                                candle=redis_candle,
                            )
                        except Exception as e:
                            logger.debug(f"Failed to persist gap candle to Redis: {e}")
                    
                    fill_time += timedelta(minutes=1)
        
        return filled

    def get_candles_1m(self, symbol: Optional[str] = None, hours: int = 6) -> List[Candle1m]:
        """
        Get 1-minute candles aggregated from WebSocket trade data.
        
        Kraken does not provide historical OHLC data via API. This method returns
        candles that have been built from real-time trade data received via WebSocket.
        
        Fills gaps with zero-volume candles to prevent chart gaps.
        
        Args:
            symbol: Market symbol (e.g., 'PI_XBTUSD'). Defaults to default_symbol.
            hours: Time window in hours (up to 6 hours are cached).
        
        Returns:
            List of Candle1m objects sorted by time, with gaps filled.
        
        Note:
            The service must be running and receiving WebSocket trade data for candles
            to be available. After startup, it may take time to build up historical data.
        """
        self._ensure_connected()
        self.flush_open_candles()
        symbol = symbol or self._config.default_symbol

        # Calculate cutoff time
        cutoff = timezone.now() - timedelta(hours=hours)

        with self._lock:
            # Get candles from cache
            candles = [c for c in self._candle_cache.get(symbol, []) if c.time >= cutoff]
        
        candles.sort(key=lambda x: x.time)
        
        # Fill gaps with zero-volume candles
        candles = self._fill_candle_gaps(candles, symbol)
        
        return candles

    def get_historical_prices(
        self,
        symbol: Optional[str] = None,
        epic: Optional[str] = None,
        interval: str = "1m",
        num_points: int = 360,
        **_: object,
    ) -> List[dict]:
        """
        Get historical price data (candles) for a market.
        
        Returns candles aggregated from WebSocket trade data. Kraken does not provide
        historical OHLC data via API, so we build candles from real-time trades.
        
        This method provides compatibility with the broker-agnostic market data interface.
        
        Args:
            symbol: Market symbol (e.g., 'PI_XBTUSD').
            epic: Optional alias for symbol for compatibility with other broker interfaces.
            interval: Candle interval ('1m' - only 1m is supported).
            num_points: Number of data points to retrieve (up to 6 hours = 360 candles).
            
        Returns:
            List of price data dictionaries, each containing:
                - time: Unix timestamp in seconds
                - open: Open price
                - high: High price
                - low: Low price
                - close: Close price
                - volume: Trading volume
                
        Raises:
            ConnectionError: If not connected to the broker.
            KrakenBrokerError: If prices cannot be retrieved.
        
        Note:
            Candles are built from WebSocket trade data. The service must be running
            and receiving trade data for candles to be available. Initial startup may
            have limited historical data until candles are aggregated.
        """
        self._ensure_connected()
        self.flush_open_candles()
        
        # Accept both symbol and epic for compatibility with broker-agnostic callers
        symbol = symbol or epic or self._config.default_symbol
        
        # Get candles from cache (built from WebSocket trades)
        with self._lock:
            cached_candles = list(self._candle_cache.get(symbol, []))
            current_candle = self._current_candle.get(symbol)
            
            # Include the current forming candle if available
            if current_candle:
                cached_candles.append(
                    Candle1m(
                        symbol=symbol,
                        time=current_candle["time"],
                        open=float(current_candle["open"]),
                        high=float(current_candle["high"]),
                        low=float(current_candle["low"]),
                        close=float(current_candle["close"]),
                        volume=float(current_candle["volume"]),
                        trade_count=int(current_candle.get("trade_count", 0)),
                    )
                )
        
        # Sort by time
        cached_candles.sort(key=lambda c: c.time)
        
        # Limit to requested number of points
        if num_points and len(cached_candles) > num_points:
            cached_candles = cached_candles[-num_points:]
        
        # Convert to dictionary format expected by market data system
        candles = []
        for c in cached_candles:
            candle = {
                "time": int(c.time.timestamp()),  # Unix timestamp in seconds
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "trade_count": int(c.trade_count),
            }
            candles.append(candle)
        
        return candles

    def get_live_candles_1m(self, symbol: Optional[str] = None) -> List[Candle1m]:
        """
        Liefert 1m-Candles (History + aktuelle laufende Candle).
        Perfekt für das Dashboard (letzte 6h).
        """
        self.flush_open_candles()
        symbol = symbol or self._config.default_symbol
        with self._lock:
            candles = list(self._candle_cache.get(symbol, []))
            cur = self._current_candle.get(symbol)
            if cur:
                candles.append(
                    Candle1m(
                        symbol=symbol,
                        time=cur["time"],
                        open=float(cur["open"]),
                        high=float(cur["high"]),
                        low=float(cur["low"]),
                        close=float(cur["close"]),
                        volume=float(cur["volume"]),
                        trade_count=int(cur.get("trade_count", 0)),
                    )
                )
        candles.sort(key=lambda x: x.time)
        return candles

    def is_candle_store_enabled(self) -> bool:
        """Check if candle persistence to Redis is enabled."""
        return self._candle_store_enabled

    def store_candle_to_redis(self, symbol: str, candle: Candle1m) -> bool:
        """
        Store a single candle to Redis.
        
        Args:
            symbol: Trading symbol
            candle: Candle1m object to store
            
        Returns:
            True if stored successfully, False otherwise
        """
        if not self._candle_store_enabled or not self._candle_store:
            return False
        
        try:
            from core.services.market_data.candle_models import Candle
            
            redis_candle = Candle(
                timestamp=int(candle.time.timestamp()),
                open=float(candle.open),
                high=float(candle.high),
                low=float(candle.low),
                close=float(candle.close),
                volume=float(candle.volume),
                trade_count=int(candle.trade_count),
                complete=True,
            )
            self._candle_store.append_candle(
                asset_id=symbol,
                timeframe='1m',
                candle=redis_candle,
            )
            return True
        except Exception as exc:
            logger.debug(f"Failed to store candle in Redis: {exc}")
            return False

    def fetch_candles_from_charts_api(
        self,
        symbol: str,
        resolution: str = "1m",
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
    ) -> List[Candle1m]:
        """
        Fetch OHLC candle data from Kraken Charts API v1.
        
        This is a public endpoint that provides historical candle data without authentication.
        Endpoint: https://futures.kraken.com/api/charts/v1/trade/:symbol/:resolution
        
        Args:
            symbol: Trading symbol (e.g., 'PI_XBTUSD')
            resolution: Candle resolution ('1m' for 1 minute)
            from_timestamp: Optional start timestamp in milliseconds
            to_timestamp: Optional end timestamp in milliseconds
            
        Returns:
            List of Candle1m objects sorted by time
            
        Raises:
            KrakenBrokerError: If the API request fails
        """
        # Build the URL
        url = f"{self._config.charts_base_url}/trade/{symbol}/{resolution}"
        
        # Add query parameters if provided
        params = {}
        if from_timestamp is not None:
            params['from'] = from_timestamp
        if to_timestamp is not None:
            params['to'] = to_timestamp
        
        try:
            if self._session is None:
                self._session = requests.Session()
            
            response = self._session.get(url, params=params, timeout=15)
            
            if response.status_code >= 400:
                raise KrakenBrokerError(
                    f"Charts API error HTTP {response.status_code} for {url}: {response.text}"
                )
            
            data = response.json()
            
            # Parse the candles from the response
            candles = []
            candles_data = data.get('candles', [])
            
            for candle_data in candles_data:
                # Charts API returns: [timestamp, open, high, low, close, volume]
                if len(candle_data) >= CHARTS_API_EXPECTED_CANDLE_FIELDS:
                    timestamp_ms = int(candle_data[0])
                    timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=dt_timezone.utc)
                    
                    candle = Candle1m(
                        symbol=symbol,
                        time=timestamp_dt,
                        open=float(candle_data[1]),
                        high=float(candle_data[2]),
                        low=float(candle_data[3]),
                        close=float(candle_data[4]),
                        volume=float(candle_data[5]),
                        trade_count=0,  # Charts API doesn't provide trade count
                    )
                    candles.append(candle)
            
            candles.sort(key=lambda c: c.time)
            logger.debug(f"Fetched {len(candles)} candles from Charts API for {symbol}")
            return candles
            
        except requests.exceptions.RequestException as exc:
            raise KrakenBrokerError(f"Failed to fetch candles from Charts API: {exc}") from exc
        except (KeyError, ValueError, IndexError) as exc:
            raise KrakenBrokerError(f"Failed to parse Charts API response: {exc}") from exc

    # -------------------------------------------------------------------------
    # Positionen & Orders
    # -------------------------------------------------------------------------

    def get_open_positions(self) -> List[Position]:
        """
        /openpositions → Liste offener Positionen in vereinfachter Struktur.
        """
        self._ensure_connected()
        payload = self._request(
            "GET",
            "/api/v3/openpositions",
            auth_required=True,
        )

        positions_raw = payload.get("openPositions") or payload.get("positions") or []
        result: List[Position] = []

        for p in positions_raw:
            symbol = p.get("symbol") or p.get("product_id") or self._config.default_symbol
            side = (p.get("side") or p.get("direction") or "").lower()
            direction: Literal["LONG", "SHORT"] = "LONG" if side == "long" else "SHORT"

            size = float(p.get("size", 0.0))
            entry_price = float(p.get("price", p.get("entryPrice", 0.0)))
            pos_id = p.get("uid") or p.get("position_id") or f"{symbol}-{side}-{size}"

            current_price = None
            unrealized_pnl = None

            try:
                sp = self.get_symbol_price(symbol)
                current_price = sp.mark or (sp.bid + sp.ask) / 2.0
            except Exception:
                logger.debug("Could not fetch current price for position %s", pos_id)

            pnl_raw = p.get("pnl")
            if pnl_raw is not None:
                try:
                    unrealized_pnl = float(pnl_raw)
                except Exception:
                    unrealized_pnl = None

            opened_at = None
            opened_raw = p.get("timestamp") or p.get("time")
            if opened_raw is not None:
                opened_at = self._parse_ws_timestamp(opened_raw)

            # Convert direction string to OrderDirection
            order_dir = OrderDirection.BUY if direction == "LONG" else OrderDirection.SELL
            
            result.append(
                Position(
                    position_id=pos_id,
                    deal_id=pos_id,
                    epic=symbol,
                    market_name=symbol,
                    direction=order_dir,
                    size=Decimal(str(size)),
                    open_price=Decimal(str(entry_price)),
                    current_price=Decimal(str(current_price)) if current_price else Decimal('0'),
                    unrealized_pnl=Decimal(str(unrealized_pnl)) if unrealized_pnl else Decimal('0'),
                    currency='USD',
                    created_at=opened_at,
                )
            )

        return result

    def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Place a new order.
        
        Args:
            order: OrderRequest with order details.
        
        Returns:
            OrderResult with deal reference and status.
        """
        self._ensure_connected()

        symbol = order.epic
        side = "buy" if order.direction == OrderDirection.BUY else "sell"

        # Map order type
        if order.order_type == OrderType.MARKET:
            order_type = "mkt"
            limit_price = None
            stop_price = None
        elif order.order_type in (OrderType.LIMIT, OrderType.BUY_LIMIT, OrderType.SELL_LIMIT):
            order_type = "lmt"
            limit_price = order.limit_price
            stop_price = None
        elif order.order_type in (OrderType.STOP, OrderType.BUY_STOP, OrderType.SELL_STOP):
            order_type = "stp"
            limit_price = None
            stop_price = order.stop_price
        else:
            raise KrakenBrokerError(f"Unsupported order type: {order.order_type}")

        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "size": float(order.size),
            "orderType": order_type,
        }

        if limit_price is not None:
            body["limitPrice"] = float(limit_price)
        if stop_price is not None:
            body["stopPrice"] = float(stop_price)

        payload = self._request(
            "POST",
            "/api/v3/sendorder",
            body=body,
            auth_required=True,
        )

        send_status = payload.get("sendStatus") or {}
        status_str = send_status.get("status", "")
        order_id = send_status.get("orderId") or send_status.get("order_id")

        success = status_str in ("placed", "filled", "open")
        message = send_status.get("errorMessage") or status_str or "unknown"
        
        # Map status to OrderStatus enum
        if status_str in ('filled', 'open'):
            status = OrderStatus.OPEN
        elif status_str == 'placed':
            status = OrderStatus.PENDING
        else:
            status = OrderStatus.REJECTED

        return OrderResult(
            success=success,
            deal_id=order_id,
            deal_reference=order_id,
            status=status,
            reason=message if not success else None,
        )

    def close_position(self, position_id: str) -> OrderResult:
        """
        Schliesst eine Position per reduce-only Market-Order (sendorder).
        """
        self._ensure_connected()

        positions = self.get_open_positions()
        pos = next((p for p in positions if p.position_id == position_id), None)
        if pos is None:
            raise KrakenBrokerError(f"Position {position_id} not found")

        side = "sell" if pos.direction == "LONG" else "buy"

        body: Dict[str, Any] = {
            "symbol": pos.symbol,
            "side": side,
            "size": float(pos.size),
            "orderType": "mkt",
            "reduceOnly": True,
        }

        payload = self._request(
            "POST",
            "/sendorder",
            body=body,
            auth_required=True,
        )

        send_status = payload.get("sendStatus") or {}
        status = send_status.get("status", "")
        order_id = send_status.get("orderId") or send_status.get("order_id")

        success = status in ("placed", "filled", "open")
        message = send_status.get("errorMessage") or status or "unknown"

        return OrderResult(
            success=success,
            order_id=order_id,
            status=status,
            message=message,
            raw_response=payload,
        )
