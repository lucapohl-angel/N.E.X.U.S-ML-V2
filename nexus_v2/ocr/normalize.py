"""Conservative OCR normalization and semantic validation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from nexus_v2.schemas.result import JsonScalar


@dataclass(frozen=True)
class ParsedOCR:
    value: JsonScalar | None
    valid: bool
    normalized: str
    messages: tuple[str, ...] = ()


def _clean(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw).strip().split())


def _numeric_text(raw: str, *, decimal: bool = False) -> str:
    text = _clean(raw).replace(",", "." if decimal else "")
    substitutions = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5"})
    text = text.translate(substitutions)
    allowed = r"[^0-9.]" if decimal else r"[^0-9]"
    return re.sub(allowed, "", text)


def parse_ocr(raw: str, *, parser: str) -> ParsedOCR:
    text = _clean(raw)
    if not text:
        return ParsedOCR(value=None, valid=False, normalized="", messages=("empty_ocr",))

    if parser == "player_name":
        valid = 1 <= len(text) <= 64
        return ParsedOCR(
            value=text if valid else None,
            valid=valid,
            normalized=text,
            messages=() if valid else ("player_name_length_invalid",),
        )

    if parser in {"battle_id", "battle_id_18"}:
        digits = _numeric_text(text)
        valid = len(digits) == 18 if parser == "battle_id_18" else 8 <= len(digits) <= 32
        return ParsedOCR(
            value=digits if valid else None,
            valid=valid,
            normalized=digits,
            messages=() if valid else ("battle_id_invalid",),
        )

    if parser == "result":
        collapsed = re.sub(r"[^A-Z]", "", text.upper())
        result = None
        if any(token in collapsed for token in ("VICTORY", "WIN")):
            result = "VICTORY"
        elif any(token in collapsed for token in ("DEFEAT", "LOSS", "LOSE")):
            result = "DEFEAT"
        return ParsedOCR(
            value=result,
            valid=result is not None,
            normalized=collapsed,
            messages=() if result is not None else ("result_unrecognized",),
        )

    if parser == "duration":
        match = re.search(r"(\d{1,2})\s*[:.]\s*(\d{2})", text)
        if match is None:
            return ParsedOCR(None, False, text, ("duration_invalid",))
        minutes, seconds = int(match.group(1)), int(match.group(2))
        valid = minutes <= 99 and seconds <= 59
        value = f"{minutes:02d}:{seconds:02d}" if valid else None
        return ParsedOCR(value, valid, value or text, () if valid else ("duration_out_of_range",))

    if parser == "datetime":
        candidate = re.sub(r"\s+", " ", text)
        iso_match = re.search(
            r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*(\d{1,2}:\d{2}(?::\d{2})?)",
            candidate,
        )
        us_match = re.search(
            r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*(\d{1,2}:\d{2}(?::\d{2})?)",
            candidate,
        )
        if iso_match is not None:
            year, month, day, time_text = iso_match.groups()
        elif us_match is not None:
            month, day, year, time_text = us_match.groups()
        else:
            return ParsedOCR(None, False, candidate, ("datetime_invalid",))
        combined = f"{year}-{month}-{day} {time_text}"
        pattern = "%Y-%m-%d %H:%M:%S" if time_text.count(":") == 2 else "%Y-%m-%d %H:%M"
        try:
            parsed = datetime.strptime(combined, pattern)
        except ValueError:
            return ParsedOCR(None, False, combined, ("datetime_out_of_range",))
        normalized_pattern = "%Y-%m-%d %H:%M:%S" if time_text.count(":") == 2 else "%Y-%m-%d %H:%M"
        normalized = parsed.strftime(normalized_pattern)
        return ParsedOCR(normalized, True, normalized)

    if parser in {"level", "short_integer", "small_integer", "large_integer"}:
        digits = _numeric_text(text)
        if not digits:
            return ParsedOCR(None, False, digits, ("integer_invalid",))
        integer_value = int(digits)
        maximum = (
            15
            if parser == "level"
            else 99
            if parser in {"short_integer", "small_integer"}
            else 999_999
        )
        valid = 0 <= integer_value <= maximum and (parser != "level" or integer_value >= 1)
        return ParsedOCR(
            integer_value if valid else None,
            valid,
            str(integer_value),
            () if valid else ("integer_out_of_range",),
        )

    if parser == "decimal":
        number = _numeric_text(text, decimal=True)
        if number.count(".") > 1 or number in {"", "."}:
            return ParsedOCR(None, False, number, ("decimal_invalid",))
        decimal_value = float(number)
        valid = 0.0 <= decimal_value <= 100.0
        return ParsedOCR(
            decimal_value if valid else None,
            valid,
            number,
            () if valid else ("decimal_out_of_range",),
        )

    if parser == "percentage":
        digits = _numeric_text(text)
        if not digits:
            return ParsedOCR(None, False, digits, ("percentage_invalid",))
        percentage_value = int(digits)
        valid = 0 <= percentage_value <= 100
        return ParsedOCR(
            percentage_value if valid else None,
            valid,
            f"{percentage_value}%",
            () if valid else ("percentage_out_of_range",),
        )

    return ParsedOCR(value=text, valid=True, normalized=text)


__all__ = ["ParsedOCR", "parse_ocr"]
