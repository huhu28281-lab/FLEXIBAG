from __future__ import annotations

import html
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.gmail_to_pending import find_env_file, load_env, receive_to_pending  # noqa: E402
from src.db import database_path  # noqa: E402


PORT = 4174
POLL_MIN_SECONDS = 15


state_lock = threading.Lock()
state = {
    "last_poll_at": "",
    "last_error": "",
    "last_created": [],
    "poll_count": 0,
}


def escape(value: object) -> str:
    return html.escape("" if value is None else str(value))


def poll_interval_seconds() -> int:
    try:
        config = load_env(find_env_file())
        return max(int(config.get("POLL_SECONDS", "30")), POLL_MIN_SECONDS)
    except Exception:
        return 30


def poll_once() -> list[dict]:
    rows = receive_to_pending(limit=0)
    with state_lock:
        state["last_poll_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["last_error"] = ""
        state["last_created"] = rows
        state["poll_count"] = int(state["poll_count"]) + 1
    return rows


def poll_loop() -> None:
    while True:
        try:
            poll_once()
        except Exception as exc:
            with state_lock:
                state["last_poll_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                state["last_error"] = str(exc)
                state["poll_count"] = int(state["poll_count"]) + 1
        time.sleep(poll_interval_seconds())


def schedule_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT schedule_id, work_date, bkg_no, location_id, pol, pod, item,
                   cntr_type, flexibag_qty, status
            FROM installation_schedule
            ORDER BY work_date DESC, schedule_id DESC
            """
        ).fetchall()
    finally:
        conn.close()


def intake_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT received_at, from_email, subject, parse_confidence, status
            FROM email_intake
            ORDER BY received_at DESC, email_id DESC
            LIMIT 10
            """
        ).fetchall()
    finally:
        conn.close()


def table(headers: list[str], rows: list[sqlite3.Row]) -> str:
    if not rows:
        return '<div class="empty">표시할 데이터가 없습니다.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{escape(row[header])}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_page() -> bytes:
    schedules = schedule_rows()
    intakes = intake_rows()
    pending_count = sum(1 for row in schedules if row["status"] == "PENDING_CONFIRMATION")
    with state_lock:
        snapshot = dict(state)

    created = snapshot.get("last_created") or []
    created_text = "없음"
    if created:
        created_text = ", ".join(
            f"{row.get('schedule_id') or '-'} / {row.get('parsed', {}).get('bkg_no') or '-'}"
            for row in created
        )

    error_html = ""
    if snapshot.get("last_error"):
        error_html = f'<div class="alert error">최근 수신 오류: {escape(snapshot["last_error"])}</div>'

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="10">
  <title>FLEXI BAG 실시간 메일 수신</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", "Malgun Gothic", sans-serif; background: #f4f7fb; color: #172033; }}
    header {{ background: #0f2138; color: white; padding: 22px 28px; }}
    header h1 {{ margin: 0 0 6px; font-size: 24px; }}
    main {{ padding: 22px 28px 36px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .card {{ background: white; border: 1px solid #dce4ef; border-radius: 8px; padding: 14px 16px; }}
    .label {{ color: #617086; font-size: 13px; }}
    .num {{ font-size: 26px; font-weight: 750; margin-top: 4px; }}
    .alert {{ background: #e9f3ff; border: 1px solid #bad8ff; color: #143e70; border-radius: 8px; padding: 12px 14px; margin-bottom: 16px; }}
    .error {{ background: #fff1f1; border-color: #ffc9c9; color: #8f1f1f; }}
    section {{ margin-top: 20px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dce4ef; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e7edf6; text-align: left; font-size: 14px; vertical-align: top; }}
    th {{ background: #eef4fb; color: #26384f; font-weight: 700; }}
    tr:hover {{ background: #f9fcff; }}
    .empty {{ background: white; border: 1px solid #dce4ef; border-radius: 8px; padding: 18px; color: #617086; }}
    .hint {{ color: #617086; font-size: 13px; margin-top: 8px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <header>
    <h1>FLEXI BAG 실시간 메일 수신</h1>
    <div>Gmail 수신 -> 기존 파서 -> DB 저장 -> 화면 자동 갱신</div>
  </header>
  <main>
    <div class="grid">
      <div class="card"><div class="label">전체 일정</div><div class="num">{len(schedules)}</div></div>
      <div class="card"><div class="label">확인 대기</div><div class="num">{pending_count}</div></div>
      <div class="card"><div class="label">최근 수신 확인</div><div class="num">{escape(snapshot.get("last_poll_at") or "-")}</div></div>
      <div class="card"><div class="label">수신 체크 횟수</div><div class="num">{escape(snapshot.get("poll_count"))}</div></div>
    </div>
    <div class="alert">최근 새로 저장된 일정: {escape(created_text)}</div>
    {error_html}
    <section>
      <h2>설치 일정</h2>
      {table(list(schedules[0].keys()) if schedules else [], schedules)}
      <div class="hint">이 화면은 10초마다 자동 새로고침됩니다. Gmail 확인 주기는 .env.mail의 POLL_SECONDS 값을 따릅니다.</div>
    </section>
    <section>
      <h2>최근 수신 메일</h2>
      {table(list(intakes[0].keys()) if intakes else [], intakes)}
    </section>
  </main>
</body>
</html>
"""
    return html_text.encode("utf-8")


def api_state() -> dict:
    schedules = [dict(row) for row in schedule_rows()]
    intakes = [dict(row) for row in intake_rows()]
    with state_lock:
        snapshot = dict(state)
    return {
        "ok": True,
        "state": snapshot,
        "schedules": schedules,
        "emails": intakes,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            body = json.dumps(api_state(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/poll-now":
            try:
                rows = poll_once()
                payload = {"ok": True, "processed": len(rows), "rows": rows}
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = render_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
