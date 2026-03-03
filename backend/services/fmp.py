"""Financial Modeling Prep (FMP) service."""
import httpx
from typing import Optional
from backend.core.config import get_settings

settings = get_settings()
BASE_URL = "https://financialmodelingprep.com/api"


async def get_quote(ticker: str) -> dict:
    url = f"{BASE_URL}/v3/quote/{ticker}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params={"apikey": settings.FMP_API_KEY})
        r.raise_for_status()
        data = r.json()
    return data[0] if data else {}


async def get_screener(
    market_cap_min: Optional[float] = None,
    market_cap_max: Optional[float] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    country: str = "US",
    volume_min: Optional[int] = None,
    limit: int = 50,
) -> list[dict]:
    url = f"{BASE_URL}/v3/stock-screener"
    params: dict = {
        "apikey": settings.FMP_API_KEY,
        "limit": limit,
        "exchange": "NYSE,NASDAQ,AMEX",
        "country": country,
        "isActivelyTrading": "true",
    }
    if market_cap_min:
        params["marketCapMoreThan"] = int(market_cap_min)
    if market_cap_max:
        params["marketCapLowerThan"] = int(market_cap_max)
    if sector:
        params["sector"] = sector
    if industry:
        params["industry"] = industry
    if volume_min:
        params["volumeMoreThan"] = volume_min

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
    return r.json() or []


async def get_analyst_ratings(ticker: str, limit: int = 20) -> list[dict]:
    url = f"{BASE_URL}/v3/analyst-stock-recommendations/{ticker}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params={"apikey": settings.FMP_API_KEY, "limit": limit})
        r.raise_for_status()
    return r.json() or []


async def get_price_targets(ticker: str) -> list[dict]:
    url = f"{BASE_URL}/v4/price-target"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params={"symbol": ticker, "apikey": settings.FMP_API_KEY})
        r.raise_for_status()
    return r.json() or []


async def get_news(tickers: list[str], limit: int = 20) -> list[dict]:
    symbols = ",".join(tickers) if tickers else "SPY,QQQ"
    url = f"{BASE_URL}/v3/stock_news"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            url, params={"tickers": symbols, "limit": limit, "apikey": settings.FMP_API_KEY}
        )
        r.raise_for_status()
    return r.json() or []


async def get_historical_prices(ticker: str, days: int = 365) -> list[dict]:
    url = f"{BASE_URL}/v3/historical-price-full/{ticker}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"apikey": settings.FMP_API_KEY, "timeseries": days})
        r.raise_for_status()
        data = r.json()
    return data.get("historical", [])
