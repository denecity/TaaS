import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "turtles.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
            inventory_json TEXT,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            heading INTEGER
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turtles_last_seen ON turtles(last_seen_ms)")
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
        "SELECT fuel_level, inventory_json, x, y, z, heading, name, label FROM turtles WHERE turtle_id=?",
        (turtle_id,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return {"fuel_level": None, "inventory": None, "coords": None}
    return {
        "fuel_level": r[0],
        "inventory": r[1],
        "coords": {"x": r[2], "y": r[3], "z": r[4]} if (r[2] is not None and r[3] is not None and r[4] is not None) else None,
        "heading": r[5],
        "name": r[6],
        "label": r[7],
    }


def set_state(
    turtle_id: int,
    *,
    fuel_level: Optional[int] = None,
    inventory_json: Optional[str] = None,
    coords: Optional[Tuple[int, int, int]] = None,
    heading: Optional[int] = None,
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
                inventory_json=COALESCE(?, inventory_json),
                x=COALESCE(?, x), y=COALESCE(?, y), z=COALESCE(?, z),
                heading=COALESCE(?, heading)
            WHERE turtle_id=?
            """,
            (fuel_level, inventory_json, x, y, z, heading, turtle_id),
        )
    else:
        cur.execute(
            "INSERT INTO turtles(turtle_id, fuel_level, inventory_json, x, y, z, heading) VALUES (?,?,?,?,?,?,?)",
            (turtle_id, fuel_level, inventory_json, x, y, z, heading),
        )
    conn.commit()
    conn.close()


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


