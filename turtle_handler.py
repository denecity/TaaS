import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

import websockets

import db_state


class Turtle:
    """Represents a connected turtle. Use `session()` to interact exclusively."""

    def __init__(self, websocket, computer_id: int, logger: logging.Logger) -> None:
        self._ws = websocket
        self.id: int = computer_id
        self._logger = logger.getChild(f"turtle[{self.id}]")
        self._pending: Dict[str, asyncio.Future] = {}
        self._alive: bool = True
        self._session_lock = asyncio.Lock()
        self._inbox_task: Optional[asyncio.Task] = None

    # Internal: start background inbox processing
    def _start_inbox(self) -> None:
        if self._inbox_task is None or self._inbox_task.done():
            self._inbox_task = asyncio.create_task(self._inbox_loop())

    async def _inbox_loop(self) -> None:
        try:
            async for data in self._ws:
                try:
                    msg = json.loads(data)
                except Exception:
                    continue
                req_id = msg.get("in_reply_to") or msg.get("request_id")
                if req_id:
                    fut = self._pending.pop(str(req_id), None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._alive = False
            # Fail any pending futures
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("turtle disconnected"))
            self._pending.clear()

    def is_alive(self) -> bool:
        return self._alive

    class _Session:
        def __init__(self, turtle: "Turtle") -> None:
            self._turtle = turtle
            self._lock_cm = turtle._session_lock
            self._entered = False

        @property
        def turtle(self) -> "Turtle":
            return self._turtle

        async def __aenter__(self) -> "Turtle._Session":
            await self._lock_cm.acquire()
            self._entered = True
            self._turtle._logger.info("session: acquired lock")
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            if self._entered:
                self._lock_cm.release()
                self._entered = False
                self._turtle._logger.info("session: released lock")

        async def _send(self, line: str) -> Dict[str, Any]:
            if not self._turtle._alive:
                raise RuntimeError("turtle is not connected")
            req_id = f"s_{uuid.uuid4().hex}"
            payload = {"id": req_id, "command": line}
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._turtle._pending[req_id] = fut
            self._turtle._logger.info("session: send id=%s cmd=%s", req_id, line)
            await self._turtle._ws.send(json.dumps(payload))
            try:
                resp = await asyncio.wait_for(fut, timeout=30)
                self._turtle._logger.info("session: recv id=%s resp=%s", req_id, resp)
            finally:
                self._turtle._pending.pop(req_id, None)
            return resp

        # Basic helpers (you can extend these later)
        async def send_command(self, line: str) -> bool:
            resp = await self._send(line)
            ok = bool(resp.get("ok"))
            self._turtle._logger.info("session: send_command ok=%s", ok)
            return ok

        async def eval(self, line: str) -> Any:
            resp = await self._send(line)
            if not resp.get("ok"):
                self._turtle._logger.error("session: eval failed: %s", resp)
                raise RuntimeError("eval failed")
            self._turtle._logger.info("session: eval value=%s", resp.get("value"))
            return resp.get("value")

        def _get_db_state(self) -> Dict[str, Any]:
            try:
                return db_state.get_state(self._turtle.id)
            except Exception:
                return {}

        def _apply_movement(self, dx: int = 0, dy: int = 0, dz: int = 0, fuel_cost: int = 0) -> None:
            st = self._get_db_state()
            coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
            x, y, z = int(coords.get("x") or 0), int(coords.get("y") or 0), int(coords.get("z") or 0)
            x, y, z = x + dx, y + dy, z + dz
            fuel = st.get("fuel_level")
            if isinstance(fuel, int) and fuel_cost:
                fuel = max(0, fuel - fuel_cost)
            db_state.set_state(self._turtle.id, fuel_level=fuel, coords=(x, y, z))

        def _apply_heading(self, delta: int) -> None:
            st = self._get_db_state()
            heading = st.get("heading")
            if isinstance(heading, int):
                heading = (heading + delta) % 4
            else:
                heading = delta % 4
            db_state.set_state(self._turtle.id, heading=heading)

        # Minimal turtle methods
        async def forward(self) -> bool:
            ok = await self.send_command("turtle.forward()")
            if ok:
                # Move along current heading and subtract fuel
                st = self._get_db_state()
                heading = st.get("heading")
                if heading == 0:
                    self._apply_movement(dx=1, fuel_cost=1)
                elif heading == 1:
                    self._apply_movement(dz=1, fuel_cost=1)
                elif heading == 2:
                    self._apply_movement(dx=-1, fuel_cost=1)
                elif heading == 3:
                    self._apply_movement(dz=-1, fuel_cost=1)
                else:
                    # Unknown heading; just reduce fuel
                    self._apply_movement(dx=0, dy=0, dz=0, fuel_cost=1)
            return ok

        async def back(self) -> bool:
            ok = await self.send_command("turtle.back()")
            if ok:
                st = self._get_db_state()
                heading = st.get("heading")
                if heading == 0:
                    self._apply_movement(dx=-1, fuel_cost=0)
                elif heading == 1:
                    self._apply_movement(dz=-1, fuel_cost=0)
                elif heading == 2:
                    self._apply_movement(dx=1, fuel_cost=0)
                elif heading == 3:
                    self._apply_movement(dz=1, fuel_cost=0)
            return ok

        async def up(self) -> bool:
            ok = await self.send_command("turtle.up()")
            if ok:
                self._apply_movement(dy=1, fuel_cost=1)
            return ok

        async def down(self) -> bool:
            ok = await self.send_command("turtle.down()")
            if ok:
                self._apply_movement(dy=-1, fuel_cost=1)
            return ok

        async def turn_left(self) -> bool:
            ok = await self.send_command("turtle.turnLeft()")
            if ok:
                self._apply_heading(delta=-1)
            return ok

        async def turn_right(self) -> bool:
            ok = await self.send_command("turtle.turnRight()")
            if ok:
                self._apply_heading(delta=1)
            return ok

        async def dig(self) -> bool:
            return await self.send_command("turtle.dig()")

        async def place(self) -> bool:
            return await self.send_command("turtle.place()")

        async def select(self, slot: int) -> bool:
            return await self.send_command(f"turtle.select({int(slot)})")

        async def get_fuel_level(self) -> Any:
            return await self.eval("turtle.getFuelLevel()")

        # Additional turtle helpers to match Routine wrappers
        async def dig_up(self) -> bool:
            return await self.send_command("turtle.digUp()")

        async def dig_down(self) -> bool:
            return await self.send_command("turtle.digDown()")

        async def place_up(self) -> bool:
            return await self.send_command("turtle.placeUp()")

        async def place_down(self) -> bool:
            return await self.send_command("turtle.placeDown()")

        async def suck(self) -> bool:
            return await self.send_command("turtle.suck()")

        async def suck_up(self) -> bool:
            return await self.send_command("turtle.suckUp()")

        async def suck_down(self) -> bool:
            return await self.send_command("turtle.suckDown()")

        async def drop(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.drop({int(count)})" if count is not None else "turtle.drop()")

        async def drop_up(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.dropUp({int(count)})" if count is not None else "turtle.dropUp()")

        async def drop_down(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.dropDown({int(count)})" if count is not None else "turtle.dropDown()")

        async def get_selected_slot(self) -> int:
            return await self.eval("turtle.getSelectedSlot()")

        async def get_item_count(self, slot: int | None = None) -> int:
            if slot is None:
                return await self.eval("turtle.getItemCount()")
            return await self.eval(f"turtle.getItemCount({int(slot)})")

        async def get_item_space(self, slot: int | None = None) -> int:
            if slot is None:
                return await self.eval("turtle.getItemSpace()")
            return await self.eval(f"turtle.getItemSpace({int(slot)})")

        async def compare(self) -> bool:
            return await self.send_command("turtle.compare()")

        async def compare_up(self) -> bool:
            return await self.send_command("turtle.compareUp()")

        async def compare_down(self) -> bool:
            return await self.send_command("turtle.compareDown()")

        async def compare_to(self, slot: int) -> bool:
            return await self.send_command(f"turtle.compareTo({int(slot)})")

        async def transfer_to(self, slot: int, count: int | None = None) -> bool:
            if count is None:
                return await self.send_command(f"turtle.transferTo({int(slot)})")
            return await self.send_command(f"turtle.transferTo({int(slot)},{int(count)})")

        async def get_fuel_limit(self) -> int:
            return await self.eval("turtle.getFuelLimit()")

        async def refuel(self, count: int | None = None) -> bool:
            if count is None:
                return await self.send_command("turtle.refuel()")
            return await self.send_command(f"turtle.refuel({int(count)})")

        async def equip_left(self) -> bool:
            return await self.send_command("turtle.equipLeft()")

        async def equip_right(self) -> bool:
            return await self.send_command("turtle.equipRight()")

        async def inspect(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspect(); return {ok=ok, data=data} end)()")
            try:
                return bool(res.get('ok')), res.get('data')
            except Exception:
                return False, None

        async def inspect_up(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspectUp(); return {ok=ok, data=data} end)()")
            try:
                return bool(res.get('ok')), res.get('data')
            except Exception:
                return False, None

        async def inspect_down(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspectDown(); return {ok=ok, data=data} end)()")
            try:
                return bool(res.get('ok')), res.get('data')
            except Exception:
                return False, None
            
        async def get_location(self) -> Any:
            return await self.eval("gps.locate()")

        # The following are optional/custom and may exist in your runtime
        async def get_position(self) -> Any:
            return await self.eval("turtle.getPosition()")

        async def get_facing(self) -> Any:
            return await self.eval("turtle.getFacing()")

        async def get_world_location(self) -> Any:
            return await self.eval("turtle.getWorldLocation()")

    def session(self) -> "Turtle._Session":
        """Open an exclusive session with this turtle.

        Only one session may be active at a time for the lifetime of the connection.
        """
        return Turtle._Session(self)


 # type: ignore