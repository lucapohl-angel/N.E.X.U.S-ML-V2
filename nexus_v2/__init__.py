"""Public interfaces for N.E.X.U.S-ML V2."""

from nexus_v2.adapters import EngineAdapter, LegacyV1Adapter
from nexus_v2.catalog import (
    AssetProvenance,
    CatalogAuditReport,
    CatalogDiff,
    CatalogSnapshot,
    HeroRecord,
    ItemRecord,
    ModelCatalogCompatibility,
    ReviewStatus,
    VisualVersion,
)
from nexus_v2.schemas import AnnotationManifest, ExtractionResult, ExtractionStatus

__all__ = [
    "AnnotationManifest",
    "AssetProvenance",
    "CatalogAuditReport",
    "CatalogDiff",
    "CatalogSnapshot",
    "EngineAdapter",
    "ExtractionResult",
    "ExtractionStatus",
    "HeroRecord",
    "ItemRecord",
    "LegacyV1Adapter",
    "ModelCatalogCompatibility",
    "ReviewStatus",
    "VisualVersion",
]

__version__ = "2.0.0a0"
