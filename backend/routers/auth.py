from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.database import get_db
from backend.schemas import UserCreate, UserLogin, Token, UserOut
from backend.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.create_user(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return user


@router.post("/login", response_model=Token)
async def login(data: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    await auth_service.log_activity(db, user.id, "login", ip=ip)
    return await auth_service.build_token(user)


@router.get("/me", response_model=UserOut)
async def me(
    current: dict = Depends(__import__("backend.core.security", fromlist=["get_current_user"]).get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from backend.services.auth_service import get_user_by_username
    user = await get_user_by_username(db, current["username"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
