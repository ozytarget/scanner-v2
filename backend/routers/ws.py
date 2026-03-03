"""WebSocket endpoint for real-time price streaming via Tradier."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import asyncio
from backend.services.tradier import get_quotes_batch

router = APIRouter(prefix="/api/ws", tags=["websocket"])


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, channel: str):
        await ws.accept()
        self.active.setdefault(channel, []).append(ws)

    def disconnect(self, ws: WebSocket, channel: str):
        if channel in self.active:
            self.active[channel] = [c for c in self.active[channel] if c is not ws]

    async def broadcast(self, channel: str, data: dict):
        dead = []
        for ws in self.active.get(channel, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)


manager = ConnectionManager()


@router.websocket("/prices")
async def price_stream(
    websocket: WebSocket,
    tickers: str = Query("SPY,QQQ,AAPL,TSLA,NVDA"),
    interval: int = Query(5, ge=2, le=60),  # seconds
):
    """
    Stream real-time quotes for a list of tickers.
    Client sends initial handshake; server pushes updates every `interval` seconds.
    """
    await websocket.accept()
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    try:
        while True:
            quotes = await get_quotes_batch(ticker_list)
            await websocket.send_json({"type": "quotes", "data": quotes})
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
