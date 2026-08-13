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

The source repository is public, but the production image is private. Cloning this repository does **not** grant access to `ghcr.io/lucapohl-angel/nexus-ml-v2`.

Two separate credentials are involved:

| Credential | Purpose | Created by |
|---|---|---|
| GitHub PAT (classic), `read:packages` | Allows Docker to download the private GHCR image | Server operator |
| N.E.X.U.S API key | Authorizes extraction and result API calls | Generated locally by the installer |

The GitHub token is never used as the N.E.X.U.S API key, and neither credential is included in the image or repository.

### Requirements

- 64-bit Linux server
- Git
- Docker Engine with Docker Compose v2
- At least 4 GB RAM available to the container
- A GitHub account that has **Read** access to the private N.E.X.U.S application package
- A personal access token (classic) for that account with `read:packages`

### 1. Get access to the official private image

The package owner must grant your GitHub account Read access first. Ask the N.E.X.U.S maintainer to add your GitHub username under:

1. GitHub profile → **Packages**
2. `nexus-ml-v2` → **Package settings**
3. **Manage access** → **Invite teams or people**
4. Select your account and assign **Read**

A token does not bypass package permissions. A valid `read:packages` token still receives `denied` if its GitHub account has not been granted access.

> [!NOTE]
> The runtime package is an internal build input. A normal server only needs Read access to `nexus-ml-v2`, the final application package.

### 2. Create the GHCR download token

GitHub Packages requires a [personal access token (classic)](https://github.com/settings/tokens). A fine-grained token is not the documented GHCR authentication method. See GitHub's [Container registry authentication guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry).

1. Open GitHub → **Settings** → **Developer settings**.
2. Open **Personal access tokens** → **Tokens (classic)**.
3. Select **Generate new token (classic)**.
4. Give it a recognizable name such as `Nexus server pull`.
5. Set an expiration date appropriate for the server.
6. Select only `read:packages`.
7. Generate the token and store it in the server's secret manager or another protected location.

Do not commit the token, put it in `.env`, pass it as a Docker build argument, or send it in chat.

### 3. Log Docker into GHCR

Use the GitHub username that was granted package access. Read the token interactively so it does not appear in shell history:

```bash
read -rsp "GHCR token: " GHCR_TOKEN
echo

printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
  -u YOUR_GITHUB_USERNAME \
  --password-stdin

unset GHCR_TOKEN
```

Expected result:

```text
Login Succeeded
```

Optional access test:

```bash
docker pull ghcr.io/lucapohl-angel/nexus-ml-v2:stable
```

If this returns `denied`, `unauthorized`, or `not found`, check all three conditions:

1. the token is a PAT **classic**, not a fine-grained token;
2. it includes `read:packages`;
3. the token owner's GitHub account has Read access to `nexus-ml-v2`.

Docker stores the registry login according to the machine's Docker credential configuration. You may remove it after installation:

```bash
docker logout ghcr.io
```

The GHCR token is not mounted into the N.E.X.U.S container. If you log out, authenticate again before a future private image pull or update.

### 4. Clone and install

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
4. generates a 256-bit N.E.X.U.S API key in a mode-`0600` secret file;
5. runs the container as the non-root account that owns that secret;
6. starts the hardened container using the exact digest with pulling disabled;
7. waits for the extraction engine to load;
8. proves missing or invalid API authentication is rejected;
9. proves the generated API key reaches a protected route;
10. records the known-good digest for future rollback.

The installer prints the generated N.E.X.U.S API key once at the end. Retrieve it again with:

```bash
./scripts/nexus-server key
```

Store that key in your website backend's secret manager. Do not expose it to browser JavaScript.

By default, the API listens only on `127.0.0.1:8000`. Put your HTTPS reverse proxy in front of it.

Custom port or deliberate public bind:

```bash
./scripts/nexus-server install --port 8080
./scripts/nexus-server install --public
```

Use `--public` only when firewall rules and TLS termination are already configured.

### Using your own GHCR package

It is possible to operate a private package under your own GitHub namespace, but the public repository alone is not a complete production image source. The official private package contains reviewed recognition catalogs, policies, and screenshot-derived prototypes that are intentionally excluded from public Git.

To publish your own production image, you must:

1. provide and review your own legally distributable runtime assets;
2. keep those assets outside public Git history;
3. configure `NEXUS_GHCR_OWNER` for your GitHub namespace;
4. authenticate with a PAT (classic) that has `read:packages` and `write:packages`;
5. run the trusted publisher with explicit runtime approval:

```bash
read -rsp "GHCR publishing token: " GHCR_TOKEN
echo
export GHCR_TOKEN
export NEXUS_GHCR_OWNER=YOUR_GITHUB_NAMESPACE

./scripts/publish-private-images --approve-reviewed-runtime

unset GHCR_TOKEN NEXUS_GHCR_OWNER
```

The publisher creates the packages on their first successful pushes; empty GHCR packages do not need to be created manually.

The stock installer deliberately trusts only the official package. A compatible custom application image can be selected with:

```bash
./scripts/nexus-server install \
  --image ghcr.io/YOUR_GITHUB_NAMESPACE/nexus-ml-v2:stable
```

That command will be rejected until your fork has its own matching trust policy. Update `DEFAULT_CHANNEL`, `EXPECTED_SOURCE`, `EXPECTED_RUNTIME_REPOSITORY`, `is_digest_reference`, and the repository check in `resolve_candidate_digest` inside `scripts/nexus-server`. Keep the repository allowlist, OCI label verification, digest pinning, health check, API authentication check, and rollback behavior. Do not pass the runtime-only image to the installer. The server needs the complete application image.

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

- non-root execution using the installer account's numeric UID/GID;
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
