"""Typed UI profiles, deterministic classification, and multi-pass geometry."""

from nexus_v2.layout.cropper import SemanticCrop, build_semantic_crops
from nexus_v2.layout.profiles import (
    ProfileRegistry,
    ProfileVerification,
    ReferenceProfile,
    ScreenType,
)
from nexus_v2.layout.solver import GeometryResult, solve_geometry

__all__ = [
    "GeometryResult",
    "ProfileRegistry",
    "ProfileVerification",
    "ReferenceProfile",
    "ScreenType",
    "SemanticCrop",
    "build_semantic_crops",
    "solve_geometry",
]
