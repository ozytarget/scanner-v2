from fastapi import APIRouter, Depends, HTTPException, Query
from backend.services import tradier, options_service
from backend.core.security import get_current_user

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/expirations")
async def expirations(
    ticker: str = Query(..., min_length=1, max_length=10),
    _: dict = Depends(get_current_user),
):
    try:
        dates = await tradier.get_expirations(ticker.upper())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tradier error: {e}")
    if not dates:
        raise HTTPException(status_code=404, detail=f"No expirations found for {ticker}")
    return {"ticker": ticker.upper(), "expirations": dates}


@router.get("/chain")
async def chain(
    ticker: str = Query(...),
    expiration: str = Query(..., description="YYYY-MM-DD"),
    _: dict = Depends(get_current_user),
):
    try:
        options = await tradier.get_option_chain(ticker.upper(), expiration)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tradier error: {e}")
    return {"ticker": ticker.upper(), "expiration": expiration, "options": options}


@router.get("/analysis")
async def analysis(
    ticker: str = Query(...),
    expiration: str = Query(..., description="YYYY-MM-DD"),
    current: dict = Depends(get_current_user),
):
    """Full analysis: max pain, GEX, PCR – the core of Gummy Data Bubbles®."""
    try:
        result = await options_service.get_full_analysis(ticker.upper(), expiration)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.get("/quote")
async def quote(
    ticker: str = Query(...),
    _: dict = Depends(get_current_user),
):
    try:
        q = await tradier.get_quote(ticker.upper())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return q
