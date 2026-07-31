# Phase 0 benchmark results

**Updated:** 2026-07-31  
**Engine requested:** V1  
**Engine identity:** `legacy-v1` / `v1-baseline-2026-07-31@55cfff72236c1152eac54ac038a225154b209950`  
**Result:** **NO DATA — PHASE 0 BLOCKED**

## Dataset evidence

The repository audit established the following input state:

| Evidence | Observed count |
|---|---:|
| Non-asset baseline files, including the V2 PRD | 25 |
| Decoded hero portrait assets | 131 |
| Decoded item icon assets | 105 |
| Total decoded catalog assets | 236 |
| Post-match screenshot fixtures | 0 |
| Benchmark manifests | 0 |
| Approved annotations | 0 |

Catalog images are reference assets, not end-to-end screenshots. They cannot supply benchmark
denominators or prove extraction behavior.

## Command

The Phase 0 V1 benchmark command is:

```bash
uv run nexus benchmark \
  --engine v1 \
  --dataset data/benchmarks/release-v1 \
  --report evaluation/reports/v1.json
```

With the current checkout, `data/benchmarks/release-v1/manifest.json` does not exist. The CLI still
writes a JSON report and prints the same payload, but returns exit code 2 so automation cannot treat
the run as a successful benchmark.

## Observed no-data report

The observed report has these material fields:

```json
{
  "status": "no_data",
  "gate_reason": "No manifest.json exists at data/benchmarks/release-v1/manifest.json",
  "dataset_path": "data/benchmarks/release-v1",
  "dataset_version": null,
  "dataset_manifest_sha256": null,
  "engine_id": "legacy-v1",
  "engine_version": "v1-baseline-2026-07-31@55cfff72236c1152eac54ac038a225154b209950",
  "discovered_samples": 0,
  "approved_samples": 0,
  "executed_samples": 0,
  "successful_samples": 0,
  "failed_samples": {}
}
```

`generated_at` is intentionally omitted from this excerpt because it is run-specific. The generated
report is the authoritative machine-readable artifact for a particular invocation.

## Metric availability

No benchmark metric has a valid denominator. The report marks every required metric unavailable
with the no-data reason:

- geometry success and normalized coordinate error;
- hero top-1, top-3, and per-class recall;
- item top-1, top-3, occupancy accuracy, and per-class recall;
- unknown false-accept and false-reject rates;
- OCR exact-sequence accuracy and character error rate;
- numeric exact-value accuracy and zero/missing confusion;
- confidence calibration and selective accuracy at coverage;
- full-JSON and critical-field exact match;
- latency and peak memory; and
- required metadata, class-frequency, native-icon-dimension, and custom slices.

There are no numeric results to report. In particular, unavailable does not mean 0%, and the 16
passing harness tests do not establish any extraction metric.

## Harness verification

The Phase 0 harness verification result is separate from benchmark quality:

| Check | Result |
|---|---|
| Ruff format | Pass |
| Ruff lint | Pass |
| Strict mypy | Pass |
| Pytest | 16 passed |
| Tesseract doctor | Pass in the recorded local environment |
| Exact `--report` no-data smoke | Exit 2; JSON written with `status: no_data` |

These are local technical results dated 2026-07-31. They prove that the harness handles missing data
truthfully; they do not prove V1 quality on screenshots.

## Gate decision

Phase 0 is **blocked on verified benchmark data**, not complete. The PRD deliverables for an initial
golden dataset and V1 benchmark report remain unsatisfied, and the clean-environment V1 extraction
gate cannot be demonstrated without representative screenshots.

Phase 1 must not begin until an authorized data owner supplies a versioned manifest and every sample
has checksum-verified, human-approved ground truth. After mounting that dataset, rerun the command
above and replace this no-data summary only with values taken directly from the generated report.
