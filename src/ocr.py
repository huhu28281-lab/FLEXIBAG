from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .utils import make_id, today_iso
from .validators import is_valid_serial, normalize_serial


def extract_serial_from_photo(image_path: str) -> dict:
    filename = Path(image_path).name.upper()
    match = re.search(r"(\d[\dOIl_-]{10,20})", filename)
    raw_serial = match.group(1) if match else "240126030028O01"
    normalized = normalize_serial(raw_serial)
    confidence = "medium" if is_valid_serial(normalized) else "low"
    warning = None if confidence == "medium" else "Mock OCR result. Please confirm manually."
    return {
        "ocr_serial": raw_serial,
        "normalized_serial": normalized,
        "confidence": confidence,
        "warning": warning,
    }


def _insert_photo_result(
    conn: sqlite3.Connection,
    *,
    photo_id: str,
    order_id: str,
    image_path: str | None,
    ocr_serial: str | None,
    ocr_confidence: str,
    confirmed_serial: str,
    location_id: str | None,
    result: str,
    confirmed_by: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO work_photos (
            photo_id, order_id, uploaded_at, image_path, ocr_serial,
            ocr_confidence, confirmed_serial, location_id, result,
            confirmed_by, confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            photo_id,
            order_id,
            datetime.now().isoformat(timespec="seconds"),
            image_path,
            ocr_serial,
            ocr_confidence,
            confirmed_serial,
            location_id,
            result,
            confirmed_by,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def _insert_event(
    conn: sqlite3.Connection,
    *,
    serial_no: str,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    location_id: str | None,
    order_id: str,
    photo_id: str,
    confirmed_by: str,
    note: str,
) -> None:
    conn.execute(
        """
        INSERT INTO inventory_events (
            event_id, serial_no, event_type, from_status, to_status,
            location_id, order_id, photo_id, confirmed_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            make_id("EVT"),
            serial_no,
            event_type,
            from_status,
            to_status,
            location_id,
            order_id,
            photo_id,
            confirmed_by,
            note,
        ),
    )


def confirm_used_serial(
    conn: sqlite3.Connection,
    order_id: str,
    confirmed_serial: str,
    confirmed_by: str,
    *,
    photo_id: str | None = None,
    image_path: str | None = None,
    ocr_serial: str | None = None,
    ocr_confidence: str = "low",
) -> dict:
    normalized_serial = normalize_serial(confirmed_serial)
    photo_id = photo_id or make_id("PH")
    order = conn.execute("SELECT * FROM work_orders WHERE order_id = ?", (order_id,)).fetchone()
    if not order:
        return {"result": "INVALID_SERIAL", "message": "작업 오더가 없습니다.", "photo_id": photo_id}

    inventory = conn.execute(
        "SELECT * FROM flexibag_inventory WHERE serial_no = ?",
        (normalized_serial,),
    ).fetchone()

    if not inventory or not is_valid_serial(normalized_serial):
        _insert_photo_result(
            conn,
            photo_id=photo_id,
            order_id=order_id,
            image_path=image_path,
            ocr_serial=ocr_serial,
            ocr_confidence=ocr_confidence,
            confirmed_serial=normalized_serial,
            location_id=order["location_id"],
            result="INVALID_SERIAL",
            confirmed_by=confirmed_by,
        )
        conn.commit()
        return {"result": "INVALID_SERIAL", "message": "시리얼 원장에 없는 번호입니다.", "photo_id": photo_id}

    if inventory["status"] == "USED":
        _insert_photo_result(
            conn,
            photo_id=photo_id,
            order_id=order_id,
            image_path=image_path,
            ocr_serial=ocr_serial,
            ocr_confidence=ocr_confidence,
            confirmed_serial=normalized_serial,
            location_id=inventory["location_id"],
            result="DUPLICATE_USED",
            confirmed_by=confirmed_by,
        )
        _insert_event(
            conn,
            serial_no=normalized_serial,
            event_type="CORRECTION",
            from_status="USED",
            to_status="USED",
            location_id=inventory["location_id"],
            order_id=order_id,
            photo_id=photo_id,
            confirmed_by=confirmed_by,
            note="Duplicate USED attempt blocked",
        )
        conn.commit()
        return {"result": "DUPLICATE_USED", "message": "이미 USED 처리된 시리얼입니다.", "photo_id": photo_id}

    if inventory["location_id"] != order["location_id"]:
        _insert_photo_result(
            conn,
            photo_id=photo_id,
            order_id=order_id,
            image_path=image_path,
            ocr_serial=ocr_serial,
            ocr_confidence=ocr_confidence,
            confirmed_serial=normalized_serial,
            location_id=inventory["location_id"],
            result="LOCATION_MISMATCH",
            confirmed_by=confirmed_by,
        )
        _insert_event(
            conn,
            serial_no=normalized_serial,
            event_type="CORRECTION",
            from_status=inventory["status"],
            to_status=inventory["status"],
            location_id=inventory["location_id"],
            order_id=order_id,
            photo_id=photo_id,
            confirmed_by=confirmed_by,
            note=f"Location mismatch: order={order['location_id']} serial={inventory['location_id']}",
        )
        conn.commit()
        return {"result": "LOCATION_MISMATCH", "message": "오더 거점과 시리얼 거점이 다릅니다.", "photo_id": photo_id}

    result = "USED_OK_CORRECTED" if ocr_serial and normalize_serial(ocr_serial) != normalized_serial else "USED_OK"
    conn.execute(
        """
        UPDATE flexibag_inventory
        SET status = 'USED', used_date = ?, current_order_id = ?
        WHERE serial_no = ?
        """,
        (today_iso(), order_id, normalized_serial),
    )
    _insert_photo_result(
        conn,
        photo_id=photo_id,
        order_id=order_id,
        image_path=image_path,
        ocr_serial=ocr_serial,
        ocr_confidence=ocr_confidence,
        confirmed_serial=normalized_serial,
        location_id=inventory["location_id"],
        result=result,
        confirmed_by=confirmed_by,
    )
    _insert_event(
        conn,
        serial_no=normalized_serial,
        event_type="USE",
        from_status=inventory["status"],
        to_status="USED",
        location_id=inventory["location_id"],
        order_id=order_id,
        photo_id=photo_id,
        confirmed_by=confirmed_by,
        note="Human-confirmed OCR serial",
    )
    conn.commit()
    return {"result": result, "message": "USED 처리와 감사 로그 기록이 완료되었습니다.", "photo_id": photo_id}

