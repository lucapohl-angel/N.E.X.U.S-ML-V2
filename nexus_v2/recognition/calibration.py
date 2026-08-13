from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_SIDES = frozenset({"ally", "enemy"})


@dataclass(frozen=True)
class HeroAcceptancePolicy:
    schema_version: int
    minimum_score: float
    default_margin: float
    side_margins: tuple[tuple[str, float], ...]
    class_margins: tuple[tuple[str, str, float], ...]
    manifest_sha256: str

    @classmethod
    def load(cls, path: Path) -> HeroAcceptancePolicy:
        raw = path.read_bytes()
        payload: Any = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported hero acceptance policy schema")
        if payload.get("passed") is not True:
            raise ValueError("hero acceptance policy did not pass promotion gates")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("hero acceptance policy payload is missing policy")
        side_payload = policy.get("side_margins")
        class_payload = policy.get("class_margins")
        if not isinstance(side_payload, dict) or not isinstance(class_payload, dict):
            raise ValueError("hero acceptance policy margins must be objects")
        side_margins = tuple(
            sorted((str(side), float(value)) for side, value in side_payload.items())
        )
        if {side for side, _ in side_margins} != _ALLOWED_SIDES:
            raise ValueError("hero acceptance policy must define ally and enemy margins")
        class_margins: list[tuple[str, str, float]] = []
        for key, value in class_payload.items():
            side, separator, hero_id = str(key).partition(":")
            if not separator or side not in _ALLOWED_SIDES or not hero_id:
                raise ValueError(f"invalid hero acceptance class key: {key}")
            class_margins.append((side, hero_id, float(value)))
        minimum_score = float(payload["minimum_score"])
        default_margin = float(payload["default_margin"])
        cls._validate_threshold("minimum score", minimum_score)
        cls._validate_threshold("default margin", default_margin)
        for side, value in side_margins:
            cls._validate_threshold(f"{side} margin", value)
        for side, hero_id, value in class_margins:
            cls._validate_threshold(f"{side}:{hero_id} margin", value)
        return cls(
            schema_version=1,
            minimum_score=minimum_score,
            default_margin=default_margin,
            side_margins=side_margins,
            class_margins=tuple(sorted(class_margins)),
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )

    @staticmethod
    def _validate_threshold(name: str, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"hero acceptance {name} must be between zero and one")

    def minimum_margin(self, *, side: str, hero_id: str) -> float:
        for candidate_side, candidate_id, value in self.class_margins:
            if candidate_side == side and candidate_id == hero_id:
                return value
        for candidate_side, value in self.side_margins:
            if candidate_side == side:
                return value
        return self.default_margin


__all__ = ["HeroAcceptancePolicy"]
