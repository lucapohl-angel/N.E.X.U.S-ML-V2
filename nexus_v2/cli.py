"""Command-line entry points for the N.E.X.U.S-ML V2 vertical slices."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from nexus_v2.adapters import LegacyV1Adapter
from nexus_v2.benchmark.dataset import DEFAULT_MAX_IMAGE_BYTES
from nexus_v2.benchmark.models import ReportStatus
from nexus_v2.benchmark.runner import run_benchmark
from nexus_v2.catalog.audit import audit_snapshot
from nexus_v2.catalog.models import CatalogKind, HeroRecord, ItemRecord
from nexus_v2.catalog.promotion import CatalogPromotionError, promote_catalog
from nexus_v2.catalog.review import (
    CatalogReviewStore,
    ReviewStoreError,
    apply_review_actions,
    create_review_server,
)
from nexus_v2.catalog.service import CatalogSyncError, catalog_diff, sync_catalog
from nexus_v2.catalog.sources import (
    CatalogSource,
    FandomItemCatalogSource,
    LocalV1CatalogSource,
    MoontonHeroCatalogSource,
)
from nexus_v2.catalog.storage import CatalogStorageError, load_snapshot, write_json
from nexus_v2.tesseract import TesseractUnavailableError, resolve_tesseract_cmd


def _catalog_kind(value: str) -> CatalogKind:
    aliases = {
        "hero": CatalogKind.HERO,
        "heroes": CatalogKind.HERO,
        "item": CatalogKind.ITEM,
        "items": CatalogKind.ITEM,
    }
    try:
        return aliases[value.casefold()]
    except KeyError as exc:
        raise argparse.ArgumentTypeError("task must be hero, heroes, item, or items") from exc


def _write_report(payload: str, output: Path | None) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _benchmark(args: argparse.Namespace) -> int:
    dataset_arg = args.dataset or os.environ.get("NEXUS_BENCHMARK_DATASET")
    dataset = Path(dataset_arg) if dataset_arg else Path("data/benchmarks/release-v1")
    adapter = LegacyV1Adapter(
        tesseract_cmd=args.tesseract_cmd,
        timeout_seconds=args.timeout_seconds,
    )
    report = run_benchmark(
        dataset_path=dataset,
        adapter=adapter,
        max_image_bytes=args.max_image_mib * 1024 * 1024,
    )
    _write_report(report.model_dump_json(indent=2), args.report)
    return 0 if report.status is ReportStatus.COMPLETED else 2


def _doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "repository": str(Path.cwd()),
        "max_default_image_bytes": DEFAULT_MAX_IMAGE_BYTES,
    }
    healthy = True
    try:
        executable = resolve_tesseract_cmd(args.tesseract_cmd)
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version_line = (completed.stdout or completed.stderr).splitlines()
        checks["tesseract"] = {
            "status": "ok" if completed.returncode == 0 else "error",
            "path": str(executable),
            "version": version_line[0] if version_line else None,
        }
        healthy = completed.returncode == 0
    except (TesseractUnavailableError, OSError, subprocess.SubprocessError) as exc:
        checks["tesseract"] = {"status": "error", "reason": str(exc)}
        healthy = False

    if args.json:
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        for name, value in checks.items():
            print(f"{name}: {value}")
    return 0 if healthy else 1


def _catalog_sync(args: argparse.Namespace) -> int:
    sources: list[CatalogSource] = []
    for source_name in args.source:
        if source_name == "local-v1":
            sources.append(LocalV1CatalogSource(args.repository))
        elif source_name == "moonton-heroes":
            sources.append(MoontonHeroCatalogSource(tuple(args.hero_id)))
        elif source_name == "fandom-items":
            sources.append(FandomItemCatalogSource(args.item_metadata))
    try:
        artifacts = sync_catalog(
            sources=tuple(sources),
            staging_path=args.staging,
            catalog_version=args.version,
            previous_path=args.previous,
        )
        audit = audit_snapshot(artifacts.snapshot, artifacts.snapshot_path)
    except (CatalogSyncError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, indent=2))
        return 2
    payload = {
        "status": "staged",
        "catalog_version": artifacts.snapshot.catalog_version,
        "snapshot_path": str(artifacts.snapshot_path),
        "snapshot_sha256": artifacts.snapshot_sha256,
        "heroes": len(artifacts.snapshot.heroes),
        "items": len(artifacts.snapshot.items),
        "hero_class_count": len(artifacts.snapshot.hero_class_map),
        "item_class_count": len(artifacts.snapshot.item_class_map),
        "mapped_files": artifacts.migration_report.mapped_files,
        "ambiguous_files": artifacts.migration_report.ambiguous_files,
        "failed_files": artifacts.migration_report.failed_files,
        "failed_downloads": len(artifacts.sync_report.failed_downloads),
        "mandatory_audit_issues": audit.mandatory_issue_count,
        "warning_audit_issues": audit.warning_issue_count,
        "promotion_ready": audit.promotion_ready,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _catalog_audit(args: argparse.Namespace) -> int:
    try:
        snapshot, _, manifest = load_snapshot(args.snapshot)
        report = audit_snapshot(snapshot, manifest.parent)
        payload = report.model_dump(mode="json")
        if args.report is not None:
            write_json(args.report, payload)
    except (CatalogStorageError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.promotion_ready else 2


def _catalog_diff(args: argparse.Namespace) -> int:
    try:
        old, _, _ = load_snapshot(args.old)
        new, _, _ = load_snapshot(args.new)
        difference = catalog_diff(old, new)
        payload = difference.model_dump(mode="json")
        if args.report is not None:
            write_json(args.report, payload)
    except (CatalogStorageError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _catalog_review(args: argparse.Namespace) -> int:
    if not args.serve:
        try:
            snapshot, digest, manifest = load_snapshot(args.snapshot)
            store = CatalogReviewStore(args.actions or manifest.parent / "review_actions.jsonl")
            actions = store.load(snapshot_sha256=digest)
            reviewed = apply_review_actions(snapshot, actions)
        except (CatalogStorageError, ReviewStoreError) as exc:
            print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
            return 2
        statuses: dict[str, int] = {}
        records: tuple[HeroRecord | ItemRecord, ...] = (*reviewed.heroes, *reviewed.items)
        for record in records:
            statuses[record.review_status.value] = statuses.get(record.review_status.value, 0) + 1
        print(
            json.dumps(
                {
                    "status": "review_summary",
                    "catalog_version": reviewed.catalog_version,
                    "actions": len(actions),
                    "class_statuses": statuses,
                    "serve_command": "add --serve to start the loopback review UI",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    try:
        server, address = create_review_server(
            args.snapshot,
            actions_path=args.actions,
            host=args.host,
            port=args.port,
        )
    except (OSError, ReviewStoreError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2
    print(
        json.dumps(
            {
                "status": "serving",
                "url": address.url,
                "snapshot": str(args.snapshot),
                "actions": str(server.store.path),
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("catalog review server stopped by operator", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def _catalog_promote(args: argparse.Namespace) -> int:
    try:
        result = promote_catalog(
            staging_path=args.snapshot,
            production_root=args.production,
            actions_path=args.actions,
        )
    except CatalogPromotionError as exc:
        payload: dict[str, Any] = {"status": "blocked", "reason": str(exc)}
        if exc.audit_report is not None:
            payload["audit"] = exc.audit_report.model_dump(mode="json")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "promoted",
                "catalog_version": result.snapshot.catalog_version,
                "production_path": str(result.production_path),
                "snapshot_sha256": result.snapshot_sha256,
                "audit": result.audit_report.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _catalog_export_classmap(args: argparse.Namespace) -> int:
    try:
        snapshot, digest, _ = load_snapshot(args.snapshot)
        entries = (
            snapshot.hero_class_map if args.task is CatalogKind.HERO else snapshot.item_class_map
        )
        payload = {
            "catalog_version": snapshot.catalog_version,
            "snapshot_sha256": digest,
            "task": args.task.value,
            "classes": [entry.model_dump(mode="json") for entry in entries],
        }
        if args.output is not None:
            write_json(args.output, payload)
    except (CatalogStorageError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    benchmark = subparsers.add_parser(
        "benchmark", description="Run V1 on every approved, checksum-verified sample"
    )
    benchmark.add_argument(
        "--dataset",
        help=(
            "Dataset directory or manifest path; defaults to NEXUS_BENCHMARK_DATASET, "
            "then data/benchmarks/release-v1"
        ),
    )
    benchmark.add_argument("--engine", choices=["v1"], default="v1")
    benchmark.add_argument(
        "--report",
        "--output",
        dest="report",
        type=Path,
        help="Write the JSON report to this path; --output is a compatibility alias",
    )
    benchmark.add_argument("--tesseract-cmd")
    benchmark.add_argument("--timeout-seconds", type=float, default=120.0)
    benchmark.add_argument("--max-image-mib", type=int, default=50)
    benchmark.set_defaults(handler=_benchmark)

    doctor = subparsers.add_parser("doctor", description="Verify local runtime prerequisites")
    doctor.add_argument("--tesseract-cmd")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_doctor)

    catalog = subparsers.add_parser("catalog", description="Manage immutable V2 catalogs")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)

    catalog_sync = catalog_commands.add_parser(
        "sync", description="Discover, validate, and write an immutable staging snapshot"
    )
    catalog_sync.add_argument("--staging", type=Path, required=True)
    catalog_sync.add_argument("--version", required=True)
    catalog_sync.add_argument("--previous", type=Path)
    catalog_sync.add_argument(
        "--source",
        action="append",
        choices=["local-v1", "moonton-heroes", "fandom-items"],
        default=None,
        help="Repeat to combine adapters; defaults to local-v1",
    )
    catalog_sync.add_argument("--repository", type=Path, default=Path.cwd())
    catalog_sync.add_argument(
        "--item-metadata", type=Path, default=Path("items/items_metadata_validated.json")
    )
    catalog_sync.add_argument("--hero-id", type=int, action="append", default=[])
    catalog_sync.set_defaults(handler=_catalog_sync)

    catalog_audit = catalog_commands.add_parser(
        "audit", description="Re-decode and audit an immutable snapshot"
    )
    catalog_audit.add_argument("snapshot", type=Path)
    catalog_audit.add_argument("--report", type=Path)
    catalog_audit.set_defaults(handler=_catalog_audit)

    catalog_diff_parser = catalog_commands.add_parser(
        "diff", description="Compare stable identity, visuals, names, and class maps"
    )
    catalog_diff_parser.add_argument("old", type=Path)
    catalog_diff_parser.add_argument("new", type=Path)
    catalog_diff_parser.add_argument("--report", type=Path)
    catalog_diff_parser.set_defaults(handler=_catalog_diff)

    catalog_review = catalog_commands.add_parser(
        "review", description="Inspect review state or run a loopback review server"
    )
    catalog_review.add_argument("snapshot", type=Path)
    catalog_review.add_argument("--serve", action="store_true")
    catalog_review.add_argument("--actions", type=Path)
    catalog_review.add_argument("--host", default="127.0.0.1")
    catalog_review.add_argument("--port", type=int, default=8765)
    catalog_review.set_defaults(handler=_catalog_review)

    catalog_promote = catalog_commands.add_parser(
        "promote", description="Apply review actions and gate a production snapshot"
    )
    catalog_promote.add_argument("snapshot", type=Path)
    catalog_promote.add_argument("--production", type=Path, default=Path("catalogs/production"))
    catalog_promote.add_argument("--actions", type=Path)
    catalog_promote.set_defaults(handler=_catalog_promote)

    export_classmap = catalog_commands.add_parser(
        "export-classmap", description="Export a deterministic model class map"
    )
    export_classmap.add_argument("snapshot", type=Path)
    export_classmap.add_argument(
        "--task",
        type=_catalog_kind,
        metavar="{hero,heroes,item,items}",
        required=True,
    )
    export_classmap.add_argument("--output", type=Path)
    export_classmap.set_defaults(handler=_catalog_export_classmap)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "catalog" and args.catalog_command == "sync":
        if args.source is None:
            args.source = ["local-v1"]
        if "moonton-heroes" in args.source and not args.hero_id:
            parser.error("--source moonton-heroes requires at least one --hero-id")
        if any(hero_id <= 0 for hero_id in args.hero_id):
            parser.error("--hero-id must be positive")
    if (
        args.command == "catalog"
        and args.catalog_command == "review"
        and not (0 <= args.port <= 65535)
    ):
        parser.error("--port must be between 0 and 65535")
    if args.command == "benchmark" and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.command == "benchmark" and args.max_image_mib <= 0:
        parser.error("--max-image-mib must be positive")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
