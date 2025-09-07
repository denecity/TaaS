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
from contextlib import asynccontextmanager
from typing import Any, Dict, Set, Optional, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from backend.server import Server
from backend.turtle import Turtle
import backend.db_state as db_state
from routines import discover_routines
from routines.base import Routine


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown.
    
    This replaces the deprecated @app.on_event("startup") and @app.on_event("shutdown").
    """
    # Startup
    logger.info("Starting up TaAS application...")
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
        - Launches a background task to collect inventory/label from firmware helpers.
        
        Note: Basic state (coords, heading, fuel) is now handled by turtle.initialize_state()
        in the server connection handler.
        """
        logger.info("on_connect: Turtle %d connected", t.id)
        seen_turtles.add(t.id)
        db_state.upsert_seen(t.id)
        await publish({"type": "connected", "turtle_id": t.id, "turtle": build_turtle_summary(t.id)})
        await publish({"type": "log", "turtle_id": t.id, "level": "INFO", "message": f"Turtle {t.id} connected"})

        async def collect_firmware_state() -> None:
            """Collect firmware-specific state from the turtle.

            Data collected
            - Inventory (via firmware helper `get_inventory_details()`)
            - Name label (via firmware helper `get_name_tag()`)

            Persistence & notifications
            - Writes to `db_state.set_state` and emits a `state_updated` event.

            Dependencies
            - Uses firmware helpers from `firmware/kinsky_turtle.lua`
            """
            try:
                async with t.session() as sess:
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
                    
                    # Store inventory if we got it
                    if inv_json is not None:
                        db_state.set_state(t.id, inventory_json=inv_json)
                    
                    # Store label separately if we got it
                    if label:
                        db_state.set_name_label(t.id, label=label)
                    
                    # Notify clients to refresh state
                    await publish({"type": "state_updated", "turtle_id": t.id, "turtle": build_turtle_summary(t.id)})
            except Exception as e:
                logger.warning("collect_firmware_state failed for turtle %d: %s", t.id, e)
        
        # Launch firmware state collection without blocking
        asyncio.create_task(collect_firmware_state())

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
    logger.info("TaAS application startup complete")
    
    # Yield control to the application
    yield
    
    # Shutdown
    logger.info("Shutting down TaAS application...")
    logger.info("Shutdown: cancelling %d tasks", len(running_tasks))
    for task in list(running_tasks.values()):
        task.cancel()
    await server.stop()
    logger.info("TaAS application shutdown complete")


app = FastAPI(lifespan=lifespan) # Create the FastAPI application instance with custom lifespan management
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow requests from any domain
    allow_credentials=True,  # Allow cookies and authentication headers
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all request headers
)

server = Server() # Initialize the TCP server that manages connections to ComputerCraft turtles

routine_registry: Dict[str, Routine] = discover_routines()
logger.info(f"Discovered {len(routine_registry)} routines: {list(routine_registry.keys())}")

# Track running routine tasks by turtle ID to enable cancellation
running_tasks: Dict[int, asyncio.Task] = {}

# Store current routine assignments (name, status, config) per turtle
assignments: Dict[int, Dict[str, Any]] = {}

# Set of active WebSocket connections for broadcasting events
event_subscribers: set[WebSocket] = set()

# Track turtle IDs that have been seen during this session
seen_turtles: Set[int] = set()







###############################
# SERVER (backend)
###############################

# SERVER: REST endpoint to start executing a routine on a specific turtle
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


# SERVER: REST endpoint to cancel a currently running turtle routine
@app.post("/turtles/{tid}/cancel")
async def cancel_routine(tid: int):
    
    """Cancel a running routine for the given turtle, if any."""
    
    logger.info("POST /turtles/%d/cancel", tid)
    if tid in running_tasks and not running_tasks[tid].done():
        running_tasks[tid].cancel()
        return {"cancelled": True}
    return {"cancelled": False}


# SERVER: Helper function for parsing turtle inventory data from database storage
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


# SERVER: Build comprehensive turtle status summary combining live and stored data
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


# APP: Broadcast events to all connected WebSocket clients
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


# SERVER: REST endpoint to continue/restart the last routine on a turtle
@app.post("/turtles/{tid}/continue")
async def continue_routine(tid: int):
    
    """Re-run the most recent routine for a turtle with its last config."""
    
    logger.info("POST /turtles/%d/continue", tid)
    last = assignments.get(tid)
    if not last or not last.get("routine"):
        raise HTTPException(404, "no previous routine")
    return await run_routine(tid, {"routine": last["routine"], "config": last.get("config")})


# SERVER: REST endpoint to restart/reboot a turtle (placeholder implementation)
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









###############################
# APP (frontend)
###############################

# APP: REST endpoint to list all known turtles with their current status
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


# APP: REST endpoint to get status of a specific turtle
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


# APP: REST endpoint to list all available turtle routines
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


# APP: Helper function for formatting turtle coordinate data for web API responses
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


# APP: WebSocket endpoint for real-time event streaming to web clients
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


# APP: Serve the main web dashboard HTML page
@app.get("/")
def dashboard_root() -> FileResponse:
    
    """Serve the web dashboard entrypoint from `web/static/index.html`."""
    
    return FileResponse("web/static/index.html")


# APP: Serve empty favicon to prevent browser 404 errors
@app.get('/favicon.ico')
def favicon() -> Response:
    
    """Return an empty favicon to avoid 404 noise in logs."""
    
    return Response(content=b"", media_type='image/x-icon')




# Mount static assets for the web UI
app.mount("/static", StaticFiles(directory="web/static"), name="static")


