# Hero recognition operating modes

The local reviewer uses `balanced` hero recognition by default. The selected mode and policy SHA-256 are saved in every review state's `engine` provenance.

## Modes

- `balanced` (default): ally-only preprocessing plus the frozen constrained-consensus policy in `data/private/recognition_policies/hero-balanced-v1/`. It preserves predictions already accepted by the original champion and only reranks champion-abstained rows.
- `strict`: ally-only preprocessing plus `hero-ally-preprocess-rerank-calibration-v1`. This is the lower-coverage, no-wrong-count-regression fallback.
- `original`: the unchanged score and margin rules without preprocessing or policy reranking.

```bash
# Balanced default
uv run nexus-review

# Strict fallback
uv run nexus-review --hero-recognition-mode strict

# Original matcher rollback
uv run nexus-review --hero-recognition-mode original
```

A saved review state records its mode. Reopening it with a different mode is rejected so predictions from different operating points cannot be silently mixed. Start a fresh review state to reprocess a capture under another mode.

## Safety contract

- The balanced policy is pinned to the exact catalog and prototype-manifest hashes it was evaluated with. A hash mismatch prevents startup.
- Historical prototype manifests remain immutable.
- Engine predictions are drafts, not truth. Truth changes require explicit human approval in the reviewer.
- Automatic truth updates and prototype updates are disabled and recorded as `false` in review provenance.
- Candidate evidence, confidence, policy hash, mode, and original crop references remain available for later reprocessing.

The historical reviewed-corpus operating point is 4,281 exact, 13 wrong, and 52 abstained across 4,346 occupied hero rows (98.50% full exact). This is an in-domain benchmark, not a guarantee under future hero revamps or UI/domain shift.
