"""Durable review ledger, minimal local UI, and review-state application."""

from __future__ import annotations

import fcntl
import html
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TypeAlias
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from nexus_v2.catalog.models import (
    CatalogReviewRecord,
    CatalogSnapshot,
    HeroRecord,
    ItemRecord,
    ProvenanceStatus,
    ReviewAction,
    ReviewStatus,
)
from nexus_v2.catalog.storage import CatalogStorageError, load_snapshot

CatalogRecord: TypeAlias = HeroRecord | ItemRecord


class ReviewStoreError(RuntimeError):
    """Raised for a malformed, mismatched, or unwritable review ledger."""


@dataclass(frozen=True)
class ReviewServerAddress:
    host: str
    port: int
    url: str


class CatalogReviewStore:
    """Append-only JSONL store with process-level locking and fsync durability."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: CatalogReviewRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (record.model_dump_json() + "\n").encode("utf-8")
        try:
            file_descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(file_descriptor, "ab", closefd=True) as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise ReviewStoreError(f"could not persist review action: {exc}") from exc

    def load(self, *, snapshot_sha256: str | None = None) -> tuple[CatalogReviewRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[CatalogReviewRecord] = []
        try:
            with self.path.open("rb") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
                for line_number, raw in enumerate(handle, 1):
                    if len(raw) > 16 * 1024:
                        raise ReviewStoreError(
                            f"review ledger line {line_number} exceeds the 16 KiB limit"
                        )
                    try:
                        record = CatalogReviewRecord.model_validate_json(raw)
                    except ValidationError as exc:
                        raise ReviewStoreError(
                            f"review ledger line {line_number} is invalid: {exc}"
                        ) from exc
                    if snapshot_sha256 is not None and record.snapshot_sha256 != snapshot_sha256:
                        raise ReviewStoreError(
                            f"review ledger line {line_number} targets a different snapshot"
                        )
                    records.append(record)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise ReviewStoreError(f"could not read review ledger: {exc}") from exc
        return tuple(records)


def create_review_record(
    *,
    snapshot: CatalogSnapshot,
    snapshot_sha256: str,
    class_id: str,
    action: ReviewAction,
    reviewer: str,
    visual_version_id: str | None = None,
    comment: str = "",
) -> CatalogReviewRecord:
    catalog_records: tuple[CatalogRecord, ...] = (*snapshot.heroes, *snapshot.items)
    records = {record.id: record for record in catalog_records}
    record = records.get(class_id)
    if record is None:
        raise ReviewStoreError(f"unknown class ID: {class_id}")
    if visual_version_id is not None and visual_version_id not in {
        visual.id for visual in record.visual_versions
    }:
        raise ReviewStoreError(
            f"visual version {visual_version_id!r} does not belong to {class_id!r}"
        )
    return CatalogReviewRecord(
        action_id=uuid.uuid4().hex,
        snapshot_sha256=snapshot_sha256,
        catalog_version=snapshot.catalog_version,
        class_id=class_id,
        visual_version_id=visual_version_id,
        action=action,
        reviewer=reviewer.strip(),
        reviewed_at=datetime.now(timezone.utc),
        comment=comment.strip(),
    )


def apply_review_actions(
    snapshot: CatalogSnapshot,
    actions: tuple[CatalogReviewRecord, ...],
) -> CatalogSnapshot:
    """Materialize the latest explicit action without mutating the staging snapshot."""

    latest: dict[tuple[str, str | None], CatalogReviewRecord] = {}
    for action in actions:
        latest[(action.class_id, action.visual_version_id)] = action

    def apply_record(record: CatalogRecord) -> CatalogRecord:
        class_action = latest.get((record.id, None))
        class_status = record.review_status
        if class_action is not None:
            class_status = (
                ReviewStatus.APPROVED
                if class_action.action is ReviewAction.APPROVE
                else ReviewStatus.REJECTED
            )
        visuals = []
        for visual in record.visual_versions:
            visual_action = latest.get((record.id, visual.id)) or class_action
            visual_status = visual.review_status
            provenance_status = visual.provenance.status
            if visual_action is not None:
                visual_status = (
                    ReviewStatus.APPROVED
                    if visual_action.action is ReviewAction.APPROVE
                    else ReviewStatus.REJECTED
                )
                provenance_status = (
                    ProvenanceStatus.VERIFIED
                    if visual_action.action is ReviewAction.APPROVE
                    else ProvenanceStatus.REJECTED
                )
            visuals.append(
                visual.model_copy(
                    update={
                        "review_status": visual_status,
                        "provenance": visual.provenance.model_copy(
                            update={"status": provenance_status}
                        ),
                    }
                )
            )
        return record.model_copy(
            update={"review_status": class_status, "visual_versions": tuple(visuals)}
        )

    heroes = tuple(apply_record(record) for record in snapshot.heroes)
    items = tuple(apply_record(record) for record in snapshot.items)
    return snapshot.model_copy(update={"heroes": heroes, "items": items})


class _ReviewHandler(BaseHTTPRequestHandler):
    server: CatalogReviewServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler interface
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._render_index()
            return
        if parsed.path.startswith("/assets/"):
            self._serve_asset(parsed.path.removeprefix("/assets/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler interface
        if urlparse(self.path).path != "/review":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if length <= 0 or length > 16 * 1024:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        if fields.get("csrf", [""])[0] != self.server.csrf_token:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid CSRF token")
            return
        try:
            record = create_review_record(
                snapshot=self.server.snapshot,
                snapshot_sha256=self.server.snapshot_sha256,
                class_id=fields.get("class_id", [""])[0],
                visual_version_id=fields.get("visual_version_id", [""])[0] or None,
                action=ReviewAction(fields.get("action", [""])[0]),
                reviewer=fields.get("reviewer", [""])[0],
                comment=fields.get("comment", [""])[0],
            )
            self.server.store.append(record)
        except (ReviewStoreError, ValueError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _render_index(self) -> None:
        try:
            actions = self.server.store.load(snapshot_sha256=self.server.snapshot_sha256)
            reviewed = apply_review_actions(self.server.snapshot, actions)
        except ReviewStoreError as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        rows: list[str] = []
        records: tuple[CatalogRecord, ...] = (*reviewed.heroes, *reviewed.items)
        for record in records:
            visual = record.visual_versions[-1]
            rows.append(
                "<tr>"
                f"<td><img src='/assets/{html.escape(visual.asset_path, quote=True)}' "
                "width='72' height='72' loading='lazy'></td>"
                f"<td><code>{html.escape(record.id)}</code></td>"
                f"<td>{html.escape(record.canonical_name)}</td>"
                f"<td>{html.escape(record.review_status.value)}</td>"
                "<td><form method='post' action='/review'>"
                f"<input type='hidden' name='csrf' value='{self.server.csrf_token}'>"
                "<input type='hidden' name='class_id' "
                f"value='{html.escape(record.id, quote=True)}'>"
                "<input name='reviewer' required maxlength='200' placeholder='Reviewer'>"
                "<input name='comment' maxlength='2000' placeholder='Evidence/comment'>"
                "<button name='action' value='approve'>"
                "Approve label + visuals + provenance</button>"
                "<button name='action' value='reject'>Reject</button>"
                "</form></td></tr>"
            )
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>N.E.X.U.S Catalog Review</title>"
            "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #ccc;padding:.4rem}img{object-fit:contain}"
            "form{display:grid;gap:.3rem}"
            "code{font-size:.8rem}</style></head><body>"
            f"<h1>Catalog {html.escape(reviewed.catalog_version)}</h1>"
            "<p>Each action is appended durably and bound to this snapshot SHA-256.</p>"
            "<table><thead><tr><th>Asset</th><th>ID</th><th>Name</th><th>Status</th>"
            f"<th>Review</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _serve_asset(self, relative_path: str) -> None:
        candidate = (self.server.snapshot_root / relative_path).resolve()
        root = self.server.snapshot_root.resolve()
        records: tuple[CatalogRecord, ...] = (
            *self.server.snapshot.heroes,
            *self.server.snapshot.items,
        )
        allowed = {
            visual.asset_path: visual.mime_type
            for record in records
            for visual in record.visual_versions
        }
        if (
            not candidate.is_relative_to(root)
            or relative_path not in allowed
            or not candidate.is_file()
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = candidate.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", allowed[relative_path])
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


class CatalogReviewServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        snapshot: CatalogSnapshot,
        snapshot_sha256: str,
        snapshot_root: Path,
        store: CatalogReviewStore,
    ) -> None:
        self.snapshot = snapshot
        self.snapshot_sha256 = snapshot_sha256
        self.snapshot_root = snapshot_root
        self.store = store
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(server_address, _ReviewHandler)


def create_review_server(
    snapshot_path: Path,
    *,
    actions_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> tuple[CatalogReviewServer, ReviewServerAddress]:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ReviewStoreError("the review server may bind only to a loopback host")
    try:
        snapshot, digest, manifest = load_snapshot(snapshot_path)
    except CatalogStorageError as exc:
        raise ReviewStoreError(str(exc)) from exc
    store = CatalogReviewStore(actions_path or manifest.parent / "review_actions.jsonl")
    server = CatalogReviewServer(
        (host, port),
        snapshot=snapshot,
        snapshot_sha256=digest,
        snapshot_root=manifest.parent,
        store=store,
    )
    raw_host, bound_port = server.server_address[:2]
    bound_host = raw_host.decode("ascii") if isinstance(raw_host, bytes) else raw_host
    address = ReviewServerAddress(
        host=str(bound_host),
        port=int(bound_port),
        url=f"http://{bound_host}:{bound_port}/",
    )
    return server, address


def serve_review(
    snapshot_path: Path,
    *,
    actions_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    server, _ = create_review_server(
        snapshot_path,
        actions_path=actions_path,
        host=host,
        port=port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
