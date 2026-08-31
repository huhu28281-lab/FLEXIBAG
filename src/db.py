from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "flexibag.db"


def database_path() -> Path:
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("sqlite:///"):
        value = url.removeprefix("sqlite:///")
        return Path(value) if value else DEFAULT_DB_PATH
    return DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    location_name TEXT NOT NULL,
    region TEXT,
    lat REAL,
    lon REAL,
    reorder_point INTEGER NOT NULL,
    target_level INTEGER NOT NULL,
    unit_price_usd REAL NOT NULL,
    lead_time_days INTEGER DEFAULT 14,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS flexibag_inventory (
    serial_no TEXT PRIMARY KEY,
    location_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('IN_STOCK', 'USED', 'DAMAGED', 'LOST')),
    intake_date DATE NOT NULL,
    used_date DATE,
    current_order_id TEXT,
    note TEXT,
    FOREIGN KEY(location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS email_intake (
    email_id TEXT PRIMARY KEY,
    received_at DATETIME NOT NULL,
    from_email TEXT,
    to_emails TEXT,
    cc_emails TEXT,
    subject TEXT,
    raw_body TEXT,
    parsed_json TEXT,
    parse_confidence TEXT CHECK(parse_confidence IN ('high', 'medium', 'low')),
    status TEXT NOT NULL CHECK(status IN ('RECEIVED', 'PARSED', 'NEEDS_REVIEW', 'CONFIRMED', 'IGNORED')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS installation_schedule (
    schedule_id TEXT PRIMARY KEY,
    source_email_id TEXT,
    work_date DATE NOT NULL,
    bkg_no TEXT,
    po_no TEXT,
    location_id TEXT,
    pol TEXT,
    pod TEXT,
    item TEXT,
    cntr_type TEXT,
    cntr_qty INTEGER,
    flexibag_qty INTEGER,
    vessel_voy TEXT,
    doc_datetime DATETIME,
    coc_datetime DATETIME,
    etd DATE,
    eta DATE,
    terminal TEXT,
    pickup_date DATE,
    destination TEXT,
    gs_pi_no TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED', 'COMPLETED')),
    confirmed_by TEXT,
    confirmed_at DATETIME,
    FOREIGN KEY(source_email_id) REFERENCES email_intake(email_id),
    FOREIGN KEY(location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS work_orders (
    order_id TEXT PRIMARY KEY,
    schedule_id TEXT,
    request_date DATE NOT NULL,
    work_date DATE,
    location_id TEXT NOT NULL,
    qty_required INTEGER NOT NULL,
    bkg_no TEXT,
    status TEXT NOT NULL CHECK(status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(schedule_id) REFERENCES installation_schedule(schedule_id),
    FOREIGN KEY(location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS work_photos (
    photo_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    uploaded_at DATETIME NOT NULL,
    image_path TEXT,
    ocr_serial TEXT,
    ocr_confidence TEXT CHECK(ocr_confidence IN ('high', 'medium', 'low', 'failed')),
    confirmed_serial TEXT,
    location_id TEXT,
    result TEXT CHECK(result IN ('PENDING_CONFIRMATION', 'USED_OK', 'USED_OK_CORRECTED', 'OCR_FAILED', 'INVALID_SERIAL', 'DUPLICATE_USED', 'LOCATION_MISMATCH')),
    confirmed_by TEXT,
    confirmed_at DATETIME,
    FOREIGN KEY(order_id) REFERENCES work_orders(order_id),
    FOREIGN KEY(location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS inventory_events (
    event_id TEXT PRIMARY KEY,
    serial_no TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('INTAKE', 'USE', 'CORRECTION', 'DAMAGE', 'LOSS')),
    from_status TEXT,
    to_status TEXT,
    location_id TEXT,
    order_id TEXT,
    photo_id TEXT,
    source_email_id TEXT,
    event_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    confirmed_by TEXT,
    note TEXT,
    FOREIGN KEY(serial_no) REFERENCES flexibag_inventory(serial_no),
    FOREIGN KEY(location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS cost_params (
    param_name TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    unit TEXT,
    note TEXT
);
"""


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        if own_connection:
            conn.close()


def table_count(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS total FROM {table_name}").fetchone()
    return int(row["total"])
