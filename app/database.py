from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_db_path() -> str:
    if DB_PATH == ":memory:":
        return DB_PATH
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    path = _resolve_db_path()
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                order_number TEXT NOT NULL UNIQUE,
                prompt TEXT NOT NULL,
                product_type TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                project_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                spec_json TEXT NOT NULL,
                design_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_lots (
                id TEXT PRIMARY KEY,
                material_grade TEXT NOT NULL,
                form TEXT NOT NULL DEFAULT 'plate',
                thickness_mm REAL NOT NULL CHECK(thickness_mm > 0),
                width_mm REAL NOT NULL CHECK(width_mm > 0),
                length_mm REAL NOT NULL CHECK(length_mm > 0),
                source_kind TEXT NOT NULL CHECK(source_kind IN ('new_stock','remnant')),
                project_code TEXT,
                quantity_available INTEGER NOT NULL DEFAULT 0 CHECK(quantity_available >= 0),
                quantity_reserved INTEGER NOT NULL DEFAULT 0 CHECK(quantity_reserved >= 0),
                quantity_consumed INTEGER NOT NULL DEFAULT 0 CHECK(quantity_consumed >= 0),
                unit_value REAL NOT NULL DEFAULT 0 CHECK(unit_value >= 0),
                traceability_verified INTEGER NOT NULL DEFAULT 0,
                material_condition TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'available',
                source_order_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_order_id) REFERENCES orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_inventory_match ON inventory_lots(
                material_grade, form, thickness_mm, status, source_kind
            );

            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                candidate_name TEXT NOT NULL,
                strategy TEXT NOT NULL,
                source_policy TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                completed_at TEXT,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_plans_order ON plans(order_id, created_at);

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id, created_at);
            """
        )


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(value: str) -> Any:
    return json.loads(value)


def audit(conn: sqlite3.Connection, actor: str, entity_type: str, entity_id: str,
          action: str, details: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_events(actor, entity_type, entity_id, action, detail_json, created_at) VALUES(?,?,?,?,?,?)",
        (actor, entity_type, entity_id, action, dump_json(details), utc_now()),
    )


def seed_demo_inventory() -> dict[str, int]:
    """Insert a small, clearly synthetic inventory fixture once."""
    created = 0
    with get_connection() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM inventory_lots WHERE id LIKE 'DEMO-%'").fetchone()["n"]
        if existing:
            return {"created": 0, "existing": int(existing)}
        now = utc_now()
        rows = [
            ("DEMO-PLATE-001", "S275JR", "plate", 3.0, 1500.0, 3000.0, "new_stock", None, 8, 0, 0, 22000.0, 1, "verified", "available", None, now),
            ("DEMO-PLATE-002", "S275JR", "plate", 3.0, 1000.0, 2000.0, "new_stock", None, 10, 0, 0, 10000.0, 1, "verified", "available", None, now),
            ("DEMO-REMNANT-001", "S275JR", "plate", 3.0, 800.0, 600.0, "remnant", "DEMO-PROJECT", 1, 0, 0, 3500.0, 1, "verified", "available", None, now),
            ("DEMO-REMNANT-002", "S275JR", "plate", 3.0, 650.0, 400.0, "remnant", "ANOTHER-PROJECT", 1, 0, 0, 2100.0, 1, "verified", "available", None, now),
            ("DEMO-REMNANT-003", "S275JR", "plate", 3.0, 900.0, 500.0, "remnant", "DEMO-PROJECT", 1, 0, 0, 0.0, 0, "unverified", "available", None, now),
        ]
        conn.executemany(
            """INSERT INTO inventory_lots(id, material_grade, form, thickness_mm, width_mm, length_mm,
            source_kind, project_code, quantity_available, quantity_reserved, quantity_consumed, unit_value,
            traceability_verified, material_condition, status, source_order_id, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows
        )
        created = len(rows)
        audit(conn, "system", "inventory", "demo-fixture", "demo_inventory_seeded", {"records": created, "synthetic": True})
    return {"created": created, "existing": 0}
