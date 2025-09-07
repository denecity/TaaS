"""HTTP/WebSocket orchestrator for ComputerCraft turtles.

This module exposes a FastAPI app that:
- Serves a small web UI from `web/static/`.
- Provides REST endpoints for inspecting turtles and launching routines.
- Publishes server/routine logs and state updates over a WebSocket stream.

Key project dependencies and collaborators:
- `server.Server` (in `server.py`) manages TCP connections to turtles and emits
    connect/disconnect events. It exposes `get_turtle()` and `list_turtles()`.
- `turtle_handler.Turtle` encapsulates a single turtle connection and provides
    an async `session()` with high-level movement/eval helpers.
- `db_state` persists last-seen timestamps and per-turtle state such as fuel,
    inventory, coordinates, heading, and label in `data/turtles.db`.
- `routines` package (`routines/*.py`) registers runnable behaviors that can be
    triggered per turtle via the `/turtles/{tid}/run` endpoint.

External libraries:
- FastAPI/Starlette for HTTP & WebSocket handling.
- PyYAML for optional YAML config parsing.

The app is started by an ASGI server (e.g. `uvicorn`) pointing at `app:app`.
"""

import asyncio
import logging
import json
import re
import traceback
from typing import Any, Dict, Set, Optional, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from backend.server import Server
from backend.turtle_handler import Turtle
import backend.db_state as db_state
from routines import discover_routines
from routines.base import Routine


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("orchestrator")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

server = Server()
routine_registry: Dict[str, Routine] = discover_routines()
logger.info("Discovered routines: %s", list(routine_registry.keys()))
running_tasks: Dict[int, asyncio.Task] = {}
assignments: Dict[int, Dict[str, Any]] = {}
event_subscribers: set[WebSocket] = set()
seen_turtles: Set[int] = set()


def _coords_to_obj(val: Any) -> Optional[Dict[str, int]]:
    """Convert a sequence of 3 numbers into a coordinates dict.

    Parameters
    - val: Any value expected to be a list/tuple like ``[x, y, z]``.

    Returns
    - dict with keys ``{"x", "y", "z"}`` if convertible, else ``None``.

    Context
    - Used when shaping data persisted by `db_state` into API-friendly output
      for clients (see `build_turtle_summary`).
    """
    try:
        if isinstance(val, (list, tuple)) and len(val) >= 3:
            x, y, z = int(val[0]), int(val[1]), int(val[2])
            return {"x": x, "y": y, "z": z}
    except Exception:
        pass
    return None


def _parse_inventory_json(inv_val: Any) -> Any:
        """Parse inventory JSON string into a Python object if applicable.

        Parameters
        - inv_val: Value stored under the "inventory" key in `db_state`.

        Returns
        - Parsed Python object if ``inv_val`` is a JSON string, ``None`` if
            parsing fails, or the original value if already structured.

        Context
        - Inventory snapshots are stored via `db_state.set_state` by
            `startup() -> collect_and_store_state()` using firmware helpers defined
            in `firmware/kinsky_turtle.lua`.
        """
        if isinstance(inv_val, str):
                try:
                        return json.loads(inv_val)
                except Exception:
                        return None
        return inv_val


def build_turtle_summary(tid: int) -> Dict[str, Any]:
        """Build a summarized view of a turtle for API responses.

        Parameters
        - tid: Turtle id.

        Returns
        - Dict containing connectivity, assignment, last seen, fuel, inventory,
            coords, heading, and label.

        Context
        - Reads live state from `server.Server` and persisted state from
            `db_state` (SQLite). Used by list endpoints and WebSocket events.
        """
        t = server.get_turtle(tid)
        alive = bool(t and t.is_alive())
        st = db_state.get_state(tid)
        last_seen_map = db_state.get_last_seen_map()
        inv = _parse_inventory_json(st.get("inventory"))
        coords_obj = _coords_to_obj(st.get("coords"))
        return {
                "id": tid,
                "alive": alive,
                "assignment": assignments.get(tid),
                "last_seen_ms": last_seen_map.get(tid, 0),
                "fuel_level": st.get("fuel_level"),
                "inventory": inv,
                "coords": coords_obj,
                "heading": st.get("heading"),
                "label": st.get("label"),
        }


async def publish(event: Dict[str, Any]) -> None:
    """Broadcast an event to all connected WebSocket subscribers.

    Parameters
    - event: JSON-serializable payload.

    Notes
    - Removes dead subscribers on send failures.
    - Used by lifecycle hooks, routine execution, and state updates.
    """
    try:
        dead = []
        for ws in list(event_subscribers):
            try:
                # Time-bound to avoid blocking under backpressure
                await asyncio.wait_for(ws.send_json(event), timeout=0.2)
            except Exception as e:
                logger.debug("publish: send failed, marking subscriber dead: %s", e)
                dead.append(ws)
        for ws in dead:
            try:
                event_subscribers.remove(ws)
            except KeyError:
                pass
        if dead:
            logger.info("publish: removed %d dead subscribers", len(dead))
    except Exception as e:
        logger.error("publish: unexpected error: %s", e)


@app.on_event("startup")
async def startup() -> None:
    """Initialize persistent state, logging, and the turtle server.

    What happens
    - Initializes the SQLite DB via `db_state.init()`.
    - Installs a logging handler that forwards logs to `/events` subscribers.
    - Registers connection lifecycle callbacks with `server.Server` and starts
      its background task.

    Cross-file dependencies
    - Uses `server.Server`, `turtle_handler.Turtle`, `db_state`, and firmware
      helpers invoked through turtle sessions.
    """
    db_state.init()

    # Forward routine and app logs to websocket subscribers
    class WebLogHandler(logging.Handler):
        """Root logger handler that mirrors log records to WebSocket clients.

        Context
        - Created during app startup and attached to the root logger. Forwards
          most log messages as `{type: "log", ...}` events via `publish()`.
        """

        def emit(self, record: logging.LogRecord) -> None:
            """Format and forward a single log record to subscribers.

            - Filters out noisy HTTP route logs that would spam clients.
            - Also tries to parse a turtle id from messages like "Turtle 3 ...".
            """
            try:
                msg = self.format(record)
                # Drop noisy HTTP route logs from being broadcast
                if msg.startswith("GET /turtles") or msg.startswith("GET /routines"):
                    return
                tid: int | None = None
                m = re.search(r"Turtle\s+(\d+)", msg)
                if m:
                    tid = int(m.group(1))
                loop = asyncio.get_running_loop()
                loop.create_task(publish({
                    "type": "log",
                    "turtle_id": tid,
                    "level": record.levelname,
                    "message": msg,
                }))
            except Exception:
                pass

    handler = WebLogHandler()
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)

    async def on_connect(t: Turtle) -> None:
        """Server callback when a turtle connects.

        Side effects
        - Marks turtle as seen in `db_state` and publishes events.
        - Launches a background task to collect fuel/inventory/coords/heading
          via the turtle session APIs and persists them with `db_state`.
        """
        logger.info("on_connect: Turtle %d connected", t.id)
        seen_turtles.add(t.id)
        db_state.upsert_seen(t.id)
        await publish({"type": "connected", "turtle_id": t.id, "turtle": build_turtle_summary(t.id)})
        await publish({"type": "log", "turtle_id": t.id, "level": "INFO", "message": f"Turtle {t.id} connected"})

        async def collect_and_store_state() -> None:
            """Collect live state from the turtle and persist it.

            Data collected
            - Fuel level, inventory (via firmware helper), name label, GPS
              coordinates, and inferred heading.

            Persistence & notifications
            - Writes to `db_state.set_state` and emits a `state_updated` event.

            Dependencies
            - Requires GPS availability on the turtle for coords/heading.
            - Uses firmware helpers `get_inventory_details()` and
              `get_name_tag()` from `firmware/kinsky_turtle.lua` (called via
              `sess.eval`).
            """
            try:
                async with t.session() as sess:
                    # Fuel
                    try:
                        fuel = await sess.get_fuel_level()
                        fuel_int = int(fuel) if fuel is not None else None
                    except Exception:
                        fuel_int = None
                    # Inventory (firmware helper)
                    inv_json: Optional[str] = None
                    try:
                        inv = await sess.eval("get_inventory_details()")
                        import json as _json
                        inv_json = _json.dumps(inv)
                    except Exception:
                        inv_json = None
                    # Name / label
                    label = None
                    try:
                        label = await sess.eval("get_name_tag()")
                        if isinstance(label, (int, float)):
                            label = str(label)
                    except Exception:
                        label = None
                    if label:
                        db_state.set_name_label(t.id, label=label)
                    # Coords by GPS
                    coords_tuple: Optional[Tuple[int, int, int]] = None
                    try:
                        loc = await sess.eval("(function() local x,y,z=gps.locate(2); return x,y,z end)()")
                        if isinstance(loc, list) and len(loc) >= 3 and all(isinstance(v, (int, float)) for v in loc[:3]):
                            x, y, z = int(loc[0]), int(loc[1]), int(loc[2])
                            coords_tuple = (x, y, z)
                    except Exception:
                        coords_tuple = None
                    if coords_tuple is None:
                        coords_tuple = (0, 0, 0)
                    # Heading by probing forward into air (requires GPS)
                    heading_val: Optional[int] = None
                    if coords_tuple != (0, 0, 0):
                        rotations = 0
                        found_air_dir: Optional[int] = None
                        for i in range(4):
                            try:
                                ok, _info = await sess.inspect()
                                if not ok:
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
                            except Exception:
                                try:
                                    for _ in range(rotations):
                                        await sess.turn_left()
                                except Exception:
                                    pass
                    # Store
                    db_state.set_state(t.id, fuel_level=fuel_int, inventory_json=inv_json, coords=coords_tuple, heading=heading_val)
                    # Notify clients to refresh state (label/coords/heading)
                    await publish({"type": "state_updated", "turtle_id": t.id, "turtle": build_turtle_summary(t.id)})
            except Exception as e:
                logger.warning("collect_and_store_state failed for turtle %d: %s", t.id, e)
        # launch without blocking
        asyncio.create_task(collect_and_store_state())

    async def on_disconnect(tid: int) -> None:
        """Server callback when a turtle disconnects.

        - Publishes a disconnected event and marks any running routine as
          paused/ended in the in-memory assignments.
        """
        logger.info("on_disconnect: Turtle %d disconnected", tid)
        await publish({"type": "disconnected", "turtle_id": tid, "turtle": build_turtle_summary(tid)})
        await publish({"type": "log", "turtle_id": tid, "level": "INFO", "message": f"Turtle {tid} disconnected"})
        if tid in running_tasks and not running_tasks[tid].done():
            running_tasks[tid].cancel()
        if tid in assignments:
            assignments[tid]["status"] = "disconnected"

    server.on_connect(on_connect)
    server.on_disconnect(on_disconnect)
    logger.info("Starting Server() background task")
    await server.start()
    # Web UI is served as static assets; no UI framework initialization needed.


@app.on_event("shutdown")
async def shutdown() -> None:
    """Stop background tasks and the turtle server cleanly."""
    logger.info("Shutdown: cancelling %d tasks", len(running_tasks))
    for task in list(running_tasks.values()):
        task.cancel()
    await server.stop()


@app.get("/turtles")
def list_turtles():
    """List all known turtles with summarized state.

    Source of truth
    - Union of ids from `db_state.list_all_ids()`, currently connected turtles
      from `server.list_turtles()`, and an in-memory set of `seen_turtles`.
    - Each turtle is shaped via `build_turtle_summary`.
    """
    logger.debug("GET /turtles")
    # Use DB-known turtles plus currently connected
    try:
        all_known = set(db_state.list_all_ids())
    except Exception:
        all_known = set()
    connected_now = set(server.list_turtles())
    ids = sorted(all_known | connected_now | set(seen_turtles))
    return [build_turtle_summary(tid) for tid in ids]


@app.get("/turtles/{tid}")
def turtle_status(tid: int):
    """Return liveness and assignment status for a connected turtle.

    Raises
    - 404 if the turtle is not currently connected per `server.get_turtle()`.
    """
    logger.debug("GET /turtles/%d", tid)
    t = server.get_turtle(tid)
    if not t:
        raise HTTPException(404, "turtle not connected")
    return {"id": tid, "alive": t.is_alive(), "assignment": assignments.get(tid)}


@app.get("/routines")
def list_routines():
    """Enumerate registered routines from the `routines` package.

    Returns name, description, and a config template for each routine.
    """
    logger.debug("GET /routines -> %d routines", len(routine_registry))
    out = []
    for name, routine in routine_registry.items():
        out.append({
            "name": name,
            "description": routine.description,
            "config_template": routine.config_template,
        })
    return out


@app.post("/turtles/{tid}/run")
async def run_routine(tid: int, body: Dict[str, Any]):
    """Start a routine on a turtle.

    Body
    - routine: str, key of a routine in the registry
    - config: dict|string, optional; if string, YAML or JSON will be parsed

    Behavior
    - Cancels a previous routine for the same turtle if still running.
    - Spawns an async task to run `routine.run(turtle, config)`.
    - Emits `routine_started`/`finished`/`paused`/`failed` events via WebSocket.

    Dependencies
    - Uses `routines/*` implementations and `turtle_handler.Turtle` session.
    - Optional YAML parsing via `PyYAML`.
    """
    logger.info("POST /turtles/%d/run body=%s", tid, body)
    name = body.get("routine")
    routine = routine_registry.get(name)
    if not routine:
        raise HTTPException(404, "unknown routine")
    t = server.get_turtle(tid)
    if not t or not t.is_alive():
        raise HTTPException(404, "turtle not connected")
    if tid in running_tasks and not running_tasks[tid].done():
        logger.info("Cancelling previous routine for turtle %d", tid)
        running_tasks[tid].cancel()

    # Parse config: allow YAML or JSON strings, or dict directly
    cfg_raw = body.get("config")
    cfg_parsed: Any = None
    if isinstance(cfg_raw, dict):
        cfg_parsed = cfg_raw
    elif isinstance(cfg_raw, str):
        txt = cfg_raw.strip()
        if txt:
            try:
                import yaml  # type: ignore
                cfg_parsed = yaml.safe_load(txt)
                logger.info("Parsed config as YAML: %s", cfg_parsed)
            except Exception:
                try:
                    cfg_parsed = json.loads(txt)
                    logger.info("Parsed config as JSON: %s", cfg_parsed)
                except Exception:
                    logger.info("Config parsing failed; passing raw text")
                    cfg_parsed = txt  # pass raw text if parsing fails
    logger.info("Using config: type=%s value=%s", type(cfg_parsed).__name__, cfg_parsed)

    # Record assignment with config
    assignments[tid] = {"routine": name, "status": "running", "config": cfg_parsed}

    async def _runner():
        """Wrapper task that executes the routine and sends lifecycle events."""
        try:
            asyncio.create_task(publish({"type": "routine_started", "turtle_id": tid, "routine": name}))
            await routine.run(t, cfg_parsed)
            assignments[tid]["status"] = "finished"
            asyncio.create_task(publish({"type": "routine_finished", "turtle_id": tid, "routine": name}))
        except asyncio.CancelledError:
            assignments[tid]["status"] = "paused"
            asyncio.create_task(publish({"type": "routine_paused", "turtle_id": tid, "routine": name}))
            raise
        except Exception as e:
            assignments[tid]["status"] = "failed"
            err_text = f"{e}\n{traceback.format_exc()}"
            logger.error("Routine '%s' failed for turtle %d: %s", name, tid, err_text)
            asyncio.create_task(publish({"type": "routine_failed", "turtle_id": tid, "routine": name, "error": err_text}))

    running_tasks[tid] = asyncio.create_task(_runner())
    return {"accepted": True}


@app.post("/turtles/{tid}/cancel")
async def cancel_routine(tid: int):
    
    """Cancel a running routine for the given turtle, if any."""
    
    logger.info("POST /turtles/%d/cancel", tid)
    if tid in running_tasks and not running_tasks[tid].done():
        running_tasks[tid].cancel()
        return {"cancelled": True}
    return {"cancelled": False}


@app.websocket("/events")
async def events(ws: WebSocket):
    
    """WebSocket endpoint that streams server logs and state/routine events.

    Protocol
    - Server only sends push events; any client text messages are treated as
        keep-alives and ignored.
    - See callers of `publish()` for event shapes.
    """
    
    logger.info("/events: client connecting")
    await ws.accept()
    event_subscribers.add(ws)
    logger.info("/events: connected; subscribers=%d", len(event_subscribers))
    try:
        while True:
            # Keep-alive or client-sent input (ignored)
            msg = await ws.receive_text()
            logger.debug("/events: received from client: %s", msg)
    except WebSocketDisconnect:
        logger.info("/events: client disconnected")
    finally:
        event_subscribers.discard(ws)
        logger.info("/events: removed subscriber; subscribers=%d", len(event_subscribers))


@app.post("/turtles/{tid}/continue")
async def continue_routine(tid: int):
    
    """Re-run the most recent routine for a turtle with its last config."""
    
    logger.info("POST /turtles/%d/continue", tid)
    last = assignments.get(tid)
    if not last or not last.get("routine"):
        raise HTTPException(404, "no previous routine")
    return await run_routine(tid, {"routine": last["routine"], "config": last.get("config")})


@app.post("/turtles/{tid}/restart")
async def restart_turtle(tid: int):
    
    """Placeholder endpoint to request a turtle restart.

    Note: Currently a no-op beyond validating connectivity and opening a
    session. Future implementations could send a reboot command.
    """
    
    logger.info("POST /turtles/%d/restart", tid)
    t = server.get_turtle(tid)
    if not t or not t.is_alive():
        raise HTTPException(404, "turtle not connected")
    async with t.session() as sess:
        pass
    return {"accepted": True}


@app.get("/", include_in_schema=False)
def dashboard_root() -> FileResponse:
    
    """Serve the web dashboard entrypoint from `web/static/index.html`."""
    
    return FileResponse("web/static/index.html")


@app.get('/favicon.ico', include_in_schema=False)
def favicon() -> Response:
    
    """Return an empty favicon to avoid 404 noise in logs."""
    
    return Response(content=b"", media_type='image/x-icon')

# Mount static assets for the web UI
app.mount("", StaticFiles(directory="web"), name="static")


