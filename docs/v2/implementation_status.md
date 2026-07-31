# V2 implementation status

**Updated:** 2026-07-31  
**Active phase:** Phase 0 — Freeze V1 and establish truth  
**Phase gate:** **BLOCKED on verified benchmark data**  
**Later phases:** Not started

## Status summary

Phase 0 implementation provides a reproducible Python environment, frozen-baseline adapter,
review-gated annotation schema, checksum-validating dataset loader, denominator-carrying metrics,
truthful no-data reports, runtime diagnostics, and tests. The repository audit is documented.

Phase 0 is not complete. The repository has no screenshot fixtures and no approved annotations, so
the initial golden dataset and empirical V1 benchmark report do not exist. Passing harness tests do
not satisfy the Phase 0 data gate and do not authorize Phase 1.

## Deliverables

| Phase 0 deliverable | Status | Evidence |
|---|---|---|
| Tagged V1 baseline | Available, unchanged | `v1-baseline-2026-07-31` targets commit `55cfff72236c1152eac54ac038a225154b209950` |
| Repository audit | Implemented | `docs/v2/repository_audit.md` records 25 non-asset files and 236 decoded assets |
| Benchmark schema | Implemented and tested | strict Pydantic annotation, prediction, report, and extraction-result models under `nexus_v2/` |
| Initial golden dataset | **Blocked** | 0 screenshot fixtures, 0 benchmark manifests, and 0 approved annotations are present |
| V1 benchmark report | Harness implemented; empirical report **blocked** | CLI emits `status: no_data`, unavailable metrics, and exit code 2 when data is absent |
| No V1 behavior changes | Preserved | benchmark execution uses a subprocess adapter; V1 `main.py` and `app/` remain outside V2 formatting/type scope |

## Implemented Phase 0 surface

- `nexus_v2.schemas.annotation` defines source metadata, match-group identity, SHA-256, review
  status, reviewer evidence, geometry, heroes, items, OCR fields, semantic JSON, and slices.
- `nexus_v2.benchmark.dataset` loads a directory or manifest, limits manifest/image sizes, validates
  annotations, resolves paths, and verifies image SHA-256 before execution.
- `nexus_v2.adapters.LegacyV1Adapter` runs each sample in a fresh interpreter and maps V1 output into
  an engine-neutral typed prediction without changing legacy source.
- `nexus_v2.benchmark.metrics` reports explicit numerators and denominators and uses `unavailable`
  rather than invented zeroes where observations or adapter capabilities are absent.
- `nexus_v2.benchmark.runner` rejects unapproved samples and integrity failures before invoking V1.
- `nexus benchmark` supports the required `--report` option; `--output` remains an alias.
- `nexus doctor` checks Python context and the external Tesseract executable.
- `uv.lock`, Ruff, strict mypy, pytest, and pinned project dependencies make the harness reproducible.

## Verification status

The final commands and exact current results are recorded in `docs/v2/benchmark_results.md`. The
quality gate covers:

- `uv lock --check`;
- Ruff formatting and lint;
- strict mypy over `nexus_v2` and `tests`;
- all automated tests;
- `nexus doctor --json`; and
- the exact no-data benchmark command using `--report`.

These checks establish implementation integrity and local runtime readiness only. They do not
establish V1 accuracy, production quality, catalog correctness, or clean-environment screenshot
reproducibility.

## Phase 0 gate assessment

| Gate condition | Result | Reason |
|---|---|---|
| V1 can be reproduced from a clean environment | **Blocked for extraction evidence** | dependencies and Tesseract can be checked, but no representative screenshot exists to reproduce an extraction |
| Every benchmark sample has approved ground truth | **Blocked** | there are no benchmark samples and therefore no approved golden dataset |

Zero samples do not make the approval gate pass vacuously. Phase 0 requires an actual initial golden
dataset and measured V1 baseline.

## Blocking work

To unblock Phase 0, an authorized data owner must provide a private dataset with representative
post-match screenshots and a `manifest.json` accepted by `AnnotationManifest`. Every sample must
include its exact SHA-256, match-group ID, source metadata, typed annotation, `approved` status,
reviewer, and review timestamp. The release split must be versioned and held out according to the
PRD.

After that data is mounted, run the documented V1 benchmark, inspect execution failures and metric
denominators, and review the generated report. Only a real, reviewed report can determine whether
the Phase 0 gate passes.

## Explicit non-claims

- No V1, V2, hero, item, geometry, OCR, latency, memory, calibration, or full-JSON metric is claimed.
- The 236 decoded catalog assets are not a golden screenshot dataset.
- Unit and integration tests verify the harness, not extraction quality.
- Phase 0 is blocked, not complete.
- Phase 1 has not started.
- No GPU or detector experiment is authorized by the current evidence.
