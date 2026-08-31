from __future__ import annotations

import re


def normalize_serial(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value.strip().upper())
    return cleaned.replace("O", "0").replace("I", "1")


def is_valid_serial(value: str | None) -> bool:
    return bool(re.fullmatch(r"\d{15}", normalize_serial(value)))


def warning_status(warnings: list[str]) -> str:
    if not warnings:
        return "high"
    if len(warnings) <= 2:
        return "medium"
    return "low"

