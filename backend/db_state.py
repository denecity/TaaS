import os
import sqlite3
import time
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable
from pathlib import Path


# Use project-relative data directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "turtles.db"

logger = logging.getLogger("db_state")

# Global change notification callback - set by main.py
_change_callback: Optional[Callable[[int], Awaitable[None]]] = None
_change_loop: Optional[asyncio.AbstractEventLoop] = None


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    conn = _conn()
    cur = conn.cursor()
    # Unified turtles table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS turtles (
            turtle_id INTEGER PRIMARY KEY,
            name TEXT,
            label TEXT,
            first_seen_ms INTEGER,
            last_seen_ms INTEGER,
            fuel_level INTEGER,
            inventory TEXT,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            heading INTEGER,
            connection_status TEXT DEFAULT 'disconnected'
        )
        """
    )
    # Add connection_status column if it doesn't exist (for existing databases)
    try:
        cur.execute("ALTER TABLE turtles ADD COLUMN connection_status TEXT DEFAULT 'disconnected'")
        logger.info("Added connection_status column to existing database")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turtles_last_seen ON turtles(last_seen_ms)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turtles_connection ON turtles(connection_status)")
    # Function calls audit table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS function_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER,
            turtle_id INTEGER,
            call_name TEXT,
            args_json TEXT,
            ok INTEGER,
            result_json TEXT,
            error_text TEXT,
            request_id TEXT,
            duration_ms INTEGER
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_calls_turtle ON function_calls(turtle_id, ts_ms)")
    conn.commit()
    conn.close()


def set_change_callback(callback: Callable[[int], Awaitable[None]], loop: asyncio.AbstractEventLoop) -> None:
    """Set the callback function to be called when turtle state changes.
    
    Parameters:
    - callback: Async function that takes a turtle_id and publishes state_updated events
    - loop: The asyncio event loop to schedule the callback on
    """
    global _change_callback, _change_loop
    _change_callback = callback
    _change_loop = loop
    logger.info("Database change callback registered")


def _notify_change(turtle_id: int) -> None:
    """Internal helper to trigger state change notifications."""
    if _change_callback and _change_loop:
        try:
            # Check if the loop is still running
            if _change_loop.is_closed():
                logger.warning("Event loop is closed, cannot schedule state change notification for turtle %d", turtle_id)
                return
            
            # Schedule the callback on the main event loop
            future = asyncio.run_coroutine_threadsafe(_change_callback(turtle_id), _change_loop)
            logger.info("Scheduled state change notification for turtle %d", turtle_id)
            
            # Don't wait for completion, but log if it fails
            def log_result(fut):
                try:
                    fut.result()  # This will raise if the coroutine failed
                except Exception as e:
                    logger.warning("State change notification failed for turtle %d: %s", turtle_id, e)
            
            future.add_done_callback(log_result)
            
        except Exception as e:
            logger.warning("Failed to schedule state change notification for turtle %d: %s", turtle_id, e)
    else:
        logger.debug("No change callback registered, skipping notification for turtle %d", turtle_id)


def upsert_seen(turtle_id: int) -> None:
    now = int(time.time() * 1000)
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT turtle_id FROM turtles WHERE turtle_id=?", (turtle_id,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE turtles SET last_seen_ms=? WHERE turtle_id=?", (now, turtle_id))
    else:
        cur.execute(
            "INSERT INTO turtles(turtle_id, first_seen_ms, last_seen_ms) VALUES (?,?,?)",
            (turtle_id, now, now),
        )
    conn.commit()
    conn.close()
    # Notify of state change
    _notify_change(turtle_id)


def list_all_ids() -> List[int]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT turtle_id FROM turtles ORDER BY turtle_id")
    out = [int(r[0]) for r in cur.fetchall()]
    conn.close()
    return out


def get_last_seen_map() -> Dict[int, int]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT turtle_id, last_seen_ms FROM turtles")
    out = {int(r[0]): int(r[1] or 0) for r in cur.fetchall()}
    conn.close()
    return out


def get_state(turtle_id: int) -> Dict[str, Any]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT fuel_level, inventory, x, y, z, heading, name, label, connection_status FROM turtles WHERE turtle_id=?",
        (turtle_id,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return {"fuel_level": None, "inventory": None, "coords": None, "connection_status": "disconnected"}
    return {
        "fuel_level": r[0],
        "inventory": r[1],
        "coords": {"x": r[2], "y": r[3], "z": r[4]} if (r[2] is not None and r[3] is not None and r[4] is not None) else None,
        "heading": r[5],
        "name": r[6],
        "label": r[7],
        "connection_status": r[8] or "disconnected",
    }


def set_state(
    turtle_id: int,
    *,
    fuel_level: Optional[int] = None,
    inventory: Optional[str] = None,
    coords: Optional[Tuple[int, int, int]] = None,
    heading: Optional[int] = None,
    connection_status: Optional[str] = None,
    label: Optional[str] = None,
) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT turtle_id FROM turtles WHERE turtle_id=?", (turtle_id,))
    exists = cur.fetchone() is not None
    x = y = z = None
    if coords is not None:
        x, y, z = coords
    if exists:
        cur.execute(
            """
            UPDATE turtles
            SET fuel_level=COALESCE(?, fuel_level),
                inventory=COALESCE(?, inventory),
                x=COALESCE(?, x), y=COALESCE(?, y), z=COALESCE(?, z),
                heading=COALESCE(?, heading),
                connection_status=COALESCE(?, connection_status),
                label=COALESCE(?, label)
            WHERE turtle_id=?
            """,
            (fuel_level, inventory, x, y, z, heading, connection_status, label, turtle_id),
        )
    else:
        cur.execute(
            "INSERT INTO turtles(turtle_id, fuel_level, inventory, x, y, z, heading, connection_status, label) VALUES (?,?,?,?,?,?,?,?,?)",
            (turtle_id, fuel_level, inventory, x, y, z, heading, connection_status or "disconnected", label),
        )
    conn.commit()
    conn.close()
    # Notify of state change
    _notify_change(turtle_id)


def set_name_label(turtle_id: int, *, name: Optional[str] = None, label: Optional[str] = None) -> None:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT turtle_id FROM turtles WHERE turtle_id=?", (turtle_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute(
            "UPDATE turtles SET name=COALESCE(?, name), label=COALESCE(?, label) WHERE turtle_id=?",
            (name, label, turtle_id),
        )
    else:
        cur.execute(
            "INSERT INTO turtles(turtle_id, name, label) VALUES (?,?,?)",
            (turtle_id, name, label),
        )
    conn.commit()
    conn.close()
    # Notify of state change
    _notify_change(turtle_id)


def log_call(
    turtle_id: int,
    *,
    call_name: str,
    args_json: Optional[str] = None,
    ok: Optional[bool] = None,
    result_json: Optional[str] = None,
    error_text: Optional[str] = None,
    request_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    ts = int(time.time() * 1000)
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO function_calls(ts_ms, turtle_id, call_name, args_json, ok, result_json, error_text, request_id, duration_ms)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            ts,
            turtle_id,
            call_name,
            args_json,
            1 if ok else (0 if ok is not None else None),
            result_json,
            error_text,
            request_id,
            duration_ms,
        ),
    )
    conn.commit()
    conn.close()


