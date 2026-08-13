"""Subprocess-isolated adapter for the immutable V1 baseline."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from nexus_v2.adapters.base import (
    BenchmarkPrediction,
    EngineCapabilities,
    EngineRun,
    FieldPrediction,
    HeroPrediction,
    ItemPrediction,
    RowPrediction,
)
from nexus_v2.schemas.annotation import BenchmarkSample, OccupancyStatus, TeamSide
from nexus_v2.schemas.result import ConfidenceSemantics, ExtractionStatus

V1_COMMIT = "55cfff72236c1152eac54ac038a225154b209950"
V1_TAG = "v1-baseline-2026-07-31"


class LegacyV1ExecutionError(RuntimeError):
    """Raised when the isolated legacy process cannot produce a valid result."""


def _legacy_hero_id(value: object) -> str | None:
    if isinstance(value, int) and value > 0:
        return f"v1-hero-{value:03d}"
    return None


def _legacy_item_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return f"v1-item:{value}"
    return None


def _semantic_json(result: dict[str, Any]) -> dict[str, Any]:
    """Remove V1 run-volatile metadata before full semantic JSON comparison."""

    copied = copy.deepcopy(result)
    metadata = copied.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "screenshot_path",
            "timestamp",
            "processing_time_seconds",
            "mapping_file",
        ):
            metadata.pop(key, None)
    return copied


def _normalise(result: dict[str, Any]) -> BenchmarkPrediction:
    rows: list[RowPrediction] = []
    heroes: list[HeroPrediction] = []
    items: list[ItemPrediction] = []
    fields: list[FieldPrediction] = []

    metadata = result.get("metadata")
    if isinstance(metadata, dict) and "battle_id" in metadata:
        battle_id = metadata.get("battle_id")
        fields.append(
            FieldPrediction(
                field="battle_id",
                value=battle_id if isinstance(battle_id, str | int | float | bool) else None,
                raw=str(battle_id) if battle_id is not None else None,
                status=(ExtractionStatus.OK if battle_id is not None else ExtractionStatus.UNKNOWN),
                confidence=0.0,
                confidence_semantics=ConfidenceSemantics.LEGACY_UNCALIBRATED,
            )
        )

    for team, result_key in ((TeamSide.ALLY, "allies"), (TeamSide.ENEMY, "enemies")):
        players = result.get(result_key, [])
        if not isinstance(players, list):
            continue
        for fallback_row, player in enumerate(players):
            if not isinstance(player, dict):
                continue
            player_number = player.get("player_number")
            row = player_number - 1 if isinstance(player_number, int) else fallback_row
            if not 0 <= row <= 4:
                continue

            coordinates = player.get("row_coordinates")
            if isinstance(coordinates, dict):
                y_start = coordinates.get("y_start")
                y_end = coordinates.get("y_end")
                if isinstance(y_start, int) and isinstance(y_end, int) and y_end > y_start:
                    rows.append(RowPrediction(team=team, row=row, y_start=y_start, y_end=y_end))

            hero = player.get("hero")
            if isinstance(hero, dict):
                class_id = _legacy_hero_id(hero.get("hero_id"))
                confidence = hero.get("confidence")
                score = float(confidence) if isinstance(confidence, int | float) else None
                heroes.append(
                    HeroPrediction(
                        team=team,
                        row=row,
                        class_id=class_id,
                        status=ExtractionStatus.OK if class_id else ExtractionStatus.UNKNOWN,
                        confidence=score,
                        confidence_semantics=(
                            ConfidenceSemantics.LEGACY_UNCALIBRATED if score is not None else None
                        ),
                        candidates=(class_id,) if class_id else (),
                    )
                )

            player_items = player.get("items", [])
            if isinstance(player_items, list):
                for fallback_slot, item in enumerate(player_items):
                    if not isinstance(item, dict):
                        continue
                    legacy_slot = item.get("slot")
                    slot = legacy_slot - 1 if isinstance(legacy_slot, int) else fallback_slot
                    if not 0 <= slot <= 5:
                        continue
                    class_id = _legacy_item_id(item.get("item_name"))
                    is_empty = item.get("is_empty") is True
                    if is_empty:
                        occupancy = OccupancyStatus.EMPTY
                        status = ExtractionStatus.EMPTY
                    elif class_id:
                        occupancy = OccupancyStatus.OCCUPIED
                        status = ExtractionStatus.OK
                    else:
                        occupancy = OccupancyStatus.UNKNOWN
                        status = ExtractionStatus.UNKNOWN
                    confidence = item.get("confidence")
                    score = float(confidence) if isinstance(confidence, int | float) else None
                    items.append(
                        ItemPrediction(
                            team=team,
                            row=row,
                            slot=slot,
                            occupancy=occupancy,
                            class_id=class_id,
                            status=status,
                            confidence=score,
                            confidence_semantics=(
                                ConfidenceSemantics.LEGACY_UNCALIBRATED
                                if score is not None
                                else None
                            ),
                            candidates=(class_id,) if class_id else (),
                        )
                    )

            structural = {"player_number", "team", "row_coordinates", "hero", "items", "error"}
            for field_name, field in player.items():
                if field_name in structural or not isinstance(field, dict) or "value" not in field:
                    continue
                value = field.get("value")
                confidence = field.get("confidence")
                score = float(confidence) if isinstance(confidence, int | float) else None
                fields.append(
                    FieldPrediction(
                        field=field_name,
                        value=value if isinstance(value, str | int | float | bool) else None,
                        raw=str(value) if value is not None else None,
                        status=ExtractionStatus.OK
                        if value is not None
                        else ExtractionStatus.UNKNOWN,
                        team=team,
                        row=row,
                        confidence=score,
                        confidence_semantics=(
                            ConfidenceSemantics.LEGACY_UNCALIBRATED if score is not None else None
                        ),
                    )
                )

    return BenchmarkPrediction(
        rows=tuple(rows),
        heroes=tuple(heroes),
        items=tuple(items),
        fields=tuple(fields),
        semantic_json=_semantic_json(result),
        capabilities=EngineCapabilities(
            hero_candidate_depth=1,
            item_candidate_depth=1,
            calibrated_confidence=False,
        ),
    )


class LegacyV1Adapter:
    """Run each V1 sample in a fresh interpreter to avoid global config leakage."""

    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        tesseract_cmd: str | Path | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.repository_root = (
            repository_root.resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.tesseract_cmd = str(tesseract_cmd) if tesseract_cmd is not None else None
        self.timeout_seconds = timeout_seconds

    @property
    def engine_id(self) -> str:
        return "legacy-v1"

    @property
    def engine_version(self) -> str:
        return f"{V1_TAG}@{V1_COMMIT}"

    def extract(self, *, sample: BenchmarkSample, image_path: Path) -> EngineRun:
        if sample.annotation is None:
            raise LegacyV1ExecutionError("sample has no approved annotation")

        command = [
            sys.executable,
            "-m",
            "nexus_v2.legacy_runner",
            "--image",
            str(image_path),
            "--screen",
            sample.annotation.screen_type.value,
        ]
        if self.tesseract_cmd:
            command.extend(["--tesseract-cmd", self.tesseract_cmd])

        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{self.repository_root}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(self.repository_root)
        )
        completed = subprocess.run(
            command,
            cwd=self.repository_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip()[-4000:]
            raise LegacyV1ExecutionError(
                f"V1 exited with {completed.returncode}: {diagnostic or 'no diagnostic output'}"
            )
        if len(completed.stdout.encode("utf-8")) > 50 * 1024 * 1024:
            raise LegacyV1ExecutionError("V1 result exceeded the 50 MiB output limit")

        try:
            envelope = json.loads(completed.stdout)
            result = envelope["result"]
            latency_ms = float(envelope["latency_ms"])
            peak_memory = envelope.get("peak_memory_mib")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LegacyV1ExecutionError(f"V1 returned an invalid envelope: {exc}") from exc

        if not isinstance(result, dict):
            raise LegacyV1ExecutionError("V1 result is not a JSON object")
        diagnostics = tuple(line for line in completed.stderr.splitlines() if line.strip())
        return EngineRun(
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            prediction=_normalise(result),
            raw_result=result,
            latency_ms=latency_ms,
            peak_memory_mib=float(peak_memory) if peak_memory is not None else None,
            diagnostics=diagnostics,
        )
