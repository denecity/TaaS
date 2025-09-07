import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

import websockets

import backend.db_state as db_state


class Turtle:
    """Represents a connected turtle. Use `session()` to interact exclusively."""

    # Initialize a new turtle connection with WebSocket and ID
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

    # Handle incoming messages from the turtle and resolve pending requests
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

    # Check if the turtle connection is still alive
    def is_alive(self) -> bool:
        return self._alive
    
    async def initialize_state(self) -> None:
        """Initialize turtle state in database and detect real position."""
        self._logger.info(f"Initializing turtle {self.id} state in database")
        
        # Check if turtle already has state in database
        existing_state = db_state.get_state(self.id)
        if existing_state and existing_state.get("coords") is not None:
            self._logger.info(f"Found existing state for turtle {self.id}, keeping it")
            # Turtle already has state, just try to update with real values
            asyncio.create_task(self._detect_real_state())
            return
        else:
            # Set defaults for new turtle
            self._logger.info(f"No existing state found, setting defaults for turtle {self.id}")
            db_state.set_state(self.id, coords=(0,0,0), heading=0, fuel_level=0)
        
        # Then try to get real values in background
        asyncio.create_task(self._detect_real_state())
    
    async def _detect_real_state(self) -> None:
        """Background task to detect real GPS position and heading."""
        self._logger.info("Detecting real turtle state")
        try:
            async with self.session() as sess:
                # Fuel level detection
                fuel_int = None
                try:
                    fuel = await sess.get_fuel_level()
                    fuel_int = int(fuel) if fuel is not None else None
                except Exception:
                    fuel_int = None
                
                # GPS coordinates detection
                coords_tuple = None
                try:
                    loc = await sess.eval("(function() local x,y,z=gps.locate(2); return x,y,z end)()")
                    if loc is None:
                        self._logger.warning("GPS detection failed: gps.locate() returned None (no GPS hosts available)")
                        coords_tuple = None
                    elif isinstance(loc, list) and len(loc) >= 3 and all(isinstance(v, (int, float)) for v in loc[:3]):
                        x, y, z = int(loc[0]), int(loc[1]), int(loc[2])
                        coords_tuple = (x, y, z)
                        self._logger.info("GPS detected coordinates: %s", coords_tuple)
                    else:
                        self._logger.warning("GPS detection failed: unexpected response format: %s", loc)
                        coords_tuple = None
                except Exception as e:
                    self._logger.warning("GPS detection failed with exception: %s", e)
                    coords_tuple = None
                
                # Heading detection by movement (only if GPS works)
                heading_val = None
                if coords_tuple is not None and coords_tuple != (0, 0, 0):
                    self._logger.info("Attempting heading detection via movement")
                    rotations = 0
                    found_air_dir = None
                    
                    # Find a direction with air to move into
                    self._logger.info("Searching for air direction to move into")
                    for i in range(4):
                        try:
                            ok, _info = await sess.inspect()
                            if not ok:  # Found air
                                found_air_dir = i
                                break
                        except Exception:
                            pass
                        await sess.turn_right()
                        rotations += 1
                    
                    if found_air_dir is not None:
                        try:
                            loc1 = coords_tuple
                            await sess.forward()
                            loc2_list = await sess.eval("(function() local x,y,z=gps.locate(2); return x,y,z end)()")
                            await sess.back()
                            
                            # Restore original rotation
                            for _ in range(rotations):
                                await sess.turn_left()
                            
                            if isinstance(loc2_list, list) and len(loc2_list) >= 3 and all(isinstance(v, (int, float)) for v in loc2_list[:3]):
                                x2, y2, z2 = int(loc2_list[0]), int(loc2_list[1]), int(loc2_list[2])
                                dx, dz = x2 - loc1[0], z2 - loc1[2]
                                if dx == 1 and dz == 0:
                                    heading_val = 0  # +X
                                elif dx == -1 and dz == 0:
                                    heading_val = 2  # -X
                                elif dz == 1 and dx == 0:
                                    heading_val = 1  # +Z
                                elif dz == -1 and dx == 0:
                                    heading_val = 3  # -Z
                                self._logger.info("Heading detected: %s", heading_val)
                        except Exception as e:
                            self._logger.warning("Heading detection movement failed: %s", e)
                            try:
                                # Try to restore rotation on error
                                for _ in range(rotations):
                                    await sess.turn_left()
                            except Exception:
                                pass
                    else:
                        self._logger.info("No air direction found for heading detection")
                else:
                    if coords_tuple is None:
                        self._logger.info("Skipping heading detection: GPS coordinates not available")
                    else:
                        self._logger.info("Skipping heading detection: turtle at origin (0,0,0)")
                
                # Update database with detected values (only update what we successfully detected)
                self._logger.info("Updating turtle state in database")
                updates = {}
                if fuel_int is not None:
                    updates["fuel_level"] = fuel_int
                if coords_tuple is not None:
                    updates["coords"] = coords_tuple
                if heading_val is not None:
                    updates["heading"] = heading_val
                
                if updates:
                    db_state.set_state(self.id, **updates)
                    self._logger.info(f"Updated turtle state: {updates}")
                else:
                    self._logger.info("No state updates detected")
                    
        except Exception as e:
            self._logger.warning(f"Real state detection failed: {e}")

    class _Session:
        # Initialize a new exclusive session with the turtle
        def __init__(self, turtle: "Turtle") -> None:
            self._turtle = turtle
            self._lock_cm = turtle._session_lock
            self._entered = False

        @property
        # Get the turtle instance for this session
        def turtle(self) -> "Turtle":
            return self._turtle

        # Acquire the session lock when entering the context
        async def __aenter__(self) -> "Turtle._Session":
            await self._lock_cm.acquire()
            self._entered = True
            self._turtle._logger.info("session: acquired lock")
            return self

        # Release the session lock when exiting the context
        async def __aexit__(self, exc_type, exc, tb) -> None:
            if self._entered:
                self._lock_cm.release()
                self._entered = False
                self._turtle._logger.info("session: released lock")

        # Send a command to the turtle and wait for response
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
        # Send a command and return whether it succeeded
        async def send_command(self, line: str) -> bool:
            resp = await self._send(line)
            ok = bool(resp.get("ok"))
            self._turtle._logger.info("session: send_command ok=%s", ok)
            return ok

        # Evaluate a Lua expression and return the result
        async def eval(self, line: str) -> Any:
            resp = await self._send(line)
            if not resp.get("ok"):
                self._turtle._logger.error("session: eval failed: %s", resp)
                raise RuntimeError("eval failed")
            self._turtle._logger.info("session: eval value=%s", resp.get("value"))
            return resp.get("value")

        # Get the current state from the database
        def _get_db_state(self) -> Dict[str, Any]:
            try:
                return db_state.get_state(self._turtle.id)
            except Exception:
                return {}

        # Update the turtle's position and fuel in the database
        def _apply_movement(self, dx: int = 0, dy: int = 0, dz: int = 0, fuel_cost: int = 0) -> None:
            st = self._get_db_state()
            coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
            x, y, z = int(coords.get("x") or 0), int(coords.get("y") or 0), int(coords.get("z") or 0)
            x, y, z = x + dx, y + dy, z + dz
            fuel = st.get("fuel_level")
            if isinstance(fuel, int) and fuel_cost:
                fuel = max(0, fuel - fuel_cost)
            db_state.set_state(self._turtle.id, fuel_level=fuel, coords=(x, y, z))

        # Update the turtle's heading in the database
        def _apply_heading(self, delta: int) -> None:
            st = self._get_db_state()
            heading = st.get("heading")
            heading = (heading + delta) % 4
            db_state.set_state(self._turtle.id, heading=heading)

        # Minimal turtle methods
        # Move the turtle forward one block
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
            return ok

        async def back(self) -> bool:
            ok = await self.send_command("turtle.back()")
            if ok:
                st = self._get_db_state()
                heading = st.get("heading")
                if heading == 0:
                    self._apply_movement(dx=-1, fuel_cost=1)
                elif heading == 1:
                    self._apply_movement(dz=-1, fuel_cost=1)
                elif heading == 2:
                    self._apply_movement(dx=1, fuel_cost=1)
                elif heading == 3:
                    self._apply_movement(dz=1, fuel_cost=1)
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

    def session(self) -> "Turtle._Session":
        """Open an exclusive session with this turtle.

        Only one session may be active at a time for the lifetime of the connection.
        """
        return Turtle._Session(self)


 # type: ignore