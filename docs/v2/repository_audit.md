# V1 repository audit

**Audit date:** 2026-07-31  
**Audit scope:** the frozen V1 tree plus the V2 PRD, before Phase 0 implementation files  
**Baseline tag:** `v1-baseline-2026-07-31`  
**Baseline commit:** `55cfff72236c1152eac54ac038a225154b209950`

## Executive summary

The V1 repository is a fixed-layout OpenCV and Tesseract extraction pipeline for five explicitly
selected MLBB post-match screen types. It contains a useful field model, configuration knowledge,
131 hero portraits, and 105 item icons. The completed inventory found 25 non-asset files and decoded
all 236 image assets successfully.

The repository contains no post-match screenshot fixtures, benchmark manifest, or approved ground
truth. V1 accuracy, coverage, latency, memory, confidence calibration, and full-JSON correctness
therefore cannot be measured from repository contents. Those values must remain unreported until a
reviewed external dataset is mounted.

## Scope and method

The audit covered source code, configuration, catalog metadata, dependency declarations, scrapers,
documentation, and image assets present at the baseline. It recorded file roles, followed the V1
execution path, decoded each hero and item asset to check readability, and searched the tree for
representative input screenshots and approved annotations. It did not infer accuracy from source
code or treat catalog artwork as benchmark input.

The baseline tag and commit identify the behavior under evaluation. Phase 0 must not move or rewrite
that tag and must not alter the V1 modules to improve a benchmark result.

## Inventory

### Non-asset files

The audit counted 25 non-asset files:

| Area | Count | Contents |
|---|---:|---|
| Root and product documents | 6 | `.gitignore`, `LICENSE`, `README.md`, `requirements.txt`, `main.py`, and `NEXUS_ML_V2_PRD.md` |
| V1 application package | 9 | package markers, configuration loader, detector, preprocessor, OCR, hero matcher, and item matcher |
| YAML configuration | 7 | field extraction, hero mapping, and five screen column maps |
| Item metadata | 1 | `items/items_metadata_validated.json` |
| Catalog scraping tools | 2 | hero portrait and item metadata/icon scrapers |
| **Total** | **25** | |

Generated caches, Git internals, virtual environments, and the 236 catalog images were not counted
as non-asset files.

### Image assets

| Asset set | Files | Decode result | Benchmark role |
|---|---:|---|---|
| Hero portraits | 131 PNG files | 131 decoded | Recognition reference material only |
| Item icons | 105 PNG files | 105 decoded | Recognition reference material only |
| **Total** | **236** | **236 decoded, 0 decode failures** | Not screenshot fixtures or ground truth |

Successful decoding establishes file readability only. It does not establish correct labels,
provenance, stable class identity, patch coverage, duplicate freedom, or recognition accuracy.

### Benchmark data

| Evidence | Count | Consequence |
|---|---:|---|
| Post-match screenshot fixtures | 0 | V1 cannot be executed on representative repository data |
| Benchmark manifests | 0 | No versioned split or checksum inventory exists |
| Approved annotations | 0 | No metric denominator is available |

Hero portraits and item icons are not screenshots and must not be substituted for end-to-end test
inputs. Configuration files and example JSON in the README are not approved annotations.

## V1 architecture and behavior

The V1 entry point accepts `screenshot_path` and an explicit `screen1` through `screen5` value.
`main.py` selects one YAML coordinate map, loads and normalizes the screenshot, detects five player
rows, extracts configured cells, applies OCR, and returns a JSON object. Screen 1 also runs hero and
item matching; screens 2 through 5 are OCR-oriented.

The main flow is:

1. load the screenshot with OpenCV;
2. resize toward a 1920 by 1080 reference;
3. detect ally rows in a configured vertical region, falling back to five equal subdivisions;
4. derive field crops from screen-specific percentage coordinates;
5. run field-specific Tesseract preprocessing and handcrafted recognition logic;
6. match screen-1 heroes and items against local catalog images; and
7. assemble metadata, allies, enemies, summary values, and per-field evidence into JSON.

V1 includes valuable domain knowledge, but its input contract requires the screen type and its
geometry remains coupled to fixed configuration maps. Row fallback can return plausible crops when
detection fails, which makes silent geometry errors possible. Image matching scores and Tesseract
scores are not calibrated probabilities.

## Runtime and dependencies

The legacy declaration requires Python 3.10+, OpenCV, NumPy, Pillow, pytesseract, and PyYAML.
Tesseract itself is a system executable and is not installed by Python dependency resolution. V1's
OCR module assigns a Windows-specific Tesseract path at import time; the Phase 0 adapter corrects
that setting only inside an isolated benchmark subprocess after resolving an explicit option,
`NEXUS_TESSERACT_CMD`, or `PATH`.

The baseline had no lockfile or Python package metadata. Phase 0 adds pinned project dependencies and
`uv.lock` around the compatibility layer without editing V1 behavior.

## Catalog observations

V1 identity is derived from numeric hero configuration and item names/filenames. The repository does
not provide the V2 catalog requirements of stable IDs, immutable snapshots, asset checksums, visual
version history, patch bounds, provenance records, deterministic class maps, or a human promotion
gate. These are Phase 1 concerns and are intentionally not implemented during Phase 0.

The two scraper scripts are maintenance utilities with network-facing behavior. Inference itself can
use local catalog assets, but a future catalog refresh must validate remote inputs and licensing
separately.

## Tests, packaging, and automation at baseline

The audited baseline contained no automated test suite, benchmark harness, approved golden cases,
Python lockfile, or CI-quality lint/type configuration. As a result, the repository could not prove
V1 extraction reproducibility or any quality target from committed evidence alone.

Phase 0 adds tests and tooling for schemas, dataset validation, metric arithmetic, Tesseract
resolution, subprocess isolation, runner behavior, and CLI behavior. These validate the harness;
they are not evidence of V1 extraction accuracy.

## Risks and constraints carried forward

- Fixed screen selection and coordinate maps are brittle under UI, aspect-ratio, viewport, and crop
  changes.
- Equal-row fallback can conceal geometry failure.
- Upscaling native-small crops does not restore lost information.
- Catalog labels and artwork have not passed the V2 integrity and provenance gates.
- OCR preprocessing is distributed across heuristic branches, and a failed read can be confused
  with a numeric value without a typed evidence boundary.
- Legacy confidence values are uncalibrated and must be labeled accordingly.
- Player names and battle IDs can be identifying data; benchmark screenshots and annotations must
  remain private and access-controlled.
- No accuracy or release claim is possible without held-out, approved ground truth.

## Phase 0 conclusions

The baseline is frozen and adapter-ready, and its repository structure and assets are inventoried.
The truth-establishment portion of Phase 0 is blocked: there are zero screenshot fixtures and zero
approved annotations, so no V1 benchmark metrics can be produced. The next valid action is to create
or mount a versioned, checksum-verified, human-approved benchmark dataset and rerun the V1 report.
Phase 1 must not begin on the strength of harness tests alone.
