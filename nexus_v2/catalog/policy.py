"""Domain policy for item classes visible in post-match equipment slots."""

from __future__ import annotations

import re


def _normalize_label(value: str) -> str:
    folded = value.casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).split())


# These API/wiki entries are controls, blessings, passives, or transient effects.
# They do not occupy a distinct post-match equipment slot and must never become
# item-recognition classes. The names were explicitly reviewed on 2026-08-01.
NON_SLOT_ITEM_NAMES: frozenset[str] = frozenset(
    {
        "Active - Conceal",
        "Allow Throw",
        "Bloody Retribution",
        "Broken Heart",
        "Flame Retribution",
        "Ice Retribution",
        "Magic Potion",
        "Passive - Dire Hit",
        "Passive - Encourage",
        "Passive - Favor",
        "Power Potion",
        "Resonating Heart",
        "Rock Potion",
        "Throw Forbidden",
    }
)

_NORMALIZED_NON_SLOT_NAMES = frozenset(_normalize_label(name) for name in NON_SLOT_ITEM_NAMES)


def is_visible_item_slot_class(name: str) -> bool:
    """Return whether an API/catalog label may be recognized as an item-slot class."""

    return _normalize_label(name) not in _NORMALIZED_NON_SLOT_NAMES
