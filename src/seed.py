from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .db import PROJECT_ROOT, get_connection, init_db, table_count

DATA_DIR = PROJECT_ROOT / "data"


def _read_csv(name: str) -> list[dict]:
    path = DATA_DIR / name
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _insert_locations(conn: sqlite3.Connection) -> None:
    for row in _read_csv("seed_locations.csv"):
        conn.execute(
            """
            INSERT OR IGNORE INTO locations (
                location_id, location_name, region, lat, lon, reorder_point,
                target_level, unit_price_usd, lead_time_days, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["location_id"],
                row["location_name"],
                row["region"],
                float(row["lat"]),
                float(row["lon"]),
                int(row["reorder_point"]),
                int(row["target_level"]),
                float(row["unit_price_usd"]),
                int(row["lead_time_days"]),
                int(row.get("is_active") or 1),
            ),
        )


def _insert_inventory(conn: sqlite3.Connection) -> None:
    for row in _read_csv("seed_flexibag_inventory.csv"):
        conn.execute(
            """
            INSERT OR IGNORE INTO flexibag_inventory (
                serial_no, location_id, status, intake_date, used_date,
                current_order_id, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["serial_no"],
                row["location_id"],
                row["status"],
                row["intake_date"],
                row.get("used_date") or None,
                row.get("current_order_id") or None,
                row.get("note") or None,
            ),
        )


def _insert_cost_params(conn: sqlite3.Connection) -> None:
    for row in _read_csv("seed_cost_params.csv"):
        conn.execute(
            "INSERT OR IGNORE INTO cost_params (param_name, value, unit, note) VALUES (?, ?, ?, ?)",
            (row["param_name"], row["value"], row["unit"], row["note"]),
        )


def _insert_demo_schedule(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO installation_schedule (
            schedule_id, work_date, bkg_no, po_no, location_id, pol, pod,
            item, cntr_type, cntr_qty, flexibag_qty, vessel_voy,
            doc_datetime, coc_datetime, etd, eta, terminal, pickup_date,
            destination, gs_pi_no, status, confirmed_by, confirmed_at
        ) VALUES (
            'SCH-2026-0529-001', '2026-05-29', 'SNKO010260508923',
            'KPO2605-17', 'ULS', 'ULSAN', 'BANGKOK', 'KIXX LUBO 150N',
            '20DV', 5, 5, 'SAWASDEE INCHEON 2607S',
            '2026-06-19 14:00', '2026-06-20 18:00', '2026-06-21',
            '2026-06-30', '유나이티드탱크터미널', '2026-05-29',
            'Bangkok, Thailand', '20260518CM_KP5', 'CONFIRMED',
            'demo', CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO work_orders (
            order_id, schedule_id, request_date, work_date, location_id,
            qty_required, bkg_no, status
        ) VALUES (
            'WO-2026-0529-001', 'SCH-2026-0529-001', '2026-05-28',
            '2026-05-29', 'ULS', 5, 'SNKO010260508923', 'OPEN'
        )
        """
    )


def seed_database(*, reset: bool = False, conn: sqlite3.Connection | None = None) -> None:
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        if reset:
            conn.executescript(
                """
                DROP TABLE IF EXISTS inventory_events;
                DROP TABLE IF EXISTS work_photos;
                DROP TABLE IF EXISTS work_orders;
                DROP TABLE IF EXISTS installation_schedule;
                DROP TABLE IF EXISTS email_intake;
                DROP TABLE IF EXISTS flexibag_inventory;
                DROP TABLE IF EXISTS locations;
                DROP TABLE IF EXISTS cost_params;
                """
            )
        init_db(conn)
        if table_count(conn, "locations") == 0:
            _insert_locations(conn)
        if table_count(conn, "flexibag_inventory") == 0:
            _insert_inventory(conn)
        if table_count(conn, "cost_params") == 0:
            _insert_cost_params(conn)
        if table_count(conn, "installation_schedule") == 0:
            _insert_demo_schedule(conn)
        conn.commit()
    finally:
        if own_connection:
            conn.close()


if __name__ == "__main__":
    seed_database()
    print("Seeded flexibag.db")

