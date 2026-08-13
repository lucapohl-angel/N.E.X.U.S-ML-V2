#!/usr/bin/env python3
"""Validate a Nexus V2 private runtime bundle without importing application dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"unsafe or missing runtime asset: {relative}")
    return path


def _load(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"runtime JSON must contain an object: {path}")
    return payload


def validate(root: Path) -> dict[str, int]:
    root = root.expanduser().resolve()
    descriptor = _load(_safe_file(root, "bundle.json"))
    checksums_path = _safe_file(root, "checksums.sha256")
    expected_files: set[str] = set()
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or SHA256.fullmatch(digest) is None:
            raise ValueError("runtime checksum manifest is malformed")
        path = _safe_file(root, relative)
        if _sha256(path) != digest:
            raise ValueError(f"runtime asset checksum mismatch: {relative}")
        expected_files.add(relative)

    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        raise ValueError(
            f"runtime file inventory mismatch; missing={missing}, unexpected={unexpected}"
        )

    catalog_path = _safe_file(root, str(descriptor["catalog"]))
    catalog_sha256 = _sha256(catalog_path)
    if catalog_sha256 != descriptor.get("catalog_sha256"):
        raise ValueError("runtime catalog SHA-256 mismatch")
    catalog = _load(catalog_path)
    catalog_ids = {
        "hero": {str(row["id"]) for row in catalog["heroes"]},
        "item": {str(row["id"]) for row in catalog["items"]},
    }

    counts: dict[str, int] = {}
    for kind in ("hero", "item"):
        manifest_key = f"{kind}_manifest"
        manifest_path = _safe_file(root, str(descriptor[manifest_key]))
        manifest = _load(manifest_path)
        if manifest.get("schema_version") != 1 or manifest.get("kind") != kind:
            raise ValueError(f"runtime {kind} manifest has the wrong schema or kind")
        if manifest.get("catalog_sha256") != catalog_sha256:
            raise ValueError(f"runtime {kind} manifest catalog SHA-256 mismatch")
        if _sha256(manifest_path) != descriptor.get(f"{kind}_manifest_sha256"):
            raise ValueError(f"runtime {kind} manifest SHA-256 mismatch")
        references = manifest.get("references")
        if not isinstance(references, list) or not references:
            raise ValueError(f"runtime {kind} manifest has no references")
        visual_ids: set[str] = set()
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError(f"runtime {kind} reference is malformed")
            if set(reference) != {"asset_path", "entity_id", "name", "visual_id"}:
                raise ValueError(f"runtime {kind} reference contains non-runtime metadata")
            entity_id = reference["entity_id"]
            if entity_id is None and kind == "hero":
                raise ValueError("runtime hero reference cannot be empty")
            if entity_id is not None and str(entity_id) not in catalog_ids[kind]:
                raise ValueError(f"runtime {kind} entity is absent from the catalog")
            visual_id = str(reference["visual_id"])
            if visual_id in visual_ids:
                raise ValueError(f"runtime {kind} visual IDs must be unique")
            visual_ids.add(visual_id)
            _safe_file(manifest_path.parent, str(reference["asset_path"]))
        if len(references) != int(descriptor[f"{kind}_references"]):
            raise ValueError(f"runtime {kind} reference count mismatch")
        counts[kind] = len(references)

    policy_path = _safe_file(root, str(descriptor["policy"]))
    policy = _load(policy_path)
    if _sha256(policy_path) != descriptor.get("policy_sha256"):
        raise ValueError("runtime balanced policy SHA-256 mismatch")
    if policy.get("catalog_sha256") != catalog_sha256:
        raise ValueError("runtime balanced policy catalog SHA-256 mismatch")
    if policy.get("prototype_manifest_sha256") != descriptor.get("hero_manifest_sha256"):
        raise ValueError("runtime balanced policy prototype SHA-256 mismatch")
    if policy.get("status") != "operator_approved" or policy.get("enabled") is not True:
        raise ValueError("runtime balanced policy is not operator approved")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_assets", type=Path)
    args = parser.parse_args()
    counts = validate(args.runtime_assets)
    print(f"runtime assets valid: {counts['hero']} hero + {counts['item']} item references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
