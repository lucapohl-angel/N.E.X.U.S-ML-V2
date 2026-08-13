from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FEATURE_NAMES = (
    "catalog_minus_prototype",
    "aligned_minus_prototype",
    "color_minus_prototype",
    "histogram_minus_prototype",
    "edge_minus_prototype",
    "preprocessing_gain",
)


@dataclass(frozen=True)
class HeroRerankerPolicy:
    schema_version: int
    coefficients: tuple[float, ...]
    override_lead: float
    top_n: int
    only_abstained: bool
    manifest_sha256: str

    @classmethod
    def load(cls, path: Path) -> HeroRerankerPolicy:
        raw = path.read_bytes()
        payload: Any = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported hero reranker policy schema")
        if payload.get("passed") is not True:
            raise ValueError("hero reranker policy did not pass promotion gates")
        names = tuple(str(value) for value in payload.get("feature_names", ()))
        if names != _FEATURE_NAMES:
            raise ValueError("hero reranker feature schema mismatch")
        coefficients = tuple(float(value) for value in payload.get("coefficients", ()))
        if len(coefficients) != len(_FEATURE_NAMES):
            raise ValueError("hero reranker coefficient count mismatch")
        override_lead = float(payload["override_lead"])
        top_n = int(payload["top_n"])
        only_abstained = payload.get("only_abstained") is True
        if not 0.0 <= override_lead <= 1.0:
            raise ValueError("hero reranker override lead must be between zero and one")
        if not 2 <= top_n <= 5:
            raise ValueError("hero reranker top-n must be between two and five")
        return cls(
            schema_version=1,
            coefficients=coefficients,
            override_lead=override_lead,
            top_n=top_n,
            only_abstained=only_abstained,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def score(self, scores: Mapping[str, float]) -> float:
        fused = float(scores["fused_similarity"])
        prototype = float(scores.get("prototype_similarity", fused))
        values = (
            float(scores.get("catalog_similarity", fused)) - prototype,
            float(scores.get("aligned_gray_correlation", prototype)) - prototype,
            float(scores.get("color_correlation", prototype)) - prototype,
            float(scores.get("histogram_correlation", prototype)) - prototype,
            float(scores.get("edge_correlation", prototype)) - prototype,
            float(scores.get("preprocessing_gain", 0.0)),
        )
        return fused + sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients, values, strict=True)
        )


__all__ = ["HeroRerankerPolicy"]
