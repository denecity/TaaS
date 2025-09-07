import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import websockets

from backend.turtle_handler import Turtle


OnConnectCallback = Callable[["Turtle"], Awaitable[None]]
OnDisconnectCallback = Callable[[int], Awaitable[None]]


class Server:
    """WebSocket gateway for turtles. Importable and event-driven."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000, *, logger: Optional[logging.Logger] = None) -> None:
        self._host = host
        self._port = port
        self._server: Optional[websockets.Server] = None
        self._clients: Dict[int, Turtle] = {}
        self._logger = (logger or logging.getLogger("gateway")).getChild("server")
        self._on_connect: List[OnConnectCallback] = []
        self._on_disconnect: List[OnDisconnectCallback] = []

    def on_connect(self, cb: OnConnectCallback) -> None:
        self._on_connect.append(cb)

    def on_disconnect(self, cb: OnDisconnectCallback) -> None:
        self._on_disconnect.append(cb)

    async def start(self) -> None:
        self._server = await websockets.serve(self._ws_handler, self._host, self._port, ping_interval=20, ping_timeout=20)
        self._logger.info("listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _ws_handler(self, websocket) -> None:
        self._logger.info("_ws_handler: new connection; waiting for hello")
        # Wait for hello to identify the turtle
        try:
            data = await asyncio.wait_for(websocket.recv(), timeout=10)
            self._logger.info("_ws_handler: received hello frame: %s", data)
            msg = json.loads(data)
        except Exception as e:
            self._logger.warning("_ws_handler: invalid hello: %s", e)
            await websocket.close(code=1002, reason="invalid hello")
            return

        if not isinstance(msg, dict) or msg.get("type") != "hello" or not isinstance(msg.get("computer_id"), int):
            self._logger.warning("_ws_handler: invalid hello payload: %s", msg)
            await websocket.close(code=1002, reason="invalid hello")
            return

        comp_id = int(msg["computer_id"])
        turtle = Turtle(websocket, comp_id, self._logger)
        turtle._start_inbox()
        # Replace any existing mapping for this turtle id
        self._clients[comp_id] = turtle
        self._logger.info("connected turtle id=%s", comp_id)
        for cb in list(self._on_connect):
            try:
                await cb(turtle)
            except Exception as e:
                self._logger.exception("on_connect callback failed: %s", e)

        try:
            # Keep the handler alive while connection is open
            await websocket.wait_closed()
        finally:
            # Cleanup
            self._clients.pop(comp_id, None)
            self._logger.info("disconnected turtle id=%s", comp_id)
            for cb in list(self._on_disconnect):
                try:
                    await cb(comp_id)
                except Exception as e:
                    self._logger.exception("on_disconnect callback failed: %s", e)

    def get_turtle(self, turtle_id: int) -> Optional[Turtle]:
        return self._clients.get(turtle_id)

    def list_turtles(self) -> List[int]:
        return list(self._clients.keys())
