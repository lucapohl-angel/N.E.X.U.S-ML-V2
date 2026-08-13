# Benchmark data mount point

No screenshots or annotations are committed in this repository. Place or mount a private dataset
outside the Git checkout and pass its directory or `manifest.json` to:

```bash
nexus benchmark --engine v1 --dataset /absolute/private/path --report /tmp/v1-report.json
```

`NEXUS_BENCHMARK_DATASET` may provide the path instead. Relative image paths in the manifest are
resolved from the manifest directory; absolute paths are also accepted. The runner verifies every
image SHA-256, refuses any unapproved sample, enforces an image-size limit, and does not copy source
screenshots into this repository.

The authoritative manifest schema is `nexus_v2.schemas.annotation.AnnotationManifest`. An approved
sample requires a reviewer, review timestamp, typed annotation, match-group ID, source metadata, and
exact image SHA-256. Git ignores everything in this directory except this README so private images
and annotations are not accidentally staged.
