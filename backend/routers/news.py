from fastapi import APIRouter, Depends, Query
from backend.services import fmp
from backend.core.security import get_current_user

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/")
async def get_news(
    tickers: str = Query("SPY,QQQ", description="Comma-separated tickers"),
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_user),
):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    return await fmp.get_news(ticker_list, limit=limit)
