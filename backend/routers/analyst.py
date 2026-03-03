from fastapi import APIRouter, Depends, Query
from backend.services import fmp
from backend.core.security import get_current_user

router = APIRouter(prefix="/api/analyst", tags=["analyst"])


@router.get("/ratings/{ticker}")
async def ratings(
    ticker: str,
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_user),
):
    return await fmp.get_analyst_ratings(ticker.upper(), limit=limit)


@router.get("/price-targets/{ticker}")
async def price_targets(
    ticker: str,
    _: dict = Depends(get_current_user),
):
    return await fmp.get_price_targets(ticker.upper())
