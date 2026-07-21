"""Fixed-rate currency conversion.

MVP uses static rates so results are deterministic. Swap `RATES_TO_INR` for a
live FX feed later without changing callers.
"""
from __future__ import annotations

RATES_TO_INR: dict[str, float] = {
    "INR": 1.0,
    "USD": 83.0,
    "EUR": 90.0,
    "GBP": 105.0,
    "CNY": 11.5,
    "JPY": 0.55,
}


def to_inr(amount: float, currency: str) -> float:
    rate = RATES_TO_INR.get(currency.upper())
    if rate is None:
        # Unknown currency: treat as INR rather than crash, but this is a signal
        # that a provider returned an unsupported currency.
        rate = 1.0
    return amount * rate
