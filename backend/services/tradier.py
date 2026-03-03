"""Tradier API service – options chains, quotes, expirations."""
import httpx
from typing import Optional
from backend.core.config import get_settings

settings = get_settings()

BASE_URL = "https://api.tradier.com/v1"
SANDBOX_URL = "https://sandbox.tradier.com/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.TRADIER_API_KEY}",
        "Accept": "application/json",
    }


async def get_expirations(ticker: str) -> list[str]:
    url = f"{BASE_URL}/markets/options/expirations"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=_headers(), params={"symbol": ticker})
        r.raise_for_status()
        data = r.json()
    exps = data.get("expirations", {}).get("date", [])
    if isinstance(exps, str):
        exps = [exps]
    return exps or []


async def get_option_chain(ticker: str, expiration: str) -> dict:
    url = f"{BASE_URL}/markets/options/chains"
    params = {
        "symbol": ticker,
        "expiration": expiration,
        "greeks": "true",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        data = r.json()
    options = data.get("options", {}).get("option", [])
    if isinstance(options, dict):
        options = [options]
    return options or []


async def get_quote(ticker: str) -> dict:
    url = f"{BASE_URL}/markets/quotes"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=_headers(), params={"symbols": ticker})
        r.raise_for_status()
        data = r.json()
    quotes = data.get("quotes", {}).get("quote", {})
    return quotes if isinstance(quotes, dict) else {}


async def get_quotes_batch(tickers: list[str]) -> list[dict]:
    url = f"{BASE_URL}/markets/quotes"
    symbols = ",".join(tickers)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=_headers(), params={"symbols": symbols})
        r.raise_for_status()
        data = r.json()
    quotes = data.get("quotes", {}).get("quote", [])
    if isinstance(quotes, dict):
        quotes = [quotes]
    return quotes or []
