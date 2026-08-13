<div align="center">

# N.E.X.U.S ML V2

**Private, authenticated screenshot extraction for Mobile Legends post-match results**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Deploy-Private%20GHCR-2496ED?logo=docker&logoColor=white)](https://github.com/features/packages)

</div>

N.E.X.U.S V2 accepts five post-match screenshots, extracts structured match data, and returns one result per screen through an asynchronous API. Production uses a preloaded CPU engine and protects every submission/result route with an API key.

> [!IMPORTANT]
> Call N.E.X.U.S from your website backend, never directly from browser JavaScript. Keep both the N.E.X.U.S API key and the GHCR deployment token server-side.

## Production architecture

```text
Public source repository
        │
        ├── GitHub Actions ── approved runtime digest
        │                           │
        ▼                           ▼
Private GHCR application image ← private reviewed runtime image
        │
        ▼
Server: digest-pinned container → authenticated N.E.X.U.S API
```

Two GHCR packages stay private:

- `ghcr.io/lucapohl-angel/nexus-ml-v2-runtime` contains reviewed catalog and recognition assets.
- `ghcr.io/lucapohl-angel/nexus-ml-v2` contains the API plus one pinned runtime digest.

The public repository and Docker build context exclude source screenshots, reviewer state, truth files, player data, reports, private catalogs, and recognition source provenance.

## Server installation

### Requirements

- 64-bit Linux server
- Git
- Docker Engine with Docker Compose v2
- At least 4 GB RAM available to the container
- A GitHub classic personal access token with `read:packages`

Authenticate Docker once. Prefer a dedicated deployment identity/token with only package-read access:

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
  -u YOUR_GITHUB_USER \
  --password-stdin
```

Clone and install:

```bash
git clone --branch v2-engine \
  https://github.com/lucapohl-angel/N.E.X.U.S-ML-V2.git
cd N.E.X.U.S-ML-V2
./scripts/nexus-server install
```

The installer:

1. pulls the private `stable` discovery channel;
2. resolves it once to an immutable `sha256` digest;
3. verifies source, commit, and pinned-runtime OCI labels;
4. generates a 256-bit API key in a mode-`0600` secret file;
5. starts the hardened container using the exact digest with pulling disabled;
6. waits for the extraction engine to load;
7. proves unauthenticated access is rejected;
8. proves the generated key reaches a protected route;
9. records the known-good digest for future rollback.

By default, the API listens only on `127.0.0.1:8000`. Put your HTTPS reverse proxy in front of it.

Custom port or deliberate public bind:

```bash
./scripts/nexus-server install --port 8080
./scripts/nexus-server install --public
```

Use `--public` only when firewall rules and TLS termination are already configured.

## Updates and rollback

Manual safe update:

```bash
git pull --ff-only
./scripts/nexus-server update
```

`stable` is never deployed directly. The updater:

- serializes deployments with a lock;
- pulls and resolves `stable` to a digest;
- exits without restarting when the digest is unchanged;
- validates image provenance labels;
- deploys the exact digest;
- runs engine-readiness and authentication checks;
- records it only after success;
- restores the previous known-good digest if validation fails.

Manual rollback:

```bash
./scripts/nexus-server rollback
```

Optional daily updates:

```bash
./scripts/nexus-server enable-auto-update
```

The scheduled updater adds randomized delay to avoid synchronized pulls, cannot overlap another deployment, and uses the same digest-pinned validation and rollback path. Logs are written to `nexus-update.log`.

Disable it with:

```bash
./scripts/nexus-server disable-auto-update
```

Automatic deployment is optional. For stricter production control, leave it disabled and run `update` after reviewing a release.

## Publishing private images

### First-time GHCR setup

The first publication machine needs:

- a running Docker daemon;
- `uv`;
- the reviewed private runtime sources;
- a classic token with `read:packages` and `write:packages`.

```bash
export GHCR_TOKEN
./scripts/publish-private-images --approve-reviewed-runtime
```

The approval flag is intentional. The publisher exports and sanitizes the reviewed runtime, validates all checksums and catalog/policy pins, verifies exact runtime parity, builds an immutable runtime image, pins the app build to its digest, starts the app candidate, checks engine readiness and API authentication, then promotes both private packages.

After first publication, verify in GitHub package settings that both packages are **Private**. Grant this repository Actions access to the runtime package. The publisher stores the approved runtime digest in the repository variable `NEXUS_RUNTIME_IMAGE` when the current GitHub credential permits it.

### Code and tuning updates

Changes under the V2 engine/API/profile build paths trigger `.github/workflows/publish-private-image.yaml` on `v2-engine`.

The workflow:

1. runs the full test, Ruff, strict Mypy, and lockfile gates;
2. requires `NEXUS_RUNTIME_IMAGE` to be an immutable runtime digest;
3. builds an immutable `sha-<commit>` application image;
4. starts the candidate and verifies engine readiness plus unauthorized/authorized requests;
5. moves the private application `stable` channel only after success.

The workflow uses SHA-pinned third-party Actions and does not cache private runtime layers in the public repository's Actions cache.

### Hero, item, or artwork updates

MLBB changes heroes, skins, and items over time. Do not let an unattended scraper replace live recognition references.

Use this boundary:

```text
Discovery/scraping → human review/truth → replay and parity gates
                  → publish reviewed runtime digest → rebuild app → stable
```

When approved recognition assets change:

1. update and review the private catalog/prototype/policy sources;
2. run the full replay and zero-wrong-output gates;
3. run `./scripts/publish-private-images --approve-reviewed-runtime`;
4. allow or manually run the app-image workflow against the new recorded runtime digest;
5. update servers manually or through the optional scheduled updater.

This keeps routine code releases automatic without allowing unreviewed game-art changes into production.

## API-key security

Show the generated key:

```bash
./scripts/nexus-server key
```

Protected routes accept either:

```http
Authorization: Bearer <server-generated-key>
X-Nexus-API-Key: <server-generated-key>
```

`GET /v2/health` remains public for readiness checks but returns no screenshot or result data. Submission, job status, and results require authentication. The key is mounted as `/run/secrets/nexus_api_key`, not placed in the container environment.

Rotate it:

```bash
./scripts/nexus-server rotate-key
```

## Submit a match

```bash
BASE_URL='http://127.0.0.1:8000'
API_KEY=$(./scripts/nexus-server key)

curl -sS -X POST "$BASE_URL/v2/extract-match" \
  -H "Authorization: Bearer $API_KEY" \
  -F 'hero_item=@hero_item.png' \
  -F 'overall=@overall.png' \
  -F 'dps=@dps.png' \
  -F 'farm=@farm.png' \
  -F 'team=@team.png'
```

The API returns `202 Accepted` with `job_id`, `status_url`, and `result_url`.

```bash
curl -sS -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/v2/jobs/<job-id>"

curl -sS -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/v2/jobs/<job-id>/result"
```

Jobs are held in process memory and do not survive a restart.

## Operations

| Action | Command |
|---|---|
| Health and container status | `./scripts/nexus-server status` |
| Follow logs | `./scripts/nexus-server logs -f` |
| Safe digest update | `./scripts/nexus-server update` |
| Previous known-good release | `./scripts/nexus-server rollback` |
| Enable daily safe updates | `./scripts/nexus-server enable-auto-update` |
| Disable daily updates | `./scripts/nexus-server disable-auto-update` |
| Restart | `./scripts/nexus-server restart` |
| Stop/start | `./scripts/nexus-server stop` / `start` |
| Show/rotate API key | `./scripts/nexus-server key` / `rotate-key` |
| Remove service and local credentials | `./scripts/nexus-server uninstall` |

If startup fails:

```bash
./scripts/nexus-server logs --tail 200
./scripts/nexus-server status
```

## Container hardening

- non-root UID/GID `10001`;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- bounded writable `/tmp` only;
- API key mounted as a Compose secret;
- localhost binding by default;
- private runtime baked from a reviewed digest;
- deployment by application digest, never by a mutable tag.

## Local development

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check nexus_v2 tests tools
uv run mypy --strict nexus_v2
```

Detailed API behavior is documented in [`docs/v2/service_api.md`](docs/v2/service_api.md).

## License

MIT. Mobile Legends: Bang Bang assets and names remain property of their respective owners.
