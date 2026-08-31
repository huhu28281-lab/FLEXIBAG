from __future__ import annotations

import re
from datetime import date
from email import policy
from email.parser import BytesParser

from .models import LOCATION_ALIASES
from .validators import warning_status


def _clean_html(value: str) -> str:
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(value, "html.parser").get_text("\n")
    except Exception:
        return re.sub(r"<[^>]+>", " ", value)


def parse_eml_bytes(raw_bytes: bytes) -> tuple[str, str, dict[str, str]]:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    subject = str(message.get("subject", ""))
    headers = {
        "from_email": str(message.get("from", "")),
        "to_emails": str(message.get("to", "")),
        "cc_emails": str(message.get("cc", "")),
    }

    text_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                text_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(_clean_html(part.get_content()))
    else:
        content = message.get_content()
        if message.get_content_type() == "text/html":
            html_parts.append(_clean_html(content))
        else:
            text_parts.append(content)

    body = "\n".join(text_parts or html_parts)
    return subject, body, headers


def _first(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def _extract_date(text: str) -> str | None:
    korean = re.search(r"(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if korean:
        year = int(korean.group(1) or date.today().year)
        return f"{year:04d}-{int(korean.group(2)):02d}-{int(korean.group(3)):02d}"

    iso = _first(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b", text)
    if iso:
        year, month, day = re.split(r"[-/.]", iso)
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    no_year = re.search(r"(?:work\s*date|작업일|작업\s*날짜)\s*[:#-]?\s*(\d{1,2})[/.](\d{1,2})\b", text, re.I)
    if no_year:
        year = date.today().year
        return f"{year:04d}-{int(no_year.group(1)):02d}-{int(no_year.group(2)):02d}"
    return None


def _extract_cntr(text: str) -> tuple[str | None, int | None]:
    type_match = re.search(r"\b((?:20|40)(?:DV|HC|HQ|GP|RF|FT))\b\s*(?:[*xX]\s*(\d+))?", text, re.I)
    cntr_type = type_match.group(1).upper() if type_match else None
    qty = int(type_match.group(2)) if type_match and type_match.group(2) else None
    qty_match = re.search(r"\b(?:QNTY|QTY|QUANTITY|CNTR\s*QTY|수량)\b[^0-9]{0,12}(\d+)", text, re.I)
    if qty_match:
        qty = int(qty_match.group(1))
    if qty is None:
        unit_match = re.search(r"\b(\d+)\s*(?:개|EA)\b", text, re.I)
        if unit_match:
            qty = int(unit_match.group(1))
    return cntr_type, qty


def _fallback_bkg_from_subject(subject: str) -> str | None:
    tail = subject.rsplit("/", 1)[-1].strip()
    match = re.search(r"\b([A-Z]{2,5}\d{6,12})\b", tail, re.I)
    return match.group(1).upper() if match else None


def _fallback_route_from_subject(subject: str) -> tuple[str | None, str | None]:
    route = re.search(r"/\s*([A-Z가-힣]+)\s*-\s*([A-Z가-힣]+)\s*/", subject, re.I)
    if not route:
        return None, None
    return route.group(1), route.group(2)


def _location_from_text(text: str, pol: str | None) -> str | None:
    candidates = [pol or "", text]
    for candidate in candidates:
        upper = candidate.upper()
        for alias, location_id in LOCATION_ALIASES.items():
            if alias.upper() in upper or alias in candidate:
                return location_id
    return None


def parse_email_to_schedule(subject: str, body: str) -> dict:
    text = f"{subject}\n{body}"
    normalized = re.sub(r"[ \t]+", " ", text)

    bkg_no = _first(r"\b(?:BKG|BOOKING(?:\s*NO\.?)?)\s*[:#-]?\s*([A-Z0-9-]{8,})", normalized)
    po_no = _first(r"\b(?:PO|P/O)(?![A-Za-z])\s*(?:NO\.?)?\s*[:#-]?\s*([A-Z0-9-]+)", normalized)
    pol = _first(r"\bPOL\s*[:#-]?\s*([A-Z가-힣]+)", normalized)
    pod = _first(r"\bPOD\s*[:#-]?\s*([A-Z가-힣]+)", normalized)
    subject_pol, subject_pod = _fallback_route_from_subject(subject)
    if pol in {"POD", "ITEM", "CNTR"}:
        pol = None
    if pod in {"ITEM", "CNTR", "VESSEL"}:
        pod = None
    bkg_no = bkg_no or _fallback_bkg_from_subject(subject)
    pol = pol or subject_pol
    pod = pod or subject_pod
    cntr_type, cntr_qty = _extract_cntr(normalized)
    item = _first(r"\bITEM\s*[:#-]?\s*([^,\n]+)", text)
    if item and item.strip().upper() in {"CNTR", "QNTY", "QTY", "VESSEL", "POL", "POD"}:
        item = None
    work_date = _extract_date(normalized)
    location_id = _location_from_text(normalized, pol)
    flexibag_qty = cntr_qty

    warnings: list[str] = []
    if not work_date:
        warnings.append("MISSING_WORK_DATE")
    if not bkg_no:
        warnings.append("MISSING_BKG")
    if not location_id:
        warnings.append("MISSING_LOCATION")
    if not flexibag_qty:
        warnings.append("MISSING_QTY")

    return {
        "work_date": work_date,
        "bkg_no": bkg_no,
        "po_no": po_no,
        "location_id": location_id,
        "pol": pol.upper() if pol else None,
        "pod": pod.upper() if pod else None,
        "item": item.strip() if item else None,
        "cntr_type": cntr_type,
        "cntr_qty": cntr_qty,
        "flexibag_qty": flexibag_qty,
        "vessel_voy": _first(r"\bVESSEL(?:/VOY)?\s*[:#-]?\s*([^,\n]+)", text),
        "doc_datetime": _first(r"\bDOC\s*[:#-]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2})", text),
        "coc_datetime": _first(r"\bCOC\s*[:#-]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2})", text),
        "etd": _first(r"\bETD\s*[:#-]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", text),
        "eta": _first(r"\bETA\s*[:#-]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", text),
        "terminal": _first(r"\bTERMINAL\s*[:#-]?\s*([^,\n]+)", text),
        "pickup_date": work_date,
        "destination": _first(r"\bDESTINATION\s*[:#-]?\s*([^,\n]+)", text),
        "gs_pi_no": _first(r"\bGS[-\s]?PI\s*(?:NO\.?)?\s*[:#-]?\s*([A-Z0-9_-]+)", text),
        "confidence": warning_status(warnings),
        "warnings": warnings,
    }
