from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.request import Request, urlopen

import pytest
from PIL import Image

import nexus_v2.review.builder as builder_module
from nexus_v2.engine import ExtractionArtifacts
from nexus_v2.input import ImageDecoder
from nexus_v2.review.builder import _item_exception_reasons
from nexus_v2.review.dataset import (
    SCREEN_FILES,
    GameCapture,
    ReviewDecision,
    ReviewRecord,
    ReviewState,
    discover_games,
    load_review_state,
    parse_edited_value,
    save_review_state,
)
from nexus_v2.review.export import export_review_truth
from nexus_v2.review.launcher import build_parser
from nexus_v2.review.server import HTML, ReviewSession, create_server
from nexus_v2.schemas.result import (
    CandidateEvidence,
    ExtractionResult,
    ExtractionStatus,
    GeometryEvidence,
    Provenance,
    QualityEvidence,
    Resolution,
    SourceEvidence,
)


def test_reviewer_defaults_to_balanced_hero_recognition_with_fallback_modes() -> None:
    parser = build_parser()

    assert parser.parse_args([]).hero_recognition_mode == "balanced"
    assert (
        parser.parse_args(["--hero-recognition-mode", "strict"]).hero_recognition_mode == "strict"
    )
    assert (
        parser.parse_args(["--hero-recognition-mode", "original"]).hero_recognition_mode
        == "original"
    )


def _capture(tmp_path: Path) -> GameCapture:
    root = tmp_path / "dataset"
    game = root / "family-a" / "game-01"
    game.mkdir(parents=True)
    for index, filename in enumerate(SCREEN_FILES):
        Image.new("RGB", (100, 80), (20 + index, 30, 40)).save(game / filename, "JPEG")
    return GameCapture(root, "family-a", "game-01", game)


def test_full_review_reuses_engine_decode_geometry_and_crops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    decoder = ImageDecoder()
    artifacts = tuple(
        ExtractionArtifacts(
            image=decoder.decode(capture.image_path(filename)),
            geometry=None,
            crops=(),
        )
        for filename in capture.source_files
    )
    results = tuple(
        ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_LAYOUT,
            provenance=Provenance(
                engine_version="test",
                preprocessing_version="test",
                processing_time_ms=1.0,
            ),
            source=SourceEvidence(
                original_resolution=Resolution(width=100, height=80),
                quality=QualityEvidence(status=ExtractionStatus.OK),
                geometry=GeometryEvidence(failure_reason="test unsupported geometry"),
            ),
            warnings=("test unsupported geometry",),
        )
        for _filename in capture.source_files
    )
    calls = 0

    class FakeEngine:
        def __init__(self, **_kwargs: object) -> None: ...

        def extract_match_with_artifacts(
            self, _sources: tuple[Path, ...]
        ) -> tuple[tuple[ExtractionResult, ...], tuple[ExtractionArtifacts, ...]]:
            nonlocal calls
            calls += 1
            return results, artifacts

    class ForbiddenDecoder:
        def __init__(self) -> None:
            raise AssertionError("reviewer repeated image decoding")

    monkeypatch.setattr(builder_module, "NexusV2Engine", FakeEngine)
    monkeypatch.setattr(builder_module, "ImageDecoder", ForbiddenDecoder)
    monkeypatch.setattr(
        builder_module,
        "resolve_hero_recognition",
        lambda **_kwargs: SimpleNamespace(
            prototype_manifest=None,
            matcher_config=None,
            mode="balanced",
            policy_sha256="test-policy",
        ),
    )
    monkeypatch.setattr(
        builder_module,
        "resolve_item_recognition",
        lambda **_kwargs: SimpleNamespace(
            prototype_manifest=None,
            manifest_sha256="test-item-manifest",
        ),
    )

    state = builder_module.build_review_state(
        capture,
        project_root=Path(__file__).resolve().parents[1],
        use_rapidocr=False,
    )

    assert calls == 1
    assert len(state.records) == len(capture.source_files)
    assert {record.kind for record in state.records} == {"geometry"}


def _visual_batch_capture(tmp_path: Path) -> GameCapture:
    root = tmp_path / "dataset"
    batch = root / "family-a" / "batch-01"
    batch.mkdir(parents=True)
    for index in range(2):
        Image.new("RGB", (100, 80), (40 + index, 50, 60)).save(
            batch / f"hero_item_{index + 1:03d}.png", "PNG"
        )
    return GameCapture(root, "family-a", "batch-01", batch)


def test_decision_buttons_use_a_fixed_non_scrolling_dock() -> None:
    assert '<div class="review-content">' in HTML
    assert '<div class="decision-dock">' in HTML
    assert ".review-content{flex:1 1 auto;min-height:0;overflow:auto" in HTML
    assert ".decision-dock{flex:0 0 auto" in HTML
    assert ".actions button{height:48px" in HTML
    assert "$('review').style.display='flex'" in HTML


def test_review_cli_accepts_explicit_calibration_manifests() -> None:
    args = build_parser().parse_args(
        [
            "--hero-prototypes",
            "/private/hero/manifest.json",
            "--item-prototypes",
            "/private/item/manifest.json",
        ]
    )
    assert args.hero_prototypes == Path("/private/hero/manifest.json")
    assert args.item_prototypes == Path("/private/item/manifest.json")


def test_review_cli_accepts_visual_only_mode() -> None:
    args = build_parser().parse_args(["--visual-only"])
    assert args.visual_only is True


def test_review_cli_accepts_item_exceptions_scope() -> None:
    args = build_parser().parse_args(["--visual-only", "--item-exceptions-only"])
    assert args.visual_only is True
    assert args.item_exceptions_only is True


def test_item_exception_scope_keeps_only_abstentions_seven_rows_and_warnings() -> None:
    def items(count: int, *, unknown_slot: int | None = None) -> tuple[SimpleNamespace, ...]:
        return tuple(
            SimpleNamespace(
                slot=slot,
                status=(ExtractionStatus.UNKNOWN if slot == unknown_slot else ExtractionStatus.OK),
            )
            for slot in range(count)
        )

    result = SimpleNamespace(
        teams=(
            SimpleNamespace(
                side="ally",
                players=(
                    SimpleNamespace(row=0, items=items(6)),
                    SimpleNamespace(row=1, items=items(7)),
                    SimpleNamespace(row=2, items=items(6, unknown_slot=3)),
                    SimpleNamespace(row=3, items=items(6)),
                ),
            ),
        ),
        warnings=("ally.row0.seven_items_without_flower_of_hope_confirmation",),
    )

    reasons = _item_exception_reasons(cast(ExtractionResult, result))

    assert {(side, row, slot) for side, row, slot in reasons if row == 0} == {
        ("ally", 0, slot) for slot in range(6)
    }
    assert {(side, row, slot) for side, row, slot in reasons if row == 1} == {
        ("ally", 1, slot) for slot in range(7)
    }
    assert reasons[("ally", 2, 3)] == "item unknown"
    assert not any(row == 3 for _side, row, _slot in reasons)


def _state(capture: GameCapture) -> ReviewState:
    now = datetime.now(timezone.utc)
    records = [
        ReviewRecord(
            record_id="first",
            screenshot=SCREEN_FILES[0],
            field_id="kills",
            kind="ocr",
            side="ally",
            row=0,
            source_box=(10, 10, 30, 30),
            prediction=7,
            display_prediction="7",
            extraction_status="ok",
            confidence=0.9,
        ),
        ReviewRecord(
            record_id="second",
            screenshot=SCREEN_FILES[1],
            field_id="hero",
            kind="hero",
            side="enemy",
            row=2,
            source_box=(40, 20, 70, 60),
            prediction="hero_015",
            display_prediction="hero_015 — Eudora",
            extraction_status="ok",
            confidence=0.8,
        ),
    ]
    return ReviewState(
        family_id=capture.family_id,
        game_id=capture.game_id,
        source_hashes=capture.source_hashes(),
        engine={"mode": "test"},
        records=records,
        created_at=now,
        updated_at=now,
    )


def test_discovers_complete_and_incomplete_games(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    incomplete = capture.dataset_root / "family-a" / "game-02"
    incomplete.mkdir()
    games = discover_games(capture.dataset_root)
    assert [(game.family_id, game.game_id) for game in games] == [
        ("family-a", "game-01"),
        ("family-a", "game-02"),
    ]
    assert games[0].complete_capture
    assert games[1].missing_files() == SCREEN_FILES


def test_full_match_capture_preserves_supported_source_extensions(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    game = root / "family-png" / "game-01"
    game.mkdir(parents=True)
    expected = tuple(f"{Path(filename).stem}.png" for filename in SCREEN_FILES)
    for index, filename in enumerate(expected):
        Image.new("RGB", (100, 80), (20 + index, 30, 40)).save(game / filename, "PNG")

    capture = discover_games(root)[0]
    assert capture.complete_capture
    assert capture.source_files == expected
    assert set(capture.source_hashes()) == set(expected)


def test_full_match_capture_rejects_duplicate_canonical_extensions(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    stem = Path(SCREEN_FILES[0]).stem
    Image.new("RGB", (100, 80), (1, 2, 3)).save(capture.path / f"{stem}.png", "PNG")

    with pytest.raises(ValueError, match="multiple canonical screenshots"):
        _ = capture.source_files


def test_visual_batch_capture_discovers_dynamic_sources_and_guards_paths(tmp_path: Path) -> None:
    capture = _visual_batch_capture(tmp_path)
    assert capture.visual_batch_capture
    assert capture.complete_capture
    assert capture.source_files == ("hero_item_001.png", "hero_item_002.png")
    assert set(capture.source_hashes()) == set(capture.source_files)
    with pytest.raises(ValueError, match="unsupported screenshot"):
        capture.image_path("../hero_item_001.png")


def test_state_saves_atomically_and_rejects_changed_sources(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    save_review_state(capture, state)
    assert load_review_state(capture) == state
    assert not capture.state_path.with_suffix(".json.tmp").exists()

    Image.new("RGB", (100, 80), (255, 0, 0)).save(capture.image_path(SCREEN_FILES[0]), "JPEG")
    with pytest.raises(ValueError, match="source screenshots changed"):
        load_review_state(capture)


def test_review_state_preserves_structured_candidate_scores(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.records[0] = state.records[0].model_copy(
        update={
            "candidate_evidence": (
                CandidateEvidence(
                    candidate_id="candidate-a",
                    raw="7",
                    scores={"fused_similarity": 0.91, "backend_support": 2.0},
                ),
            )
        }
    )

    save_review_state(capture, state)
    loaded = load_review_state(capture)

    assert loaded is not None
    evidence = loaded.records[0].candidate_evidence[0]
    assert evidence.candidate_id == "candidate-a"
    assert evidence.scores == {"fused_similarity": 0.91, "backend_support": 2.0}


def test_session_accept_edit_unknown_skip_back_and_crop(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    session = ReviewSession(capture, _state(capture))
    first = session.public_state()
    assert first["current"]["record_id"] == "first"

    second = session.decide("accept")
    assert second["current"]["record_id"] == "second"
    assert session.state.records[0].decision.value == ReviewDecision.ACCEPTED.value
    assert session.state.records[0].truth_value == 7

    skipped = session.decide("skip")
    assert skipped["current"]["record_id"] == "second"
    assert skipped["counts"]["skipped"] == 1

    done = session.decide("edit", "hero_999")
    assert done["done"] is True
    assert session.state.records[1].truth_value == "hero_999"
    assert session.state.records[1].decision.value == ReviewDecision.EDITED.value

    previous = session.decide("back")
    assert previous["done"] is False
    assert previous["current"]["record_id"] == "second"
    final = session.decide("unknown")
    assert final["done"] is True
    assert session.state.records[1].decision.value == ReviewDecision.UNKNOWN.value
    assert session.crop_png().startswith(b"\x89PNG")


def test_local_http_api_and_loopback_guard(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    session = ReviewSession(capture, _state(capture))
    with pytest.raises(ValueError, match="localhost"):
        create_server(session, host="0.0.0.0", port=0)

    server = create_server(session, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
            payload = json.load(response)
        assert payload["current"]["field_id"] == "kills"
        assert response.headers["Cache-Control"] == "no-store"

        request = Request(
            f"http://127.0.0.1:{port}/api/decision",
            data=b'{"action":"accept"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            advanced = json.load(response)
        assert advanced["current"]["field_id"] == "hero"
        with urlopen(f"http://127.0.0.1:{port}/crop.png", timeout=5) as response:
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_parse_edited_values_preserves_expected_scalar_type() -> None:
    assert parse_edited_value("12", 1) == 12
    assert parse_edited_value("12,5", 1.0) == 12.5
    assert parse_edited_value("false", True) is False
    assert parse_edited_value("empty", None) is None
    assert parse_edited_value("hero_015", "hero_001") == "hero_015"


def test_parser_aware_edit_types_an_unknown_numeric_prediction(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.records[0] = state.records[0].model_copy(
        update={"parser": "large_integer", "prediction": None}
    )
    session = ReviewSession(capture, state)
    session.decide("edit", "12")
    assert session.state.records[0].truth_value == 12
    assert isinstance(session.state.records[0].truth_value, int)


def test_entity_name_corrections_are_saved_as_stable_ids(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.current_index = 1
    session = ReviewSession(
        capture,
        state,
        correction_options={"hero": (("hero_015", "Eudora"),)},
    )
    completed = session.decide("edit", "Eudora")
    assert completed["done"] is False
    assert session.state.records[1].truth_value == "hero_015"

    session.state.current_index = 1
    with pytest.raises(ValueError, match="valid hero ID or name"):
        session.decide("edit", "not-a-real-hero")


def test_repeated_review_truth_is_suggested_for_later_tabs(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.records[0] = state.records[0].model_copy(
        update={
            "decision": ReviewDecision.EDITED,
            "truth_value": 8,
            "reviewed_at": datetime.now(timezone.utc),
        }
    )
    state.records.append(
        ReviewRecord(
            record_id="repeated-kills",
            screenshot=SCREEN_FILES[2],
            field_id="kills",
            kind="ocr",
            side="ally",
            row=0,
            source_box=(10, 10, 30, 30),
            prediction=None,
            display_prediction="UNKNOWN",
            extraction_status="unknown",
        )
    )
    state.current_index = 2
    public = ReviewSession(capture, state).public_state()
    assert public["repeated_truth"] == {
        "value": 8,
        "source_screenshot": SCREEN_FILES[0],
    }


def test_visual_batch_does_not_propagate_truth_between_independent_screens(
    tmp_path: Path,
) -> None:
    capture = _visual_batch_capture(tmp_path)
    now = datetime.now(timezone.utc)
    records = [
        ReviewRecord(
            record_id=f"hero-{index}",
            screenshot=filename,
            field_id="hero",
            kind="hero",
            side="ally",
            row=0,
            source_box=(10, 10, 30, 30),
            prediction="hero_001",
            display_prediction="hero_001",
            extraction_status="ok",
            decision=ReviewDecision.ACCEPTED if index == 0 else ReviewDecision.PENDING,
            truth_value="hero_001" if index == 0 else None,
            reviewed_at=now if index == 0 else None,
        )
        for index, filename in enumerate(capture.source_files)
    ]
    state = ReviewState(
        family_id=capture.family_id,
        game_id=capture.game_id,
        source_hashes=capture.source_hashes(),
        engine={"mode": "test", "review_scope": "hero_item_only"},
        records=records,
        current_index=1,
        created_at=now,
        updated_at=now,
    )
    assert ReviewSession(capture, state).public_state()["repeated_truth"] is None


def test_completed_review_exports_five_hash_traced_truth_files(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.records = [
        record.model_copy(
            update={
                "decision": ReviewDecision.ACCEPTED,
                "truth_value": record.prediction,
                "reviewed_at": datetime.now(timezone.utc),
            }
        )
        for record in state.records
    ]
    state.current_index = len(state.records)
    save_review_state(capture, state)
    manifest = export_review_truth(capture, state)
    assert len(manifest["files"]) == 5
    for filename in SCREEN_FILES:
        truth_path = capture.path / f"{Path(filename).stem}.txt"
        assert truth_path.is_file()
        assert f"source_sha256: {state.source_hashes[filename]}" in truth_path.read_text()
    assert (capture.review_dir / "truth_export_manifest.json").is_file()


def test_completed_visual_batch_exports_each_dynamic_source(tmp_path: Path) -> None:
    capture = _visual_batch_capture(tmp_path)
    now = datetime.now(timezone.utc)
    state = ReviewState(
        family_id=capture.family_id,
        game_id=capture.game_id,
        source_hashes=capture.source_hashes(),
        engine={"mode": "test", "review_scope": "hero_plus_item_exceptions"},
        records=[
            ReviewRecord(
                record_id=f"hero-{index}",
                screenshot=filename,
                field_id="hero",
                kind="hero",
                side="ally",
                row=0,
                source_box=(10, 10, 30, 30),
                prediction="hero_001",
                display_prediction="hero_001",
                extraction_status="ok",
                decision=ReviewDecision.ACCEPTED,
                truth_value="hero_001",
                reviewed_at=now,
            )
            for index, filename in enumerate(capture.source_files)
        ],
        current_index=len(capture.source_files),
        created_at=now,
        updated_at=now,
    )
    save_review_state(capture, state)
    manifest = export_review_truth(capture, state)
    assert [entry["screenshot"] for entry in manifest["files"]] == list(capture.source_files)
    assert all(
        (capture.path / f"{Path(filename).stem}.txt").is_file() for filename in capture.source_files
    )
    scoped_truth = (capture.path / f"{Path(capture.source_files[0]).stem}.txt").read_text()
    assert "review_status: human_approved_scoped" in scoped_truth
    assert "review_scope: hero_plus_item_exceptions" in scoped_truth


def test_export_never_overwrites_a_preexisting_manual_truth(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    state = _state(capture)
    state.records = [
        record.model_copy(
            update={
                "decision": ReviewDecision.ACCEPTED,
                "truth_value": record.prediction,
                "reviewed_at": datetime.now(timezone.utc),
            }
        )
        for record in state.records
    ]
    state.current_index = len(state.records)
    save_review_state(capture, state)
    manual = capture.path / "hero_item_screen.txt"
    manual.write_text("MANUAL AUTHORITATIVE TRUTH\n")
    manifest = export_review_truth(capture, state)
    assert manual.read_text() == "MANUAL AUTHORITATIVE TRUTH\n"
    hero_export = next(
        entry for entry in manifest["files"] if entry["screenshot"] == SCREEN_FILES[0]
    )
    assert hero_export["truth"] == ".review/exports/hero_item_screen.reviewed.txt"
    assert (capture.path / hero_export["truth"]).is_file()
