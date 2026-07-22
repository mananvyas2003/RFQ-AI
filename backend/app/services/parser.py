"""BOM file parser: reads CSV/XLSX and auto-detects the relevant columns."""
from __future__ import annotations

import io
from typing import List, Optional

import pandas as pd
from rapidfuzz import fuzz

from app.models import BomLine, ColumnMapping, ParseResponse

# Header synonyms per target field, checked before fuzzy matching.
# IMPORTANT: "value" and "description" are separate. Many BOMs have BOTH
# (Value=10K, Description="Resistor 10K 0603"). Mapping "value" into
# description used to discard the richer Description column and leave the
# matcher with a bare "10K" that can't be sourced reliably.
_SYNONYMS: dict[str, List[str]] = {
    "mpn": [
        "mpn", "manufacturer part number", "manufacturer part no", "mfr part",
        "mfr part number", "mfg part", "part number", "part no", "partnumber",
        "part#", "part #", "component", "manufacturer part", "mfr. part #",
    ],
    "manufacturer": [
        "manufacturer", "mfr", "mfg", "brand", "make", "mfr name", "manufacturer name",
    ],
    "quantity": [
        "qty", "quantity", "qnty", "count", "pieces", "pcs", "qty per board",
        "quantity per board", "no", "amount",
    ],
    "reference": [
        "reference", "refdes", "ref des", "designator", "designators",
        "references", "ref", "reference designator",
    ],
    "value": [
        "value", "val", "comp value", "component value",
    ],
    "description": [
        "description", "desc", "comment", "comments", "details",
        "part description", "component description", "footprint",
    ],
}


def _norm_header(h: str) -> str:
    return str(h).strip().lower()


def _detect_columns(headers: List[str]) -> ColumnMapping:
    normalized = {h: _norm_header(h) for h in headers}
    used: set[str] = set()
    mapping: dict[str, Optional[str]] = {k: None for k in _SYNONYMS}

    # Pass 1: exact / substring synonym match.
    for field, syns in _SYNONYMS.items():
        for header, norm in normalized.items():
            if header in used:
                continue
            if any(norm == s or norm in s or s in norm for s in syns):
                mapping[field] = header
                used.add(header)
                break

    # Pass 2: fuzzy match for anything still unmapped.
    for field, syns in _SYNONYMS.items():
        if mapping[field] is not None:
            continue
        best_header, best_score = None, 0.0
        for header, norm in normalized.items():
            if header in used:
                continue
            score = max(fuzz.token_set_ratio(norm, s) for s in syns)
            if score > best_score:
                best_header, best_score = header, score
        if best_header is not None and best_score >= 82:
            mapping[field] = best_header
            used.add(best_header)

    return ColumnMapping(**mapping)


def _read_dataframe(filename: str, content: bytes) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), dtype=str)
    # Default to CSV; handle stray BOM/whitespace.
    return pd.read_csv(io.BytesIO(content), dtype=str, skipinitialspace=True)


def _to_int(value: object, default: int = 1) -> int:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s or s.lower() == "nan":
            return default
        # Handle values like "2 pcs" or "1,000".
        s = s.replace(",", "")
        digits = "".join(ch for ch in s if ch.isdigit())
        return int(digits) if digits else default
    except (ValueError, TypeError):
        return default


def _cell(row: pd.Series, col: Optional[str]) -> str:
    if not col or col not in row:
        return ""
    val = row[col]
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def _merge_value_description(value: str, description: str) -> str:
    """Combine BOM Value + Description into one search-friendly string.

    Prefers the longer free-text Description, and prepends Value when it
    adds signal that isn't already present in the description text.
    """
    value = (value or "").strip()
    description = (description or "").strip()
    if value and description:
        if value.lower() in description.lower():
            return description
        return f"{value} {description}".strip()
    return description or value


def parse_bom(filename: str, content: bytes) -> ParseResponse:
    df = _read_dataframe(filename, content)
    df = df.dropna(how="all")
    headers = [str(c) for c in df.columns]
    mapping = _detect_columns(headers)

    lines: List[BomLine] = []
    for _, row in df.iterrows():
        mpn = _cell(row, mapping.mpn)
        value = _cell(row, mapping.value)
        description = _cell(row, mapping.description)
        # Merge Value + Description so search gets both the short value
        # ("10K") and the human label ("Resistor 10K 0603").
        description = _merge_value_description(value, description)
        # Skip fully empty rows.
        if not mpn and not description:
            continue
        lines.append(
            BomLine(
                # Sequential position in the output list, so skipped empty rows
                # don't create gaps in the numbering shown to users.
                line_no=len(lines) + 1,
                mpn=mpn,
                manufacturer=_cell(row, mapping.manufacturer),
                quantity=_to_int(_cell(row, mapping.quantity)) if mapping.quantity else 1,
                reference=_cell(row, mapping.reference),
                description=description,
            )
        )

    return ParseResponse(headers=headers, mapping=mapping, lines=lines, row_count=len(lines))
