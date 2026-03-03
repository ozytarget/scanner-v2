# SCANNER - Project Notes

## Date: 2026-03-02

## Current State
- Streamlit app (~8700 lines) deployed on Railway (production, running)
- Repo: https://github.com/ozytarget/max-pain-analysis-public.git (branch: main)
- Railway service variables set: FINVIZ_API_TOKEN, FMP_API_KEY, INITIAL_PASSWORDS, KRAKEN_API_KEY, KRAKEN_PRIVATE_KEY, POLYGON_API_KEY, TRADIER_API_KEY

## Bugs Fixed (2026-03-02)
1. Orphan `with tab7:` block removed (was outside any function, crashed on import)
2. Tab 1 indentation fixed (code was running without data guard)
3. IP locking fixed for Railway cloud (uses HTTP_X_FORWARDED_FOR instead of socket.gethostbyname)
4. 4 `@st.cache_data` functions moved from inside main() to module level (cache was invalidated every rerun)
5. `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in market_maker_analyzer.py
6. `daily_range` self-cancelling formula fixed (removed redundant sqrt(252)/sqrt(252))
7. All changes committed and pushed: commit 7434991

## scanner-v2 Migration — Status: IN PROGRESS (2026-03-02)

### Completed
- [x] `backend/` – FastAPI app scaffolded and importing cleanly
  - `backend/main.py` – entry point, CORS, lifespan (DB init on startup)
  - `backend/core/config.py` – pydantic-settings (reads `.env`, no conflict with legacy)
  - `backend/core/security.py` – JWT (python-jose) + bcrypt, `get_current_user` dep
  - `backend/db/database.py` – async SQLAlchemy engine (SQLite dev / PostgreSQL prod via `V2_DATABASE_URL`)
  - `backend/db/models.py` – User, Session, ActivityLog ORM models
  - `backend/schemas.py` – Pydantic v2 request/response schemas
  - `backend/services/tradier.py` – async Tradier client (expirations, chains, quotes)
  - `backend/services/fmp.py` – async FMP client (quotes, screener, analyst, news, history)
  - `backend/services/options_service.py` – Max Pain, GEX, PCR computation (ported from app.py)
  - `backend/services/auth_service.py` – async user CRUD, authenticate, usage tracking
  - `backend/routers/auth.py` – POST /register, POST /login, GET /me
  - `backend/routers/options.py` – GET /expirations, /chain, /analysis, /quote
  - `backend/routers/screener.py` – GET /screener/
  - `backend/routers/news.py` – GET /news/
  - `backend/routers/analyst.py` – GET /analyst/ratings/{ticker}, /price-targets/{ticker}
  - `backend/routers/ws.py` – WS /api/ws/prices (real-time quote streaming)
  - `backend/requirements.txt`
- [x] `frontend/` – Next.js 14 (App Router) scaffolded with 0 TypeScript errors
  - Stack: Next.js + TypeScript + Tailwind CSS dark theme + SWR + Zustand + Axios
  - `frontend/app/login/page.tsx` – Login form with JWT auth
  - `frontend/middleware.ts` – Auth guard (redirect unauthenticated to /login)
  - `frontend/components/Navbar.tsx` – Sticky nav with all 8 tabs + user badge + logout
  - `frontend/lib/api.ts` – Axios client with JWT interceptor + all API calls
  - `frontend/lib/auth.ts` – Zustand auth store (persisted to localStorage)
  - All 8 dashboard pages:
    - `/dashboard/options` – Gummy Data Bubbles® (Max Pain + GEX + OI bar charts)
    - `/dashboard/screener` – Market Scanner (FMP screener with filters)
    - `/dashboard/news` – News feed (auto-refresh 60s)
    - `/dashboard/analyst` – Analyst Rating Flow (ratings + price targets)
    - `/dashboard/elliott` – Elliott Pulse® (placeholder, porting in progress)
    - `/dashboard/metrics` – Metrics (placeholder, porting in progress)
    - `/dashboard/multidate` – Multi-Date Options (placeholder)
    - `/dashboard/calculo` – Options P&L calculator (functional)

### Next Steps
- [ ] Run backend: `uvicorn backend.main:app --reload` from SCANNER root
- [ ] Run frontend: `npm run dev` from `frontend/`
- [ ] Port Elliott Wave detection logic from app.py → backend service
- [ ] Port Metrics/macro tab (VIX, sector heatmap) → backend + frontend
- [ ] Add TradingView Lightweight Charts to options page (candlestick overlay)
- [ ] Create Alembic migrations (`alembic init alembic` in SCANNER root)
- [ ] Deploy v2 to Railway: 2 new services (backend + frontend), set `V2_DATABASE_URL`
- [ ] Admin panel for user management (currently only in Streamlit)
- [ ] Market Maker Analyzer tab (port mm_orchestrator + mm_quant_engine)

## App Structure (Current)
- app.py: Main Streamlit app (8 radio-based tabs)
- user_management.py: Auth system (2 systems: legacy passwords.db + users.db with tiers)
- market_maker_analyzer.py: MM analysis with Tradier API
- mm_quant_engine.py: Quantitative engine for MM
- mm_orchestrator.py: Orchestration layer for MM
- mm_memory.py: Memory/state for MM analysis
- gestor_registro.py: Registration manager

## APIs Used
- Tradier: Options chains, quotes
- FMP (Financial Modeling Prep): Quotes, screener, macro data
- FinViz Elite: Screener export
- yfinance: Fallback for quotes
- Polygon: Market data
- Kraken: Crypto data
