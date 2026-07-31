# N.E.X.U.S-ML V2 — Product Requirements Document

**Product:** N.E.X.U.S-ML V2 Extraction Engine  
**Document version:** 1.0  
**Status:** Build-ready draft  
**Date:** 31 July 2026  
**Existing repository:** `lucapohl-angel/N.E.X.U.S-ML`  
**Recommended implementation branch:** `v2-engine`  
**Primary input:** Mobile Legends: Bang Bang post-match screenshots  
**Primary output:** Validated, versioned, structured JSON  
**Primary deployment target:** CPU-first local/server inference, with optional GPU-trained models  
**V1 policy:** Preserve V1 unchanged as a baseline and fallback during migration

---

## 1. Executive summary

N.E.X.U.S-ML V2 is a new extraction engine that converts MLBB post-match screenshots into trustworthy structured JSON. It must improve on V1 in four fundamental areas:

1. **Automatic geometry:** Locate tables, rows, hero portraits, item slots, and text fields from image content instead of relying on one fixed coordinate map. Two initial device calibrations are allowed only as bootstrap reference profiles. Runtime extraction must solve the geometry automatically and support any screenshot resolution that preserves a supported MLBB UI structure.
2. **Native-detail preservation:** Never claim that upscaling a small icon restores lost information. V2 must crop from the highest available native screenshot resolution, retain the original crop, and train/evaluate recognizers on realistic small-icon degradation, resizing, compression, and crop variation.
3. **Catalog integrity:** Rebuild and version the hero and item catalogs using stable IDs, verified labels, asset checksums, visual-version history, human review, and automated drift detection. Filenames must never be the primary class identity.
4. **Measured hybrid recognition:** Combine deterministic OpenCV methods, OCR, visual prototypes/embeddings, and optional trained classifiers. YOLO or another detector remains an optional final escalation path, not a mandatory dependency.

The engine must prefer an explicit `unknown`, `unsupported_layout`, or `low_quality` status over silently returning a wrong hero, item, battle ID, or statistic.

The project is successful only when accuracy is demonstrated on a versioned, held-out benchmark. Internal score values must not be presented as probabilities unless they have been calibrated against validation data.

---

## 2. Background

### 2.1 Current V1 behavior

V1 currently:

- Accepts a screenshot path and an explicitly supplied screen type.
- Uses screen-specific percentage coordinate maps.
- Detects five player rows and falls back to equal row division.
- Uses Tesseract with many field-specific preprocessing passes.
- Identifies heroes and items using several handcrafted OpenCV similarity methods.
- Combines method scores through manually selected weights, boosts, voting, or ranking.
- Returns structured JSON.
- Contains separate scrapers for hero portraits and item icons.

This foundation is valuable. V2 should preserve the useful domain knowledge—screen semantics, field schemas, validation ranges, known catalogs, and deterministic methods—while replacing brittle geometry, uncalibrated confidence, duplicated OCR code, and catalog drift.

### 2.2 Problems to solve

#### Geometry and resolution

V1’s screen maps are tied to expected layouts. Resizing or changing aspect ratio can move field boundaries, and left/right mirroring is not reliable enough by itself. A crop that is wrong by only a few pixels can materially reduce item or OCR accuracy.

#### Small-icon information

A 30–40-pixel icon can be resized to a model’s required tensor dimensions, but interpolation does not recreate missing detail. Recognition must be trained and tested on the same native-detail limitations seen in production.

#### Catalog drift

Hero and item assets can change over time. Sources may be incomplete, mislabeled, duplicated, URL-encoded incorrectly, or out of sync with the model’s class map. V2 needs one authoritative local catalog snapshot per release.

#### OCR reliability

The current OCR code contains many independent preprocessing branches and several disagreement rules that may prefer longer or larger values. Failure, true zero, invalid crop, and low-confidence recognition must be represented separately.

#### Confidence semantics

A normalized rank, weighted similarity, or Tesseract confidence is not automatically the probability that the final value is correct. V2 needs calibrated final confidence and clear abstention policies.

#### Benchmark absence

No architecture decision should be accepted based only on visual inspection or a few screenshots. V2 requires reproducible module-level and end-to-end evaluation.

---

## 3. Product vision

> Given one or more MLBB post-match screenshots from any supported screen resolution, N.E.X.U.S-ML V2 automatically identifies the UI layout, extracts every required field at native detail, recognizes heroes and items, reads text and numeric statistics, validates the result, and returns versioned JSON with trustworthy confidence and explicit failure states.

---

## 4. Product goals

### 4.1 Primary goals

- Automatically detect the post-match screen type.
- Automatically locate and align the result UI without requiring the caller to pass coordinate maps.
- Support arbitrary image resolutions for supported MLBB UI structures.
- Detect viewport cropping, letterboxing, scaling, blur, and unsupported layouts.
- Independently solve ally and enemy panel geometry; do not assume one side is a perfect mirror of the other.
- Rebuild hero and item catalogs with correct labels and stable IDs.
- Preserve original native-resolution crops.
- Improve hero, item, and OCR accuracy compared with V1 on the same held-out benchmark.
- Return exact structured JSON with raw evidence, calibrated confidence, model versions, catalog versions, and failure status.
- Run a useful CPU-only baseline without requiring a local GPU.
- Provide reproducible GPU training scripts for optional classifiers and detector experiments.
- Keep YOLO optional and gated by benchmark evidence and licensing review.
- Support adding new heroes/items without immediately requiring a full detector retrain through prototype/template fallback.
- Provide a human review and active-learning workflow for uncertain samples.

### 4.2 Target quality objectives

These are release targets, not claims before measurement:

- **Geometry success:** at least 99.5% of supported-layout screenshots produce valid field crops or explicitly abstain.
- **Silent geometry failure:** below 0.1% on the release benchmark.
- **Accepted hero precision:** at least 99.5% at the selected production coverage.
- **Accepted item precision:** at least 99.5% at the selected production coverage.
- **Battle ID exact accepted precision:** at least 99.9%.
- **Critical numeric field exact accepted precision:** at least 99.5%.
- **Unsupported/unknown handling:** new or invalid classes must not be routinely forced into a known class.
- **End-to-end metric:** report exact full-JSON accuracy, not only average per-field accuracy.
- **CPU-first latency target:** configurable, with a provisional target of under 5 seconds for one screen on a modern desktop CPU after model warmup. Accuracy has priority over this provisional latency target.

Coverage and precision must always be reported together.

---

## 5. Non-goals

- General OCR for arbitrary games or arbitrary screenshots.
- Recognition of live gameplay, minimaps, or video frames in the first V2 release.
- Inferring hidden values not visible in the screenshot.
- Guaranteeing correct extraction after an entirely new MLBB UI redesign that has never been seen. The required behavior is to detect `unsupported_layout`, not guess.
- Using a general-purpose vision-language model as the authoritative source of exact IDs or digits.
- Treating super-resolution output as recovered ground truth.
- Training one huge full-screen detector before the deterministic and crop-classification baselines have been benchmarked.
- Replacing V1 before V2 passes the formal benchmark.

---

## 6. Users and use cases

### 6.1 Primary user

A developer or service that needs reliable structured MLBB match data from screenshots.

### 6.2 Core use cases

1. Process one screenshot with automatic screen-type detection.
2. Process all available post-match screens for one match and merge evidence.
3. Run locally through Python or CLI.
4. Run behind an API.
5. Review uncertain hero/item/OCR predictions.
6. Synchronize the current hero/item catalog.
7. Compare a new engine version against V1.
8. Train or fine-tune a crop classifier on a rented GPU.
9. Optionally train a layout or YOLO model only after an evidence gate is met.
10. Update the catalog after a game patch without silently breaking old screenshots.

---

## 7. Product principles

1. **Geometry before recognition.**
2. **Crop at native resolution; standardize only after the crop exists.**
3. **Use multiple independent signals, but learn/calibrate their fusion from data.**
4. **Never force a known class when evidence is insufficient.**
5. **Stable IDs, not filenames, define labels.**
6. **One authoritative catalog snapshot per engine release.**
7. **Old visual versions remain available for historical screenshots.**
8. **Separate layout detection from hero/item identity recognition.**
9. **Separate hero and item recognizers.**
10. **Preserve raw OCR text and the processed value.**
11. **A true zero is not the same as OCR failure.**
12. **No paid GPU training before the CPU baseline and benchmark exist.**
13. **Every accuracy claim must name the dataset version and split.**
14. **The system must be debuggable through overlays, crops, candidates, and scores.**
15. **Inference must not depend on internet access.**

---

## 8. Definitions

- **Reference profile:** A canonical representation of a supported MLBB UI structure. It contains semantic geometry, masks, anchor templates, and expected relationships. It is not a fixed device-only coordinate map.
- **Bootstrap calibration:** One of the first two manually verified reference screenshots used to seed profile construction.
- **Viewport:** The actual game content region after removing black bars, browser chrome, social-media borders, or unrelated margins.
- **Canonical space:** A normalized coordinate system in which semantic fields are defined.
- **Native crop:** A crop taken directly from the original screenshot pixels before any global resize.
- **Layout hypothesis:** One complete proposed mapping from screenshot pixels to semantic UI fields.
- **Visual version:** A version of a hero portrait or item icon that is visibly different.
- **Catalog snapshot:** An immutable manifest containing all class IDs, labels, assets, checksums, and active patch ranges.
- **Accepted prediction:** A value that passes quality, confidence, margin, and validation thresholds.
- **Abstention:** A deliberate `unknown`, `low_quality`, or `unsupported` response rather than a guessed value.

---

## 9. High-level system architecture

```text
Input image(s)
    │
    ▼
Input decoder + quality analyzer
    │
    ▼
Viewport detector
    │
    ▼
Screen-type / UI-profile candidate generator
    │
    ▼
Multi-Pass Visual Geometry Solver
    │
    ├── global transform
    ├── ally panel transform
    ├── enemy panel transform
    ├── row lattice
    ├── column/slot lattice
    ├── local micro-registration
    └── hypothesis validation/retry
    │
    ▼
Native-resolution semantic crop extractor
    │
    ├── hero crops
    ├── item crops
    ├── OCR field crops
    └── metadata crops
    │
    ▼
Specialized recognizers
    │
    ├── HeroRecognizer
    │     ├── deterministic/template
    │     ├── prototype/embedding
    │     └── optional trained classifier
    │
    ├── ItemRecognizer
    │     ├── empty/occupied
    │     ├── deterministic/template
    │     ├── prototype/embedding
    │     └── optional trained classifier
    │
    └── OCRRecognizer
          ├── short integer
          ├── large integer
          ├── decimal/percentage
          ├── battle ID
          └── player name
    │
    ▼
Fusion + calibration + schema validation
    │
    ▼
Optional cross-screen consensus
    │
    ▼
Versioned JSON + debug evidence
```

---

## 10. Functional requirements

### 10.1 Input and image quality

**FR-001 — Supported inputs**

The engine shall accept:

- File path.
- Bytes.
- NumPy array.
- PIL image.
- API upload.
- A list of screenshots for one match.

**FR-002 — Original preservation**

The engine shall preserve the original image dimensions and pixel data throughout geometry analysis. Any preview or low-resolution pyramid must not replace the original.

**FR-003 — Viewport detection**

The engine shall identify the game-content viewport and remove or account for:

- Black bars.
- Device screenshot margins.
- Browser/window chrome.
- Social-media canvas padding.
- Cropping.
- Rotation metadata.

**FR-004 — Quality analysis**

The engine shall estimate:

- Blur.
- Compression artifacts.
- Effective icon resolution.
- Clipping.
- Aspect ratio.
- Suspected rescaling.
- Screenshot validity.

**FR-005 — Failure status**

If the screenshot lacks sufficient information, the engine shall return `low_quality`, `invalid_image`, or `unsupported_layout`; it shall not silently continue with unreliable coordinates.

---

### 10.2 Screen and profile recognition

**FR-010 — Automatic screen-type detection**

The engine shall classify the post-match screen automatically. The caller may optionally provide a hint, but the engine must verify it.

**FR-011 — Candidate profiles**

The engine shall select multiple plausible UI reference profiles based on viewport aspect ratio, header/tab evidence, stable UI elements, and game patch metadata when available.

**FR-012 — Two bootstrap calibrations**

The initial system shall contain two manually verified reference calibrations from different device/layout sizes. These calibrations seed the canonical profiles and testing corpus. Runtime extraction must not choose fields only by matching the image’s resolution to one of those devices.

**FR-013 — Unsupported profile**

A screenshot that does not structurally match any known profile shall return `unsupported_layout` and save a review artifact when debug mode is enabled.

---

### 10.3 Multi-Pass Visual Geometry Solver

**FR-020 — Geometry hypotheses**

The solver shall generate and score multiple geometry hypotheses rather than committing to the first anchor match.

**FR-021 — Independent panels**

The ally and enemy sides shall be solved independently after global alignment. The enemy side must not be generated only by mirroring ally coordinates.

**FR-022 — Global registration**

The solver shall support, in order:

1. Translation/scale.
2. Similarity transform.
3. Partial affine.
4. Full affine when justified.
5. Homography only for perspective-distorted images or when benchmarked as beneficial.

**FR-023 — Robust estimation**

Anchor correspondences shall use robust estimation such as RANSAC and reject inconsistent points.

**FR-024 — Intensity refinement**

After coarse alignment, the solver may refine the transform using masked intensity-based alignment. Dynamic regions—names, numbers, heroes, items, ratings, and badges—must be masked out of the optimization.

**FR-025 — Row lattice**

The solver shall fit the five-row structure using several signals:

- Horizontal separators.
- Repeating row heights.
- Hero slot centers.
- Text baselines.
- Item-slot groups.
- Expected monotonic order.

**FR-026 — Column and slot lattice**

The solver shall detect or refine:

- Hero portrait column.
- Player name/KDA line.
- Six item slots.
- Rating.
- Screen-specific numeric columns.
- Battle ID and metadata regions.

**FR-027 — Local correction**

Each panel, row, and field group may receive a local offset/scale correction within bounded limits. Local corrections must be constrained so they cannot drift into adjacent fields.

**FR-028 — Correction loop**

The geometry loop shall:

1. Create a hypothesis.
2. Extract provisional crops.
3. Score structural evidence.
4. Score crop quality.
5. Optionally use recognizer confidence as a secondary signal.
6. Reject impossible geometry.
7. Retry with an alternative profile, transform family, anchor subset, or local correction.
8. Invoke a learned layout fallback only after classical hypotheses fail.
9. Return `unsupported_layout` when all paths fail.

**FR-029 — Geometry evidence**

The result shall include:

- Viewport.
- Chosen profile.
- Global transform.
- Panel transforms.
- Row and field rectangles.
- Alignment confidence.
- Hypotheses attempted.
- Failure reason when not accepted.

---

### 10.4 Native-resolution crop extraction

**FR-030 — No destructive global normalization**

The original screenshot shall not be resized to a fixed reference resolution before final crops are extracted.

**FR-031 — Coordinate mapping**

Canonical regions shall be mapped back to the original viewport so crops use the original pixels.

**FR-032 — Original crop retention**

Each recognizer shall receive or be able to access:

- Original native crop.
- A padded context crop.
- Standardized model input generated from the native crop.
- Crop metadata including source dimensions and transform.

**FR-033 — Honest resizing**

Resizing to a network input size is allowed, but code and documentation must describe it as input standardization, not detail recovery.

**FR-034 — Multi-view crops**

Hero and item recognition may use:

- Tight icon crop.
- Slightly larger context crop.
- Masked center crop.
- Border-aware crop.

The model or fusion layer shall determine whether these views improve accuracy.

**FR-035 — Optional super-resolution experiment**

A super-resolution branch may be benchmarked only as an optional derived signal. The original crop remains authoritative, and the branch shall be disabled if it does not improve held-out exact accuracy.

---

### 10.5 Catalog management

**FR-040 — One authoritative manifest**

V2 shall generate a versioned `catalog.json` containing heroes, items, visual variants, aliases, active patch ranges, source information, and asset checksums.

**FR-041 — Stable IDs**

Every hero and item shall have a stable machine ID independent of filename and display name.

Examples:

```text
hero_0001
item_0042
```

**FR-042 — Source adapters**

The catalog synchronizer shall support source adapters in priority order:

1. Approved official/first-party MLBB source where available.
2. Approved official website assets.
3. Manually verified fallback source.
4. Existing local assets as a migration source.

No source-specific scraping logic may define production labels without validation.

**FR-043 — Secret handling**

API tokens, authorization headers, cookies, or credentials shall come from environment variables or a secret manager. They shall never be committed.

**FR-044 — Asset validation**

Each downloaded asset shall be checked for:

- Successful image decode.
- Expected MIME type.
- Minimum dimensions.
- Non-empty alpha/color content.
- Exact SHA-256.
- Duplicate exact hashes.
- Near-duplicate perceptual hashes.
- Unexpected aspect ratio.
- Suspicious HTML/error payloads saved as image files.

**FR-045 — Label normalization**

Names and aliases shall be normalized separately from stable IDs. Apostrophes, URL encoding, punctuation, and localized names must not affect identity.

**FR-046 — Visual history**

When an asset changes, the old asset shall remain stored as a separate visual version with patch bounds.

**FR-047 — Human promotion gate**

Added, deleted, renamed, or visually changed entries shall enter a review queue. A catalog snapshot becomes production-ready only after audit checks and required human approval pass.

**FR-048 — Catalog drift report**

`catalog sync` shall produce:

- Added classes.
- Removed classes.
- Renamed labels.
- Changed assets.
- Failed downloads.
- Exact duplicates.
- Near duplicates.
- Missing metadata.
- Model/catalog compatibility impact.

**FR-049 — Model compatibility**

Every model shall declare:

- Catalog version used during training.
- Supported class IDs.
- Preprocessing version.
- Input size.
- Visual versions observed.

When the runtime catalog contains a new class outside the classifier, prototype/template paths may still evaluate it. The engine shall expose this mismatch instead of silently remapping indices.

---

### 10.6 Hero recognition

**FR-050 — Pluggable recognizer**

`HeroRecognizer` shall expose one common interface for deterministic matching, prototype matching, trained classification, or an ensemble.

**FR-051 — Baseline signals**

The CPU-first baseline shall benchmark:

- Masked template matching.
- Gradient/edge similarity.
- Perceptual hash.
- Screenshot-derived visual prototypes.
- Optional frozen visual embedding model after license review.

V1’s numerous handcrafted metrics shall not automatically be carried over. Each retained signal must demonstrate incremental value.

**FR-052 — Trained classifier**

The preferred trained path shall use a crop classifier rather than a full-screen per-hero detector. Candidate backbones include ConvNeXt-Tiny, EfficientNetV2-S, MobileNetV3, or a current permissively licensed alternative.

**FR-053 — Embedding head**

The trained hero model should support an embedding/prototype head so:

- Visually similar classes can be analyzed.
- Unknown distance can be measured.
- New visual versions can be introduced before a complete retrain.

**FR-054 — Visual variants**

A hero may have multiple recognized visual variants if MLBB post-match portraits vary by skin, UI patch, event, or display mode. The output hero ID remains stable.

**FR-055 — Unknown handling**

The recognizer shall reject the candidate when:

- Source crop quality is too low.
- Top-1 score is below its calibrated threshold.
- Top-1/top-2 margin is too small.
- Prototype distance is outside the known-class distribution.
- Geometry confidence is too low.
- The catalog/model versions are incompatible.

**FR-056 — Candidate evidence**

Debug output shall include top candidates and individual signal scores.

---

### 10.7 Item recognition

**FR-060 — Separate item recognizer**

Hero and item recognition shall use separate models, catalogs, thresholds, and evaluation.

**FR-061 — Empty/occupied stage**

Item processing shall first classify the slot as:

- `empty`
- `occupied`
- `invalid_crop`
- `unknown`

Only occupied slots proceed to item identity recognition.

**FR-062 — Hard negatives**

The item dataset shall include:

- Empty slots.
- Slot borders.
- Battle spells.
- Emblems.
- Medals.
- Hero portraits.
- Adjacent text.
- Shifted crops.
- Unknown/new items.
- Low-quality crops.

**FR-063 — Small-icon training**

Training shall model native small-icon conditions. It shall include realistic downsampling, interpolation, compression, blur, brightness, UI border, and crop-offset variations.

**FR-064 — Item visual versions**

Old and changed item icons shall remain available for historical screenshot extraction.

**FR-065 — Optional build/context prior**

Game-mode or build metadata may be used only as a weak reranking signal after visual recognition. It shall not override strong contradictory visual evidence.

---

### 10.8 OCR

**FR-070 — Recognition-only by default**

Because geometry provides text regions, OCR shall run recognition on exact field crops rather than using full-screen text detection for most fields.

**FR-071 — Field-specific recognizers**

At minimum, the OCR layer shall support:

- Short integer: KDA, level, short counters.
- Large integer: damage, gold, healing, shields.
- Decimal: rating and decimal percentages.
- Percentage.
- Duration.
- Battle ID.
- Player name.

**FR-072 — Baselines**

The benchmark shall compare V1 Tesseract against current PaddleOCR recognition models and at least one independent alternative where practical.

As of this PRD date, PaddleOCR provides PP-OCRv6 recognition models in tiny, small, and medium tiers and documents custom recognition training. The implementation must still benchmark the actual MLBB dataset instead of assuming general benchmark superiority.

**FR-073 — Restricted alphabets**

Numeric recognizers shall use the smallest valid character set for each field.

**FR-074 — Original and processed evidence**

Every OCR result shall preserve:

- Native crop reference.
- Raw recognized text.
- Parsed value.
- Character-level or sequence confidence when available.
- Validation status.
- Model/preprocessing version.

**FR-075 — Zero versus failure**

The result schema shall distinguish:

```text
value = 0, status = ok
value = null, status = unknown
value = null, status = invalid_crop
value = null, status = low_quality
value = null, status = validation_failed
```

**FR-076 — Battle ID**

Battle ID shall:

- Remain a string.
- Preserve leading zeros.
- Use digit-only recognition.
- Support character-level consensus across preprocessing variants and multiple match screenshots.
- Validate length/grammar against verified observed data.
- Never truncate or pad merely to satisfy a hardcoded expected length.

**FR-077 — OCR retries**

The engine shall run the fastest primary OCR path first. Additional preprocessing/model candidates shall run only when confidence or validation fails.

**FR-078 — No “choose largest” default**

Candidate selection shall use calibrated likelihood, consensus, grammar, and field validation. Choosing the numerically largest candidate shall not be a generic rule.

---

### 10.9 Fusion, validation, and confidence

**FR-080 — Score separation**

The engine shall keep separate:

- Raw classifier probability.
- Embedding similarity.
- Template similarity.
- OCR sequence confidence.
- Candidate margin.
- Geometry confidence.
- Crop-quality score.
- Final calibrated correctness probability.

**FR-081 — Calibration**

Final accepted confidence shall be calibrated on held-out validation data using a documented method such as temperature scaling, isotonic regression, logistic regression, or a small fusion model.

**FR-082 — Field validation**

Validation shall include field-specific grammar and plausible ranges. It may rerank candidates but must not invent absent characters.

**FR-083 — Cross-field checks**

Where verified by MLBB rules and supported modes, use soft checks such as:

- Exactly five rows per team.
- Six item slots per player.
- Monotonic row order.
- Screen-specific field presence.
- Repeated battle ID consistency.
- Repeated hero/player consistency across match screens.

Do not apply hard rules that are invalid in special game modes.

**FR-084 — Abstention**

The system shall allow a field-level and screenshot-level abstention.

**FR-085 — Selective accuracy reporting**

Benchmarks shall report accuracy versus coverage at multiple confidence thresholds.

---

### 10.10 Multi-screen match consensus

**FR-090 — Match bundle input**

The API shall accept multiple screenshots believed to belong to the same match.

**FR-091 — Match grouping**

The system shall group or validate screenshots using battle ID and other visual metadata.

**FR-092 — Shared evidence**

Repeated fields may be fused:

- Battle ID characters.
- Hero identities.
- Player row order.
- Repeated player names.
- Shared match metadata.

**FR-093 — Conflict handling**

Conflicting high-confidence values shall be returned as a conflict requiring review, not arbitrarily overwritten.

---

### 10.11 JSON output

**FR-100 — Schema versioning**

Every response shall include a schema version.

**FR-101 — Provenance**

Every response shall include:

- Engine version.
- Catalog version.
- UI profile.
- Model versions.
- Preprocessing version.
- Source resolution.
- Viewport.
- Processing time.

**FR-102 — Field object**

Each extracted field shall support:

```json
{
  "raw": "12",
  "value": 12,
  "status": "ok",
  "confidence": 0.998,
  "source_box": [100, 200, 140, 230],
  "candidates": []
}
```

Candidate lists and source boxes may be omitted outside debug mode.

**FR-103 — Deterministic serialization**

The same model/catalog/config versions and same image must produce semantically identical JSON.

---

### 10.12 Debugging and review

**FR-110 — Debug bundle**

Debug mode shall optionally produce:

- Original image.
- Viewport overlay.
- Anchor matches.
- Transform overlay.
- Row/column rectangles.
- Individual crops.
- Recognition candidates.
- OCR raw outputs.
- Geometry hypotheses and rejection reasons.
- Final JSON.

**FR-111 — No file clutter by default**

Normal programmatic inference shall return data without writing files unless explicitly requested.

**FR-112 — Review UI**

Provide a lightweight local review application that can:

- Display screenshot and overlays.
- Correct screen type/profile.
- Correct row/panel geometry.
- Correct hero and item labels.
- Correct OCR values.
- Mark unknown/unsupported.
- Save immutable annotation records.
- Prioritize low-confidence and disagreement cases.

The UI may be implemented with a lightweight framework, but its saved format must remain engine-independent.

---

### 10.13 Benchmarking and regression

**FR-120 — V1 baseline**

Before changing recognition behavior, create a benchmark runner that evaluates V1 on the same dataset.

**FR-121 — Versioned ground truth**

The benchmark dataset and annotations shall have immutable version IDs and checksums.

**FR-122 — Module metrics**

Report:

- Geometry success and normalized coordinate error.
- Hero top-1/top-3 and per-class recall.
- Item top-1, occupied/empty accuracy, and per-class recall.
- Unknown false-accept and false-reject rates.
- OCR exact sequence accuracy and character error rate.
- Numeric exact value accuracy.
- Confidence calibration.
- Full-JSON exact match.
- Critical-field exact match.
- Latency and memory.

**FR-123 — Slice metrics**

Report metrics by:

- Screen type.
- Device/source.
- Resolution.
- Aspect ratio.
- UI profile.
- Game patch.
- Compression level.
- Blur.
- Class frequency.
- Native icon dimensions.

**FR-124 — Temporal holdout**

A new-patch or later-captured split shall be kept separate to measure drift.

**FR-125 — Release gate**

V2 may replace V1 only when it meets documented thresholds on the held-out release benchmark and has no unacceptable regression slices.

---

### 10.14 Training and model experiments

**FR-130 — CPU-first baseline**

The first functional V2 release shall not require newly trained YOLO weights.

**FR-131 — Training packages**

Training code shall be optional dependencies, separate from the minimal inference install.

**FR-132 — Reproducibility**

Each training run shall record:

- Git commit.
- Dataset version.
- Catalog version.
- Random seed.
- Model configuration.
- Augmentation configuration.
- Training environment.
- Metrics.
- Checkpoint hashes.

**FR-133 — RunPod-ready**

Provide containerized or scripted GPU training that can run on a rented CUDA machine. Training shall support resume, early stopping, mixed precision, checkpoint export, and automatic benchmark execution.

**FR-134 — Experiment gate**

No paid detector experiment shall begin until:

- The ground-truth dataset exists.
- Geometry-only improvements have been measured.
- The crop-classification baseline has been measured.
- Expected benefit and experiment budget are documented.
- Licensing has been reviewed.

---

### 10.15 Optional YOLO and learned-layout path

**FR-140 — Optional provider**

YOLO shall be behind a provider interface and must not be required for core CPU inference.

**FR-141 — Escalation order**

If deterministic geometry and standard crop classifiers are insufficient, test in this order:

1. Generic UI keypoint/box detector for layout.
2. Separate YOLO-style classification model for hero crops.
3. Separate YOLO-style classification model for item crops.
4. Detector on high-resolution row or panel crops.
5. Full-screen per-hero/per-item detector only as the final experiment.

**FR-142 — Separate hero/item models**

Any YOLO classification experiment shall use separate hero and item models.

**FR-143 — Layout classes**

A learned layout detector should predict generic structure, for example:

```text
result_panel
ally_panel
enemy_panel
player_row
hero_slot
item_strip
battle_id_region
tab_header
```

It should not need one detection class per hero or item to solve geometry.

**FR-144 — High-resolution policy**

If detector experiments are run, they shall preserve small-object information through panel crops, tiling, or appropriate input resolution. A 640-pixel full-screen resize must not be accepted without evidence that tiny item detail remains sufficient.

**FR-145 — License gate**

Ultralytics currently publishes AGPL-3.0 and Enterprise licensing paths. The project must review the intended commercial/open-source use before integrating Ultralytics code or trained weights. A permissively licensed detector path such as PaddleDetection/RT-DETR should remain available for comparison.

**FR-146 — Benchmark equality**

YOLO experiments shall use the same held-out splits and exact-output metrics as non-YOLO methods.

---

## 11. Detailed automatic geometry design

### 11.1 Why two calibrations are not enough by themselves

The two initial device calibrations provide:

- Verified semantic regions.
- Stable anchor candidates.
- Expected row and column relationships.
- Examples of two different scale/layout conditions.

They are not runtime coordinate tables. Production inference must infer transforms from visible structure. If the same UI is rendered at an unseen resolution, the solver should map it automatically.

### 11.2 Multi-Pass Visual Geometry Solver

#### Pass 0 — Decode and orientation

- Decode without unintended color or size conversion.
- Apply EXIF orientation.
- Reject corrupt images.
- Record original width/height.

#### Pass 1 — Viewport hypotheses

Generate possible game-content rectangles using:

- Uniform border detection.
- Black-bar detection.
- Edge density.
- MLBB panel-color signatures.
- Known header/footer structural templates.
- Aspect-ratio constraints.

Retain multiple viewport candidates when scores are close.

#### Pass 2 — Screen/profile hypotheses

For each viewport:

- Estimate screen type from active tab/header.
- Compare stable structural regions with every compatible reference profile.
- Generate top profile candidates.

#### Pass 3 — Coarse anchor constellation

Use multiple stable anchor families rather than one point:

- Panel corners.
- Header separators.
- Team-color markers.
- Tab underline or selected state.
- Table outer edges.
- Battle-ID label region.
- Repeating decorative elements.

Each anchor should have:

- Search area.
- Template/version.
- Optional mask.
- Expected semantic location.
- Minimum score.
- Ambiguity score.

#### Pass 4 — Robust global transform

- Convert anchor matches to point correspondences.
- Estimate translation/similarity/partial affine with RANSAC.
- Reject high-reprojection-error anchors.
- Score transform plausibility.
- Avoid homography unless required.

#### Pass 5 — Masked intensity refinement

- Warp a stable reference mask.
- Exclude dynamic content.
- Refine using ECC or equivalent area-based registration.
- Abort safely if refinement does not converge or decreases structural score.

#### Pass 6 — Independent panel registration

For ally and enemy panels independently:

- Search panel-specific edges and separators.
- Fit local affine or constrained translation/scale.
- Enforce plausible panel shape and vertical alignment.
- Do not mirror one panel to create the other.

This directly addresses previous mirror-based failure.

#### Pass 7 — Row lattice fitting

Build candidate row centers from:

- Repeating hero-circle responses.
- Horizontal separators.
- Text baseline density.
- Item-strip repetition.

Fit a five-row lattice with robust regression or dynamic programming. Penalize:

- Unequal spacing beyond tolerance.
- Overlapping rows.
- Rows outside the panel.
- Non-monotonic order.

#### Pass 8 — Column and slot refinement

Within each panel:

- Detect six repeated item slots as a one-dimensional lattice.
- Refine hero portrait and text line positions.
- Use edge/color/template responses around expected locations.
- Estimate bounded local offsets.

#### Pass 9 — Recognition-aware micro-registration

For difficult small crops, evaluate a small bounded set of offsets/scales. The objective may combine:

- Slot-border alignment.
- Circular-mask alignment.
- Text-foreground separation.
- Crop sharpness.
- Recognizer top-1 margin.

Recognizer confidence is secondary; geometry cannot move freely merely to make a model confident.

#### Pass 10 — Structural validation

Reject a hypothesis if:

- Rows or slots overlap.
- The wrong number of repeated structures exists.
- Field boxes leave the viewport.
- Ally/enemy panels are implausibly shaped.
- Too many provisional crops are invalid.
- Geometry confidence is below threshold.

#### Pass 11 — Retry strategy

Try, in order:

- Next viewport.
- Next profile.
- Alternative anchor subset.
- Alternative transform family.
- Alternative local panel fit.
- Learned layout fallback.

#### Pass 12 — Final abstention

Return `unsupported_layout` with debug evidence when no candidate passes.

### 11.3 Geometry confidence

The final geometry confidence should be calibrated from features such as:

- Anchor match scores.
- Anchor score margins.
- RANSAC inlier ratio.
- Reprojection error.
- ECC score improvement.
- Panel-edge agreement.
- Row-spacing residual.
- Slot-lattice residual.
- Crop validity ratio.
- Profile ambiguity.

A hand-selected weighted sum may be used temporarily for instrumentation, but production acceptance thresholds must be fit against labeled valid/invalid geometry examples.

### 11.4 “Any screen size” acceptance definition

V2 must automatically support any pixel resolution and scaling factor that renders one of the supported UI structures without clipping required information.

If aspect ratio causes MLBB to use a materially different structure, that structure becomes a new UI profile. The engine must detect this rather than force an existing profile.

---

## 12. Native-resolution recognition design

### 12.1 Required crop flow

```text
Original screenshot
→ viewport transform
→ semantic box in canonical coordinates
→ inverse-map box/polygon to original pixels
→ native crop
→ optional context crop
→ model-specific resize/padding
```

### 12.2 Training treatment

The training dataset must include the observed distribution of native crop dimensions. For every sample, retain metadata such as:

```json
{
  "source_width": 38,
  "source_height": 38,
  "screenshot_width": 2400,
  "screenshot_height": 1080,
  "interpolation_history": "unknown",
  "compression": "jpeg_estimated",
  "crop_offset": [1, -2]
}
```

### 12.3 Realistic augmentation

Allowed examples:

- Downsample then resize back.
- INTER_AREA, bilinear, bicubic, and game-like interpolation mixtures.
- Mild JPEG/WebP compression.
- Mild blur.
- Small gamma/contrast/saturation changes.
- One-to-three-pixel crop shifts.
- Small border contamination.
- Correct UI mask and badge overlays.
- Different visual versions.

Disallowed by default:

- Horizontal flips.
- 90-degree rotations.
- Extreme hue changes.
- Large perspective warps.
- Arbitrary object cutout that never appears in the UI.

### 12.4 Quality-based abstention

The system shall determine whether a crop contains enough effective detail. If not, it shall:

- Attempt context/prototype/template alternatives.
- Use evidence from another match screenshot when available.
- Otherwise return `low_quality` or `unknown`.

---

## 13. Catalog design

### 13.1 Manifest example

```json
{
  "catalog_version": "mlbb-2026.07.1",
  "generated_at": "2026-07-31T00:00:00Z",
  "heroes": [
    {
      "id": "hero_0073",
      "canonical_name": "Fanny",
      "aliases": {
        "en": ["Fanny"]
      },
      "active_from_patch": null,
      "active_until_patch": null,
      "visual_versions": [
        {
          "id": "hero_0073_visual_2026_07",
          "asset_path": "assets/heroes/hero_0073/2026.07.png",
          "sha256": "...",
          "phash": "...",
          "source_adapter": "official_mlbb",
          "source_reference": "...",
          "review_status": "approved"
        }
      ]
    }
  ]
}
```

### 13.2 Synchronization workflow

```text
fetch source metadata
→ normalize records
→ match to existing stable IDs
→ download candidate assets
→ validate bytes and image properties
→ detect exact/near duplicates
→ compare with previous snapshot
→ produce review queue
→ human approve/reject/map
→ generate immutable catalog snapshot
→ generate model class maps
→ run catalog tests
→ promote snapshot
```

### 13.3 Labeling rules

- A display-name change does not create a new stable ID.
- A visually changed asset creates a new visual version.
- Two names with identical assets require review.
- Two assets mapped to one class are valid only when they are approved variants.
- Placeholder records are forbidden in production snapshots.
- Scraper success does not equal label correctness.
- New classes are `unreviewed` until approved.
- Removed classes remain available for historical extraction when legally and technically appropriate.

### 13.4 Catalog CLI

```bash
nexus catalog sync --source official
nexus catalog audit
nexus catalog diff mlbb-2026.06.1 mlbb-2026.07.1
nexus catalog review --open
nexus catalog promote mlbb-2026.07.1
nexus catalog export-classmap --task heroes
nexus catalog export-classmap --task items
```

---

## 14. Hero and item model strategy

### 14.1 Stage A — No-new-training baseline

- Correct geometry.
- Correct fresh catalog.
- Masked template bank.
- Screenshot-derived prototypes.
- Optional frozen embeddings.
- PP-OCRv6/Tesseract OCR benchmark.
- Calibrated acceptance using validation data.

This stage must exist before GPU spending.

### 14.2 Stage B — Low-cost crop classification

Train separate hero and item classifiers.

Recommended experiment matrix:

| Task | Candidate 1 | Candidate 2 | Candidate 3 |
|---|---|---|---|
| Heroes | ConvNeXt-Tiny | EfficientNetV2-S | MobileNetV3 |
| Items | ConvNeXt-Tiny | EfficientNetV2-S | MobileNetV3 |
| Optional YOLO classify | YOLO26n-cls or current equivalent | YOLO26s-cls | only after license gate |

Use transfer learning, class-balanced sampling, hard-negative mining, and real/synthetic mixtures.

### 14.3 Dual-head output

Preferred model output:

```text
classification logits
normalized embedding
```

Possible loss:

```text
cross entropy
+ supervised contrastive or metric loss
```

The exact loss is chosen by validation.

### 14.4 Fusion

A candidate fusion feature vector may include:

```text
classifier top-1 probability
classifier margin
prototype similarity
prototype margin
template similarity
template margin
crop quality
geometry confidence
native crop size
class identity
visual-version compatibility
```

Train a simple correctness model on validation predictions. Do not fuse on the test set.

---

## 15. OCR strategy

### 15.1 Initial experiment matrix

| Field group | Baseline | Candidate | Fine-tuned candidate |
|---|---|---|---|
| KDA/level | V1 Tesseract | PP-OCRv6 tiny/small recognition | MLBB numeric model |
| Damage/gold | V1 Tesseract | PP-OCRv6 small/medium recognition | MLBB large-integer model |
| Rating/% | V1 Tesseract | PP-OCRv6 recognition | MLBB decimal model |
| Battle ID | V1 Tesseract | PP-OCRv6 digit-only recognition | Dedicated sequence model |
| Player names | V1 Tesseract | PP-OCRv6 medium/multilingual | Fine-tuned if dataset permits |

### 15.2 Synthetic OCR data

Generate with:

- Closest verified MLBB font.
- Correct outline and shadow.
- Real field backgrounds.
- Real color and anti-aliasing.
- Field-specific value distributions.
- Compression and resampling.
- Random but bounded crop offsets.

If the exact font cannot be acquired legally, derive a glyph atlas from consented/approved screenshots or use multiple close fonts and rely on real-data fine-tuning.

### 15.3 Character-level battle ID consensus

For multiple variants or multiple screenshots:

1. Obtain sequence candidates and per-character confidence.
2. Align candidate strings.
3. Vote at character positions.
4. Reject unresolved positions.
5. Validate observed grammar.
6. Preserve candidate provenance.

---

## 16. Data requirements

### 16.1 Catalog assets

- At least one clean canonical image per visual version.
- Correct stable ID.
- Human-approved label.
- Patch/version metadata.
- Checksum.

One clean image is enough for a template/prototype entry, but not enough by itself to prove a high-accuracy trained recognizer.

### 16.2 Real hero crops

Planning targets:

- Pilot: 15–25 real crops per hero.
- Strong production target: 50–100 per hero.
- Hard/confusable or visually changed classes: 100–200.
- Include multiple devices, scales, rows, teams, compression states, and overlays.

### 16.3 Real item crops

- Pilot: 20–30 occupied crops per item.
- Strong production target: 50–100.
- Hard/confusable item families: 100–200.
- Thousands of empty and hard-negative slots.

### 16.4 Layout screenshots

- Initial two bootstrap calibrations.
- Pilot benchmark: 300–500 screenshots across all five screens.
- Strong production geometry set: 1,500–3,000 screenshots across resolutions, profiles, patches, and compression.
- If training a layout detector: begin with 300–1,000 carefully labeled screenshots and use learning curves before collecting more.

### 16.5 OCR crops

- Initial real numeric crops: at least 10,000.
- Strong target: 50,000–100,000.
- Synthetic numeric crops: 100,000 to 1,000,000 depending on observed learning curves.
- Player-name crops: use consented or appropriately protected data; synthetic names should cover expected character sets.

### 16.6 Unknown/negative set

Include:

- New classes absent from the training class map.
- Old visual versions.
- Non-MLBB images.
- Wrong tab.
- Cropped panel.
- Severe blur/compression.
- Incorrectly shifted crops.
- Battle spells/emblems in item recognizer.
- Empty slots.
- UI redesign samples.

---

## 17. Annotation and dataset format

### 17.1 Full-screenshot annotation

Use one match-level source of truth rather than manually maintaining disconnected crop labels.

```json
{
  "annotation_version": "1.0",
  "screenshot_id": "shot_000184",
  "match_group_id": "match_000037",
  "screen_type": "screen1",
  "ui_profile": "postmatch-2026.07-standard",
  "patch": "2026.07",
  "language": "en",
  "source_resolution": [2400, 1080],
  "viewport": [120, 0, 2280, 1080],
  "geometry": {
    "ally_panel": [0, 0, 0, 0],
    "enemy_panel": [0, 0, 0, 0],
    "rows": []
  },
  "battle_id": "436609948828842102",
  "players": []
}
```

### 17.2 Derived crops

A deterministic export tool shall generate hero, item, and OCR crops from approved full-screenshot annotations. Every crop retains a link to:

- Screenshot ID.
- Match group.
- Field.
- Team/row/slot.
- Geometry version.
- Catalog ID.
- Native source dimensions.

### 17.3 Annotation tooling

CVAT can be used for boxes/keypoints and supports standard exports such as COCO, YOLO, and Datumaro. A N.E.X.U.S review UI is still required for structured field values and rapid correction of model predictions.

### 17.4 Dataset versioning

Use a reproducible data-version mechanism such as DVC or an equivalent manifest/object-store workflow. Git shall store manifests and code, not large private raw datasets.

### 17.5 Split rules

Split by `match_group_id`, not by crop.

Also prevent leakage across:

- Re-encoded copies of one screenshot.
- Same recording session.
- Same device capture burst.
- Same synthetic source.
- Same exact asset-derived synthetic family.

Required splits:

```text
train
validation
normal held-out test
compressed/low-resolution test
new-device test
temporal/new-patch test
unknown-class test
```

---

## 18. Evaluation plan

### 18.1 Geometry metrics

- Viewport IoU.
- Panel IoU.
- Row center normalized error.
- Field box normalized edge error.
- Valid-crop rate.
- Silent-miscrop rate.
- Unsupported-layout detection accuracy.

### 18.2 Recognition metrics

- Hero top-1/top-3.
- Item top-1/top-3.
- Per-class precision/recall.
- Macro and frequency-weighted metrics.
- Empty/occupied confusion.
- Open-set false-accept rate.
- Unknown detection AUROC/AUPR where appropriate.

### 18.3 OCR metrics

- Exact sequence accuracy.
- Character error rate.
- Exact numeric value accuracy.
- Battle ID exact accuracy.
- Decimal-point error rate.
- Zero/missing confusion.

### 18.4 End-to-end metrics

- Exact full JSON.
- Exact critical fields.
- Average incorrect fields per screenshot.
- Screens with any silent error.
- Screens requiring review.
- Accuracy at 100%, 99%, 98%, 95% coverage.

### 18.5 Ablation studies

Run:

```text
V1
V1 + new geometry
new geometry + deterministic catalog matcher
+ prototype embeddings
+ trained crop classifier
+ calibrated fusion
+ new OCR
+ multi-screen consensus
+ learned layout fallback
+ optional YOLO variants
```

---

## 19. API and CLI requirements

### 19.1 Python API

```python
from nexus_v2 import NexusEngine

engine = NexusEngine.load("configs/production.yaml")

result = engine.extract_screenshot(
    image="match.png",
    screen_type="auto",
    debug=False,
)

match = engine.extract_match(
    images=["screen1.png", "screen2.png", "screen5.png"],
    debug=False,
)
```

### 19.2 CLI

```bash
nexus extract match.png --screen auto --json
nexus extract-match ./match_screens --json
nexus debug-overlay match.png --output ./debug
nexus benchmark --dataset data/benchmarks/release-v1
nexus compare-v1-v2 --dataset data/benchmarks/release-v1
nexus catalog sync
nexus catalog audit
nexus review
nexus train heroes --config training/heroes.yaml
nexus train items --config training/items.yaml
nexus train layout --backend rtdetr
nexus train layout --backend yolo
```

### 19.3 Service API

Optional FastAPI service:

```text
POST /v2/extract
POST /v2/extract-match
GET  /v2/health
GET  /v2/models
GET  /v2/catalog
```

Uploads must have configurable size limits and should be processed without permanent storage by default.

---

## 20. Proposed result schema

```json
{
  "schema_version": "2.0",
  "engine_version": "2.0.0",
  "catalog_version": "mlbb-2026.07.1",
  "ui_profile": "postmatch-2026.07-standard",
  "screen_type": "screen1",
  "status": "ok",

  "source": {
    "original_resolution": {
      "width": 2400,
      "height": 1080
    },
    "viewport": [120, 0, 2280, 1080],
    "quality": {
      "status": "ok",
      "blur_score": 0.91,
      "compression_score": 0.84
    },
    "geometry": {
      "confidence": 0.997,
      "profile": "postmatch-2026.07-standard",
      "fallback_used": false
    }
  },

  "metadata": {
    "battle_id": {
      "raw": "436609948828842102",
      "value": "436609948828842102",
      "status": "ok",
      "confidence": 0.999
    }
  },

  "teams": [
    {
      "side": "ally",
      "players": [
        {
          "row": 0,
          "hero": {
            "id": "hero_0073",
            "name": "Fanny",
            "status": "ok",
            "confidence": 0.996
          },
          "items": [
            {
              "slot": 0,
              "id": "item_0017",
              "name": "Blade of Despair",
              "status": "ok",
              "confidence": 0.992
            }
          ],
          "stats": {
            "kills": {
              "raw": "12",
              "value": 12,
              "status": "ok",
              "confidence": 0.999
            }
          }
        }
      ]
    }
  ],

  "models": {
    "geometry": "geometry-classical-0.4.0",
    "hero": "hero-hybrid-0.3.0",
    "item": "item-hybrid-0.3.0",
    "ocr_numeric": "ppocrv6-mlbb-numeric-0.1.0"
  },

  "warnings": []
}
```

---

## 21. Non-functional requirements

### 21.1 Accuracy

Accuracy and abstention quality take priority over maximum coverage and raw speed.

### 21.2 CPU deployment

The production baseline must run on CPU. ONNX Runtime or another tested portable runtime should be supported for exported neural models.

### 21.3 Reproducibility

Dependencies shall be pinned through a lockfile. Model and catalog assets shall have checksums.

### 21.4 Maintainability

- No giant orchestration file containing all OCR and recognition logic.
- Typed interfaces.
- Pydantic/dataclass schemas.
- Clear module boundaries.
- Configuration validated at startup.
- No global singleton that can retain the wrong screen configuration.

### 21.5 Security

- No embedded credentials.
- Validate untrusted images and model files.
- Resource limits for uploads.
- Dependency and license inventory.
- Debug data disabled by default in production.

### 21.6 Privacy

Player names and battle IDs may be linkable identifiers. Private screenshots and annotations shall be access-controlled. Public datasets should pseudonymize or omit names unless consent and a lawful basis exist.

### 21.7 Offline inference

After models and catalog snapshots are installed, inference shall not require an external API.

### 21.8 Licensing and asset rights

- Record dependency licenses.
- Review Ultralytics licensing before optional integration.
- Prefer permissive alternatives where they meet accuracy goals.
- Record asset provenance.
- Do not imply ownership of MLBB artwork.
- Respect source terms and applicable rights.

---

## 22. Proposed repository structure

```text
N.E.X.U.S-ML/
├── legacy_v1/                         # optional snapshot or untouched existing code
├── nexus_v2/
│   ├── __init__.py
│   ├── engine.py
│   ├── settings.py
│   │
│   ├── schemas/
│   │   ├── input.py
│   │   ├── result.py
│   │   ├── annotation.py
│   │   └── catalog.py
│   │
│   ├── input/
│   │   ├── decoder.py
│   │   ├── viewport.py
│   │   └── quality.py
│   │
│   ├── layout/
│   │   ├── profiles.py
│   │   ├── screen_classifier.py
│   │   ├── anchors.py
│   │   ├── transforms.py
│   │   ├── panel_solver.py
│   │   ├── row_lattice.py
│   │   ├── slot_lattice.py
│   │   ├── micro_registration.py
│   │   ├── validator.py
│   │   └── learned_backend.py
│   │
│   ├── crops/
│   │   ├── extractor.py
│   │   ├── masks.py
│   │   ├── quality.py
│   │   └── debug.py
│   │
│   ├── catalog/
│   │   ├── registry.py
│   │   ├── sync.py
│   │   ├── audit.py
│   │   ├── diff.py
│   │   ├── review.py
│   │   └── sources/
│   │
│   ├── recognition/
│   │   ├── base.py
│   │   ├── hero.py
│   │   ├── item.py
│   │   ├── empty_slot.py
│   │   ├── templates.py
│   │   ├── prototypes.py
│   │   ├── classifier.py
│   │   └── calibrator.py
│   │
│   ├── ocr/
│   │   ├── base.py
│   │   ├── paddle_backend.py
│   │   ├── tesseract_backend.py
│   │   ├── numeric.py
│   │   ├── battle_id.py
│   │   ├── names.py
│   │   └── parsers.py
│   │
│   ├── fusion/
│   │   ├── fields.py
│   │   ├── constraints.py
│   │   └── match_consensus.py
│   │
│   ├── providers/
│   │   ├── onnx.py
│   │   ├── torch.py
│   │   ├── rtdetr.py
│   │   └── ultralytics.py
│   │
│   ├── api/
│   └── cli/
│
├── catalogs/
│   ├── snapshots/
│   ├── staging/
│   └── schemas/
│
├── profiles/
│   ├── reference_a/
│   └── reference_b/
│
├── training/
│   ├── datasets/
│   ├── augmentations/
│   ├── heroes/
│   ├── items/
│   ├── ocr/
│   ├── layout/
│   └── runpod/
│
├── review_app/
├── evaluation/
│   ├── metrics.py
│   ├── benchmark.py
│   ├── compare_v1_v2.py
│   ├── reports/
│   └── regression_cases/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   └── catalog/
│
├── docs/
│   ├── architecture.md
│   ├── catalog.md
│   ├── geometry.md
│   ├── data.md
│   ├── training.md
│   └── implementation_status.md
│
├── pyproject.toml
├── uv.lock or equivalent lockfile
├── Dockerfile.cpu
├── Dockerfile.gpu
└── README.md
```

---

## 23. Implementation phases and gates

### Phase 0 — Freeze V1 and establish truth

Deliverables:

- Tagged V1 baseline.
- Repository audit.
- Benchmark schema.
- Initial golden dataset.
- V1 benchmark report.
- No V1 behavior changes.

Gate:

- V1 can be reproduced from a clean environment.
- Every benchmark sample has approved ground truth.

### Phase 1 — Catalog rebuild

Deliverables:

- Stable catalog schema.
- Source adapters.
- Secure downloader.
- Asset validation.
- Diff/audit/review workflow.
- Fresh hero and item snapshot.
- Migration map from V1 filenames to stable IDs.

Gate:

- No placeholder records.
- Every active approved class has at least one valid asset.
- No unresolved duplicate/conflicting IDs.
- Class maps generated deterministically.

### Phase 2 — Automatic geometry

Deliverables:

- Two bootstrap profiles.
- Viewport detector.
- Screen classifier.
- Multi-pass solver.
- Independent panel transforms.
- Row/slot lattice.
- Debug overlays.
- Geometry benchmark.

Gate:

- Geometry target achieved or failure explicitly abstains.
- No reliance on exact input resolution.
- Left/right extraction works without simple mirroring.

### Phase 3 — Native crop and deterministic recognizers

Deliverables:

- Native crop extractor.
- Crop-quality model/heuristics.
- Simplified template bank.
- Prototype bank.
- Empty-slot baseline.
- Calibrated thresholds from validation data.

Gate:

- Better or equal hero/item accepted precision than V1.
- No forced-match regression.

### Phase 4 — OCR modernization

Deliverables:

- Recognition-only OCR interface.
- Tesseract baseline adapter.
- PP-OCRv6 adapter.
- Field parsers.
- Battle ID consensus.
- Real zero/failure distinction.
- OCR benchmark.

Gate:

- Exact-value improvement over V1 on critical fields.
- Battle ID does not truncate/pad to a guessed format.

### Phase 5 — Dataset and review system

Deliverables:

- Review UI.
- Full-screenshot annotations.
- Derived crop exporter.
- Dataset versioning.
- Active-learning queue.
- Privacy controls.

Gate:

- Training/validation/test leakage checks pass.
- Class distributions and missing classes are reported.

### Phase 6 — Trained crop classifiers

Deliverables:

- Separate hero and item training pipelines.
- RunPod scripts.
- Model export to ONNX where supported.
- Calibration and fusion.
- Class/unknown benchmarks.

Gate:

- Statistically meaningful improvement over deterministic/prototype baseline.
- CPU inference remains acceptable.
- New model is compatible with catalog snapshot.

### Phase 7 — Optional learned geometry / YOLO

Trigger only when Phase 2 or Phase 6 fails target slices.

Deliverables:

- Generic layout detector or keypoint model.
- Optional YOLO classification experiments.
- Optional panel/row detection experiments.
- Licensing decision record.
- Equal benchmark comparison.

Gate:

- Measurable improvement justifies cost, dependency, and license impact.

### Phase 8 — Multi-screen fusion and production hardening

Deliverables:

- `extract_match`.
- Cross-screen evidence fusion.
- API.
- Docker CPU/GPU images.
- Observability.
- Release benchmark.
- Migration documentation.

Gate:

- Full release acceptance criteria pass.

---

## 24. Test strategy

### Unit tests

- Coordinate transforms and inverse transforms.
- Viewport detection.
- Catalog ID normalization.
- Asset validation.
- Duplicate detection.
- Row and slot lattice fitting.
- OCR parsers.
- Confidence threshold logic.
- JSON schema.
- No global config leakage.

### Property tests

- Random resolutions map canonical boxes consistently.
- Transform/inverse-transform round trips.
- Stable IDs remain unchanged after label formatting changes.
- Zero and null remain distinct.
- Adding a catalog class does not reorder existing class IDs.

### Integration tests

- Each screen type.
- Both teams.
- Two bootstrap devices.
- Unseen resolutions generated from supported profiles.
- Letterboxed/cropped screenshots.
- Multi-screen match bundle.
- Unsupported layout.
- New item absent from classifier.
- Old visual version.

### Golden tests

Store expected JSON for approved examples. Use tolerant comparisons only for non-semantic floating-point evidence; field values and IDs must match exactly.

### Catalog tests

- All referenced files exist.
- All files decode.
- All hashes match.
- No production placeholder.
- No unresolved duplicate mapping.
- Model class maps reference valid IDs.

---

## 25. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Entire MLBB UI changes | Geometry fails | Profile detection, unsupported status, new-profile workflow |
| Tiny icons lose detail | Wrong item/hero | Native crops, context views, realistic training, abstention |
| Source catalog mislabeled | Model learns wrong class | Stable IDs, human promotion gate, duplicate audit |
| New hero/item not in classifier | Forced old class | Prototype/template fallback and open-set rejection |
| Mirrored side differs | Enemy crops shift | Independent panel solve |
| OCR decimal point disappears | Wrong rating | Dedicated decimal model, raw evidence, character validation |
| OCR failure becomes zero | Silent error | Separate status enum |
| YOLO license conflicts | Product/legal risk | Provider isolation, explicit license gate, RT-DETR comparison |
| GPU costs increase | Budget risk | CPU-first gate, small experiments, early stopping |
| Random crop split leaks data | Inflated metrics | Split by match/session/source |
| Personal identifiers in data | Privacy risk | Access controls, pseudonymization, synthetic names |
| Source endpoint changes | Catalog sync fails | Adapter architecture, cached snapshots, manual fallback |
| Confidence is overtrusted | Silent wrong data | Calibration, coverage reporting, unknown state |

---

## 26. Release acceptance criteria

V2 is release-ready when all of the following are true:

1. V1 remains runnable and benchmarked.
2. The fresh hero/item catalog passes audit and human promotion.
3. Two bootstrap calibrations exist, but unseen resolutions within supported profiles are parsed automatically.
4. Ally and enemy panels are independently registered.
5. Final crops use original screenshot pixels.
6. Every field can return an explicit failure/unknown status.
7. Hero/item recognition does not force unknown classes into known classes beyond the approved false-accept target.
8. Battle IDs remain strings and pass exact-match evaluation.
9. OCR zero/failure handling is correct.
10. Full-JSON exact accuracy, critical-field accuracy, and selective accuracy are reported.
11. Model and catalog versions are present in output.
12. CPU inference works from a clean install.
13. Debug overlays explain extraction decisions.
14. Tests, catalog audits, and benchmark commands pass in CI.
15. Any YOLO dependency has passed the license and benchmark gate.
16. No secrets are committed.
17. Documentation explains how to add a new UI profile, hero, item, OCR field, and recognizer backend.

---

## 27. Decision log

### Confirmed decisions

- Build V2 as a separate architecture while preserving V1.
- Use two device calibrations as bootstrap references only.
- Automatic geometry is a first-class subsystem.
- Do not rely on left/right mirroring alone.
- Preserve native-resolution crops.
- Rebuild and relabel hero/item assets.
- Use stable IDs and versioned catalog snapshots.
- Start without YOLO.
- Keep separate hero and item recognizers.
- Train YOLO classification/detection only as an optional final path when benchmark results justify it.
- Support rented-GPU training scripts but do not require a local GPU.
- Return structured JSON with explicit unknown/failure states.

### Defaults selected by this PRD

- Python implementation.
- OpenCV for classical geometry.
- Recognition-only OCR after geometry.
- PP-OCRv6 as a current benchmark candidate, not an assumed winner.
- PyTorch/torchvision classifiers as the first trained non-YOLO path.
- ONNX Runtime as a preferred portable CPU deployment target where exports are reliable.
- CVAT-compatible layout annotations plus a custom structured review UI.
- DVC or equivalent for private data versioning.
- RT-DETR/PaddleDetection as a permissive learned-layout comparison.
- Ultralytics integration isolated behind an optional extra.

---

## 28. Official technical references

- OpenCV template matching and masks: <https://docs.opencv.org/master/de/da9/tutorial_template_matching.html>
- OpenCV affine/homography estimation: <https://docs.opencv.org/master/d9/d0c/group__calib3d.html>
- OpenCV ECC alignment: <https://docs.opencv.org/master/dc/d6b/group__video__track.html>
- PaddleOCR documentation and PP-OCRv6: <https://www.paddleocr.ai/main/en/>
- PaddleOCR text-recognition module and custom training: <https://www.paddleocr.ai/main/en/version3.x/module_usage/text_recognition.html>
- Torchvision classification models: <https://docs.pytorch.org/vision/main/models.html>
- Ultralytics image classification: <https://docs.ultralytics.com/tasks/classify>
- Ultralytics object detection: <https://docs.ultralytics.com/tasks/detect>
- Ultralytics licensing: <https://www.ultralytics.com/license>
- PaddleDetection / RT-DETR: <https://github.com/PaddlePaddle/PaddleDetection>
- ONNX Runtime: <https://onnxruntime.ai/docs/>
- CVAT dataset formats: <https://docs.cvat.ai/docs/dataset_management/formats/>
- DVC: <https://dvc.org/>
