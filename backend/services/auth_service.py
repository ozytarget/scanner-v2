"""Auth service – user CRUD with async SQLAlchemy."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from backend.db.models import User, ActivityLog, Session as DBSession
from backend.core.security import hash_password, verify_password, create_access_token
from backend.schemas import UserCreate


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    existing = await get_user_by_username(db, data.username)
    if existing:
        raise ValueError(f"Username '{data.username}' already exists")
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        tier=data.tier,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[User]:
    user = await get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    # Update last_login
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(last_login=datetime.now(timezone.utc))
    )
    await db.commit()
    await db.refresh(user)
    return user


async def build_token(user: User) -> dict:
    token = create_access_token({"sub": user.username, "tier": user.tier})
    return {"access_token": token, "token_type": "bearer", "user": user}


async def log_activity(db: AsyncSession, user_id: int, action: str, detail: str = "", ip: str = "") -> None:
    log = ActivityLog(user_id=user_id, action=action, detail=detail, ip_address=ip)
    db.add(log)
    await db.commit()


async def check_and_increment_usage(db: AsyncSession, user: User) -> bool:
    """Returns False if user has hit daily limit."""
    if user.unlimited or user.tier == "admin":
        return True
    if user.daily_calls >= user.max_daily_calls:
        return False
    await db.execute(
        update(User).where(User.id == user.id).values(daily_calls=User.daily_calls + 1)
    )
    await db.commit()
    return True


async def get_all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars().all())
