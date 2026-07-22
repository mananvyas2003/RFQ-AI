"""Shared relevance gate for catalog matches.

Maker/hobby stores return keyword-ranked products, so a search for a resistor
can surface a "load cell" that merely shares the text "10K". This gate is the
single source of truth for deciding whether a candidate product genuinely
corresponds to the queried part. It is enforced by every scrape-derived
provider (the crawled local catalog AND the live scrape fallback) so a wrong
product becomes an honest "no match" instead of a confident false positive.
"""
from __future__ import annotations

import re
from typing import List

from rapidfuzz import fuzz

from app.config import settings

# Generic words that carry no identifying signal, so they don't count toward
# description-overlap relevance (avoids "with"/"pack"/"new" inflating a match).
_GENERIC_TOKENS = {
    "THE", "FOR", "AND", "WITH", "PCS", "PC", "PACK", "OF", "PIECE", "PIECES",
    "NEW", "ORIGINAL", "GENUINE", "QTY", "SET", "KIT", "PACKOF", "BUY",
}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _part_cores(mpn: str) -> List[str]:
    """Part-number-like fragments of an MPN: alphanumeric tokens containing a
    digit (e.g. NE555, STM32F103C8T6, RC0603FR) plus standalone digit runs
    (e.g. 555). Plain words like "HEADER" are intentionally excluded so a real
    part number is required, not an incidental shared English word."""
    up = (mpn or "").upper()
    cores = {
        t for t in re.findall(r"[A-Z0-9]+", up)
        if len(t) >= 3 and any(c.isdigit() for c in t)
    }
    cores |= set(re.findall(r"\d{3,}", up))
    return list(cores)


def _tokens(text: str) -> List[str]:
    """Meaningful tokens from a description, preserving component values.

    Decimal values like ``0.1uF`` / ``4.7k`` must stay intact — splitting on
    ``.`` turns ``0.1uF`` into ``1UF``, which then falsely matches a ``100pF /
    0.1nF / 0.0001uF`` title via the coverage rule.
    """
    up = (text or "").upper()
    # Protect decimal magnitudes so they survive alphanumeric splitting.
    up = re.sub(r"(\d)\.(\d)", r"\1DOT\2", up)
    return [
        t for t in re.findall(r"[A-Z0-9]+", up)
        if len(t) >= 2 and t not in _GENERIC_TOKENS
    ]


def _normalize_value_token(tok: str) -> str:
    """Canonical form for magnitude tokens (0DOT1UF → 0.1UF)."""
    return tok.replace("DOT", ".")


def _value_tokens(tokens: List[str]) -> List[str]:
    """Tokens that look like electrical values (10K, 0.1UF, 100NF)."""
    out: List[str] = []
    for tok in tokens:
        plain = _normalize_value_token(tok)
        if re.fullmatch(r"\d+\.?\d*[A-Z]+", plain):
            out.append(plain)
    return out


def _title_has_value(title: str, value: str) -> bool:
    """True when `value` appears as a whole magnitude in the title.

    Compares against title tokens (also decimal-preserving) so ``0.1UF`` does
    not match ``0.1NF`` / ``0.0001UF`` / ``10K`` inside ``10KG``.
    """
    title_tokens = [_normalize_value_token(t) for t in _tokens(title)]
    title_vals = set(title_tokens)
    # Merge adjacent "10" + "KOHM" / "K" forms stores often use.
    for i in range(len(title_tokens) - 1):
        a, b = title_tokens[i], title_tokens[i + 1]
        if re.fullmatch(r"\d+\.?\d*", a) and re.fullmatch(r"[A-Z]+", b):
            title_vals.add(f"{a}{b}")
            if b in ("KOHM", "OHM", "OHMS"):
                title_vals.add(f"{a}K")
                title_vals.add(f"{a}R")
                title_vals.add(f"{a}OHM")
            if b == "K":
                title_vals.add(f"{a}KOHM")
    # Also accept common uF ↔ nF / pF equivalents for ceramic caps.
    aliases = {value}
    m = re.fullmatch(r"(\d+\.?\d*)([A-Z]+)", value)
    if m:
        num, unit = float(m.group(1)), m.group(2)
        if unit in ("UF", "MFD"):
            aliases.add(f"{num * 1000:g}NF")
            aliases.add(f"{num * 1_000_000:g}PF")
        elif unit == "NF":
            aliases.add(f"{num / 1000:g}UF")
            aliases.add(f"{num * 1000:g}PF")
        elif unit == "PF":
            aliases.add(f"{num / 1_000_000:g}UF")
            aliases.add(f"{num / 1000:g}NF")
        elif unit == "K":
            aliases.add(f"{num * 1000:g}R")
            aliases.add(f"{num * 1000:g}OHM")
            aliases.add(f"{num:g}KOHM")
        elif unit in ("R", "OHM"):
            if num >= 1000:
                aliases.add(f"{num / 1000:g}K")
    return any(a in title_vals for a in aliases)


def _is_identifier(tok: str) -> bool:
    """A part-number-like token (e.g. 1N4007, WS2812) as opposed to a bare value
    or magnitude (10K, 1UF) or a plain word (HEADER). Distinctive enough to
    confirm a match on its own."""
    plain = _normalize_value_token(tok)
    if re.fullmatch(r"\d+\.?\d*[A-Z]+", plain) and not any(
        c.isalpha() and c not in "KMRUFNPVH" for c in plain
    ):
        # Pure magnitude like 10K / 0.1UF — not an identifier.
        if re.fullmatch(r"\d+\.?\d*(K|R|OHM|UF|NF|PF|MH|UH|H|V|MV|A|MA|UA)", plain):
            return False
    return len(tok) >= 5 and any(c.isdigit() for c in tok)


def is_relevant(mpn: str, description: str, title: str) -> bool:
    """True when the candidate `title` genuinely corresponds to the queried part.

    A candidate is relevant when any of:
      1. the full MPN (must contain a digit) appears in the title,
      2. a part-number-like core of the MPN appears in the title,
      3. a distinctive identifier token from the description appears in the title
         (covers no-MPN lines like a 1N4007 diode), or
      4. at least two meaningful description tokens overlap the title tokens
         (covers name-based maker parts like "Arduino Uno"),
         AND if the description names a magnitude (10K / 0.1uF) that magnitude
         must also appear in the title.

    A bare value or single generic word ("10K", "Header", "0.1uF") is
    deliberately NOT enough on its own, so a resistor query can't be rescued by
    "10K" incidentally appearing inside "10Kg Load Cell".
    """
    if not settings.scrape_strict_matching:
        return True

    tnorm = _norm(title)
    if not tnorm:
        return False

    mnorm = _norm(mpn)
    # Require a digit so a generic word in the MPN field (e.g. "Header") can't
    # match a tangential product ("...with Headers") via a plain substring.
    if len(mnorm) >= 5 and any(c.isdigit() for c in mnorm) and mnorm in tnorm:
        return True

    for core in _part_cores(mpn):
        if _norm(core) in tnorm:
            return True

    q_tokens = _tokens(description)

    # 3. A distinctive identifier in the description is enough on its own.
    for tok in q_tokens:
        if _is_identifier(tok) and _norm(tok) in tnorm:
            return True

    # If the query names an electrical value, the title must carry that value
    # (or an equivalent unit). This blocks "0.1uF" → "100pF / 0.1nF".
    required_values = _value_tokens(q_tokens)
    if required_values and not any(_title_has_value(title, v) for v in required_values):
        return False

    # 4. Otherwise require genuine multi-token overlap (whole tokens, not
    #    substrings, so "10K" does not match "10KG").
    if len(q_tokens) >= 2:
        title_tokens = _tokens(title)
        hits = sum(
            1 for tok in q_tokens
            if tok in title_tokens
            or _normalize_value_token(tok) in {_normalize_value_token(t) for t in title_tokens}
            or any(fuzz.ratio(tok, tt) >= 90 for tt in title_tokens)
        )
        if hits / len(q_tokens) >= settings.scrape_match_min_coverage:
            return True

    return False
