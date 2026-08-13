"""Catalog source adapters, including contained V1 migration and remote sources."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlencode, urlparse, urlunparse

import requests

from nexus_v2.catalog.models import CatalogKind, SourceFailure
from nexus_v2.catalog.policy import is_visible_item_slot_class


@dataclass(frozen=True)
class SourceCandidate:
    kind: CatalogKind
    source_adapter: str
    source_identity: str
    canonical_name: str
    aliases: dict[str, tuple[str, ...]]
    source_reference: str
    local_path: Path | None = None
    asset_url: str | None = None
    allowed_asset_hosts: frozenset[str] = frozenset()
    credential_environment_variables: tuple[str, ...] = ()
    classification_enabled: bool = True
    legacy_path: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.local_path is None) == (self.asset_url is None):
            raise ValueError("source candidate requires exactly one local_path or asset_url")


@dataclass(frozen=True)
class SourceResult:
    candidates: tuple[SourceCandidate, ...]
    failures: tuple[SourceFailure, ...] = ()


class CatalogSource(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def discover(self) -> SourceResult: ...


def normalize_label(value: str) -> str:
    """Normalize a human label only for matching; never use it as a stable ID."""

    folded = value.casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).split())


def _hero_name_from_filename(path: Path) -> str:
    match = re.fullmatch(r"hero_(\d+)_([A-Za-z0-9_.-]+)\.png", path.name)
    if match is None:
        raise ValueError("hero filename does not match the V1 migration convention")
    return match.group(2).replace("_", " ").replace("-", " ").replace(".", " ").title()


def _item_name_from_filename(path: Path) -> str:
    match = re.fullmatch(r"item_(.+)\.png", path.name)
    if match is None:
        raise ValueError("item filename does not match the V1 migration convention")
    return match.group(1)


class LocalV1CatalogSource:
    """Read-only adapter over the exact hero/item assets used by V1."""

    adapter_id = "local_v1_migration"

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def discover(self) -> SourceResult:
        candidates: list[SourceCandidate] = []
        failures: list[SourceFailure] = []
        metadata = self._load_item_metadata(failures)
        hero_paths = sorted((self.repository_root / "heroes" / "portraits").glob("*.png"))
        item_paths = sorted((self.repository_root / "items" / "icons").glob("*.png"))
        for path in hero_paths:
            try:
                match = re.fullmatch(r"hero_(\d+)_([A-Za-z0-9_.-]+)\.png", path.name)
                if match is None:
                    raise ValueError("filename does not contain a numeric V1 hero identity")
                source_id = str(int(match.group(1)))
                name = _hero_name_from_filename(path)
                candidates.append(
                    SourceCandidate(
                        kind=CatalogKind.HERO,
                        source_adapter=self.adapter_id,
                        source_identity=f"v1-hero:{source_id}",
                        canonical_name=name,
                        aliases={"en": (name,)},
                        source_reference=path.relative_to(self.repository_root).as_posix(),
                        local_path=path,
                        legacy_path=path.relative_to(self.repository_root).as_posix(),
                        notes=("label inferred from the V1 filename; not human verified",),
                    )
                )
            except ValueError as exc:
                failures.append(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        source_identity=path.name,
                        stage="metadata",
                        reason=str(exc),
                    )
                )
        for path in item_paths:
            try:
                filename_name = _item_name_from_filename(path)
                item_metadata = metadata.get(path.name)
                metadata_name = item_metadata.get("name") if item_metadata is not None else None
                name = metadata_name if isinstance(metadata_name, str) else filename_name
                if not is_visible_item_slot_class(name):
                    continue
                source_reference_value = (
                    item_metadata.get("url") if item_metadata is not None else None
                )
                source_reference = (
                    _redacted_reference(str(source_reference_value))
                    if source_reference_value
                    else path.relative_to(self.repository_root).as_posix()
                )
                is_empty_sentinel = normalize_label(filename_name) == "empty"
                notes = ["label and provenance are inherited from V1 and remain unverified"]
                if item_metadata is None:
                    notes.append("V1 item metadata has no entry for this filename")
                if is_empty_sentinel:
                    notes.append(
                        "V1 empty-slot sentinel; excluded from the item identity class map"
                    )
                candidates.append(
                    SourceCandidate(
                        kind=CatalogKind.ITEM,
                        source_adapter=self.adapter_id,
                        source_identity=f"v1-item:{path.name}",
                        canonical_name="Empty Slot" if is_empty_sentinel else name,
                        aliases={"en": (name,)},
                        source_reference=source_reference,
                        local_path=path,
                        classification_enabled=not is_empty_sentinel,
                        legacy_path=path.relative_to(self.repository_root).as_posix(),
                        notes=tuple(notes),
                    )
                )
            except ValueError as exc:
                failures.append(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        source_identity=path.name,
                        stage="metadata",
                        reason=str(exc),
                    )
                )
        return SourceResult(candidates=tuple(candidates), failures=tuple(failures))

    def _load_item_metadata(self, failures: list[SourceFailure]) -> dict[str, dict[str, object]]:
        path = self.repository_root / "items" / "items_metadata_validated.json"
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(
                SourceFailure(
                    source_adapter=self.adapter_id,
                    stage="metadata",
                    reason=f"could not load V1 item metadata: {exc}",
                )
            )
            return {}
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            failures.append(
                SourceFailure(
                    source_adapter=self.adapter_id,
                    stage="metadata",
                    reason="V1 item metadata has an invalid top-level shape",
                )
            )
            return {}
        result: dict[str, dict[str, object]] = {}
        for entry in payload["items"]:
            if isinstance(entry, dict) and isinstance(entry.get("filename"), str):
                result[entry["filename"]] = entry
        return result


def _redacted_reference(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


class MoontonHeroCatalogSource:
    """Bounded adapter for the hero endpoint formerly used by the V1 scraper.

    The required authorization value is read only from ``NEXUS_MOONTON_AUTHORIZATION``.
    A missing credential becomes a source failure rather than a process-level exception.
    """

    adapter_id = "moonton_hero_api"
    api_url = "https://api.gms.moontontech.com/api/gms/source/2669606/2756564"
    credential_env = "NEXUS_MOONTON_AUTHORIZATION"
    allowed_asset_hosts = frozenset(
        {
            "akmweb.youngjoygame.com",
            "akmwebstatic.yuanzhanapp.com",
            "mlbbweb-static.moonton.com",
        }
    )

    def __init__(self, hero_ids: tuple[int, ...], *, timeout_seconds: float = 10.0) -> None:
        self.hero_ids = hero_ids
        self.timeout_seconds = timeout_seconds

    def discover(self) -> SourceResult:
        credential = os.environ.get(self.credential_env)
        if not credential:
            return SourceResult(
                candidates=(),
                failures=(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        stage="credentials",
                        reason=f"required environment variable {self.credential_env} is not set",
                    ),
                ),
            )
        candidates: list[SourceCandidate] = []
        failures: list[SourceFailure] = []
        headers = {
            "Accept": "application/json",
            "Authorization": credential,
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.mobilelegends.com",
            "Referer": "https://www.mobilelegends.com/",
        }
        try:
            for hero_id in self.hero_ids:
                payload = {
                    "pageSize": 1,
                    "pageIndex": 1,
                    "filters": [{"field": "hero_id", "operator": "eq", "value": str(hero_id)}],
                    "sorts": [],
                    "object": [],
                }
                try:
                    response = requests.post(
                        self.api_url,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout_seconds,
                        allow_redirects=False,
                    )
                    if response.status_code != 200:
                        raise ValueError(f"unexpected HTTP status {response.status_code}")
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                    if content_type not in {"application/json", "text/json"}:
                        raise ValueError(f"unexpected Content-Type {content_type!r}")
                    if len(response.content) > 2 * 1024 * 1024:
                        raise ValueError("metadata response exceeded 2 MiB")
                    data: object = response.json()
                    candidate = self._parse_candidate(hero_id, data)
                    if candidate is not None:
                        candidates.append(candidate)
                    else:
                        raise ValueError("response contained no complete hero record")
                except (requests.RequestException, ValueError) as exc:
                    failures.append(
                        SourceFailure(
                            source_adapter=self.adapter_id,
                            source_identity=str(hero_id),
                            stage="metadata",
                            reason=str(exc),
                        )
                    )
        finally:
            headers.clear()
            credential = ""
        return SourceResult(candidates=tuple(candidates), failures=tuple(failures))

    def _parse_candidate(self, hero_id: int, payload: object) -> SourceCandidate | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        records = data.get("records")
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            return None
        outer = records[0].get("data")
        if not isinstance(outer, dict):
            return None
        hero_wrapper = outer.get("hero")
        hero = hero_wrapper.get("data") if isinstance(hero_wrapper, dict) else None
        if not isinstance(hero, dict):
            return None
        name = hero.get("name")
        url = outer.get("head") or outer.get("head_big") or hero.get("squarehead")
        if not isinstance(name, str) or not isinstance(url, str):
            return None
        hostname = urlparse(url).hostname
        if hostname is None or hostname.lower() not in self.allowed_asset_hosts:
            return None
        return SourceCandidate(
            kind=CatalogKind.HERO,
            source_adapter=self.adapter_id,
            source_identity=f"moonton-hero:{hero_id}",
            canonical_name=name,
            aliases={"en": (name,)},
            source_reference=_redacted_reference(url),
            asset_url=url,
            allowed_asset_hosts=self.allowed_asset_hosts,
            credential_environment_variables=(self.credential_env,),
            notes=("remote label and provenance require human verification",),
        )


class FandomItemCatalogSource:
    """Remote-image adapter over the validated Fandom metadata used by V1."""

    adapter_id = "fandom_v1_item_metadata"

    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = metadata_path

    @staticmethod
    def wiki_api_title(item_name: str) -> str:
        """Build a correctly encoded query for names containing apostrophes and Unicode."""

        title = f"File:{item_name}.png"
        return "https://mobile-legends.fandom.com/api.php?" + urlencode(
            {"action": "query", "format": "json", "titles": title},
            quote_via=quote,
        )

    def discover(self) -> SourceResult:
        try:
            payload: object = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return SourceResult(
                candidates=(),
                failures=(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        stage="metadata",
                        reason=str(exc),
                    ),
                ),
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            return SourceResult(
                candidates=(),
                failures=(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        stage="metadata",
                        reason="metadata does not contain an items list",
                    ),
                ),
            )
        candidates: list[SourceCandidate] = []
        failures: list[SourceFailure] = []
        for entry in payload["items"]:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            url = entry.get("url")
            if not isinstance(name, str) or not isinstance(url, str):
                failures.append(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        stage="metadata",
                        reason="item entry omitted a string name or URL",
                    )
                )
                continue
            if not is_visible_item_slot_class(name):
                continue
            host = urlparse(url).hostname
            allowed_hosts = frozenset({"static.wikia.nocookie.net", "vignette.wikia.nocookie.net"})
            if host is None or host.lower() not in allowed_hosts:
                failures.append(
                    SourceFailure(
                        source_adapter=self.adapter_id,
                        source_identity=name,
                        stage="metadata",
                        reason="item URL host is absent or outside the Fandom image allowlist",
                    )
                )
                continue
            candidates.append(
                SourceCandidate(
                    kind=CatalogKind.ITEM,
                    source_adapter=self.adapter_id,
                    source_identity=f"fandom-item:{normalize_label(name)}",
                    canonical_name=name,
                    aliases={"en": (name,)},
                    source_reference=_redacted_reference(url),
                    asset_url=url,
                    allowed_asset_hosts=allowed_hosts,
                    notes=("Fandom-derived label and artwork require human verification",),
                )
            )
        return SourceResult(candidates=tuple(candidates), failures=tuple(failures))
