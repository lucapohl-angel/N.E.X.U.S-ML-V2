from __future__ import annotations

import hashlib
import io
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, cast
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
import requests
from PIL import Image, PngImagePlugin

from nexus_v2.catalog import images as catalog_images
from nexus_v2.catalog.audit import audit_snapshot, model_catalog_compatibility
from nexus_v2.catalog.images import (
    AssetValidationError,
    DownloadError,
    SafeImageDownloader,
    ValidatedImage,
    phash_distance,
    validate_image_bytes,
)
from nexus_v2.catalog.models import (
    CatalogKind,
    CatalogMigrationReport,
    MigrationStatus,
    ReviewAction,
    ReviewStatus,
    SourceFailure,
)
from nexus_v2.catalog.promotion import CatalogPromotionError, promote_catalog
from nexus_v2.catalog.review import (
    CatalogReviewServer,
    CatalogReviewStore,
    ReviewStoreError,
    _ReviewHandler,
    create_review_record,
)
from nexus_v2.catalog.service import catalog_diff, sync_catalog
from nexus_v2.catalog.sources import (
    FandomItemCatalogSource,
    MoontonHeroCatalogSource,
    SourceCandidate,
    SourceResult,
)
from nexus_v2.catalog.storage import load_snapshot


class FakeSource:
    adapter_id = "test_source"

    def __init__(
        self,
        candidates: tuple[SourceCandidate, ...],
        failures: tuple[SourceFailure, ...] = (),
    ) -> None:
        self.candidates = candidates
        self.failures = failures

    def discover(self) -> SourceResult:
        return SourceResult(candidates=self.candidates, failures=self.failures)


class ExplodingSource:
    adapter_id = "exploding_source"

    def discover(self) -> SourceResult:
        raise RuntimeError("contained discovery outage")


class FailingDownloader(SafeImageDownloader):
    def download(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        headers: dict[str, str] | None = None,
    ) -> ValidatedImage:
        raise DownloadError("contained download outage")


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, responses: tuple[FakeResponse, ...]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []
        self.max_redirects = 0
        self.closed = False

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        stream: bool,
        allow_redirects: bool,
        timeout: tuple[float, float],
    ) -> FakeResponse:
        self.urls.append(url)
        assert headers is None
        assert stream
        assert not allow_redirects
        assert all(value > 0 for value in timeout)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class MemorySocket:
    """Minimal socket-shaped transport for exercising BaseHTTPRequestHandler without a port."""

    def __init__(self, request: bytes) -> None:
        self.request = request
        self.response = bytearray()

    def makefile(self, mode: str, buffering: int = -1) -> BinaryIO:
        del buffering
        if mode != "rb":
            raise AssertionError(f"unexpected socket file mode: {mode}")
        return cast(BinaryIO, io.BytesIO(self.request))

    def sendall(self, data: bytes) -> None:
        self.response.extend(data)


def _accept_remote_host(hostname: str, allowed_hosts: frozenset[str]) -> None:
    assert hostname in allowed_hosts


def _handle_review_request(
    request: bytes,
    *,
    result_path: Path,
    actions_path: Path,
) -> tuple[bytes, CatalogReviewStore, str]:
    snapshot, digest, manifest = load_snapshot(result_path)
    store = CatalogReviewStore(actions_path)
    server = CatalogReviewServer.__new__(CatalogReviewServer)
    server.snapshot = snapshot
    server.snapshot_sha256 = digest
    server.snapshot_root = manifest.parent
    server.store = store
    server.csrf_token = "catalog-review-smoke-token"
    transport = MemorySocket(request)
    _ReviewHandler(
        cast(socket.socket, transport),
        ("127.0.0.1", 4242),
        server,
    )
    return bytes(transport.response), store, server.csrf_token


def _write_pattern(path: Path, seed: int, *, metadata: str | None = None) -> None:
    image = Image.new("RGB", (32, 32))
    for y in range(32):
        for x in range(32):
            image.putpixel(
                (x, y),
                (
                    (x * 17 + seed * 11) % 256,
                    (y * 19 + seed * 23) % 256,
                    ((x + y) * 13 + seed * 29) % 256,
                ),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    png_info = None
    if metadata is not None:
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("variant", metadata)
    image.save(path, format="PNG", pnginfo=png_info)


def _candidate(
    path: Path,
    *,
    kind: CatalogKind,
    source_identity: str,
    name: str,
) -> SourceCandidate:
    return SourceCandidate(
        kind=kind,
        source_adapter="test_source",
        source_identity=source_identity,
        canonical_name=name,
        aliases={"en": (name,)},
        source_reference=f"test-fixture:{source_identity}",
        local_path=path,
        legacy_path=path.name,
    )


def test_stable_ids_ignore_source_order_and_display_name_changes(tmp_path: Path) -> None:
    hero = tmp_path / "hero.png"
    item = tmp_path / "item.png"
    _write_pattern(hero, 1)
    _write_pattern(item, 2)
    first_candidates = (
        _candidate(
            hero,
            kind=CatalogKind.HERO,
            source_identity="upstream-hero:7",
            name="Old Hero Name",
        ),
        _candidate(
            item,
            kind=CatalogKind.ITEM,
            source_identity="upstream-item:durable-42",
            name="Old Item Name",
        ),
    )
    first = sync_catalog(
        sources=(FakeSource(first_candidates),),
        staging_path=tmp_path / "first",
        catalog_version="test-1",
    )
    second_candidates = (
        _candidate(
            item,
            kind=CatalogKind.ITEM,
            source_identity="upstream-item:durable-42",
            name="Renamed Item",
        ),
        _candidate(
            hero,
            kind=CatalogKind.HERO,
            source_identity="upstream-hero:7",
            name="Renamed Hero",
        ),
    )
    second = sync_catalog(
        sources=(FakeSource(second_candidates),),
        staging_path=tmp_path / "second",
        catalog_version="test-2",
        previous_path=first.snapshot_path,
    )

    assert second.snapshot.heroes[0].id == first.snapshot.heroes[0].id == "hero_0007"
    assert second.snapshot.items[0].id == first.snapshot.items[0].id
    assert second.snapshot.heroes[0].canonical_name == "Renamed Hero"
    assert second.snapshot.heroes[0].review_status is ReviewStatus.CHANGES_PENDING


def test_new_classes_append_without_shifting_existing_class_map(tmp_path: Path) -> None:
    paths = [tmp_path / f"item-{index}.png" for index in range(3)]
    for index, path in enumerate(paths):
        _write_pattern(path, index + 10)
    initial = sync_catalog(
        sources=(
            FakeSource(
                tuple(
                    _candidate(
                        path,
                        kind=CatalogKind.ITEM,
                        source_identity=f"durable:{index}",
                        name=f"Item {index}",
                    )
                    for index, path in enumerate(paths[:2])
                )
            ),
        ),
        staging_path=tmp_path / "initial",
        catalog_version="classmap-1",
    )
    updated_candidates = tuple(
        _candidate(
            path,
            kind=CatalogKind.ITEM,
            source_identity=f"durable:{index}",
            name=f"Item {index}",
        )
        for index, path in reversed(list(enumerate(paths)))
    )
    updated = sync_catalog(
        sources=(FakeSource(updated_candidates),),
        staging_path=tmp_path / "updated",
        catalog_version="classmap-2",
        previous_path=initial.snapshot_path,
    )

    old_map = {entry.stable_id: entry.index for entry in initial.snapshot.item_class_map}
    new_map = {entry.stable_id: entry.index for entry in updated.snapshot.item_class_map}
    assert all(new_map[stable_id] == index for stable_id, index in old_map.items())
    assert max(new_map.values()) == 2


def test_apostrophe_url_encoding_is_single_and_round_trips() -> None:
    url = FandomItemCatalogSource.wiki_api_title("Athena's Shield")
    assert "Athena%27s%20Shield.png" in url
    assert "%2527" not in url
    assert parse_qs(urlparse(url).query)["titles"] == ["File:Athena's Shield.png"]


def test_secure_downloader_follows_bounded_https_redirect_and_validates_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = tmp_path / "download.png"
    _write_pattern(asset, 15)
    content = asset.read_bytes()
    session = FakeSession(
        (
            FakeResponse(302, headers={"Location": "/final.png"}),
            FakeResponse(
                200,
                headers={
                    "Content-Type": "image/png; charset=binary",
                    "Content-Length": str(len(content)),
                },
                body=content,
            ),
        )
    )
    monkeypatch.setattr(catalog_images, "_validate_remote_host", _accept_remote_host)
    monkeypatch.setattr(requests, "Session", lambda: session)

    downloaded = SafeImageDownloader().download(
        "https://assets.example.test/start.png",
        allowed_hosts=frozenset({"assets.example.test"}),
    )

    assert session.urls == [
        "https://assets.example.test/start.png",
        "https://assets.example.test/final.png",
    ]
    assert session.closed
    assert downloaded.content == content
    assert downloaded.mime_type == "image/png"
    assert downloaded.width == downloaded.height == 32
    assert phash_distance(downloaded.phash, downloaded.phash) == 0
    with pytest.raises(DownloadError, match="HTTPS"):
        SafeImageDownloader().download(
            "http://assets.example.test/insecure.png",
            allowed_hosts=frozenset({"assets.example.test"}),
        )


def test_changed_visual_keeps_history_and_requires_review(tmp_path: Path) -> None:
    asset = tmp_path / "hero.png"
    _write_pattern(asset, 20)
    candidate = _candidate(
        asset,
        kind=CatalogKind.HERO,
        source_identity="hero:99",
        name="Visual Hero",
    )
    first = sync_catalog(
        sources=(FakeSource((candidate,)),),
        staging_path=tmp_path / "visual-1",
        catalog_version="visual-1",
    )
    _write_pattern(asset, 21)
    second = sync_catalog(
        sources=(FakeSource((candidate,)),),
        staging_path=tmp_path / "visual-2",
        catalog_version="visual-2",
        previous_path=first.snapshot_path,
    )

    assert second.snapshot.heroes[0].id == first.snapshot.heroes[0].id
    assert len(second.snapshot.heroes[0].visual_versions) == 2
    assert second.snapshot.heroes[0].review_status is ReviewStatus.CHANGES_PENDING
    assert second.diff is not None
    assert second.diff.changed_visual_classes == (second.snapshot.heroes[0].id,)
    assert all(
        (second.snapshot_path / visual.asset_path).is_file()
        for visual in second.snapshot.heroes[0].visual_versions
    )


def test_exact_and_near_duplicates_are_reported(tmp_path: Path) -> None:
    exact_a = tmp_path / "exact-a.png"
    exact_b = tmp_path / "exact-b.png"
    near_a = tmp_path / "near-a.png"
    near_b = tmp_path / "near-b.png"
    _write_pattern(exact_a, 30)
    exact_b.write_bytes(exact_a.read_bytes())
    _write_pattern(near_a, 31, metadata="a")
    _write_pattern(near_b, 31, metadata="b")
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        exact_a,
                        kind=CatalogKind.ITEM,
                        source_identity="item:exact-a",
                        name="Exact A",
                    ),
                    _candidate(
                        exact_b,
                        kind=CatalogKind.ITEM,
                        source_identity="item:exact-b",
                        name="Exact B",
                    ),
                    _candidate(
                        near_a,
                        kind=CatalogKind.ITEM,
                        source_identity="item:near-a",
                        name="Near A",
                    ),
                    _candidate(
                        near_b,
                        kind=CatalogKind.ITEM,
                        source_identity="item:near-b",
                        name="Near B",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "duplicates",
        catalog_version="duplicates-1",
    )
    audit = audit_snapshot(result.snapshot, result.snapshot_path)

    assert result.sync_report.exact_duplicate_groups
    assert result.sync_report.near_duplicate_groups
    assert "exact_duplicate" in {issue.code for issue in audit.issues}
    assert "near_duplicate" in {issue.code for issue in audit.issues}


def test_missing_asset_is_mandatory_and_promotion_fails(tmp_path: Path) -> None:
    asset = tmp_path / "item.png"
    _write_pattern(asset, 40)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        asset,
                        kind=CatalogKind.ITEM,
                        source_identity="item:missing",
                        name="Missing Later",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "missing",
        catalog_version="missing-1",
    )
    visual = result.snapshot.items[0].visual_versions[0]
    (result.snapshot_path / visual.asset_path).unlink()
    audit = audit_snapshot(result.snapshot, result.snapshot_path)
    assert "missing_or_invalid_asset" in {issue.code for issue in audit.issues}
    with pytest.raises(CatalogPromotionError):
        promote_catalog(
            staging_path=result.snapshot_path,
            production_root=tmp_path / "production",
        )


def test_network_and_adapter_failures_are_contained_in_sync_report(tmp_path: Path) -> None:
    remote = SourceCandidate(
        kind=CatalogKind.ITEM,
        source_adapter="remote_test",
        source_identity="remote:item",
        canonical_name="Remote Item",
        aliases={"en": ("Remote Item",)},
        source_reference="https://example.com/item.png",
        asset_url="https://example.com/item.png",
        allowed_asset_hosts=frozenset({"example.com"}),
    )
    result = sync_catalog(
        sources=(FakeSource((remote,)), ExplodingSource()),
        staging_path=tmp_path / "failed-network",
        catalog_version="failure-1",
        downloader=FailingDownloader(),
    )

    assert result.snapshot.items == ()
    assert len(result.sync_report.failed_downloads) == 2
    assert {failure.stage for failure in result.sync_report.failed_downloads} == {
        "download",
        "discovery",
    }


def test_invalid_and_placeholder_images_are_rejected(tmp_path: Path) -> None:
    html_body = b"<!doctype html><html><body>upstream error</body></html>"
    with pytest.raises(AssetValidationError, match="HTML"):
        validate_image_bytes(html_body, declared_content_type="image/png")
    with pytest.raises(AssetValidationError, match="Content-Type"):
        validate_image_bytes(b"not an image", declared_content_type="text/html")

    transparent = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    buffer = io.BytesIO()
    transparent.save(buffer, format="PNG")
    with pytest.raises(AssetValidationError, match="transparent"):
        validate_image_bytes(buffer.getvalue(), declared_content_type="image/png")

    valid_asset = tmp_path / "valid.png"
    _write_pattern(valid_asset, 49)
    valid_content = valid_asset.read_bytes()
    validated = validate_image_bytes(valid_content, declared_content_type="image/png")
    assert validated.sha256 == hashlib.sha256(valid_content).hexdigest()
    with pytest.raises(AssetValidationError, match="does not match"):
        validate_image_bytes(valid_content, declared_content_type="image/jpeg")

    constant = Image.new("RGB", (32, 32), (128, 128, 128))
    constant_buffer = io.BytesIO()
    constant.save(constant_buffer, format="PNG")
    with pytest.raises(AssetValidationError, match="constant"):
        validate_image_bytes(constant_buffer.getvalue())

    tiny_buffer = io.BytesIO()
    with Image.open(valid_asset) as image:
        image.resize((8, 8)).save(tiny_buffer, format="PNG")
    with pytest.raises(AssetValidationError, match="below"):
        validate_image_bytes(tiny_buffer.getvalue())

    valid = tmp_path / "unknown.png"
    _write_pattern(valid, 50)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        valid,
                        kind=CatalogKind.HERO,
                        source_identity="hero:placeholder",
                        name="Unknown",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "placeholder",
        catalog_version="placeholder-1",
    )
    audit = audit_snapshot(result.snapshot, result.snapshot_path)
    assert "placeholder_record" in {issue.code for issue in audit.issues}


def test_ambiguous_source_identity_is_reported_without_mapping(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _write_pattern(first, 60)
    _write_pattern(second, 61)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        first,
                        kind=CatalogKind.ITEM,
                        source_identity="ambiguous:same",
                        name="First",
                    ),
                    _candidate(
                        second,
                        kind=CatalogKind.ITEM,
                        source_identity="ambiguous:same",
                        name="Second",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "ambiguous",
        catalog_version="ambiguous-1",
    )

    assert result.snapshot.items == ()
    assert result.migration_report.ambiguous_files == 2
    assert all(
        mapping.status is MigrationStatus.AMBIGUOUS
        and mapping.stable_id is None
        and mapping.ambiguity_candidates
        for mapping in result.migration_report.mappings
    )


def test_review_ledger_is_snapshot_bound_and_promotion_requires_actions(tmp_path: Path) -> None:
    asset = tmp_path / "review.png"
    _write_pattern(asset, 70)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        asset,
                        kind=CatalogKind.HERO,
                        source_identity="hero:review",
                        name="Reviewed Hero",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "review",
        catalog_version="review-1",
    )
    with pytest.raises(CatalogPromotionError, match="blocked"):
        promote_catalog(
            staging_path=result.snapshot_path,
            production_root=tmp_path / "production-before-review",
        )
    mismatched_store = CatalogReviewStore(tmp_path / "mismatched-actions.jsonl")
    mismatched_store.append(
        create_review_record(
            snapshot=result.snapshot,
            snapshot_sha256="0" * 64,
            class_id=result.snapshot.heroes[0].id,
            action=ReviewAction.APPROVE,
            reviewer="wrong-snapshot-reviewer",
        )
    )
    with pytest.raises(ReviewStoreError, match="different snapshot"):
        mismatched_store.load(snapshot_sha256=result.snapshot_sha256)

    store = CatalogReviewStore(result.snapshot_path / "review_actions.jsonl")
    store.append(
        create_review_record(
            snapshot=result.snapshot,
            snapshot_sha256=result.snapshot_sha256,
            class_id=result.snapshot.heroes[0].id,
            action=ReviewAction.APPROVE,
            reviewer="catalog-test-reviewer",
            comment="fixture pixels and label explicitly reviewed",
        )
    )
    promoted = promote_catalog(
        staging_path=result.snapshot_path,
        production_root=tmp_path / "production",
    )
    assert promoted.audit_report.promotion_ready
    assert promoted.snapshot.heroes[0].review_status is ReviewStatus.APPROVED
    assert promoted.production_path.is_dir()


def test_review_http_handler_serves_assets_and_persists_explicit_action(tmp_path: Path) -> None:
    asset = tmp_path / "server.png"
    _write_pattern(asset, 80)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        asset,
                        kind=CatalogKind.HERO,
                        source_identity="hero:server",
                        name="Server Hero",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "server-snapshot",
        catalog_version="server-1",
    )
    actions_path = tmp_path / "http-review-actions.jsonl"
    get_response, _, csrf_token = _handle_review_request(
        b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        result_path=result.snapshot_path,
        actions_path=actions_path,
    )
    assert get_response.startswith(b"HTTP/1.0 200 OK")
    assert b"Server Hero" in get_response
    visual = result.snapshot.heroes[0].visual_versions[0]
    asset_request = (
        f"GET /assets/{visual.asset_path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    ).encode()
    asset_response, _, _ = _handle_review_request(
        asset_request,
        result_path=result.snapshot_path,
        actions_path=actions_path,
    )
    assert asset_response.startswith(b"HTTP/1.0 200 OK")
    assert asset_response.endswith((result.snapshot_path / visual.asset_path).read_bytes())

    form = urlencode(
        {
            "csrf": csrf_token,
            "class_id": result.snapshot.heroes[0].id,
            "action": "approve",
            "reviewer": "http-reviewer",
            "comment": "explicit HTTP review",
        }
    ).encode()
    post_request = (
        b"POST /review HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        + f"Content-Length: {len(form)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + form
    )
    post_response, store, _ = _handle_review_request(
        post_request,
        result_path=result.snapshot_path,
        actions_path=actions_path,
    )
    assert post_response.startswith(b"HTTP/1.0 303 See Other")
    actions = store.load(snapshot_sha256=result.snapshot_sha256)
    assert len(actions) == 1
    assert actions[0].reviewer == "http-reviewer"


def test_credentials_are_environment_only_and_no_credential_literal_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEXUS_MOONTON_AUTHORIZATION", raising=False)
    result = MoontonHeroCatalogSource((1,)).discover()
    assert result.candidates == ()
    assert result.failures[0].stage == "credentials"

    repository_root = Path(__file__).resolve().parents[1]
    assignment_pattern = re.compile(
        r"(?i)\b(?:authoriz" + r"ation|cookie|api[_-]?key|access[_-]?token|client[_-]?secret)"
        r"['\"]?\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"
    )
    bearer_pattern = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
    excluded_parts = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".venv",
    }
    scanned_suffixes = {".json", ".md", ".py", ".toml", ".yaml", ".yml"}
    for path in repository_root.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.casefold() not in scanned_suffixes
            or excluded_parts.intersection(path.parts)
        ):
            continue
        text = path.read_text(encoding="utf-8")
        assert assignment_pattern.search(text) is None, path
        assert bearer_pattern.search(text) is None, path


def test_diff_reports_visual_and_class_map_changes(tmp_path: Path) -> None:
    asset = tmp_path / "diff.png"
    added = tmp_path / "added.png"
    _write_pattern(asset, 90)
    _write_pattern(added, 91)
    first_candidate = _candidate(
        asset,
        kind=CatalogKind.ITEM,
        source_identity="item:diff",
        name="Diff Item",
    )
    first = sync_catalog(
        sources=(FakeSource((first_candidate,)),),
        staging_path=tmp_path / "diff-1",
        catalog_version="diff-1",
    )
    second = sync_catalog(
        sources=(
            FakeSource(
                (
                    first_candidate,
                    _candidate(
                        added,
                        kind=CatalogKind.ITEM,
                        source_identity="item:added",
                        name="Added Item",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "diff-2",
        catalog_version="diff-2",
        previous_path=first.snapshot_path,
    )
    difference = catalog_diff(first.snapshot, second.snapshot)
    assert len(difference.added_class_ids) == 1
    assert not any(
        old_index != new_index
        for old_index, new_index in difference.class_map_changes.values()
        if old_index is not None and new_index is not None
    )


def test_model_catalog_compatibility_exposes_new_removed_and_unseen_visuals(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "model.png"
    _write_pattern(asset, 100)
    result = sync_catalog(
        sources=(
            FakeSource(
                (
                    _candidate(
                        asset,
                        kind=CatalogKind.HERO,
                        source_identity="hero:model",
                        name="Model Hero",
                    ),
                )
            ),
        ),
        staging_path=tmp_path / "model-catalog",
        catalog_version="model-catalog-1",
    )
    stable_id = result.snapshot.hero_class_map[0].stable_id
    visual_id = result.snapshot.heroes[0].visual_versions[0].id
    compatible = model_catalog_compatibility(
        snapshot=result.snapshot,
        model_id="hero-classifier-1",
        model_catalog_version=result.snapshot.catalog_version,
        supported_class_ids=(stable_id,),
        observed_visual_version_ids=(visual_id,),
        preprocessing_version="hero-rgb-v1",
        input_size=(224, 224),
    )
    assert compatible.classifier_compatible
    assert not compatible.prototype_fallback_required
    assert compatible.runtime_only_class_ids == ()
    assert compatible.model_only_class_ids == ()

    incompatible = model_catalog_compatibility(
        snapshot=result.snapshot,
        model_id="hero-classifier-stale",
        model_catalog_version="older-catalog",
        supported_class_ids=("hero_removed_from_runtime",),
        observed_visual_version_ids=("hero_missing_visual",),
        preprocessing_version="hero-rgb-v1",
        input_size=(224, 224),
    )
    assert not incompatible.classifier_compatible
    assert incompatible.prototype_fallback_required
    assert incompatible.runtime_only_class_ids == (stable_id,)
    assert incompatible.model_only_class_ids == ("hero_removed_from_runtime",)
    assert incompatible.missing_observed_visual_version_ids == ("hero_missing_visual",)


@pytest.mark.integration
def test_local_v1_staging_snapshot_has_truthful_inventory_and_integrity() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    snapshot_root = repository_root / "catalogs" / "staging" / "phase1-v1-migration-2026-08-01"
    snapshot, digest, _ = load_snapshot(snapshot_root)
    migration = CatalogMigrationReport.model_validate_json(
        (snapshot_root / "migration_report.json").read_bytes()
    )
    audit = audit_snapshot(snapshot, snapshot_root)

    assert digest == (snapshot_root / "catalog.sha256").read_text(encoding="ascii").split()[0]
    assert len(snapshot.heroes) == len(snapshot.hero_class_map) == 131
    assert len(snapshot.items) == len(snapshot.item_class_map) == 104
    assert migration.hero_files_discovered == 131
    assert migration.item_files_discovered == 105
    assert migration.mapped_files == 236
    assert migration.ambiguous_files == migration.failed_files == 0
    empty_slot = next(
        mapping for mapping in migration.mappings if mapping.stable_id == "item_empty_slot"
    )
    assert empty_slot.match_basis == "excluded_empty_slot_sentinel"
    assert all(record.canonical_name != "Empty Slot" for record in snapshot.items)
    assert audit.decoded_asset_count == audit.visual_version_count == 235
    assert audit.mandatory_issue_count == 705
    assert audit.warning_issue_count == 0
    assert not audit.promotion_ready
    assert {issue.code for issue in audit.issues} == {
        "unreviewed_class",
        "unreviewed_visual",
        "unverified_provenance",
    }
