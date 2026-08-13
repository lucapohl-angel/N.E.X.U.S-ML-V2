"""Export completed private review decisions as readable, hash-traceable TXT truth."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nexus_v2.review.dataset import (
    GameCapture,
    ReviewDecision,
    ReviewRecord,
    ReviewState,
    utc_now,
)

FINAL_DECISIONS = {
    ReviewDecision.ACCEPTED,
    ReviewDecision.EDITED,
    ReviewDecision.UNKNOWN,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _display_maps(catalog_path: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    if catalog_path is None:
        return {}, {}
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return (
        {str(entity["id"]): str(entity["canonical_name"]) for entity in payload["heroes"]},
        {str(entity["id"]): str(entity["canonical_name"]) for entity in payload["items"]},
    )


def _format_value(value: object) -> str:
    if value is None:
        return "<UNKNOWN_OR_EMPTY>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _truth(record: ReviewRecord) -> object:
    if record.decision not in FINAL_DECISIONS:
        raise ValueError(f"record {record.record_id} is not finalized")
    if record.decision is ReviewDecision.UNKNOWN:
        return None
    return record.truth_value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _screen_truth(
    *,
    capture: GameCapture,
    state: ReviewState,
    screenshot: str,
    hero_names: dict[str, str],
    item_names: dict[str, str],
) -> str:
    records = [record for record in state.records if record.screenshot == screenshot]
    geometry = [record for record in records if record.kind == "geometry"]
    metadata = [record for record in records if record.kind == "metadata"]
    players: dict[tuple[str, int], list[ReviewRecord]] = defaultdict(list)
    for record in records:
        if record.side is not None and record.row is not None:
            players[(record.side, record.row)].append(record)

    lines = [
        "NEXUS_ML_V2_REVIEWED_TRUTH",
        "format_version: 1.0",
        f"family_id: {capture.family_id}",
        f"game_id: {capture.game_id}",
        f"source_file: {screenshot}",
        f"source_sha256: {state.source_hashes[screenshot]}",
        (
            "review_status: human_approved_scoped"
            if state.engine.get("review_scope") == "hero_plus_item_exceptions"
            else "review_status: human_approved"
        ),
        f"review_scope: {state.engine.get('review_scope', 'full_match')}",
        "truth_origin: prediction_assisted_field_review",
        "",
        "[SCREEN]",
    ]
    for record in geometry:
        lines.append(f"{record.field_id}: {_format_value(_truth(record))}")
    lines.extend(("", "[MATCH]"))
    for record in metadata:
        lines.append(f"{record.field_id}: {_format_value(_truth(record))}")

    for side in ("ally", "enemy"):
        for row in range(5):
            lines.extend(("", f"[{side.upper()}_PLAYER_{row + 1}]", f"row: {row + 1}"))
            row_records = players.get((side, row), [])
            heroes = [record for record in row_records if record.kind == "hero"]
            for record in heroes:
                value = _truth(record)
                lines.append(f"hero_id: {_format_value(value)}")
                if isinstance(value, str) and value in hero_names:
                    lines.append(f"hero_name: {hero_names[value]}")
            for record in row_records:
                if record.kind == "ocr":
                    lines.append(f"{record.field_id}: {_format_value(_truth(record))}")
            for record in sorted(
                (record for record in row_records if record.kind == "item"),
                key=lambda candidate: -1 if candidate.slot is None else candidate.slot,
            ):
                slot = 0 if record.slot is None else record.slot + 1
                value = _truth(record)
                if value is None:
                    marker = "<UNKNOWN>" if record.decision is ReviewDecision.UNKNOWN else "<EMPTY>"
                    lines.append(f"item{slot}_id: {marker}")
                else:
                    lines.append(f"item{slot}_id: {_format_value(value)}")
                    if isinstance(value, str) and value in item_names:
                        lines.append(f"item{slot}_name: {item_names[value]}")
    return "\n".join(lines) + "\n"


def export_review_truth(
    capture: GameCapture,
    state: ReviewState,
    *,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    if not state.complete:
        counts = state.counts()
        raise ValueError(
            "review is incomplete: "
            f"{counts[ReviewDecision.PENDING.value]} pending, "
            f"{counts[ReviewDecision.SKIPPED.value]} skipped"
        )
    if state.source_hashes != capture.source_hashes():
        raise ValueError("cannot export truth because source screenshot hashes changed")
    hero_names, item_names = _display_maps(catalog_path)
    state_payload = capture.state_path.read_bytes()
    state_digest = _sha256_bytes(state_payload)
    manifest_path = capture.review_dir / "truth_export_manifest.json"
    previous_files: dict[str, dict[str, str]] = {}
    if manifest_path.is_file():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_files = {
            str(entry["screenshot"]): entry for entry in previous_manifest.get("files", [])
        }
    files: list[dict[str, str]] = []
    for screenshot in capture.source_files:
        truth_name = f"{Path(screenshot).stem}.txt"
        truth_path = capture.path / truth_name
        payload = _screen_truth(
            capture=capture,
            state=state,
            screenshot=screenshot,
            hero_names=hero_names,
            item_names=item_names,
        ).encode("utf-8")
        if truth_path.is_file():
            previous = previous_files.get(screenshot)
            relative_truth = str(truth_path.relative_to(capture.path))
            reviewer_owned = (
                previous is not None
                and previous.get("truth") == relative_truth
                and previous.get("truth_sha256") == _sha256_bytes(truth_path.read_bytes())
            )
            if not reviewer_owned:
                truth_path = (
                    capture.review_dir / "exports" / f"{Path(screenshot).stem}.reviewed.txt"
                )
        if truth_path.is_file():
            previous = previous_files.get(screenshot)
            relative_truth = str(truth_path.relative_to(capture.path))
            reviewer_owned = (
                previous is not None
                and previous.get("truth") == relative_truth
                and previous.get("truth_sha256") == _sha256_bytes(truth_path.read_bytes())
            )
            if not reviewer_owned and truth_path.read_bytes() != payload:
                truth_path = (
                    capture.review_dir
                    / "exports"
                    / (f"{Path(screenshot).stem}.reviewed.{state_digest[:12]}.txt")
                )
                if truth_path.is_file() and truth_path.read_bytes() != payload:
                    raise ValueError(
                        f"protected reviewed truth export already exists: {truth_path}"
                    )
        _write_atomic(truth_path, payload)
        relative_truth = str(truth_path.relative_to(capture.path))
        files.append(
            {
                "screenshot": screenshot,
                "screenshot_sha256": state.source_hashes[screenshot],
                "truth": relative_truth,
                "truth_sha256": _sha256_bytes(payload),
            }
        )
    manifest = {
        "schema_version": 1,
        "family_id": capture.family_id,
        "game_id": capture.game_id,
        "exported_at": utc_now().isoformat(),
        "review_state": str(capture.state_path.relative_to(capture.path)),
        "review_state_sha256": state_digest,
        "files": files,
    }
    _write_atomic(
        manifest_path,
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    return manifest


TruthExporter = Callable[[GameCapture, ReviewState], object]

__all__ = ["TruthExporter", "export_review_truth"]
