import asyncio
import json
import logging
import uuid
from functools import wraps
from typing import Any, Dict, Optional, Tuple

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
    
    async def on_connect(self) -> None:
        """Handle turtle connection setup and state management."""
        self._logger.info(f"Turtle {self.id} connected - handling connection setup")
        
        # Set connection status in database
        db_state.set_state(self.id, connection_status="connected")
        
        # Update last seen timestamp  
        db_state.upsert_seen(self.id)
        
        # Initialize turtle state (GPS, fuel, coordinates, heading)
        await self.initialize_state()
    
    async def on_disconnect(self) -> None:
        """Handle turtle disconnection and state cleanup."""
        self._logger.info(f"Turtle {self.id} disconnected - handling disconnection cleanup")
        
        # Set connection status in database
        db_state.set_state(self.id, connection_status="disconnected")
    
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
        """Background task to detect real GPS position, heading, inventory, and label."""
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
                
                # GPS coordinates detection using the session method
                coords_tuple = None
                try:
                    loc = await sess.get_location()
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
                
                # Inventory collection
                try:
                    await sess.get_inventory_details()
                    self._logger.debug("Inventory state collected")
                except Exception as e:
                    self._logger.warning("Inventory collection failed: %s", e)
                
                # Label collection (from firmware if available)
                try:
                    label = await sess.get_label()
                    if label:
                        sess._apply_label(label)
                        self._logger.info(f"Retrieved and stored label from firmware: {repr(label)}")
                except Exception as e:
                    self._logger.debug(f"No label available from firmware: {e}")
                
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
                            loc2_list = await sess.get_location()
                            await sess.back()
                            
                            # Restore original rotation
                            for _ in range(rotations):
                                await sess.turn_left()
                            
                            if isinstance(loc2_list, list) and len(loc2_list) >= 3 and all(isinstance(v, (int, float)) for v in loc2_list[:3]):
                                x2, y2, z2 = int(loc2_list[0]), int(loc2_list[1]), int(loc2_list[2])
                                dx, dz = x2 - loc1[0], z2 - loc1[2]
                                if dx == 1 and dz == 0:
                                    heading_val = (0 - rotations)%4  # +X
                                elif dx == -1 and dz == 0:
                                    heading_val = (2 - rotations)%4  # -X
                                elif dz == 1 and dx == 0:
                                    heading_val = (1 - rotations)%4  # +Z
                                elif dz == -1 and dx == 0:
                                    heading_val = (3 - rotations)%4  # -Z
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

        # Decorator for logging turtle operations with context
        def _log_turtle_operation(func):
            @wraps(func)
            async def wrapper(self, *args, **kwargs):
                operation_name = func.__name__
                self._turtle._logger.info(f"Turtle {self._turtle.id}: {operation_name}")
                
                result = await func(self, *args, **kwargs)
                
                # Log the return value if there is one
                if result is not None:
                    self._turtle._logger.info(f"Turtle {self._turtle.id}: {operation_name} → {result}")
                
                return result
            return wrapper
        
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
                self._turtle._logger.warning("Attempted to send command to disconnected turtle")
                return {"ok": False, "error": "turtle disconnected"}
            
            req_id = f"s_{uuid.uuid4().hex}"
            payload = {"id": req_id, "command": line}
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._turtle._pending[req_id] = fut
            try:
                await self._turtle._ws.send(json.dumps(payload))
                resp = await asyncio.wait_for(fut, timeout=30)
                return resp
            except asyncio.TimeoutError:
                self._turtle._logger.warning("Command timeout: %s", line)
                return {"ok": False, "error": "timeout"}
            except Exception as e:
                self._turtle._logger.warning("Send failed for command '%s': %s", line, e)
                return {"ok": False, "error": str(e)}
            finally:
                self._turtle._pending.pop(req_id, None)

        # Basic helpers (you can extend these later)
        # Send a command and return whether it succeeded
        async def send_command(self, line: str) -> bool:
            resp = await self._send(line)
            ok = bool(resp.get("ok"))
            return ok

        # Evaluate a Lua expression and return the result
        async def eval(self, line: str) -> Any:
            resp = await self._send(line)
            resp_ok = bool(resp.get("ok"))
            if not resp_ok: #means eval returned false
                # Log the full response for debugging
                self._turtle._logger.warning("session: eval command failed: %s, response: %s", line, resp)
                return False
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
            
        # Update the turtle's coordinates in the database from GPS location
        def _apply_location(self, loc: Any) -> None:
            try:
                if loc is None:
                    # GPS returned None - no GPS hosts available
                    return
                
                if isinstance(loc, list) and len(loc) >= 3:
                    # Validate all coordinates are numbers
                    if all(isinstance(v, (int, float)) for v in loc[:3]):
                        x, y, z = int(loc[0]), int(loc[1]), int(loc[2])
                        coords_tuple = (x, y, z)
                        db_state.set_state(self._turtle.id, coords=coords_tuple)
                        self._turtle._logger.debug(f"Updated coordinates to {coords_tuple}")
                    else:
                        self._turtle._logger.warning(f"Invalid GPS coordinates format: {loc}")
                else:
                    self._turtle._logger.warning(f"Unexpected GPS response format: {loc}")
            except Exception as e:
                self._turtle._logger.warning(f"Failed to update location in database: {e}")

        # Update the turtle's label in the database
        def _apply_label(self, label: str) -> None:
            db_state.set_state(self._turtle.id, label=label)

        # Update the turtle's fuel level in the database by querying current fuel
        async def _apply_refuel(self) -> None:
            try:
                current_fuel = await self.get_fuel_level()
                if isinstance(current_fuel, (int, float)):
                    db_state.set_state(self._turtle.id, fuel_level=int(current_fuel))
            except Exception as e:
                self._turtle._logger.warning(f"Failed to update fuel level after refuel: {e}")

        # Update the turtle's inventory in the database
        def _apply_inventory(self, inventory_data: Any) -> None:
            try:
                if inventory_data is not None:
                    import json as _json
                    inventory = _json.dumps(inventory_data)
                    db_state.set_state(self._turtle.id, inventory=inventory)
                    self._turtle._logger.debug(f"Updated inventory for turtle {self._turtle.id}")
            except Exception as e:
                self._turtle._logger.warning(f"Failed to update inventory: {e}")
        
        
        def _evaluate_inspect_return(self, res: Dict[str, Any]) -> Tuple[bool, Any]:
            """Parse inspect result into clean format with predefined tag fields."""
            # Initialize with tags we care about
            result = {
                "name": "unknown",
                "c:ores": False,
                "minecraft:mineable/pickaxe": False,
            }
            
            ok = bool(res.get('ok'))
            if not ok:
                return False, None
                
            raw_data = res.get('data')
            if not raw_data:
                return False, None
                
            # Set the name
            result["name"] = raw_data.get("name", "unknown")
            
            # Fill in tags that exist
            raw_tags = raw_data.get("tags", {})
            for tag in result.keys():
                if tag == "name":
                    continue
                if tag in raw_tags:
                    result[tag] = True
                    
            return ok, result

        def _evaluate_inventory_returns(self, res: Dict[str, Any]) -> Tuple[bool, Any]:
            """Parse inventory result into clean format with predefined tag fields."""
            # Initialize with tags we care about for inventory items
            result = {
                "name": "unknown",
                "displayName": "Unknown",
                "count": 0,
                "c:ores": False,
                "c:gems": False,
                "c:stones": False,
                "c:chests": False,
                "minecraft:building_blocks": False,
            }
            
            ok = bool(res.get('ok'))
            if not ok:
                return False, None
                
            raw_data = res.get('data')
            if not raw_data:
                return False, None
                
            # Set the name, displayName, and count
            result["name"] = raw_data.get("name", "unknown")
            result["displayName"] = raw_data.get("displayName", "Unknown")
            result["count"] = raw_data.get("count", 0)
            
            # Fill in tags that exist
            raw_tags = raw_data.get("tags", {})
            for tag in result.keys():
                if tag in ["name", "displayName", "count"]:
                    continue
                if tag in raw_tags:
                    result[tag] = True
                    
            return ok, result

        # Minimal turtle methods
        # Move the turtle forward one block
        @_log_turtle_operation
        async def forward(self) -> bool:
            # turtle.forward() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.forward()")
            
            # Handle the different return types from turtle.forward()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean (or False from failed eval)
                success = bool(result)
            
            if success:
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
            
            return success

        @_log_turtle_operation
        async def back(self) -> bool:
            # turtle.back() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.back()")
            
            # Handle the different return types from turtle.back()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            if success:
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
            return success

        @_log_turtle_operation
        async def up(self) -> bool:
            # turtle.up() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.up()")
            
            # Handle the different return types from turtle.up()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            if success:
                self._apply_movement(dy=1, fuel_cost=1)
            return success

        @_log_turtle_operation
        async def down(self) -> bool:
            # turtle.down() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.down()")
            
            # Handle the different return types from turtle.down()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            if success:
                self._apply_movement(dy=-1, fuel_cost=1)
            return success

        @_log_turtle_operation
        async def turn_left(self) -> bool:
            ok = await self.send_command("turtle.turnLeft()")
            if ok:
                self._apply_heading(delta=-1)
            return ok

        @_log_turtle_operation
        async def turn_right(self) -> bool:
            ok = await self.send_command("turtle.turnRight()")
            if ok:
                self._apply_heading(delta=1)
            return ok

        @_log_turtle_operation
        async def dig(self) -> bool:
            # turtle.dig() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.dig()")
            
            # Handle the different return types from turtle.dig()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def place(self) -> bool:
            # turtle.place() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.place()")
            
            # Handle the different return types from turtle.place()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def select(self, slot: int) -> bool:
            return await self.send_command(f"turtle.select({int(slot)})")

        @_log_turtle_operation
        async def dig_up(self) -> bool:
            # turtle.digUp() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.digUp()")
            
            # Handle the different return types from turtle.digUp()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def dig_down(self) -> bool:
            # turtle.digDown() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.digDown()")
            
            # Handle the different return types from turtle.digDown()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def place_up(self) -> bool:
            # turtle.placeUp() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.placeUp()")
            
            # Handle the different return types from turtle.placeUp()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def place_down(self) -> bool:
            # turtle.placeDown() returns true on success, false on failure, or [false, reason] on failure with reason
            result = await self.eval("turtle.placeDown()")
            
            # Handle the different return types from turtle.placeDown()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            
            return success

        @_log_turtle_operation
        async def suck(self) -> bool:
            return await self.send_command("turtle.suck()")

        @_log_turtle_operation
        async def suck_up(self) -> bool:
            return await self.send_command("turtle.suckUp()")

        @_log_turtle_operation
        async def suck_down(self) -> bool:
            return await self.send_command("turtle.suckDown()")

        @_log_turtle_operation
        async def drop(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.drop({int(count)})" if count is not None else "turtle.drop()")

        @_log_turtle_operation
        async def drop_up(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.dropUp({int(count)})" if count is not None else "turtle.dropUp()")

        @_log_turtle_operation
        async def drop_down(self, count: int | None = None) -> bool:
            return await self.send_command(f"turtle.dropDown({int(count)})" if count is not None else "turtle.dropDown()")

        @_log_turtle_operation
        async def get_selected_slot(self) -> int:
            return await self.eval("turtle.getSelectedSlot()")

        @_log_turtle_operation
        async def get_item_count(self) -> int:
            return await self.eval("turtle.getItemCount()")

        @_log_turtle_operation
        async def get_item_space(self) -> int:
            return await self.eval("turtle.getItemSpace()")

        @_log_turtle_operation
        async def get_item_detail(self) -> Any:
            result = await self.eval("turtle.getItemDetail()")
            # Process the single item result
            if result:
                # Wrap the result in the expected response format
                item_response = {"ok": True, "data": result}
                ok, processed_item = self._evaluate_inventory_returns(item_response)
                if ok and processed_item:
                    return processed_item
            return result

        @_log_turtle_operation
        async def compare(self) -> bool:
            return await self.send_command("turtle.compare()")

        @_log_turtle_operation
        async def compare_up(self) -> bool:
            return await self.send_command("turtle.compareUp()")

        @_log_turtle_operation
        async def compare_down(self) -> bool:
            return await self.send_command("turtle.compareDown()")

        @_log_turtle_operation
        async def compare_to(self, slot: int) -> bool:
            return await self.send_command(f"turtle.compareTo({int(slot)})")

        @_log_turtle_operation
        async def transfer_to(self, slot: int, count: int | None = None) -> bool:
            if count is None:
                return await self.send_command(f"turtle.transferTo({int(slot)})")
            return await self.send_command(f"turtle.transferTo({int(slot)},{int(count)})")

        @_log_turtle_operation        
        async def get_fuel_level(self) -> Any:
            return await self.eval("turtle.getFuelLevel()")

        @_log_turtle_operation
        async def get_fuel_limit(self) -> int:
            return await self.eval("turtle.getFuelLimit()")

        @_log_turtle_operation
        async def refuel(self, count: int) -> bool:
            # turtle.refuel() returns true on success, false on failure, or (false, reason) on failure with reason
            result = await self.eval(f"turtle.refuel({int(count)})")
            # Handle the different return types from turtle.refuel()
            if isinstance(result, list) and len(result) >= 1:
                # Result is a tuple/array: [false, reason] or [true]
                success = bool(result[0])
            else:
                # Result is a single boolean
                success = bool(result)
            if success:
                # Update database fuel level with actual current fuel
                await self._apply_refuel()
            
            return success

        @_log_turtle_operation
        async def equip_left(self) -> bool:
            return await self.send_command("turtle.equipLeft()")

        @_log_turtle_operation
        async def equip_right(self) -> bool:
            return await self.send_command("turtle.equipRight()")

        @_log_turtle_operation
        async def inspect(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspect(); return {ok=ok, data=data} end)()")
            return self._evaluate_inspect_return(res)

        @_log_turtle_operation
        async def inspect_up(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspectUp(); return {ok=ok, data=data} end)()")
            return self._evaluate_inspect_return(res)

        @_log_turtle_operation
        async def inspect_down(self) -> Any:
            res = await self.eval("(function() local ok,data=turtle.inspectDown(); return {ok=ok, data=data} end)()")
            return self._evaluate_inspect_return(res)

        @_log_turtle_operation            
        async def get_location(self) -> Any:
            loc = await self.eval("gps.locate()")
            # Update database with the new location
            self._apply_location(loc)
            return loc
            

        async def get_inventory_details(self) -> Any:
            """Get inventory details with clean logging and tag filtering."""
            try:
                # Get raw inventory from firmware (list of 16 items, 0-indexed)
                raw_inventory = await self.eval("get_inventory_details()")
                
                # Initialize complete inventory with all 16 slots
                processed_inventory = {}
                for slot in range(1, 17):  # Slots 1-16
                    processed_inventory[slot] = None
                
                # Process items from the list (convert 0-indexed to 1-indexed)
                if isinstance(raw_inventory, list):
                    for i, item in enumerate(raw_inventory):
                        slot = i + 1  # Convert 0-indexed to 1-indexed slots
                        if item is not None:
                            # Wrap item and process through tag filtering
                            item_response = {"ok": True, "data": item}
                            ok, processed_item = self._evaluate_inventory_returns(item_response)
                            if ok and processed_item:
                                processed_item["slot"] = slot
                                processed_inventory[slot] = processed_item
                
                # Save cleaned inventory to database
                self._apply_inventory(processed_inventory)
                
                # Log clean summary with item names and counts
                items_summary = {}
                for item in processed_inventory.values():
                    if item is not None:
                        name = item.get("name", "unknown")
                        count = item.get("count", 0)
                        if name in items_summary:
                            items_summary[name] += count
                        else:
                            items_summary[name] = count
                
                self._turtle._logger.info(f"Turtle {self._turtle.id}: get_inventory_details → {items_summary}")
                
                return processed_inventory
            except Exception as e:
                self._turtle._logger.warning(f"Turtle {self._turtle.id}: get_inventory_details failed: {e}")
                return None

        @_log_turtle_operation            
        async def get_label(self) -> Optional[str]:
            try:
                label = await self.eval("get_name_tag()")
                if label and isinstance(label, (str, int, float)):
                    return str(label)
                return None
            except Exception as e:
                return None

        @_log_turtle_operation
        async def set_label(self, label: str) -> bool:
            # Escape quotes for safe embedding in Lua string
            escaped = label.replace("\\", "\\\\").replace('"', '\\"')
            try:
                result = await self.eval(f'((function() return set_name_tag("{escaped}") end)())')
                # Convert result to boolean
                success = bool(result)
                if success:
                    # Update database state which triggers frontend notification
                    self._apply_label(label)
                return success
            except Exception as e:
                return False

    def session(self) -> "Turtle._Session":
        """Open an exclusive session with this turtle.

        Only one session may be active at a time for the lifetime of the connection.
        """
        return Turtle._Session(self)


 # type: ignore