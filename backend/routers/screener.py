from fastapi import APIRouter, Depends, Query
from typing import Optional
from backend.services import fmp
from backend.core.security import get_current_user

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/")
async def screener(
    market_cap_min: Optional[float] = Query(None),
    market_cap_max: Optional[float] = Query(None),
    sector: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    country: str = Query("US"),
    volume_min: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: dict = Depends(get_current_user),
):
    return await fmp.get_screener(
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        sector=sector,
        industry=industry,
        country=country,
        volume_min=volume_min,
        limit=limit,
    )
