from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def make_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:6].upper()}"


def today_iso() -> str:
    return datetime.now().date().isoformat()

