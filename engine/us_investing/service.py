"""
us_investing/service.py
=======================
Provider-isolated service interface for US market data.
Swap out YFinanceUSService for any other provider (Polygon, Alpha Vantage, etc.)
without touching routers or scoring logic.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import yfinance as yf

logger = logging.getLogger("fortress.us_investing.service")


class USInvestingService(ABC):
    """Abstract base — defines the contract for any US data provider."""

    @abstractmethod
    def fetch_batch(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """
        Fetch raw metrics for a list of symbols.
        Returns dict keyed by symbol.
        """
        ...

    @abstractmethod
    def fetch_single(self, symbol: str) -> Optional[dict[str, Any]]:
        """Fetch raw metrics for a single symbol."""
        ...

    @abstractmethod
    def get_usd_inr_rate(self) -> float:
        """Return the current USD/INR exchange rate."""
        ...


class YFinanceUSService(USInvestingService):
    """Concrete implementation using Yahoo Finance (yfinance)."""

    def fetch_batch(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            data = self.fetch_single(sym)
            if data:
                result[sym] = data
        return result

    def fetch_single(self, symbol: str) -> Optional[dict[str, Any]]:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            hist = ticker.history(period="1y", interval="1d", auto_adjust=True)
            if isinstance(hist.columns, __import__("pandas").MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            return {
                "info": info,
                "history": hist,
            }
        except Exception as exc:
            logger.debug("YFinance fetch failed for %s: %s", symbol, exc)
            return None

    def get_usd_inr_rate(self) -> float:
        try:
            import yfinance as yf
            data = yf.download("USDINR=X", period="5d", interval="1d", progress=False)
            if not data.empty and "Close" in data.columns:
                val = float(data["Close"].dropna().iloc[-1])
                if 70 < val < 120:   # sanity check
                    return val
        except Exception:
            pass
        return 84.0  # fallback rate


# Module-level default service instance
_default_service: USInvestingService = YFinanceUSService()


def get_service() -> USInvestingService:
    """Return the active data service. Override in tests or alternate providers."""
    return _default_service


def set_service(svc: USInvestingService) -> None:
    """Replace the active service (useful for tests or provider swaps)."""
    global _default_service
    _default_service = svc
