from __future__ import annotations

import sqlite3

from .forecast import calculate_forecast_stock


def get_reorder_recommendation(conn: sqlite3.Connection, location_id: str, target_date: str) -> dict:
    location = conn.execute("SELECT * FROM locations WHERE location_id = ?", (location_id,)).fetchone()
    if not location:
        raise ValueError(f"Unknown location_id: {location_id}")
    forecast_stock = calculate_forecast_stock(conn, location_id, target_date)
    reorder_point = int(location["reorder_point"])
    target_level = int(location["target_level"])
    if forecast_stock <= 0:
        status = "부족"
    elif forecast_stock <= reorder_point:
        status = "주문 권장"
    else:
        status = "정상"
    recommended_order_qty = max(target_level - forecast_stock, 0) if status != "정상" else 0
    return {
        "location_id": location_id,
        "location_name": location["location_name"],
        "target_date": target_date,
        "forecast_stock": forecast_stock,
        "reorder_point": reorder_point,
        "target_level": target_level,
        "status": status,
        "recommended_order_qty": recommended_order_qty,
    }


def reorder_alerts(conn: sqlite3.Connection, target_date: str) -> list[dict]:
    locations = conn.execute("SELECT location_id FROM locations WHERE is_active = 1 ORDER BY location_id").fetchall()
    return [
        alert
        for alert in (get_reorder_recommendation(conn, row["location_id"], target_date) for row in locations)
        if alert["status"] != "정상"
    ]

