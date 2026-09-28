"""Normalization helpers applied to both the document side and the master side.

Everything here is deterministic and side-effect free.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

_TRAILING_ZERO_DECIMAL = re.compile(r"^(-?\d+)\.0+$")
_WHITESPACE = re.compile(r"\s+")


# --------------------------------------------------------------------------- IDs


def normalize_id(value: Any) -> Optional[str]:
    """Convert an identifier to a clean string: ``58264.0`` -> ``"58264"``.

    Strips whitespace and drops a trailing ``.0`` (Excel stores numeric IDs as floats).
    Returns ``None`` for empty values.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    match = _TRAILING_ZERO_DECIMAL.match(text)
    if match:
        return match.group(1)
    return text


# ------------------------------------------------------------------------- names


def normalize_name(value: Any) -> Optional[str]:
    """Normalize a company name for comparison.

    Unicode NFKC, casefold, punctuation -> space, collapse whitespace, strip.
    ``ClearLine Hygiene GmbH`` == ``Clearline Hygiene GmbH`` and
    ``Northbridge Catering Systems Ltd.`` == ``Northbridge Catering Systems Ltd``.
    """
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


# ------------------------------------------------------------------------- units

# Maps printed units to the item master's "Base UoM". Extend as needed.
UNIT_MAP: dict[str, str] = {
    "pc": "pc",
    "pcs": "pc",
    "pce": "pc",
    "pces": "pc",
    "piece": "pc",
    "pieces": "pc",
    "stk": "pc",
    "stck": "pc",
    "stück": "pc",
    "stueck": "pc",
    "st": "pc",
    "ea": "pc",
    "each": "pc",
    "canister": "canister",
    "canisters": "canister",
    "kanister": "canister",
    "set": "set",
    "sets": "set",
    "satz": "set",
    "pack": "pack",
    "packs": "pack",
    "pkg": "pack",
    "pck": "pack",
    "roll": "roll",
    "rolls": "roll",
    "rolle": "roll",
    "rollen": "roll",
    "m": "m",
    "meter": "m",
    "metre": "m",
    "meters": "m",
    "metres": "m",
}


def normalize_unit(value: Any) -> Optional[str]:
    """Map a printed unit (``Stk``, ``pcs``, ``canisters``...) to the master's base UoM.

    Unknown units are returned casefolded and stripped, so they can still be compared.
    """
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold().rstrip(".")
    if not text:
        return None
    return UNIT_MAP.get(text, text)


# ----------------------------------------------------------------------- numbers

_NUMBER_JUNK = re.compile(r"[^\d,.\-+]")


def parse_number(value: Any) -> Optional[float]:
    """Parse numbers in German or English notation to float.

    ``"1.118,00"`` -> 1118.0, ``"5,00"`` -> 5.0, ``"1,118.00"`` -> 1118.0, ``"19 %"`` -> 19.0.
    A single comma is treated as the decimal separator (German documents); several
    commas or several dots are thousands separators.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _NUMBER_JUNK.sub("", text)
    if not text or text in {"-", "+", ".", ","}:
        raise ValueError(f"not a number: {value!r}")

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # The separator that appears last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = text.replace(",", "") if text.count(",") > 1 else text.replace(",", ".")
    elif has_dot and text.count(".") > 1:
        text = text.replace(".", "")

    number = float(text)
    return -number if negative else number


# ------------------------------------------------------------------------- dates

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y.%m.%d")


def parse_date(value: Any) -> Optional[date]:
    """Parse ISO and common European date formats (``18.08.2026``) to ``date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:  # ISO datetime
        text = text.split("T", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}; expected YYYY-MM-DD")


def is_active(value: Any) -> bool:
    """Master 'Active' column: ``Yes`` (case-insensitive) means active."""
    if value is True:
        return True
    return str(value or "").strip().casefold() == "yes"
