# V2 implementation status

**Updated:** 2026-08-01
**Active work:** Phase 1 catalog rebuild — local implementation verified, promotion blocked
**Phase 0 data gate:** **BLOCKED on verified benchmark data**
**Phase 1 promotion gate:** **BLOCKED on human label, asset, and provenance review**

## Status summary

The Phase 0 compatibility and benchmark harness remains implemented, but the repository still has no
post-match screenshot fixtures or approved annotations. Its empirical benchmark gate therefore
remains blocked and no extraction-accuracy metric is available.

The Phase 1 catalog software is implemented and locally verified: strict immutable models, stable
IDs, three source adapters, defensive image retrieval and validation, exact/perceptual duplicate
checks, visual history, deterministic class maps, diff/audit reports, a snapshot-bound append-only
review ledger, local review HTTP handling, model/catalog compatibility reporting, and gated
promotion. This technical implementation does not make the local V1 catalog production-ready.

The checked-in snapshot is explicitly staging-only. Its 235 inherited class records/assets have not
received human approval or verified provenance. The audit therefore reports 705 mandatory issues
and promotion correctly refuses to create a production snapshot.

## Phase 1 deliverables

| Deliverable | Status | Evidence |
|---|---|---|
| Stable catalog schema | Implemented | Frozen Pydantic models reject unknown fields, unsafe paths, duplicate IDs, and invalid class maps |
| Source adapters | Implemented | Local V1 migration, credential-gated Moonton hero metadata, and allowlisted Fandom item metadata adapters |
| Secure downloader and asset validation | Implemented and tested | HTTPS/host/redirect/size limits; Pillow plus OpenCV decode; MIME, dimensions, transparency/content, SHA-256, and pHash checks |
| Diff, audit, and duplicate workflow | Implemented and tested | Exact and near duplicates, label conflicts, visual changes, missing assets, placeholders, hashes, MIME, dimensions, and aspect ratios are reported |
| Review workflow | Implemented and tested | Snapshot-bound append-only JSONL ledger, CSRF-protected HTTP review action, safe asset serving, and immutable action application |
| Model compatibility | Implemented and tested | Runtime-only, model-only, and missing observed visual IDs are exposed; new runtime classes require prototype fallback |
| Fresh local migration snapshot | Staged, not approved | `catalogs/staging/phase1-v1-migration-2026-08-01/catalog.json` and SHA-256 sidecar |
| Migration report | Generated | 131 hero files, 105 item files, 236 mappings, 0 ambiguous, 0 failed |
| Class maps | Generated deterministically | 131 hero entries and 104 item entries, both bound to the snapshot SHA-256 |
| Production snapshot | **Blocked** | No review actions exist; audit has 705 mandatory issues and promotion exits 2 |

## Inventory boundary

The legacy source tree contains 131 hero portrait files and 105 item icon files. `item_EMPTY.png` is
a slot-state sentinel, not an item identity. The migration report preserves its mapping as
`item_empty_slot` with `excluded_empty_slot_sentinel`, while the manifest and item class map exclude
it. The authoritative staging inventory is therefore:

| Evidence | Count |
|---|---:|
| Hero source files / hero classes | 131 / 131 |
| Item source files | 105 |
| Non-item empty-slot sentinels | 1 |
| Item identity classes | 104 |
| Catalog records and decoded assets | 235 |
| Migration mappings | 236 |
| Ambiguous or failed mappings | 0 / 0 |

No source label is treated as human-verified merely because its bytes decode or its filename maps
deterministically.

## Audit and promotion state

The final local audit on 2026-08-01 produced:

| Audit result | Count/state |
|---|---:|
| Decoded assets | 235 |
| Hash, pHash, MIME, dimension, missing-file, placeholder, duplicate, or aspect-ratio issues | 0 |
| Unreviewed class issues | 235 |
| Unreviewed visual issues | 235 |
| Unverified provenance issues | 235 |
| Mandatory issues | 705 |
| Warnings | 0 |
| Promotion ready | No |

The absence of structural asset errors does not validate labels or provenance. Promotion refusal is
the expected successful behavior for this snapshot.

## Verification status

The local quality gate currently passes:

- `uv lock --check`;
- Ruff formatting and lint over `nexus_v2` and `tests`;
- strict mypy over `nexus_v2` and `tests`;
- 32 automated tests, including 16 catalog tests, with no skips;
- fresh local-V1 `catalog sync` with 131 heroes, 104 item identities, and 0 failed downloads;
- snapshot `catalog audit` with expected exit 2 and 705 mandatory review issues;
- catalog diff with no identity, visual, rename, removal, or class-map drift;
- review summary with 235 unreviewed classes and zero actions;
- 131-entry hero and 104-entry item class-map exports; and
- `catalog promote` with expected exit 2 and no production snapshot.

The HTTP review handler was functionally exercised for index GET, allowlisted asset GET,
CSRF-protected review POST, redirect response, and durable ledger write. A live
`catalog review --serve --port 0` bind was attempted, but this managed execution sandbox denied the
loopback socket with `Operation not permitted`; a live listening-socket smoke is therefore not
claimed for this environment.

## Gate assessment

| Gate condition | Result | Reason |
|---|---|---|
| No placeholder records | Pass for staged identities | The empty-slot sentinel is documented in migration evidence and excluded from the manifest/class map |
| Every active approved class has a valid asset | Not yet satisfiable | Every asset is structurally valid, but there are zero approved classes; the gate does not pass vacuously |
| No unresolved duplicate/conflicting IDs | Structural pass | Migration has 0 ambiguous/failed mappings and audit found no exact/near duplicates or normalized-label conflicts |
| Class maps generated deterministically | Pass | Existing indices survive and new IDs append in stable order; exports are snapshot-bound |
| Required human promotion approval | **Blocked** | 235 classes, 235 visuals, and 235 provenance records remain unreviewed/unverified |

## Remaining external work

An authorized reviewer must compare every label and asset against an approved source, document the
evidence, and append explicit review actions bound to this exact snapshot digest. Official-source
authority and licensing must also be resolved. Only then may the audit and promotion commands be
rerun. Separately, an authorized data owner must still supply the private, approved screenshot
benchmark needed to unblock Phase 0 empirical evaluation.

## Explicit non-claims

- No V1 or V2 extraction accuracy, latency, memory, calibration, or full-JSON metric is claimed.
- Successful decoding and checksums do not prove catalog label correctness or source authority.
- Phase 1 is not promoted, production-ready, or human-approved.
- The loopback listening socket was not permitted in this sandbox.
- No catalog production directory was created by the refused promotion.
