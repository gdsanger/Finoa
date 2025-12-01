import logging
from datetime import datetime, timezone
from typing import List, Optional

import requests

from core.services.strategy.models import Candle

from .mexc_broker_service import MexcBrokerService


logger = logging.getLogger(__name__)


class MexcMarketDataError(Exception):
    """Error raised when MEXC market data cannot be retrieved."""


class MexcMarketDataFetcher:
    """Fetch OHLCV data from the MEXC Kline API."""

    def __init__(
        self,
        base_url: str = MexcBrokerService.DEFAULT_BASE_URL,
        timeout: int = 10,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()

    def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 2,
    ) -> List[Candle]:
        """Return recent klines as Candle objects ordered oldest to newest."""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        url = f"{self._base_url}/api/v3/klines"

        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch klines from MEXC: %s", exc)
            raise MexcMarketDataError(f"Failed to fetch klines for {symbol}") from exc

        data = response.json()

        candles: List[Candle] = []
        for kline in data:
            open_time_ms = kline[0]
            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc),
                    open=float(kline[1]),
                    high=float(kline[2]),
                    low=float(kline[3]),
                    close=float(kline[4]),
                    volume=float(kline[5]),
                )
            )

        return candles
