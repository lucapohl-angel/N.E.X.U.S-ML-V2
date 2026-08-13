"""Deterministic hero and visible equipment-slot recognition."""

from nexus_v2.recognition.balanced import HeroBalancedPolicy
from nexus_v2.recognition.calibration import HeroAcceptancePolicy
from nexus_v2.recognition.matcher import (
    ReferenceLibrary,
    VisualMatcher,
    VisualMatcherConfig,
    VisualReference,
)
from nexus_v2.recognition.modes import (
    HeroRecognitionMode,
    HeroRecognitionSetup,
    ItemRecognitionSetup,
    resolve_hero_recognition,
    resolve_item_recognition,
)
from nexus_v2.recognition.reranker import HeroRerankerPolicy

__all__ = [
    "HeroAcceptancePolicy",
    "HeroBalancedPolicy",
    "HeroRerankerPolicy",
    "HeroRecognitionMode",
    "HeroRecognitionSetup",
    "ItemRecognitionSetup",
    "ReferenceLibrary",
    "VisualMatcher",
    "VisualMatcherConfig",
    "VisualReference",
    "resolve_hero_recognition",
    "resolve_item_recognition",
]
