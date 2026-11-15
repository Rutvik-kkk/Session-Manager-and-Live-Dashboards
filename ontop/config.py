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

# Factory device list, kept so settings can always be reset (settings.apply() replaces DEVICES at startup).
DEFAULT_DEVICES: tuple[str, ...] = DEVICES
DEFAULT_DEVICE_PRICE_GROUP = dict(DEVICE_PRICE_GROUP)

# Snacks and drinks sold with a session.
ITEM_SNACK = "Snack"
ITEM_DRINK = "Drink"
ITEM_KINDS: tuple[str, ...] = (ITEM_SNACK, ITEM_DRINK)

# Text limits shared by the settings, the forms and the stored records.
MAX_DEVICE_NAME_LENGTH = 30
MAX_PRICE_GROUP_LENGTH = MAX_DEVICE_NAME_LENGTH  # a new device's own price column is named after it
MAX_GAME_LENGTH = 60
MAX_ITEM_NAME_LENGTH = 60
MAX_ITEM_QUANTITY = 99
MAX_CATALOG_ENTRIES = 200
MAX_EXPENSE_NOTE_LENGTH = 200

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

# Factory price lists. settings.apply() updates the live dicts above in place, so these untouched copies are
# what "Restore Defaults" and a fresh AppSettings() start from.
DEFAULT_HOURLY_RATES_PAISE = {group: dict(rates) for group, rates in HOURLY_RATES_PAISE.items()}
DEFAULT_HALF_HOUR_PRICES_PAISE = dict(HALF_HOUR_PRICES_PAISE)

PASS_HOURS = 30
PASS_VALID_DAYS = 30
# Placeholder price: 80% of 30 single-player PS5 hours (30 × ₹80 × 0.8 = ₹1,920).
PASS_DEFAULT_PRICE_PAISE = PASS_HOURS * HOURLY_RATES_PAISE["PS5"][1] * 80 // 100
