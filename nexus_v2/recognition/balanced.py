from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_SCORES = (
    "prototype_similarity",
    "catalog_similarity",
    "aligned_gray_correlation",
    "color_correlation",
    "histogram_correlation",
    "edge_correlation",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class HeroBalancedPolicy:
    """Operator-approved constrained reranking and consensus acceptance policy."""

    schema_version: int
    beta: float
    gamma: float
    top_n: int
    only_abstained: bool
    minimum_prototype: float
    minimum_rank_margin: float
    minimum_prototype_margin: float
    minimum_votes: int
    catalog_sha256: str
    prototype_manifest_sha256: str
    manifest_sha256: str

    @classmethod
    def load(cls, path: Path) -> HeroBalancedPolicy:
        raw = path.read_bytes()
        payload: Any = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported balanced hero policy schema")
        if payload.get("kind") != "constrained_consensus" or payload.get("mode") != "balanced":
            raise ValueError("balanced hero policy kind or mode mismatch")
        if payload.get("enabled") is not True:
            raise ValueError("balanced hero policy is not enabled")
        if payload.get("status") != "operator_approved":
            raise ValueError("balanced hero policy is not operator approved")
        gate = payload.get("gate")
        if not isinstance(gate, dict):
            raise ValueError("balanced hero policy is missing its consensus gate")
        beta = float(payload["beta"])
        gamma = float(payload["gamma"])
        top_n = int(payload["top_n"])
        minimum_prototype = float(gate["minimum_prototype"])
        minimum_rank_margin = float(gate["minimum_rank_margin"])
        minimum_prototype_margin = float(gate["minimum_prototype_margin"])
        minimum_votes = int(gate["minimum_votes"])
        catalog_sha256 = str(payload["catalog_sha256"])
        prototype_manifest_sha256 = str(payload["prototype_manifest_sha256"])
        for name, value in (
            ("beta", beta),
            ("gamma", gamma),
            ("minimum prototype", minimum_prototype),
            ("minimum rank margin", minimum_rank_margin),
            ("minimum prototype margin", minimum_prototype_margin),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"balanced hero policy {name} must be between zero and one")
        if not 2 <= top_n <= 5:
            raise ValueError("balanced hero policy top-n must be between two and five")
        if not 0 <= minimum_votes <= 4:
            raise ValueError("balanced hero policy minimum votes must be between zero and four")
        if _SHA256_PATTERN.fullmatch(catalog_sha256) is None:
            raise ValueError("balanced hero policy catalog SHA-256 is invalid")
        if _SHA256_PATTERN.fullmatch(prototype_manifest_sha256) is None:
            raise ValueError("balanced hero policy prototype manifest SHA-256 is invalid")
        return cls(
            schema_version=1,
            beta=beta,
            gamma=gamma,
            top_n=top_n,
            only_abstained=payload.get("only_abstained") is True,
            minimum_prototype=minimum_prototype,
            minimum_rank_margin=minimum_rank_margin,
            minimum_prototype_margin=minimum_prototype_margin,
            minimum_votes=minimum_votes,
            catalog_sha256=catalog_sha256,
            prototype_manifest_sha256=prototype_manifest_sha256,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )

    @staticmethod
    def supports(scores: Mapping[str, float]) -> bool:
        return all(
            name in scores and math.isfinite(float(scores[name])) for name in _REQUIRED_SCORES
        )

    def score(self, scores: Mapping[str, float]) -> float:
        if not self.supports(scores):
            raise ValueError("balanced hero policy requires prototype, catalog, and channel scores")
        prototype = float(scores["prototype_similarity"])
        catalog = float(scores["catalog_similarity"])
        gain = float(scores.get("preprocessing_gain", 0.0))
        return (1.0 - self.beta) * prototype + self.beta * catalog - self.gamma * gain

    @staticmethod
    def channel_votes(
        winner_scores: Mapping[str, float], runner_scores: Mapping[str, float]
    ) -> int:
        return sum(
            float(winner_scores[name]) > float(runner_scores[name])
            for name in (
                "aligned_gray_correlation",
                "color_correlation",
                "histogram_correlation",
                "edge_correlation",
            )
        )

    def accepts(
        self,
        winner_scores: Mapping[str, float],
        runner_scores: Mapping[str, float],
        *,
        rank_margin: float,
    ) -> bool:
        if not self.supports(winner_scores) or not self.supports(runner_scores):
            return False
        prototype = float(winner_scores["prototype_similarity"])
        prototype_margin = prototype - float(runner_scores["prototype_similarity"])
        votes = self.channel_votes(winner_scores, runner_scores)
        return (
            prototype >= self.minimum_prototype
            and rank_margin >= self.minimum_rank_margin
            and prototype_margin >= self.minimum_prototype_margin
            and votes >= self.minimum_votes
        )


__all__ = ["HeroBalancedPolicy"]
