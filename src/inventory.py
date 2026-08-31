from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .utils import make_id, today_iso


def actual_stock(conn: sqlite3.Connection, location_id: str | None = None) -> int:
    if location_id:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM flexibag_inventory WHERE location_id = ? AND status = 'IN_STOCK'",
            (location_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM flexibag_inventory WHERE status = 'IN_STOCK'"
        ).fetchone()
    return int(row["total"])


def used_stock(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS total FROM flexibag_inventory WHERE status = 'USED'").fetchone()
    return int(row["total"])


def planned_usage(conn: sqlite3.Connection, location_id: str | None, until_date: str) -> int:
    if location_id:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(flexibag_qty), 0) AS total
            FROM installation_schedule
            WHERE location_id = ? AND status = 'CONFIRMED' AND work_date <= ?
            """,
            (location_id, until_date),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(flexibag_qty), 0) AS total
            FROM installation_schedule
            WHERE status = 'CONFIRMED' AND work_date <= ?
            """,
            (until_date,),
        ).fetchone()
    return int(row["total"] or 0)


def total_asset_value(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(l.unit_price_usd), 0) AS total
        FROM flexibag_inventory f
        JOIN locations l ON l.location_id = f.location_id
        WHERE f.status = 'IN_STOCK'
        """
    ).fetchone()
    return float(row["total"] or 0)


def inventory_by_location(conn: sqlite3.Connection, target_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            l.location_id,
            l.location_name,
            l.region,
            l.reorder_point,
            l.target_level,
            l.unit_price_usd,
            SUM(CASE WHEN f.status = 'IN_STOCK' THEN 1 ELSE 0 END) AS actual_stock,
            SUM(CASE WHEN f.status = 'USED' THEN 1 ELSE 0 END) AS used_stock,
            COALESCE((
                SELECT SUM(s.flexibag_qty)
                FROM installation_schedule s
                WHERE s.location_id = l.location_id
                  AND s.status = 'CONFIRMED'
                  AND s.work_date <= ?
            ), 0) AS planned_usage
        FROM locations l
        LEFT JOIN flexibag_inventory f ON f.location_id = l.location_id
        WHERE l.is_active = 1
        GROUP BY l.location_id
        ORDER BY l.location_id
        """,
        (target_date,),
    ).fetchall()


def create_pending_schedule(
    conn: sqlite3.Connection,
    parsed_email: dict,
    *,
    subject: str = "",
    body: str = "",
    headers: dict | None = None,
) -> tuple[str, str]:
    headers = headers or {}
    email_id = make_id("EM")
    schedule_id = make_id("SCH")
    status = "NEEDS_REVIEW" if parsed_email.get("warnings") else "PARSED"
    conn.execute(
        """
        INSERT INTO email_intake (
            email_id, received_at, from_email, to_emails, cc_emails, subject,
            raw_body, parsed_json, parse_confidence, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id,
            datetime.now().isoformat(timespec="seconds"),
            headers.get("from_email"),
            headers.get("to_emails"),
            headers.get("cc_emails"),
            subject,
            body,
            json.dumps(parsed_email, ensure_ascii=False),
            parsed_email.get("confidence", "low"),
            status,
        ),
    )
    conn.execute(
        """
        INSERT INTO installation_schedule (
            schedule_id, source_email_id, work_date, bkg_no, po_no, location_id,
            pol, pod, item, cntr_type, cntr_qty, flexibag_qty, vessel_voy,
            doc_datetime, coc_datetime, etd, eta, terminal, pickup_date,
            destination, gs_pi_no, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_CONFIRMATION')
        """,
        (
            schedule_id,
            email_id,
            parsed_email.get("work_date") or today_iso(),
            parsed_email.get("bkg_no"),
            parsed_email.get("po_no"),
            parsed_email.get("location_id"),
            parsed_email.get("pol"),
            parsed_email.get("pod"),
            parsed_email.get("item"),
            parsed_email.get("cntr_type"),
            parsed_email.get("cntr_qty"),
            parsed_email.get("flexibag_qty") or parsed_email.get("cntr_qty") or 0,
            parsed_email.get("vessel_voy"),
            parsed_email.get("doc_datetime"),
            parsed_email.get("coc_datetime"),
            parsed_email.get("etd"),
            parsed_email.get("eta"),
            parsed_email.get("terminal"),
            parsed_email.get("pickup_date") or parsed_email.get("work_date"),
            parsed_email.get("destination"),
            parsed_email.get("gs_pi_no"),
        ),
    )
    conn.commit()
    return email_id, schedule_id


def confirm_schedule(conn: sqlite3.Connection, schedule_id: str, confirmed_by: str) -> str:
    schedule = conn.execute(
        "SELECT * FROM installation_schedule WHERE schedule_id = ?",
        (schedule_id,),
    ).fetchone()
    if not schedule:
        raise ValueError(f"Unknown schedule_id: {schedule_id}")
    if not schedule["location_id"]:
        raise ValueError("location_id is required before confirmation")
    if not schedule["flexibag_qty"]:
        raise ValueError("flexibag_qty is required before confirmation")
    conn.execute(
        """
        UPDATE installation_schedule
        SET status = 'CONFIRMED', confirmed_by = ?, confirmed_at = ?
        WHERE schedule_id = ?
        """,
        (confirmed_by, datetime.now().isoformat(timespec="seconds"), schedule_id),
    )
    order_id = f"WO-{schedule_id.removeprefix('SCH-')}"
    conn.execute(
        """
        INSERT OR IGNORE INTO work_orders (
            order_id, schedule_id, request_date, work_date, location_id,
            qty_required, bkg_no, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """,
        (
            order_id,
            schedule_id,
            today_iso(),
            schedule["work_date"],
            schedule["location_id"],
            schedule["flexibag_qty"] or 0,
            schedule["bkg_no"],
        ),
    )
    if schedule["source_email_id"]:
        conn.execute("UPDATE email_intake SET status = 'CONFIRMED' WHERE email_id = ?", (schedule["source_email_id"],))
    conn.commit()
    return order_id


def set_schedule_status(conn: sqlite3.Connection, schedule_id: str, status: str) -> None:
    conn.execute("UPDATE installation_schedule SET status = ? WHERE schedule_id = ?", (status, schedule_id))
    conn.commit()


def ledger_rows(conn: sqlite3.Connection, location_id: str | None = None, status: str | None = None, search: str = ""):
    clauses = ["1=1"]
    params: list[str] = []
    if location_id:
        clauses.append("f.location_id = ?")
        params.append(location_id)
    if status:
        clauses.append("f.status = ?")
        params.append(status)
    if search:
        clauses.append("f.serial_no LIKE ?")
        params.append(f"%{search}%")
    return conn.execute(
        f"""
        SELECT f.serial_no, f.location_id, l.location_name, f.status,
               f.intake_date, f.used_date, f.current_order_id, f.note
        FROM flexibag_inventory f
        JOIN locations l ON l.location_id = f.location_id
        WHERE {' AND '.join(clauses)}
        ORDER BY f.location_id, f.serial_no
        """,
        params,
    ).fetchall()
