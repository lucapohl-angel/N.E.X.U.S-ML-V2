from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nexus_v2.recognition.balanced import HeroBalancedPolicy
from nexus_v2.recognition.calibration import HeroAcceptancePolicy
from nexus_v2.recognition.matcher import VisualMatcherConfig
from nexus_v2.recognition.reranker import HeroRerankerPolicy

HeroRecognitionMode = Literal["original", "strict", "balanced"]
_MODES = frozenset({"original", "strict", "balanced"})
_PREPROCESSING_VIEWS = ("clahe_luma", "gamma_085", "gamma_115", "unsharp")
_CURRENT_PROTOTYPES = Path(
    "data/private/recognition_prototypes/hero-catalog-batches01-07-v1/hero/manifest.json"
)
_CURRENT_ITEM_PROTOTYPES = Path(
    "data/private/recognition_prototypes/family-01-v1/item/manifest.json"
)
_STRICT_BUNDLE = Path(
    "data/private/recognition_policies/hero-ally-preprocess-rerank-calibration-v1"
)
_BALANCED_POLICY = Path("data/private/recognition_policies/hero-balanced-v1/policy.json")


@dataclass(frozen=True)
class HeroRecognitionSetup:
    mode: HeroRecognitionMode
    prototype_manifest: Path
    matcher_config: VisualMatcherConfig
    policy_sha256: str | None


@dataclass(frozen=True)
class ItemRecognitionSetup:
    prototype_manifest: Path
    manifest_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolved_file(root: Path, relative: Path) -> Path:
    path = (root / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"hero recognition artifact is missing: {path}")
    return path


def _mode(value: str) -> HeroRecognitionMode:
    if value not in _MODES:
        raise ValueError(f"unknown hero recognition mode: {value}")
    if value == "original":
        return "original"
    if value == "strict":
        return "strict"
    return "balanced"


def _preprocessed_config(
    *,
    balanced: HeroBalancedPolicy | None = None,
    acceptance: HeroAcceptancePolicy | None = None,
    reranker: HeroRerankerPolicy | None = None,
) -> VisualMatcherConfig:
    return VisualMatcherConfig(
        hero_preprocessing_views=_PREPROCESSING_VIEWS,
        hero_preprocessing_sides=("ally",),
        preprocessing_bonus_weight=0.45,
        preprocessing_rerank_top_n=5,
        hero_balanced_policy=balanced,
        hero_acceptance_policy=acceptance,
        hero_reranker_policy=reranker,
    )


def resolve_hero_recognition(
    *,
    project_root: Path,
    catalog_path: Path,
    mode: str = "balanced",
    hero_prototypes: Path | None = None,
) -> HeroRecognitionSetup:
    root = project_root.resolve()
    resolved_mode = _mode(mode)
    catalog = catalog_path.resolve()
    if not catalog.is_file():
        raise FileNotFoundError(f"hero catalog is missing: {catalog}")
    prototypes = (
        hero_prototypes.expanduser().resolve()
        if hero_prototypes is not None
        else _resolved_file(root, _CURRENT_PROTOTYPES)
    )
    if not prototypes.is_file():
        raise FileNotFoundError(f"hero prototype manifest is missing: {prototypes}")
    if resolved_mode == "original":
        return HeroRecognitionSetup(
            mode=resolved_mode,
            prototype_manifest=prototypes,
            matcher_config=VisualMatcherConfig(),
            policy_sha256=None,
        )
    if resolved_mode == "balanced":
        policy = HeroBalancedPolicy.load(_resolved_file(root, _BALANCED_POLICY))
        if _sha256(catalog) != policy.catalog_sha256:
            raise ValueError("balanced hero policy catalog SHA-256 mismatch")
        if _sha256(prototypes) != policy.prototype_manifest_sha256:
            raise ValueError("balanced hero policy prototype manifest SHA-256 mismatch")
        return HeroRecognitionSetup(
            mode=resolved_mode,
            prototype_manifest=prototypes,
            matcher_config=_preprocessed_config(balanced=policy),
            policy_sha256=policy.manifest_sha256,
        )
    strict_root = _resolved_file(root, _STRICT_BUNDLE / "manifest.json").parent
    strict_manifest = json.loads((strict_root / "manifest.json").read_text(encoding="utf-8"))
    expected_prototype = str(strict_manifest["prototype_library"]["sha256"])
    if _sha256(prototypes) != expected_prototype:
        raise ValueError("strict hero policy prototype manifest SHA-256 mismatch")
    acceptance = HeroAcceptancePolicy.load(strict_root / "acceptance.json")
    reranker = HeroRerankerPolicy.load(strict_root / "reranker.json")
    policy_sha256 = hashlib.sha256(
        (acceptance.manifest_sha256 + reranker.manifest_sha256).encode("ascii")
    ).hexdigest()
    return HeroRecognitionSetup(
        mode=resolved_mode,
        prototype_manifest=prototypes,
        matcher_config=_preprocessed_config(acceptance=acceptance, reranker=reranker),
        policy_sha256=policy_sha256,
    )


def resolve_item_recognition(
    *,
    project_root: Path,
    catalog_path: Path,
    item_prototypes: Path | None = None,
) -> ItemRecognitionSetup:
    """Resolve the reviewed item references used by production and review drafts."""

    root = project_root.resolve()
    catalog = catalog_path.resolve()
    if not catalog.is_file():
        raise FileNotFoundError(f"item catalog is missing: {catalog}")
    prototypes = (
        item_prototypes.expanduser().resolve()
        if item_prototypes is not None
        else (root / _CURRENT_ITEM_PROTOTYPES).resolve()
    )
    if not prototypes.is_file():
        raise FileNotFoundError(f"item prototype manifest is missing: {prototypes}")
    payload = json.loads(prototypes.read_text(encoding="utf-8"))
    if payload.get("kind") != "item":
        raise ValueError("item prototype manifest has the wrong kind")
    if payload.get("catalog_sha256") != _sha256(catalog):
        raise ValueError("item prototype manifest catalog SHA-256 mismatch")
    return ItemRecognitionSetup(
        prototype_manifest=prototypes,
        manifest_sha256=_sha256(prototypes),
    )


__all__ = [
    "HeroRecognitionMode",
    "HeroRecognitionSetup",
    "ItemRecognitionSetup",
    "resolve_hero_recognition",
    "resolve_item_recognition",
]
