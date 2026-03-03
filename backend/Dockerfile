FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Railway sets Root Directory = backend/
# All paths are relative to backend/ folder
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./backend/

RUN mkdir -p data

EXPOSE 8000

# Railway injects $PORT at runtime
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
