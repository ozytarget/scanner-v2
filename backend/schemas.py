from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ─── Auth ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    email: Optional[EmailStr] = None
    tier: str = "basic"


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    tier: str
    is_active: bool
    daily_calls: int
    max_daily_calls: int
    unlimited: bool
    license_expires: Optional[datetime]
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


Token.model_rebuild()


# ─── Options ──────────────────────────────────────────────────────────────────

class OptionChainParams(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    expiration: Optional[str] = None  # YYYY-MM-DD


class MaxPainResult(BaseModel):
    ticker: str
    expiration: str
    max_pain: float
    strikes: list
    call_oi: list
    put_oi: list


# ─── Screener ─────────────────────────────────────────────────────────────────

class ScreenerParams(BaseModel):
    market_cap_min: Optional[float] = None
    market_cap_max: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = "US"
    volume_min: Optional[int] = None
    limit: int = Field(50, ge=1, le=200)


# ─── Quotes ───────────────────────────────────────────────────────────────────

class QuoteOut(BaseModel):
    symbol: str
    price: float
    change: float
    change_pct: float
    volume: int
    market_cap: Optional[float]
    timestamp: datetime
