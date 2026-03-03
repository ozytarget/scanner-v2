"""SCANNER v2 – FastAPI backend entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.core.config import get_settings
from backend.db.database import init_db
from backend.routers import auth, options, screener, news, analyst, ws

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup/shutdown tasks."""
    await init_db()
    yield


app = FastAPI(
    title="SCANNER v2 API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ─── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(options.router)
app.include_router(screener.router)
app.include_router(news.router)
app.include_router(analyst.router)
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
