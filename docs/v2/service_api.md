# Asynchronous extraction API

N.E.X.U.S runs as a separate private service with one persistent, preloaded extraction engine and one
serialized heavy worker. A website should call it from the website backend; browser JavaScript must
never receive the N.E.X.U.S API key or call this service directly.

```text
Browser -> website backend -> authenticated N.E.X.U.S API -> job polling -> website backend
```

The API keeps uploads in memory, releases encoded screenshot bytes when a job terminates, and does not
write screenshots to permanent storage.

## Private GHCR deployment

Production is distributed as the private application image
`ghcr.io/lucapohl-angel/nexus-ml-v2`. It contains one reviewed runtime bundle pinned by
immutable digest. The separate private runtime package is never mounted from the host and
neither package is public.

Authenticate Docker with a dedicated classic GitHub token that has `read:packages`, then
clone and install:

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
  -u YOUR_GITHUB_USER --password-stdin

git clone --branch v2-engine https://github.com/lucapohl-angel/N.E.X.U.S-ML-V2.git
cd N.E.X.U.S-ML-V2
./scripts/nexus-server install
```

The installer generates a 256-bit API key, writes `.env` and `.env.key` with mode `0600`,
resolves the `stable` discovery channel to an immutable application digest, verifies image
provenance labels, starts the hardened service with pulling disabled, waits for the engine,
and checks both rejected unauthenticated access and accepted authenticated access. The
service binds to loopback by default.

Compose runs the container as an unprivileged user, drops Linux capabilities, uses a
read-only root filesystem, and caps memory and process count. Reviewed source screenshots,
truth files, reviewer states, evaluation reports, private catalog worktrees, and prototype
source provenance remain outside the public repository and normal application build context.

Use the lifecycle helper for normal operation:

```bash
./scripts/nexus-server status
./scripts/nexus-server logs -f
./scripts/nexus-server update
./scripts/nexus-server rollback
./scripts/nexus-server rotate-key
```

Updates deploy exact digests and automatically restore the previous known-good digest if
engine readiness or authentication checks fail. Optional daily updates use the same bounded,
locked path:

```bash
./scripts/nexus-server enable-auto-update
./scripts/nexus-server disable-auto-update
```

Runtime artwork/catalog refreshes are not blindly promoted. After human review and replay,
a trusted Docker-capable machine publishes them with:

```bash
./scripts/publish-private-images --approve-reviewed-runtime
```

See the root `README.md` for first-time GHCR permissions and the code-versus-runtime update
workflow.

The default `auto` profile resolves to the fastest profile certified on the current reviewed corpus.
Override it in `.env` when needed:

```text
NEXUS_PERFORMANCE_PROFILE=exact-cpu
NEXUS_PERFORMANCE_PROFILE=fast-cpu
NEXUS_PERFORMANCE_PROFILE=fast-cpu-vectorized
```

## Native start

```bash
uv sync --frozen
export NEXUS_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run nexus-api --host 127.0.0.1 --port 8000 --performance-profile auto
```

The process is not ready until catalogs, prototypes, policies, RapidOCR, and ONNX sessions have
preloaded. Do not add Uvicorn workers: every process would load an independent engine and maintain an
independent active-job registry.

## Authentication and website integration

`GET /v2/health` is intentionally unauthenticated for container orchestration. Submission, status, and
result routes require either header form. Docker reads the key from the mounted
`NEXUS_API_KEY_FILE`; native development may use `NEXUS_API_KEY` directly:

```http
Authorization: Bearer <secret>
X-Nexus-API-Key: <secret>
```

Keep this key in the website backend environment or secret store. Do not place it in frontend source,
public runtime configuration, cookies, analytics, URLs, or browser requests. N.E.X.U.S adds no CORS
middleware because direct browser access is not part of the production architecture.

If both services are in one Compose project, attach them to the same private Docker network and call:

```text
http://nexus-api:8000
```

The `ports` mapping can then be removed entirely. If the website backend runs directly on the same
host, keep the default loopback mapping and call `http://127.0.0.1:8000`.

## Submit and poll

```bash
# NEXUS_API_KEY must already be exported in this server shell.
BASE_URL='http://127.0.0.1:8000'

curl -sS -X POST "$BASE_URL/v2/extract-match" \
  -H "Authorization: Bearer $NEXUS_API_KEY" \
  -F 'hero_item=@hero_item.jpg' \
  -F 'overall=@overall.jpg' \
  -F 'dps=@dps.jpg' \
  -F 'farm=@farm.jpg' \
  -F 'team=@team.jpg'

curl -sS -H "Authorization: Bearer $NEXUS_API_KEY" "$BASE_URL/v2/jobs/<job-id>"
curl -sS -H "Authorization: Bearer $NEXUS_API_KEY" "$BASE_URL/v2/jobs/<job-id>/result"
```

Admission returns `202 Accepted` immediately. Result polling returns `202` while queued/processing,
`200` with five structured results on completion, or a sanitized `500` state on failure.

Jobs and result polling are process-local and are lost on restart. The latest 64 terminal jobs are
retained by default; this is not a completed-result cache.

`played_at` has been removed from extraction. The engine no longer defines or OCRs that crop, reviewer
queues and reviewed TXT exports omit it, and the API result schema rejects it if reintroduced. Match
metadata continues to include fields such as battle ID, result, scores, and duration.

## Performance profiles and quality contract

Performance profiles are independent from hero recognition modes (`balanced`, `strict`, `original`).
The API continues to use `balanced` hero recognition by default.

| Profile | Provider | OCR detector | Certification | Current five-screen time |
|---|---|---:|---|---:|
| `auto` | CPU | localized recognition only | certified vectorized hero scorer | 57.56 s first-request median |
| `exact-cpu` | CPU | metadata detector enabled | complete evidence parity | 173.20 s |
| `fast-cpu` | CPU | localized recognition only | selected-output parity | 98.94 s |
| `fast-cpu-vectorized` | CPU | localized recognition only | selected-output certified | 57.56 s first / 59.37 s warm median |
| `nvidia-cuda` | CUDA | localized recognition only | server validation required | not benchmarked |

`fast-cpu` retained the accepted complete reviewed-family selected outcomes:

```text
OCR screenshots:          25
Non-name OCR:             1,848 / 1,855 exact
Wrong:                    7
Abstained:                0
Accuracy:                 99.6226%
Hero balanced replay:     4,281 / 4,346 exact
Hero wrong / abstained:   13 / 52
Reviewed item gate:       320 / 324 exact, 1 wrong, 3 abstained
Overall including names:  2,058 / 2,100 exact (98.0%)
```

No selected OCR failure identity, per-field count, or per-game count changed. The item matcher now loads
the immutable 300-reference `family-01-v1` reviewed prototype manifest in production and reviewer drafts.
Grouped leave-one-game-out replay on the original family plus entirely held-out iPad-family replay produced
320 exact, 1 wrong, and 3 abstained occupied-item outcomes across 324 reviewed slots; the iPad subset improved
from 71 exact and 42 abstained to 112 exact and 1 abstained with no wrong accepted identity. Global item
acceptance thresholds were not lowered. OCR sequence confidence remains available and versioned, but raw
candidate evidence can differ from `exact-cpu`; use `exact-cpu` when complete evidence-level replay is
required.

`fast-cpu-vectorized` vectorizes only exhaustive hero scoring; item matching, OCR, preprocessing,
policies, stable ranking, and result assembly remain unchanged. Its final chunk-256 implementation
builds directly into one contiguous feature bank, avoiding approximately 718 MiB of stale duplicate
construction memory. The complete post-fix 4,346-row scalar-oracle replay has zero score, ranking,
status, decision, or evidence differences and retains Kaja 42/42. The 25-screen engine/API and
authenticated Docker gates also preserve selected outputs.

CPU profiles use one RapidOCR ONNX intra-op and one inter-op thread. The corrected 10-process ABBA
benchmark required three consecutive preflight samples at no more than 75 C with at most 2 C spread,
load at most 2, CPU idle at least 70%, and no conflicting workers. Without deleting any run, vectorized
first-request median fell from 70.088 to 57.557 seconds (17.88%) and warm median fell from 73.971 to
59.365 seconds (19.75%); p95 improved by approximately 19% for both. Median startup remained 8.993
seconds versus 8.879 for scalar, and maximum vectorized peak RSS was 1,566,140 KiB. The profile is
selected-output certified as `hero-vectorized-v2-item-prototypes-cross-device-v1`, and `auto` now
selects it. Explicit `fast-cpu` remains the certified scalar rollback profile.

An explicit `nvidia-cuda` request fails at startup unless `CUDAExecutionProvider` is available. Even on
a CUDA host it remains blocked from normal production startup until that server passes the reviewed
corpus. Operators may set `NEXUS_ALLOW_UNCERTIFIED_RUNTIME=true` only for a controlled validation run;
this override must not be used for website production traffic. `auto` does not silently activate an
uncertified GPU. A future GPU image/server must run all reviewed OCR and hero/item gates before its
certification can be promoted.

The health response exposes requested/selected profile, effective ONNX provider, ONNX Runtime version,
text-detection policy, and certification ID. The same values are included in result model provenance.

## Active deduplication and ephemeral inference reuse

The service fingerprints ordered upload roles and encoded bytes. Identical submissions reuse an
existing job only while it is queued or processing. After completion/failure, the active fingerprint is
removed and a later upload creates a new extraction.

Within one active match, exact byte-identical OCR inputs and hero crops can reuse immutable inference
results. This memo is destroyed when extraction terminates and never crosses jobs.

## Concurrency and scaling

One expensive extraction per process remains the safe default. Two screenshot workers improved the old
291.03-second baseline by only 2.36% while peak memory increased from 1.93 to 2.70 GiB.

For larger production load, run multiple one-engine replicas behind an external durable queue and move
active deduplication/job state into shared storage. Do not simply increase Uvicorn workers in one
container.

## Health

```bash
curl -sS http://127.0.0.1:8000/v2/health
```

Readiness requires `status: ok`, `engine_loaded: true`, and `worker_alive: true`. Docker uses this exact
condition for its healthcheck.
