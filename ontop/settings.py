"""User-editable settings (theme, opening hours, prices, pass terms) kept in settings.json.

Settings are applied to :mod:`ontop.config` once at startup, before the rest of
the app is imported, so every module sees the same values. Changes made in the
app are saved here and take effect after a restart.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import time
from pathlib import Path

from . import config

SETTINGS_FILE = "settings.json"
DEFAULT_THEME = "Midnight"


def _default_rates() -> dict[str, dict[int, int]]:
    return {group: dict(rates) for group, rates in config.HOURLY_RATES_PAISE.items()}


@dataclass
class AppSettings:
    theme: str = DEFAULT_THEME
    opening: str = config.OPENING_TIME.strftime("%H:%M")
    closing: str = config.CLOSING_TIME.strftime("%H:%M")
    hourly_rates_paise: dict[str, dict[int, int]] = field(default_factory=_default_rates)
    half_hour_paise: dict[str, int] = field(default_factory=lambda: dict(config.HALF_HOUR_PRICES_PAISE))
    pass_price_paise: int = config.PASS_DEFAULT_PRICE_PAISE
    pass_hours: int = config.PASS_HOURS
    pass_valid_days: int = config.PASS_VALID_DAYS

    def problems(self) -> list[str]:
        errors = []
        try:
            opening, closing = _parse_hhmm(self.opening), _parse_hhmm(self.closing)
            if closing <= opening:
                errors.append("Closing time must be after opening time.")
        except ValueError:
            errors.append("Opening and closing times must be HH:MM.")
        for group in config.HOURLY_RATES_PAISE:
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


def apply(settings: AppSettings) -> None:
    """Copy settings into ontop.config. Call before importing the rest of the app."""
    config.OPENING_TIME = _parse_hhmm(settings.opening)
    config.CLOSING_TIME = _parse_hhmm(settings.closing)
    config.HOURLY_RATES_PAISE = {g: dict(r) for g, r in settings.hourly_rates_paise.items()}
    config.HALF_HOUR_PRICES_PAISE = dict(settings.half_hour_paise)
    config.PASS_DEFAULT_PRICE_PAISE = settings.pass_price_paise
    config.PASS_HOURS = settings.pass_hours
    config.PASS_VALID_DAYS = settings.pass_valid_days
