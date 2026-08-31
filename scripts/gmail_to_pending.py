from __future__ import annotations

import argparse
import imaplib
import json
import ssl
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_PATH = PROJECT_ROOT / "data" / "processed_gmail_uids.json"

sys.path.insert(0, str(PROJECT_ROOT))

from src.db import get_connection, init_db  # noqa: E402
from src.email_parser import parse_email_to_schedule, parse_eml_bytes  # noqa: E402
from src.inventory import create_pending_schedule  # noqa: E402


def find_env_file() -> Path:
    for base in [PROJECT_ROOT, *PROJECT_ROOT.parents]:
        candidate = base / ".env.mail"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find .env.mail in the project folder or parent folders.")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_processed_uids() -> set[str]:
    if not PROCESSED_PATH.exists():
        return set()
    return set(json.loads(PROCESSED_PATH.read_text(encoding="utf-8")))


def save_processed_uids(uids: set[str]) -> None:
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_PATH.write_text(json.dumps(sorted(uids), indent=2), encoding="utf-8")


def connect_imap(config: dict[str, str]) -> imaplib.IMAP4_SSL:
    host = config.get("IMAP_HOST", "imap.gmail.com")
    port = int(config.get("IMAP_PORT", "993"))
    context = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, port, ssl_context=context)
    client.login(config["IMAP_USER"], config["IMAP_PASS"])
    return client


def fetch_unseen_uids(client: imaplib.IMAP4_SSL) -> list[str]:
    status, data = client.uid("SEARCH", None, "UNSEEN")
    if status != "OK":
        raise RuntimeError("Could not search Gmail inbox.")
    return [uid.decode("ascii") for uid in data[0].split()]


def fetch_raw_email(client: imaplib.IMAP4_SSL, uid: str) -> bytes:
    status, fetched = client.uid("FETCH", uid.encode("ascii"), "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError(f"Could not fetch email UID {uid}.")
    for item in fetched:
        if isinstance(item, tuple):
            return item[1]
    raise RuntimeError(f"Email UID {uid} had no RFC822 body.")


def mark_seen(client: imaplib.IMAP4_SSL, uid: str) -> None:
    client.uid("STORE", uid.encode("ascii"), "+FLAGS", "(\\Seen)")


def receive_to_pending(limit: int, dry_run: bool = False, uid: str | None = None) -> list[dict]:
    config = load_env(find_env_file())
    processed = load_processed_uids()
    created: list[dict] = []

    conn = get_connection()
    init_db(conn)

    client = connect_imap(config)
    try:
        mailbox = config.get("IMAP_MAILBOX", "INBOX")
        client.select(mailbox)
        uids = [uid] if uid else [uid for uid in fetch_unseen_uids(client) if uid not in processed]
        selected_uids = uids[-limit:] if limit > 0 else uids

        for uid in selected_uids:
            raw = fetch_raw_email(client, uid)
            subject, body, headers = parse_eml_bytes(raw)
            parsed = parse_email_to_schedule(subject, body)

            result = {
                "uid": uid,
                "subject": subject,
                "parsed": parsed,
                "email_id": None,
                "schedule_id": None,
            }

            if not dry_run:
                email_id, schedule_id = create_pending_schedule(
                    conn,
                    parsed,
                    subject=subject,
                    body=body,
                    headers=headers,
                )
                result["email_id"] = email_id
                result["schedule_id"] = schedule_id
                processed.add(uid)
                if config.get("MARK_SEEN", "").lower() == "true":
                    mark_seen(client, uid)

            created.append(result)
    finally:
        try:
            client.logout()
        finally:
            conn.close()

    if not dry_run:
        save_processed_uids(processed)

    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive Gmail messages and create PENDING_CONFIRMATION schedules.")
    parser.add_argument("--limit", type=int, default=1, help="Number of unread emails to process. Use 0 for all.")
    parser.add_argument("--uid", help="Process one specific Gmail IMAP UID, even if it is already read.")
    parser.add_argument("--dry-run", action="store_true", help="Parse emails without writing to the database.")
    args = parser.parse_args()

    rows = receive_to_pending(limit=args.limit, dry_run=args.dry_run, uid=args.uid)
    print(json.dumps({"processed": len(rows), "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
