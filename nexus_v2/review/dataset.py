"""Private capture discovery and durable field-review state."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from nexus_v2.schemas.result import CandidateEvidence

SCREEN_STEMS: tuple[str, ...] = (
    "hero_item_screen",
    "overall_screen",
    "dps_screen",
    "farm_screen",
    "team_screen",
)
SCREEN_SUFFIXES = (".jpeg", ".jpg", ".png")
SCREEN_FILES: tuple[str, ...] = tuple(f"{stem}.jpeg" for stem in SCREEN_STEMS)
VISUAL_BATCH_PREFIX = "hero_item_"
VISUAL_BATCH_SUFFIXES = {".jpeg", ".jpg", ".png"}


class ReviewDecision(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    screenshot: str
    field_id: str
    kind: str
    side: str | None = None
    row: int | None = None
    slot: int | None = None
    source_box: tuple[int, int, int, int] | None = None
    parser: str | None = None
    prediction: JsonValue = None
    suggested_value: JsonValue = None
    display_prediction: str = ""
    extraction_status: str
    review_reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    candidates: tuple[str, ...] = ()
    candidate_evidence: tuple[CandidateEvidence, ...] = ()
    decision: ReviewDecision = ReviewDecision.PENDING
    truth_value: JsonValue = None
    reviewed_at: datetime | None = None


class ReviewState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    family_id: str
    game_id: str
    source_hashes: dict[str, str]
    engine: dict[str, JsonValue]
    records: list[ReviewRecord]
    current_index: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    def counts(self) -> dict[str, int]:
        result = {decision.value: 0 for decision in ReviewDecision}
        for record in self.records:
            result[record.decision.value] += 1
        return result

    @property
    def complete(self) -> bool:
        return all(
            record.decision not in {ReviewDecision.PENDING, ReviewDecision.SKIPPED}
            for record in self.records
        )


@dataclass(frozen=True)
class GameCapture:
    dataset_root: Path
    family_id: str
    game_id: str
    path: Path

    @property
    def review_dir(self) -> Path:
        return self.path / ".review"

    @property
    def state_path(self) -> Path:
        return self.review_dir / "truth.review.json"

    def image_path(self, filename: str) -> Path:
        if filename not in self.source_files:
            raise ValueError(f"unsupported screenshot filename: {filename}")
        return self.path / filename

    @property
    def visual_batch_files(self) -> tuple[str, ...]:
        return tuple(
            path.name
            for path in sorted(self.path.iterdir())
            if path.is_file()
            and path.name.startswith(VISUAL_BATCH_PREFIX)
            and path.suffix.casefold() in VISUAL_BATCH_SUFFIXES
        )

    @property
    def visual_batch_capture(self) -> bool:
        return bool(self.visual_batch_files) and len(self.full_match_files) < len(SCREEN_STEMS)

    @property
    def full_match_files(self) -> tuple[str, ...]:
        resolved: list[str] = []
        for stem in SCREEN_STEMS:
            matches = [
                f"{stem}{suffix}"
                for suffix in SCREEN_SUFFIXES
                if (self.path / f"{stem}{suffix}").is_file()
            ]
            if len(matches) > 1:
                joined = ", ".join(matches)
                raise ValueError(f"multiple canonical screenshots found for {stem}: {joined}")
            if matches:
                resolved.append(matches[0])
        return tuple(resolved)

    @property
    def source_files(self) -> tuple[str, ...]:
        if self.visual_batch_capture:
            return self.visual_batch_files
        return self.full_match_files

    def missing_files(self) -> tuple[str, ...]:
        if self.visual_batch_capture:
            return ()
        available = {Path(filename).stem for filename in self.full_match_files}
        return tuple(
            canonical
            for stem, canonical in zip(SCREEN_STEMS, SCREEN_FILES, strict=True)
            if stem not in available
        )

    @property
    def complete_capture(self) -> bool:
        return not self.missing_files()

    def source_hashes(self) -> dict[str, str]:
        if not self.complete_capture:
            raise ValueError(f"incomplete game capture: {', '.join(self.missing_files())}")
        return {
            filename: hashlib.sha256(self.image_path(filename).read_bytes()).hexdigest()
            for filename in self.source_files
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def discover_games(dataset_root: Path) -> tuple[GameCapture, ...]:
    root = dataset_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"review dataset does not exist: {root}")
    games: list[GameCapture] = []
    for family in sorted(path for path in root.iterdir() if path.is_dir()):
        for game in sorted(path for path in family.iterdir() if path.is_dir()):
            games.append(
                GameCapture(
                    dataset_root=root,
                    family_id=family.name,
                    game_id=game.name,
                    path=game,
                )
            )
    return tuple(games)


def load_review_state(capture: GameCapture) -> ReviewState | None:
    if not capture.state_path.is_file():
        return None
    state = ReviewState.model_validate_json(capture.state_path.read_text(encoding="utf-8"))
    current_hashes = capture.source_hashes()
    if state.source_hashes != current_hashes:
        changed = sorted(
            filename
            for filename in set((*state.source_hashes, *current_hashes))
            if state.source_hashes.get(filename) != current_hashes.get(filename)
        )
        raise ValueError(
            "review truth is stale because source screenshots changed: " + ", ".join(changed)
        )
    return state


def save_review_state(capture: GameCapture, state: ReviewState) -> None:
    capture.review_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = utc_now()
    target = capture.state_path
    temporary = target.with_suffix(target.suffix + ".tmp")
    payload = state.model_dump_json(indent=2)
    temporary.write_text(payload + "\n", encoding="utf-8")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def parse_edited_value(text: str, predicted: JsonValue) -> JsonValue:
    stripped = text.strip()
    if isinstance(predicted, bool):
        lowered = stripped.lower()
        if lowered not in {"true", "false"}:
            raise ValueError("enter true or false")
        return lowered == "true"
    if isinstance(predicted, int):
        return int(stripped)
    if isinstance(predicted, float):
        return float(stripped.replace(",", "."))
    if predicted is None and stripped.lower() in {"none", "null", "empty", "__empty__"}:
        return None
    return stripped


__all__ = [
    "GameCapture",
    "ReviewDecision",
    "ReviewRecord",
    "ReviewState",
    "SCREEN_FILES",
    "SCREEN_STEMS",
    "discover_games",
    "load_review_state",
    "parse_edited_value",
    "save_review_state",
    "utc_now",
]
