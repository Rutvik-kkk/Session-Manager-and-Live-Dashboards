"""Suggested session charges from the café price list."""

from __future__ import annotations

from .config import (
    BILLING_BLOCK_MINUTES,
    DEVICE_PRICE_GROUP,
    HALF_HOUR_PERCENT,
    HOURLY_RATES_PAISE,
    MIN_MULTIPLAYER_MINUTES,
    PLAYER_COUNTS,
)
from .formatting import fmt_duration, fmt_money


def billable_minutes(duration_minutes: int) -> int:
    """Duration rounded up to the next 30-minute block."""
    if duration_minutes <= 0:
        return 0
    blocks = -(-duration_minutes // BILLING_BLOCK_MINUTES)
    return blocks * BILLING_BLOCK_MINUTES


def hourly_rate(device: str, players: int) -> int:
    return HOURLY_RATES_PAISE[DEVICE_PRICE_GROUP[device]][players]


def players_problem(players: object, duration_minutes: int | None = None) -> str | None:
    if not isinstance(players, int) or isinstance(players, bool) or players not in PLAYER_COUNTS:
        return f"Select the number of players (1 to {PLAYER_COUNTS[-1]})."
    if players > 1 and duration_minutes is not None and 0 < duration_minutes < MIN_MULTIPLAYER_MINUTES:
        return (
            f"Sessions with {players} players must be at least {fmt_duration(MIN_MULTIPLAYER_MINUTES)}. "
            "30-minute sessions are for 1 player only."
        )
    return None


def _charge_for(rate_paise: int, billed: int) -> int:
    if billed == BILLING_BLOCK_MINUTES:
        return (rate_paise * HALF_HOUR_PERCENT + 50) // 100
    return rate_paise * billed // 60


def suggested_charge(device: str, players: int, duration_minutes: int, on_pass: bool = False) -> int:
    """Charge in paise. On a pass the holder's own time is prepaid, so only extra players pay."""
    billed = billable_minutes(duration_minutes)
    if billed == 0:
        return 0
    full = _charge_for(hourly_rate(device, players), billed)
    if not on_pass:
        return full
    return full - _charge_for(hourly_rate(device, 1), billed)


def charge_explanation(device: str, players: int, duration_minutes: int, on_pass: bool = False) -> str:
    billed = billable_minutes(duration_minutes)
    rate = hourly_rate(device, players)
    who = f"{players} player{'s' if players != 1 else ''}"
    if billed == BILLING_BLOCK_MINUTES:
        basis = f"30 min at {HALF_HOUR_PERCENT}% of {fmt_money(rate)}/h"
    else:
        basis = f"{fmt_duration(billed)} × {fmt_money(rate)}/h"
    text = f"{DEVICE_PRICE_GROUP[device]} · {who} · {basis}"
    if billed != duration_minutes:
        text += f" (billed {fmt_duration(billed)} for {fmt_duration(duration_minutes)})"
    if on_pass:
        text += f" · minus the pass holder's share ({fmt_money(hourly_rate(device, 1))}/h)"
    return text
