# SCANNER

Repositorio monorepo con dos versiones del sistema de análisis de mercado.

## Estructura

```
SCANNER/
├── streamlit-v1/   ← App original (Streamlit) — desplegada en Railway (en producción)
├── backend/        ← SCANNER v2 API (FastAPI + async SQLAlchemy)
└── frontend/       ← SCANNER v2 UI  (Next.js 14 + Tailwind CSS)
```

## SCANNER v1 — Streamlit (producción actual)
- Directorio: `streamlit-v1/`
- Deploy: Railway → `streamlit-v1/Dockerfile`
- Repo mirror: https://github.com/ozytarget/max-pain-analysis-public

## SCANNER v2 — FastAPI + Next.js
- Directorio: `backend/` + `frontend/`
- Repo: https://github.com/ozytarget/scanner-v2

### Levantar localmente v2

```bash
# Backend
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
# → http://localhost:8000/api/docs

# Frontend
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

### Variables de entorno v2

| Variable | Descripción |
|---|---|
| `TRADIER_API_KEY` | Tradier (opciones, quotes) |
| `FMP_API_KEY` | Financial Modeling Prep |
| `FINVIZ_API_TOKEN` | FinViz Elite |
| `POLYGON_API_KEY` | Polygon.io |
| `SECRET_KEY` | JWT secret (genera uno random) |
| `V2_DATABASE_URL` | PostgreSQL Railway (opcional, SQLite por defecto) |
| `NEXT_PUBLIC_API_URL` | URL del backend v2 (para el frontend) |
