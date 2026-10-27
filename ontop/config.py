"""Café business settings: consoles, opening hours, prices and monthly pass terms.

Edit the values here to change prices or hours; everything else in the app
reads from this file. Money is in paise (₹1 = 100 paise).
"""

from __future__ import annotations

from datetime import time

DEVICES: tuple[str, ...] = ("PS5(X)", "PS5(Y)", "PS4")

# Device names used before version 2 of the data file, mapped to current names.
LEGACY_DEVICE_NAMES = {"ps5A": "PS5(X)", "ps5B": "PS5(Y)", "ps4": "PS4"}

# Which price list each console uses.
DEVICE_PRICE_GROUP = {"PS5(X)": "PS5", "PS5(Y)": "PS5", "PS4": "PS4"}

MAX_PLAYERS = 4
PLAYER_COUNTS: tuple[int, ...] = tuple(range(1, MAX_PLAYERS + 1))

# Price per hour for the whole group, by number of players.
HOURLY_RATES_PAISE = {
    "PS5": {1: 80_00, 2: 180_00, 3: 280_00, 4: 380_00},
    "PS4": {1: 60_00, 2: 120_00, 3: 180_00, 4: 240_00},
}

# Time is billed in 30-minute blocks, rounded up.
BILLING_BLOCK_MINUTES = 30
# Fixed price of a 30-minute session (1 player only).
HALF_HOUR_PRICES_PAISE = {"PS5": 55_00, "PS4": 40_00}
# Sessions with 2 or more players must be booked for at least this long.
MIN_MULTIPLAYER_MINUTES = 60

OPENING_TIME = time(9, 0)
CLOSING_TIME = time(22, 0)

PASS_HOURS = 30
PASS_VALID_DAYS = 30
# Placeholder price: 80% of 30 single-player PS5 hours (30 × ₹80 × 0.8 = ₹1,920).
PASS_DEFAULT_PRICE_PAISE = PASS_HOURS * HOURLY_RATES_PAISE["PS5"][1] * 80 // 100
