"""Filter name normalization and kit membership."""

from __future__ import annotations

# Display / sort order for all reports
CANONICAL = ("L", "R", "G", "B", "SII", "Ha", "OIII")

_ALIASES: dict[str, str] = {
    # LRGB
    "l": "L",
    "lum": "L",
    "luminance": "L",
    "r": "R",
    "red": "R",
    "g": "G",
    "green": "G",
    "b": "B",
    "blue": "B",
    # Ha / Hα — ASIAIR often stores short "H"
    "h": "Ha",
    "ha": "Ha",
    "h-a": "Ha",
    "h-alpha": "Ha",
    "halpha": "Ha",
    "h_alpha": "Ha",
    "hydrogen-alpha": "Ha",
    "hydrogenalpha": "Ha",
    # OIII — ASIAIR often stores short "O"
    "o": "OIII",
    "oiii": "OIII",
    "o3": "OIII",
    "o-iii": "OIII",
    "o-3": "OIII",
    "oxygen": "OIII",
    "oxygeniii": "OIII",
    # SII — ASIAIR often stores short "S"
    "s": "SII",
    "sii": "SII",
    "s2": "SII",
    "s-ii": "SII",
    "s-2": "SII",
    "sulfur": "SII",
    "sulphur": "SII",
    "sulfurii": "SII",
}

LRGB_KIT = frozenset({"L", "R", "G", "B"})
NB_KIT = frozenset({"Ha", "OIII", "SII"})


def normalize_filter(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    key = text.lower().replace(" ", "").replace("_", "-")
    # collapse repeated separators
    key = key.replace("--", "-")
    if key in _ALIASES:
        return _ALIASES[key]
    # already canonical?
    for name in CANONICAL:
        if text == name or text.lower() == name.lower():
            return name
    return text  # keep unknown as-is, flagged later


def kit_for(filter_name: str) -> str | None:
    if filter_name in LRGB_KIT:
        return "LRGB"
    if filter_name in NB_KIT:
        return "NB"
    return None
