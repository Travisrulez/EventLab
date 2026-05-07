from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active: DefaultDict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, task_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active[task_id].add(websocket)

    def disconnect(self, task_id: int, websocket: WebSocket) -> None:
        self.active[task_id].discard(websocket)
        if not self.active[task_id]:
            self.active.pop(task_id, None)

    async def broadcast(self, task_id: int, payload: dict) -> None:
        stale: list[WebSocket] = []
        for ws in list(self.active.get(task_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(task_id, ws)


manager = ConnectionManager()
