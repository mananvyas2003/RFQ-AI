"""Fuzzy part matcher: resolves messy BOM entries to canonical catalog parts.

This is the core "AI" normalization step. It handles partial MPNs, missing
manufacturers, and description-only lines (common for regional distributors
that list parts without an MPN).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from rapidfuzz import fuzz

from app.models import BomLine, LineStatus
from app.services.catalog.mock_data import get_parts

_MATCH_THRESHOLD = 88.0
_LOW_CONF_THRESHOLD = 70.0


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


@dataclass
class MatchResult:
    part: Optional[dict]
    confidence: float
    status: LineStatus

    @property
    def mpn(self) -> str:
        return self.part["mpn"] if self.part else ""

    @property
    def manufacturer(self) -> str:
        return self.part["manufacturer"] if self.part else ""


def _part_candidates(part: dict) -> List[str]:
    cands = [part["mpn"], *part.get("aliases", [])]
    return [_norm(c) for c in cands if c]


def _part_text(part: dict) -> str:
    pieces = [part.get("mpn", ""), part.get("description", ""), *part.get("aliases", [])]
    return " ".join(p for p in pieces if p).upper()


def _score_part(q_mpn: str, q_text: str, part: dict) -> float:
    q_mpn_norm = _norm(q_mpn)
    mpn_score = 0.0
    if q_mpn_norm:
        cand_norms = _part_candidates(part)
        for cand in cand_norms:
            if not cand:
                continue
            mpn_score = max(mpn_score, fuzz.ratio(q_mpn_norm, cand))
            if q_mpn_norm == cand:
                return 100.0
            if len(q_mpn_norm) >= 4 and (q_mpn_norm in cand or cand in q_mpn_norm):
                mpn_score = max(mpn_score, 92.0)

    text_score = fuzz.token_set_ratio(q_text.upper(), _part_text(part)) if q_text else 0.0
    return max(mpn_score, text_score)


def match_line(line: BomLine) -> MatchResult:
    q_text = " ".join(x for x in [line.mpn, line.manufacturer, line.description] if x)
    best_part: Optional[dict] = None
    best_score = 0.0

    for part in get_parts():
        score = _score_part(line.mpn, q_text, part)
        if score > best_score:
            best_part, best_score = part, score

    if best_part is None or best_score < _LOW_CONF_THRESHOLD:
        return MatchResult(part=None, confidence=round(best_score, 1), status=LineStatus.unmatched)

    status = LineStatus.matched if best_score >= _MATCH_THRESHOLD else LineStatus.low_confidence
    return MatchResult(part=best_part, confidence=round(best_score, 1), status=status)
