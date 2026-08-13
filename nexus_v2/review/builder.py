"""Build engine-drafted, crop-addressable review queues for one private game."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from pydantic import JsonValue

from nexus_v2.engine import ExtractionArtifacts, NexusV2Engine
from nexus_v2.input import ImageDecoder
from nexus_v2.layout import GeometryResult, ProfileRegistry, build_semantic_crops, solve_geometry
from nexus_v2.layout.cropper import SemanticCrop
from nexus_v2.layout.profiles import FieldKind
from nexus_v2.ocr.normalize import parse_ocr
from nexus_v2.recognition.modes import resolve_hero_recognition, resolve_item_recognition
from nexus_v2.review.dataset import (
    GameCapture,
    ReviewRecord,
    ReviewState,
    save_review_state,
    utc_now,
)
from nexus_v2.schemas.result import (
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    HeroResult,
    ItemResult,
)

ProgressCallback = Callable[[str], None]
_VISUAL_WORKER_ENGINE: NexusV2Engine | None = None
_VISUAL_KINDS = frozenset({FieldKind.HERO, FieldKind.ITEM})


def _extract_visual_source(source: Path) -> ExtractionResult:
    if _VISUAL_WORKER_ENGINE is None:
        raise RuntimeError("visual worker engine was not initialized before fork")
    return _VISUAL_WORKER_ENGINE.extract(source, field_kinds=_VISUAL_KINDS)


def _record_id(crop: SemanticCrop) -> str:
    side = crop.side.value if crop.side is not None else "global"
    row = "none" if crop.row is None else str(crop.row)
    slot = "none" if crop.slot is None else str(crop.slot)
    return (
        f"{Path(crop.screen_type.value).stem}:{crop.kind.value}:{side}:{row}:{slot}:{crop.field_id}"
    )


def _candidate_labels(candidates: tuple[object, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for candidate in candidates:
        candidate_id = getattr(candidate, "candidate_id", None)
        raw = getattr(candidate, "raw", None)
        if isinstance(candidate_id, str):
            result.append(f"{candidate_id} — {raw}" if raw not in {None, ""} else candidate_id)
    return tuple(result)


def _entity_record(
    *,
    screenshot: str,
    crop: SemanticCrop,
    entity: HeroResult | ItemResult,
    review_reason: str | None = None,
) -> ReviewRecord:
    entity_id = entity.hero_id if isinstance(entity, HeroResult) else entity.item_id
    if entity.status.value == "empty":
        prediction: JsonValue = None
        display = "EMPTY SLOT"
    else:
        prediction = entity_id
        display = f"{entity_id} — {entity.name}" if entity_id is not None else "UNKNOWN"
    return ReviewRecord(
        record_id=f"{Path(screenshot).stem}:{_record_id(crop)}",
        screenshot=screenshot,
        field_id=crop.field_id,
        kind=crop.kind.value,
        side=crop.side.value if crop.side is not None else None,
        row=crop.row,
        slot=crop.slot,
        source_box=crop.tight_box,
        prediction=prediction,
        display_prediction=display,
        extraction_status=entity.status.value,
        review_reason=review_reason,
        confidence=entity.confidence,
        candidates=_candidate_labels(entity.candidates),
        candidate_evidence=entity.candidates,
    )


def _item_exception_reasons(result: ExtractionResult) -> dict[tuple[str, int, int], str]:
    reasons: dict[tuple[str, int, int], set[str]] = {}

    def add(side: str, row: int, slot: int, reason: str) -> None:
        reasons.setdefault((side, row, slot), set()).add(reason)

    teams = {team.side: team for team in result.teams}
    for team in result.teams:
        for player in team.players:
            if len(player.items) == 7:
                for item in player.items:
                    add(team.side, player.row, item.slot, "seven-item row verification")
            for item in player.items:
                if item.status not in {ExtractionStatus.OK, ExtractionStatus.EMPTY}:
                    add(team.side, player.row, item.slot, f"item {item.status.value}")

    for warning in result.warnings:
        if not any(marker in warning for marker in ("floryn", "seven_item", "flower_of_hope")):
            continue
        side = warning.split(".", maxsplit=1)[0]
        warning_team = teams.get(side)
        if warning_team is None:
            continue
        row_match = re.search(r"\.row(\d+)\.", warning)
        target_rows = (
            {int(row_match.group(1))}
            if row_match is not None
            else {player.row for player in warning_team.players}
        )
        for player in warning_team.players:
            if player.row not in target_rows:
                continue
            for item in player.items:
                add(side, player.row, item.slot, f"semantic warning: {warning}")
    return {key: "; ".join(sorted(values)) for key, values in reasons.items()}


def _field_record(
    *, screenshot: str, crop: SemanticCrop, extracted: ExtractedField
) -> ReviewRecord:
    display = "UNKNOWN" if extracted.value is None else str(extracted.value)
    suggestion: JsonValue = None
    if extracted.value is None and crop.parser is not None:
        candidate_raws = [extracted.raw]
        candidate_raws.extend(getattr(candidate, "raw", None) for candidate in extracted.candidates)
        for raw in candidate_raws:
            if not isinstance(raw, str):
                continue
            parsed = parse_ocr(raw, parser=crop.parser)
            if parsed.valid:
                suggestion = parsed.value
                break
    return ReviewRecord(
        record_id=f"{Path(screenshot).stem}:{_record_id(crop)}",
        screenshot=screenshot,
        field_id=crop.field_id,
        kind=crop.kind.value,
        side=crop.side.value if crop.side is not None else None,
        row=crop.row,
        slot=crop.slot,
        source_box=crop.tight_box,
        parser=crop.parser,
        prediction=extracted.value,
        suggested_value=suggestion,
        display_prediction=display,
        extraction_status=extracted.status.value,
        confidence=extracted.confidence,
        candidates=_candidate_labels(extracted.candidates),
        candidate_evidence=extracted.candidates,
    )


def build_review_state(
    capture: GameCapture,
    *,
    project_root: Path,
    hero_prototypes: Path | None = None,
    item_prototypes: Path | None = None,
    hero_recognition_mode: str = "balanced",
    use_rapidocr: bool = True,
    visual_only: bool = False,
    item_exceptions_only: bool = False,
    progress: ProgressCallback | None = None,
) -> ReviewState:
    if item_exceptions_only and not visual_only:
        raise ValueError("item-exceptions-only review requires visual-only mode")
    if not capture.complete_capture:
        raise ValueError("capture is incomplete: " + ", ".join(capture.missing_files()))
    notify = progress or (lambda _message: None)
    root = project_root.resolve()
    catalog_path = root / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
    hero_setup = resolve_hero_recognition(
        project_root=root,
        catalog_path=catalog_path,
        mode=hero_recognition_mode,
        hero_prototypes=hero_prototypes,
    )
    item_setup = resolve_item_recognition(
        project_root=root,
        catalog_path=catalog_path,
        item_prototypes=item_prototypes,
    )
    registry = ProfileRegistry.load(root / "profiles")
    notify("Loading deterministic hero/item references and OCR backends…")
    engine = NexusV2Engine(
        profiles_root=root / "profiles",
        catalog_path=catalog_path,
        hero_prototypes=hero_setup.prototype_manifest,
        item_prototypes=item_setup.prototype_manifest,
        hero_matcher_config=hero_setup.matcher_config,
        use_rapidocr=use_rapidocr,
    )
    source_files = capture.source_files
    sources = tuple(capture.image_path(filename) for filename in source_files)
    if visual_only:
        scope_text = "heroes plus item exceptions" if item_exceptions_only else "heroes and items"
        notify(f"Running {scope_text} matching on {len(sources)} screenshots (OCR disabled)…")
        global _VISUAL_WORKER_ENGINE
        _VISUAL_WORKER_ENGINE = engine
        # Six workers keep the cumulative batches01-06 feature bank below the
        # measured workstation memory ceiling (about 1.7 GB RSS per worker).
        worker_count = min(6, len(sources))
        try:
            with ProcessPoolExecutor(
                max_workers=worker_count,
                mp_context=get_context("fork"),
            ) as executor:
                results = tuple(executor.map(_extract_visual_source, sources))
        finally:
            _VISUAL_WORKER_ENGINE = None
        extraction_artifacts: tuple[ExtractionArtifacts, ...] | None = None
    else:
        notify("Running all five screenshots through the local engine…")
        results, extraction_artifacts = engine.extract_match_with_artifacts(sources)
    records: list[ReviewRecord] = []
    item_inferred = 0
    item_queued = 0
    item_status_counts: Counter[str] = Counter()
    item_seven_rows = 0
    screens_with_semantic_warnings = 0
    item_audit_screens: dict[str, JsonValue] = {}
    decoder = ImageDecoder() if visual_only else None
    for index, (screenshot, source, result) in enumerate(
        zip(source_files, sources, results, strict=True)
    ):
        notify(f"Preparing review fields for {screenshot}…")
        geometry: GeometryResult | None
        if extraction_artifacts is None:
            if decoder is None:
                raise RuntimeError("visual review decoder is unavailable")
            decoded = decoder.decode(source)
            geometry = solve_geometry(decoded, registry)
            if geometry.status is ExtractionStatus.OK and geometry.profile_id is not None:
                loaded = registry.get(geometry.profile_id)
                crops = build_semantic_crops(decoded, loaded, geometry)
            else:
                crops = ()
        else:
            artifact = extraction_artifacts[index]
            geometry = artifact.geometry
            crops = artifact.crops
        viewport_box = (
            geometry.viewport.box
            if geometry is not None and geometry.viewport is not None
            else result.source.viewport
        )
        geometry_status = geometry.status if geometry is not None else result.status
        geometry_confidence = (
            geometry.screen.score if geometry is not None else result.source.geometry.confidence
        )
        geometry_reasons = geometry.reasons if geometry is not None else result.warnings
        screen_value = result.screen_type
        if not visual_only:
            records.append(
                ReviewRecord(
                    record_id=f"{Path(screenshot).stem}:geometry:screen_type",
                    screenshot=screenshot,
                    field_id="screen_type_and_geometry",
                    kind="geometry",
                    source_box=viewport_box,
                    prediction={
                        "screen_type": screen_value,
                        "viewport": list(viewport_box) if viewport_box is not None else None,
                    },
                    display_prediction=screen_value or "UNSUPPORTED/UNKNOWN GEOMETRY",
                    extraction_status=geometry_status.value,
                    confidence=geometry_confidence,
                    candidates=tuple(geometry_reasons),
                )
            )
        if geometry is None or geometry.status is not ExtractionStatus.OK:
            continue
        teams = {team.side: team for team in result.teams}
        item_exception_reasons = _item_exception_reasons(result) if item_exceptions_only else {}
        if item_exceptions_only:
            screen_status_counts: Counter[str] = Counter()
            screen_seven_rows = 0
            for team_result in result.teams:
                for player_result in team_result.players:
                    screen_seven_rows += int(len(player_result.items) == 7)
                    screen_status_counts.update(item.status.value for item in player_result.items)
            semantic_warnings: list[JsonValue] = [
                warning
                for warning in result.warnings
                if any(marker in warning for marker in ("floryn", "seven_item", "flower_of_hope"))
            ]
            screen_inferred = sum(screen_status_counts.values())
            item_inferred += screen_inferred
            item_queued += len(item_exception_reasons)
            item_status_counts.update(screen_status_counts)
            item_seven_rows += screen_seven_rows
            screens_with_semantic_warnings += int(bool(semantic_warnings))
            screen_audit: dict[str, JsonValue] = {
                "inferred": screen_inferred,
                "queued": len(item_exception_reasons),
                "status_counts": dict(screen_status_counts),
                "seven_item_rows": screen_seven_rows,
                "semantic_warnings": semantic_warnings,
            }
            item_audit_screens[screenshot] = screen_audit
        for crop in crops:
            if visual_only and crop.kind not in {FieldKind.HERO, FieldKind.ITEM}:
                continue
            if crop.kind is FieldKind.METADATA:
                extracted = result.metadata.get(crop.field_id)
                if extracted is not None:
                    records.append(
                        _field_record(screenshot=screenshot, crop=crop, extracted=extracted)
                    )
                continue
            if crop.side is None or crop.row is None:
                continue
            team = teams.get(crop.side.value)
            if team is None:
                continue
            player = next(
                (candidate for candidate in team.players if candidate.row == crop.row), None
            )
            if player is None:
                continue
            if crop.kind is FieldKind.HERO:
                if player.hero is not None:
                    records.append(
                        _entity_record(screenshot=screenshot, crop=crop, entity=player.hero)
                    )
            elif crop.kind is FieldKind.ITEM:
                if crop.slot is not None and crop.slot < len(player.items):
                    key = (crop.side.value, crop.row, crop.slot)
                    if item_exceptions_only and key not in item_exception_reasons:
                        continue
                    records.append(
                        _entity_record(
                            screenshot=screenshot,
                            crop=crop,
                            entity=player.items[crop.slot],
                            review_reason=item_exception_reasons.get(key),
                        )
                    )
            elif crop.kind is FieldKind.OCR:
                extracted = player.fields.get(crop.field_id)
                if extracted is not None:
                    records.append(
                        _field_record(screenshot=screenshot, crop=crop, extracted=extracted)
                    )
    identifiers = [record.record_id for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("review queue contains duplicate record IDs")
    now = utc_now()
    review_scope = (
        "hero_plus_item_exceptions"
        if item_exceptions_only
        else "hero_item_only"
        if visual_only
        else "full_match"
    )
    item_inference_audit: JsonValue = None
    if item_exceptions_only:
        status_json: dict[str, JsonValue] = {
            status: count for status, count in sorted(item_status_counts.items())
        }
        item_inference_audit = {
            "inferred": item_inferred,
            "queued": item_queued,
            "status_counts": status_json,
            "seven_item_rows": item_seven_rows,
            "screens_with_semantic_warnings": screens_with_semantic_warnings,
            "per_screenshot": item_audit_screens,
        }
    state = ReviewState(
        family_id=capture.family_id,
        game_id=capture.game_id,
        source_hashes=capture.source_hashes(),
        engine={
            "mode": "local_draft",
            "rapidocr": use_rapidocr,
            "profile_policy": "verified_runtime_profiles",
            "catalog": "mlbb-user-approved-2026.08.01.2",
            "private_match_prototypes": True,
            "hero_recognition_mode": hero_setup.mode,
            "hero_recognition_policy_sha256": hero_setup.policy_sha256,
            "item_prototype_manifest_sha256": item_setup.manifest_sha256,
            "automatic_truth_updates": False,
            "automatic_prototype_updates": False,
            "review_scope": review_scope,
            "item_inference_audit": item_inference_audit,
        },
        records=records,
        created_at=now,
        updated_at=now,
    )
    save_review_state(capture, state)
    notify(f"Draft ready: {len(records)} fields require review.")
    return state


__all__ = ["build_review_state"]
