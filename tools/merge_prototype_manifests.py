#!/usr/bin/env python3
"""Merge two private visual-prototype roots without mutating either parent."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_asset(manifest: Path, relative: str) -> Path:
    path = (manifest.parent / relative).resolve()
    if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
        raise ValueError(f"unsafe or missing prototype asset: {relative}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--additional", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "data/private").resolve()):
        raise SystemExit("merged prototypes must remain under data/private")
    temporary = output.with_name(output.name + ".tmp")
    if output.exists():
        raise SystemExit(f"refusing to overwrite merged prototypes: {output}")
    if temporary.exists():
        shutil.rmtree(temporary)

    summary: dict[str, int] = {}
    for kind in ("hero", "item"):
        parents = [
            ("base", args.base.resolve() / kind / "manifest.json"),
            ("additional", args.additional.resolve() / kind / "manifest.json"),
        ]
        loaded = [
            (label, path, json.loads(path.read_text(encoding="utf-8"))) for label, path in parents
        ]
        if any(payload["kind"] != kind for _, _, payload in loaded):
            raise SystemExit(f"prototype kind mismatch for {kind}")
        if len({payload["profile_id"] for _, _, payload in loaded}) != 1:
            raise SystemExit(f"profile mismatch for {kind}")
        if len({payload["catalog_sha256"] for _, _, payload in loaded}) != 1:
            raise SystemExit(f"catalog mismatch for {kind}")

        references: list[dict[str, Any]] = []
        seen: dict[str, str | None] = {}
        for label, manifest, payload in loaded:
            for source_reference in payload["references"]:
                source = safe_asset(manifest, source_reference["asset_path"])
                digest = sha256(source)
                if digest != source_reference["asset_sha256"]:
                    raise SystemExit(f"prototype asset hash mismatch: {source}")
                entity_id = source_reference.get("entity_id")
                prior = seen.get(digest)
                if prior is not None and prior != entity_id:
                    raise SystemExit("identical prototype bytes have conflicting labels")
                if digest in seen:
                    continue
                seen[digest] = entity_id
                index = len(references)
                relative = Path("assets") / label / f"{kind}_{index:04d}{source.suffix.lower()}"
                target = temporary / kind / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                reference = dict(source_reference)
                reference.update(
                    {
                        "visual_id": f"{args.version}_{kind}_{index:04d}",
                        "asset_path": relative.as_posix(),
                        "asset_sha256": digest,
                        "merged_from": label,
                    }
                )
                references.append(reference)

        manifest_path = temporary / kind / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "prototype_version": args.version,
            "kind": kind,
            "profile_id": loaded[0][2]["profile_id"],
            "calibration_only": True,
            "evaluation_warning": (
                "Merged calibration references; benchmark by grouped source holdout."
            ),
            "catalog_sha256": loaded[0][2]["catalog_sha256"],
            "parent_manifest_sha256": {label: sha256(path) for label, path, _ in loaded},
            "references": references,
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary[kind] = len(references)
    temporary.rename(output)
    print(json.dumps({"output": str(output), "references": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
