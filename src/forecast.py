from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .inventory import actual_stock, planned_usage


def calculate_forecast_stock(conn: sqlite3.Connection, location_id: str, target_date: str) -> int:
    return actual_stock(conn, location_id) - planned_usage(conn, location_id, target_date)


def projection_rows(
    conn: sqlite3.Connection,
    location_id: str,
    *,
    start_date: str | None = None,
    days: int = 30,
) -> list[dict]:
    start = date.fromisoformat(start_date) if start_date else date.today()
    current = actual_stock(conn, location_id)
    rows: list[dict] = []
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        planned_on_day = conn.execute(
            """
            SELECT COALESCE(SUM(flexibag_qty), 0) AS total
            FROM installation_schedule
            WHERE location_id = ? AND status = 'CONFIRMED' AND work_date = ?
            """,
            (location_id, day.isoformat()),
        ).fetchone()["total"]
        current -= int(planned_on_day or 0)
        rows.append(
            {
                "date": day.isoformat(),
                "planned_usage": int(planned_on_day or 0),
                "projected_stock": current,
            }
        )
    return rows

