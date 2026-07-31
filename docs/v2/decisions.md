# Phase 0 decision record

**Updated:** 2026-07-31  
**Scope:** decisions needed to freeze V1 and establish a truthful benchmark foundation

## Decision status vocabulary

- **Accepted:** implemented for Phase 0.
- **Deferred:** intentionally belongs to a later phase or requires missing evidence.
- **Blocked:** cannot be resolved truthfully with the repository's current data.

## D-000 — Preserve the existing baseline tag

**Status:** Accepted

`v1-baseline-2026-07-31` at commit `55cfff72236c1152eac54ac038a225154b209950`
is the immutable V1 comparison point. Phase 0 records it but does not recreate, move, delete, or
otherwise modify it.

**Consequence:** all benchmark reports identify that tag and commit. Working-tree implementation
changes are not folded into the V1 identity.

## D-001 — Isolate V1 instead of refactoring it

**Status:** Accepted

Each benchmark sample runs through `nexus_v2.legacy_runner` in a fresh Python subprocess. The adapter
normalizes the returned JSON into the common benchmark contract. V1 modules remain behaviorally
unchanged.

**Rationale:** V1 contains global configuration and a platform-specific Tesseract assignment. A
fresh process prevents screen configuration or runtime state from leaking between samples while a
process-local Tesseract correction preserves portability.

**Consequence:** subprocess startup is included in the operational path, failures are captured as
sample diagnostics, and the adapter imposes timeout and output-size limits.

## D-002 — Keep benchmark data private and external

**Status:** Accepted

Screenshot data is mounted outside the Git checkout or placed in the ignored
`data/benchmarks/` area. A manifest may use relative paths rooted at its directory or absolute paths.
The loader verifies file type, size, and SHA-256 before executing an engine.

**Rationale:** screenshots may contain player names and battle IDs. Source data must not be copied
into reports or accidentally staged.

**Consequence:** repository tests use synthetic metadata and temporary files; they do not create a
fake golden screenshot set.

## D-003 — Require human-approved ground truth before execution

**Status:** Accepted

Every sample in a benchmark manifest must have `approval: approved`, a reviewer, review timestamp,
and typed annotation. One unapproved sample blocks the run before any screenshot is accessed.

**Rationale:** partial or silently unreviewed denominators would make comparison results misleading.

**Consequence:** a manifest with zero samples returns `no_data`; a manifest with unapproved or
invalid samples returns `blocked`. Neither state is a successful benchmark.

## D-004 — Carry numerators, denominators, and unavailability

**Status:** Accepted

Every scalar accuracy/error metric carries its observation count. Metrics with no approved truth or
unsupported candidate depth are `unavailable` with a reason, not numeric zero. Reports also preserve
dataset version and manifest SHA-256.

**Rationale:** zero can be a real measurement. It must not stand in for missing evidence.

**Consequence:** the current no-data report contains no fabricated accuracy, latency, memory, or
calibration values.

## D-005 — Treat V1 confidence as uncalibrated

**Status:** Accepted

V1 scores are labeled `legacy_uncalibrated`. Calibration output may describe score behavior when
data exists, but it cannot call the values correctness probabilities.

**Rationale:** weighted similarities, rank scores, and Tesseract confidence are not probabilities
without held-out calibration evidence.

**Consequence:** downstream comparisons can distinguish legacy scores from future calibrated
confidence.

## D-006 — Use engine-neutral benchmark models

**Status:** Accepted

The schema separates annotations, engine predictions, raw results, execution evidence, and aggregate
metrics. Legacy hero/item identity translation is confined to the V1 adapter and metric truth
mapping.

**Rationale:** Phase 0 must establish one comparison protocol that future engines can implement
without shaping ground truth around V1's output quirks.

**Consequence:** the same approved samples and metric functions can later compare V1 and V2.

## D-007 — Resolve Tesseract explicitly and portably

**Status:** Accepted

The compatibility layer resolves Tesseract in this order: CLI option, `NEXUS_TESSERACT_CMD`, then
`PATH`. It rejects missing or non-executable candidates and offers `nexus doctor` for diagnosis.

**Rationale:** V1's hard-coded Windows path is not portable, while Tesseract remains an external
system dependency.

**Consequence:** no host-specific executable path is committed to V2 configuration.

## D-008 — Standardize the report option

**Status:** Accepted

The required command spelling is `--report`. `--output` is retained as an alias for compatibility,
and both populate the same destination. JSON is written even for `no_data` and `blocked` states;
those states return a non-zero exit code.

**Rationale:** callers need a machine-readable diagnostic artifact without mistaking absent data for
a successful benchmark.

## D-009 — Pin the Phase 0 toolchain without weakening V1 boundaries

**Status:** Accepted

The V2 package pins runtime and development dependencies in `pyproject.toml` and `uv.lock`. Ruff and
strict mypy cover `nexus_v2` and tests. Existing V1 application files are excluded because Phase 0
does not authorize a broad legacy refactor. The untyped third-party pytesseract import has one
narrow, code-specific mypy suppression at the import boundary.

**Consequence:** new Phase 0 code is strictly checked; no global `ignore_missing_imports`, relaxed
strictness, or broad `Any` escape was introduced.

## D-010 — Keep the Phase 0 gate blocked until measured

**Status:** Blocked

The audit found 25 non-asset files and 236 decodable catalog images, but zero screenshot fixtures
and zero approved annotations. Phase 0 is therefore blocked on a real golden dataset and verified V1
report.

**Rationale:** implementation completeness is not benchmark evidence, and catalog assets cannot be
repurposed as screenshots.

**Consequence:** Phase 1, catalog replacement, model training, and detector experiments remain out
of scope. No metrics will be invented to advance the gate.

## Deferred decisions

Stable catalog IDs, source authority, visual-version policy, geometry profiles, recognizer selection,
confidence thresholds, trained models, detector providers, and release thresholds remain deferred
to their PRD phases and evidence gates. This document does not select or implement them.
