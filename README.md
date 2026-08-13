<div align="center">

# N.E.X.U.S ML V2

**Authenticated screenshot extraction API for Mobile Legends post-match results**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Deploy-Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

</div>

N.E.X.U.S V2 accepts the five post-match screenshots, extracts structured match data, and returns one result per screen through an asynchronous API. The production service preloads one certified CPU engine, keeps uploaded screenshots in memory, and protects every submission/result route with an API key.

> [!IMPORTANT]
> Call N.E.X.U.S from your **website backend**, never directly from browser JavaScript. The API key must remain a server-side secret.

## Production architecture

```text
Browser → your backend → N.E.X.U.S API → queued extraction → structured JSON
                              │
                              └── Bearer API key
```

The Docker image contains application code and screen-layout profiles only. Reviewed screenshots, reviewer state, truth files, reports, and recognition source provenance are excluded. A validated private runtime bundle is mounted read-only when the container starts.

## Server installation

### Requirements

- 64-bit Linux server
- Git
- Docker Engine with Docker Compose v2
- At least **4 GB RAM** available to the container
- The private `nexus-runtime-assets.tar.gz` bundle

Docker must already be installed and usable by your server user:

```bash
docker info
docker compose version
```

### 1. Export the private runtime bundle

Run this once on the trusted development machine that contains the reviewed runtime assets:

```bash
uv sync --frozen
uv run python tools/export_runtime_assets.py \
  --archive nexus-runtime-assets.tar.gz
```

The exporter strips reviewer/source metadata, includes only inference files, writes per-file checksums, and verifies catalog/policy relationships. Transfer the archive privately:

```bash
scp nexus-runtime-assets.tar.gz user@your-server:/tmp/
```

Do **not** publish this archive or add it to Git.

### 2. Install with one command

On the server:

```bash
git clone --branch v2-engine https://github.com/lucapohl-an/N.E.X.U.S-ML-V2.git
cd N.E.X.U.S-ML-V2
./scripts/nexus-server install --runtime-assets /tmp/nexus-runtime-assets.tar.gz
```

The installer automatically:

1. validates Docker and Compose;
2. validates every runtime-asset checksum and integrity pin;
3. generates a 256-bit API key;
4. saves configuration in `.env` and the token in `.env.key`, both mode `0600`;
5. builds and starts the hardened container;
6. waits for the extraction engine to finish loading;
7. proves unauthenticated access is rejected;
8. proves the generated key reaches a protected route.

By default the API listens only on `127.0.0.1:8000`.

> [!TIP]
> Keep the loopback default and expose the API through your existing HTTPS reverse proxy. Use `--public` only when firewall rules and TLS termination are already configured.

Custom port:

```bash
./scripts/nexus-server install \
  --runtime-assets /tmp/nexus-runtime-assets.tar.gz \
  --port 8080
```

## API-key security

The key is generated during installation. Show it later with:

```bash
./scripts/nexus-server key
```

Protected routes accept either header:

```http
Authorization: Bearer <API_KEY>
X-Nexus-API-Key: <API_KEY>
```

`GET /v2/health` remains public for container readiness checks but returns no screenshot or result data. Submission, job status, and results require the key. Key comparisons use constant-time verification, and production startup fails closed when the key is missing.

Compose mounts the token from `.env.key` as `/run/secrets/nexus_api_key`; it is not placed in the
container environment. Store the key in your backend secret manager. Never put it in frontend code,
URLs, cookies, analytics, screenshots, or Git.

Rotate it at any time:

```bash
./scripts/nexus-server rotate-key
```

The old key stops working after the container is recreated.

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

Result polling returns `202` while queued/processing and `200` when all five results are ready. Jobs are held in process memory and do not survive a restart.

## Operations

| Action | Command |
|---|---|
| Health and container status | `./scripts/nexus-server status` |
| Follow logs | `./scripts/nexus-server logs -f` |
| Restart | `./scripts/nexus-server restart` |
| Stop | `./scripts/nexus-server stop` |
| Start | `./scripts/nexus-server start` |
| Rebuild/update current checkout | `./scripts/nexus-server update` |
| Show API key | `./scripts/nexus-server key` |
| Rotate API key | `./scripts/nexus-server rotate-key` |
| Remove container, preserve assets | `./scripts/nexus-server uninstall` |
| Remove container and private assets | `./scripts/nexus-server uninstall --purge-assets` |

Upgrade to the newest branch revision:

```bash
git pull --ff-only
./scripts/nexus-server update
```

The runtime bundle is mounted outside the image, so ordinary code upgrades do not duplicate or expose it. If a release requires new recognition assets, export a new archive and rerun `install --runtime-assets ...`.

## Recovery

If startup fails:

```bash
./scripts/nexus-server logs --tail 200
./scripts/nexus-server status
```

Common causes:

- Docker daemon is stopped or the user cannot access it;
- port 8000 is already in use;
- fewer than 4 GB are available;
- the runtime archive is incomplete, modified, or from a different catalog;
- a reverse proxy points at the wrong host port.

The installer never reports success from container launch alone; it waits for the model engine and authentication checks. A failed runtime-bundle replacement keeps the previously installed bundle until the new one validates.

## Recognition and privacy contract

- `auto` selects the certified vectorized CPU profile.
- Reviewed item prototypes are loaded automatically without lowering global score or margin thresholds.
- Held-out iPad evaluation reached **112/113 exact occupied items**, **0 wrong accepted identities**, and **1 abstention**.
- `played_at` is completely absent from extraction and API output.
- Upload bytes are kept in memory and released when a job terminates.
- No raw screenshots, reviewer state, player identifiers, truth exports, or benchmark reports enter the image or repository.

Detailed API behavior, performance certification, concurrency, and provenance are documented in [`docs/v2/service_api.md`](docs/v2/service_api.md).

## Local development

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check nexus_v2 tests tools
uv run mypy --strict nexus_v2
```

For an authenticated native API process, first export/mount the private runtime bundle and set `NEXUS_RUNTIME_ASSETS_ROOT`, `NEXUS_API_KEY`, and `NEXUS_REQUIRE_API_KEY=true`.

## License

MIT. Mobile Legends: Bang Bang assets and names remain property of their respective owners.
