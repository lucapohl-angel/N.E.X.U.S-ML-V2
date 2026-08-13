"""Regression tests for private reviewed-batch prototype tooling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nexus_v2.layout.profiles import FieldKind
from tools.build_review_batch_prototypes import load_empty_player_rows, review_truth_required


def test_active_learning_scope_requires_every_hero_but_not_omitted_items() -> None:
    scope = "hero_plus_item_exceptions"

    assert review_truth_required(FieldKind.HERO, scope) is True
    assert review_truth_required(FieldKind.ITEM, scope) is False


def test_exhaustive_scope_requires_item_truth() -> None:
    assert review_truth_required(FieldKind.ITEM, "hero_item_only") is True


def _write_empty_player_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    batch = tmp_path / "batch"
    review = batch / ".review"
    review.mkdir(parents=True)
    state_path = review / "truth.review.json"
    state = {"source_hashes": {"screen.png": "source-hash"}}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    sidecar = {
        "truth_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "rows": [
            {
                "screenshot": "screen.png",
                "side": "ally",
                "row": 4,
                "source_sha256": "source-hash",
            }
        ],
    }
    (review / "empty_player_rows.review.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return batch, state_path, state


def test_empty_player_rows_require_matching_truth_and_source_hashes(tmp_path: Path) -> None:
    batch, state_path, state = _write_empty_player_fixture(tmp_path)

    rows, sidecar = load_empty_player_rows(batch, state_path, state)

    assert rows == {("screen.png", "ally", 4)}
    assert sidecar == batch / ".review/empty_player_rows.review.json"


def test_empty_player_rows_reject_stale_truth(tmp_path: Path) -> None:
    batch, state_path, state = _write_empty_player_fixture(tmp_path)
    state_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="does not match canonical review truth"):
        load_empty_player_rows(batch, state_path, state)
