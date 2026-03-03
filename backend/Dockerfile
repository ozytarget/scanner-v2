FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install backend deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/
COPY .env* ./

# Create data dirs
RUN mkdir -p data

EXPOSE 8000

# Railway injects $PORT at runtime — uvicorn must bind to it
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
