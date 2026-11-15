"""User-editable settings kept in settings.json: theme, clock, opening hours, devices, prices, pass terms,
and the catalogues of games and of snacks & drinks.

Settings are applied to :mod:`ontop.config` once at startup, before the rest of
the app is imported, so every module sees the same values. Games, the
snack/drink menu and the price lists are read live by the app (the price dicts in
``config`` are updated in place), so changes there apply to new entries straight
away; adding or removing devices, opening hours and pass terms take effect after
a restart. Saved sessions always keep the amount they were saved with.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import time
from pathlib import Path

from . import config, formatting

SETTINGS_FILE = "settings.json"
DEFAULT_THEME = "Midnight"

# Settings that apply without a restart. Everything else (devices added or removed, opening hours, pass
# terms) is only read at startup.
LIVE_FIELDS = ("games", "menu_items", "hourly_rates_paise", "half_hour_paise")


def _default_rates() -> dict[str, dict[int, int]]:
    return {group: dict(rates) for group, rates in config.DEFAULT_HOURLY_RATES_PAISE.items()}


def _default_devices() -> list[dict[str, str]]:
    return [{"name": name, "group": config.DEFAULT_DEVICE_PRICE_GROUP[name]} for name in config.DEFAULT_DEVICES]


@dataclass
class AppSettings:
    theme: str = DEFAULT_THEME
    opening: str = config.OPENING_TIME.strftime("%H:%M")
    closing: str = config.CLOSING_TIME.strftime("%H:%M")
    hourly_rates_paise: dict[str, dict[int, int]] = field(default_factory=_default_rates)
    half_hour_paise: dict[str, int] = field(default_factory=lambda: dict(config.DEFAULT_HALF_HOUR_PRICES_PAISE))
    pass_price_paise: int = config.PASS_DEFAULT_PRICE_PAISE
    pass_hours: int = config.PASS_HOURS
    pass_valid_days: int = config.PASS_VALID_DAYS
    clock_24h: bool = True
    devices: list[dict[str, str]] = field(default_factory=_default_devices)  # [{"name", "group"}]
    games: list[str] = field(default_factory=list)
    menu_items: list[dict] = field(default_factory=list)  # [{"name", "kind", "price_paise"}]

    @property
    def device_names(self) -> list[str]:
        return [d["name"] for d in self.devices if isinstance(d, dict) and isinstance(d.get("name"), str)]

    @property
    def price_groups(self) -> list[str]:
        """The distinct price groups the devices use, in first-seen order."""
        seen: list[str] = []
        for d in self.devices:
            if isinstance(d, dict) and isinstance(d.get("group"), str) and d["group"] not in seen:
                seen.append(d["group"])
        return seen

    def needs_restart(self, other: "AppSettings") -> bool:
        """True if ``other`` differs from these settings in anything that is only read at startup."""
        def startup_only(s: "AppSettings") -> dict:
            data = asdict(s)
            for key in LIVE_FIELDS:
                data.pop(key)
            # Which price list a device uses is live; only the set of devices is read at startup.
            data["devices"] = s.device_names
            return data

        return startup_only(self) != startup_only(other)

    def problems(self) -> list[str]:
        errors = []
        if not isinstance(self.clock_24h, bool):
            errors.append("Clock format must be true (24-hour) or false (12-hour).")
        try:
            opening, closing = _parse_hhmm(self.opening), _parse_hhmm(self.closing)
            if closing <= opening:
                errors.append("Closing time must be after opening time.")
        except ValueError:
            errors.append("Opening and closing times must be HH:MM.")
        errors += self._device_problems()
        for group in self.price_groups:
            rates = self.hourly_rates_paise.get(group, {})
            if sorted(rates) != list(config.PLAYER_COUNTS) or any(not _money_ok(v) for v in rates.values()):
                errors.append(f"{group} hourly prices are incomplete or invalid.")
            if not _money_ok(self.half_hour_paise.get(group)):
                errors.append(f"{group} 30-minute price is invalid.")
        if not _money_ok(self.pass_price_paise):
            errors.append("Monthly pass price is invalid.")
        if not (_int_ok(self.pass_hours) and 1 <= self.pass_hours <= 744):
            errors.append("Monthly pass hours must be between 1 and 744.")
        if not (_int_ok(self.pass_valid_days) and 1 <= self.pass_valid_days <= 366):
            errors.append("Monthly pass validity must be between 1 and 366 days.")
        errors += self._game_problems()
        errors += self._menu_problems()
        return errors

    def _device_problems(self) -> list[str]:
        if not isinstance(self.devices, list) or not self.devices:
            return ["Add at least one device."]
        errors, seen = [], set()
        for d in self.devices:
            name, group = (d.get("name"), d.get("group")) if isinstance(d, dict) else (None, None)
            if not isinstance(name, str) or not name.strip() or len(name) > config.MAX_DEVICE_NAME_LENGTH:
                errors.append(f"Device names must be 1–{config.MAX_DEVICE_NAME_LENGTH} characters.")
                continue
            if name != name.strip() or "  " in name:
                errors.append(f"Device name '{name}' has extra spaces.")
            if name.casefold() in seen:
                errors.append(f"There are two devices called '{name}'.")
            seen.add(name.casefold())
            if not isinstance(group, str) or not group.strip() or len(group) > config.MAX_PRICE_GROUP_LENGTH:
                errors.append(f"Device '{name}' needs a price group of 1–{config.MAX_PRICE_GROUP_LENGTH} characters.")
        return errors

    def _game_problems(self) -> list[str]:
        if not isinstance(self.games, list) or len(self.games) > config.MAX_CATALOG_ENTRIES:
            return [f"Games must be a list of at most {config.MAX_CATALOG_ENTRIES} names."]
        errors, seen = [], set()
        for game in self.games:
            if not isinstance(game, str) or not game.strip() or len(game) > config.MAX_GAME_LENGTH:
                errors.append(f"Game names must be 1–{config.MAX_GAME_LENGTH} characters.")
            elif game.casefold() in seen:
                errors.append(f"The game '{game}' is listed twice.")
            elif isinstance(game, str):
                seen.add(game.casefold())
        return errors

    def _menu_problems(self) -> list[str]:
        if not isinstance(self.menu_items, list) or len(self.menu_items) > config.MAX_CATALOG_ENTRIES:
            return [f"The menu must be a list of at most {config.MAX_CATALOG_ENTRIES} items."]
        errors, seen = [], set()
        for item in self.menu_items:
            if not isinstance(item, dict):
                errors.append("Menu items must have a name, kind and price.")
                continue
            name, kind, price = item.get("name"), item.get("kind"), item.get("price_paise")
            if not isinstance(name, str) or not name.strip() or len(name) > config.MAX_ITEM_NAME_LENGTH:
                errors.append(f"Item names must be 1–{config.MAX_ITEM_NAME_LENGTH} characters.")
                continue
            if kind not in config.ITEM_KINDS:
                errors.append(f"'{name}' must be a {' or '.join(config.ITEM_KINDS).lower()}.")
            if not _money_ok(price):
                errors.append(f"The price of '{name}' is invalid.")
            key = (name.casefold(), kind)
            if key in seen:
                errors.append(f"'{name}' is listed twice as a {str(kind).lower()}.")
            seen.add(key)
        return errors


def _int_ok(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _money_ok(value: object) -> bool:
    return _int_ok(value) and 0 <= value <= 10_000_000


def _parse_hhmm(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILE


def load(path: Path) -> tuple[AppSettings, str | None]:
    """Settings from ``path`` (defaults if it doesn't exist), plus a warning if the file couldn't be used."""
    defaults = AppSettings()
    if not path.exists():
        return defaults, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = asdict(defaults) | {k: v for k, v in raw.items() if k in asdict(defaults)}
        data["hourly_rates_paise"] = {
            group: {int(players): price for players, price in rates.items()}
            for group, rates in data["hourly_rates_paise"].items()
        }
        loaded = AppSettings(**data)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return defaults, f"{path.name} could not be read ({exc}); default settings are in use."
    errors = loaded.problems()
    if errors:
        return defaults, f"{path.name} has invalid values ({' '.join(errors)}); default settings are in use."
    return loaded, None


def save(path: Path, settings: AppSettings) -> None:
    """Atomically write the settings file."""
    errors = settings.problems()
    if errors:
        raise ValueError(" ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(settings), indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_prices(settings: AppSettings) -> None:
    """Make the price lists live. The dicts are updated in place because other modules hold references to them."""
    config.DEVICE_PRICE_GROUP.clear()
    config.DEVICE_PRICE_GROUP.update({d["name"]: d["group"] for d in settings.devices})
    config.HOURLY_RATES_PAISE.clear()
    config.HOURLY_RATES_PAISE.update({g: dict(r) for g, r in settings.hourly_rates_paise.items()})
    config.HALF_HOUR_PRICES_PAISE.clear()
    config.HALF_HOUR_PRICES_PAISE.update(settings.half_hour_paise)


def apply(settings: AppSettings) -> None:
    """Copy settings into ontop.config. Call before importing the rest of the app."""
    config.OPENING_TIME = _parse_hhmm(settings.opening)
    config.CLOSING_TIME = _parse_hhmm(settings.closing)
    config.DEVICES = tuple(settings.device_names)
    apply_prices(settings)
    config.PASS_DEFAULT_PRICE_PAISE = settings.pass_price_paise
    config.PASS_HOURS = settings.pass_hours
    config.PASS_VALID_DAYS = settings.pass_valid_days
    formatting.CLOCK_24H = settings.clock_24h
