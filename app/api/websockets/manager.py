"""
Maintains a mapping of auction_id → set of connected WebSocket clients.
Thread-safe enough for a single-process deployment; use Redis Pub/Sub for multi-pod.
"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # auction_id → set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, auction_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[auction_id].add(ws)
        logger.info("WS connected to auction %s (total: %d)", auction_id, len(self._connections[auction_id]))

    async def disconnect(self, auction_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[auction_id].discard(ws)
        logger.info("WS disconnected from auction %s", auction_id)

    async def broadcast_to_auction(self, auction_id: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        dead: list[WebSocket] = []

        for ws in list(self._connections.get(auction_id, [])):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Cleanup dead connections
        async with self._lock:
            for ws in dead:
                self._connections[auction_id].discard(ws)

    async def send_to_connection(self, ws: WebSocket, data: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(data))


# Singleton used across the application
ws_manager = ConnectionManager()