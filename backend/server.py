import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, List, Optional

import websockets

from backend.turtle import Turtle


OnConnectCallback = Callable[["Turtle"], Awaitable[None]]
OnDisconnectCallback = Callable[[int], Awaitable[None]]


class Server:
    """WebSocket gateway for turtles."""

    # Initialize the server object with host and port settings
    def __init__(self, host: str = "0.0.0.0", port: int = 5000) -> None:
        self._host = host
        self._port = port
        self._server: Optional[websockets.Server] = None
        self._clients: Dict[int, Turtle] = {}
        self._logger = logging.getLogger("server")
        self._on_connect: List[OnConnectCallback] = []
        self._on_disconnect: List[OnDisconnectCallback] = []

    # Register a callback function to run when a turtle connects
    def on_connect(self, cb: OnConnectCallback) -> None:
        self._on_connect.append(cb)

    # Register a callback function to run when a turtle disconnects
    def on_disconnect(self, cb: OnDisconnectCallback) -> None:
        self._on_disconnect.append(cb)

    # Start the WebSocket server and begin listening for connections
    async def start(self) -> None:
        self._server = await websockets.serve(self._ws_handler, self._host, self._port, ping_interval=20, ping_timeout=20)
        self._logger.info(f"listening on ws://{self._host}:{self._port}")

    # Stop the WebSocket server and close all connections
    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # Handle incoming WebSocket connections and turtle registration
    async def _ws_handler(self, websocket) -> None:
        # Wait for hello to identify the turtle
        try:
            data = await asyncio.wait_for(websocket.recv(), timeout=10)
            msg = json.loads(data)
        except Exception as e:
            self._logger.warning(f"invalid hello: {e}")
            await websocket.close(code=1002, reason="invalid hello")
            return

        if not isinstance(msg, dict) or msg.get("type") != "hello" or not isinstance(msg.get("computer_id"), int):
            self._logger.warning(f"invalid hello payload: {msg}")
            await websocket.close(code=1002, reason="invalid hello")
            return

        comp_id = int(msg["computer_id"])
        turtle = Turtle(websocket, comp_id, self._logger)
        turtle._start_inbox()
        
        # Initialize turtle state in database
        await turtle.initialize_state()
        
        self._clients[comp_id] = turtle
        self._logger.info(f"connected turtle id={comp_id}")

        for cb in self._on_connect:
            try:
                await cb(turtle)
            except Exception as e:
                self._logger.exception(f"on_connect callback failed: {e}")

        try:
            await websocket.wait_closed()
        finally:
            self._clients.pop(comp_id, None)
            self._logger.info(f"disconnected turtle id={comp_id}")
            for cb in self._on_disconnect:
                try:
                    await cb(comp_id)
                except Exception as e:
                    self._logger.exception(f"on_disconnect callback failed: {e}")

    # Get a specific turtle by its ID
    def get_turtle(self, turtle_id: int) -> Optional[Turtle]:
        return self._clients.get(turtle_id)

    # Get a list of all connected turtle IDs
    def list_turtles(self) -> List[int]:
        return list(self._clients.keys())
