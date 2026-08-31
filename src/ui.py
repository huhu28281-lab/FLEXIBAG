from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from .db import PROJECT_ROOT, get_connection
from .seed import seed_database


def page_setup(title: str) -> sqlite3.Connection:
    st.set_page_config(page_title=title, layout="wide")
    seed_database()
    return get_connection()


def rows_to_dataframe(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(row) for row in rows])


def sample_email_text() -> str:
    return (PROJECT_ROOT / "data" / "sample_email.txt").read_text(encoding="utf-8")


def save_upload(uploaded_file, folder: str) -> str:
    folder_path = PROJECT_ROOT / "uploads" / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    path = folder_path / uploaded_file.name
    path.write_bytes(uploaded_file.getbuffer())
    return str(path)


def status_color(status: str) -> str:
    if status == "부족":
        return "red"
    if status == "주문 권장":
        return "orange"
    if status in {"USED_OK", "USED_OK_CORRECTED", "정상"}:
        return "green"
    return "blue"

