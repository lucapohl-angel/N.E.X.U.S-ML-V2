from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_REPOSITORY = "ghcr.io/lucapohl-angel/nexus-ml-v2"
RUNTIME_REPOSITORY = "ghcr.io/lucapohl-angel/nexus-ml-v2-runtime"
STABLE_DIGEST = "a" * 64
BAD_DIGEST = "b" * 64
CURRENT_DIGEST = "c" * 64
RUNTIME_DIGEST = "d" * 64


def test_application_image_is_hardened_and_embeds_only_approved_runtime_stage() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG NEXUS_RUNTIME_IMAGE\n" in dockerfile
    assert "ARG NEXUS_RUNTIME_IMAGE=" not in dockerfile
    assert "FROM ${NEXUS_RUNTIME_IMAGE} AS runtime-assets" in dockerfile
    assert "COPY --from=runtime-assets /runtime-assets /runtime-assets" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["nexus-api", "--host", "0.0.0.0", "--port", "8000"]' in dockerfile
    assert "NEXUS_REQUIRE_API_KEY=true" in dockerfile
    assert "NEXUS_RUNTIME_ASSETS_ROOT=/runtime-assets" in dockerfile
    assert "COPY profiles ./profiles" in dockerfile
    assert "COPY data" not in dockerfile
    assert "COPY catalogs" not in dockerfile
    assert "review_dataset" not in dockerfile


def test_runtime_image_has_a_minimal_scratch_contract() -> None:
    dockerfile = (ROOT / "Dockerfile.runtime").read_text(encoding="utf-8")

    assert dockerfile.splitlines()[1] == "FROM scratch"
    assert "COPY runtime-assets/ /runtime-assets/" in dockerfile
    assert "COPY ." not in dockerfile


def test_dockerignore_excludes_private_and_development_data() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for entry in (
        ".git",
        ".env",
        ".work",
        "data",
        "catalogs",
        "heroes",
        "items",
        "tests",
        "tools",
        "scripts",
    ):
        assert entry in ignored
    assert not any(line.startswith("!") and "private" in line for line in ignored)


def test_compose_pulls_private_image_and_applies_container_hardening() -> None:
    payload = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = payload["services"]["nexus-api"]

    assert service["image"] == "${NEXUS_IMAGE:?Set NEXUS_IMAGE to the private GHCR image}"
    assert service["user"] == (
        "${NEXUS_CONTAINER_UID:?Run ./scripts/nexus-server install}:"
        "${NEXUS_CONTAINER_GID:?Run ./scripts/nexus-server install}"
    )
    assert "build" not in service
    assert "volumes" not in service
    assert service["environment"]["NEXUS_API_KEY_FILE"] == "/run/secrets/nexus_api_key"
    assert service["environment"]["NEXUS_REQUIRE_API_KEY"] == "true"
    assert service["environment"]["NEXUS_RUNTIME_ASSETS_ROOT"] == "/runtime-assets"
    assert service["ports"] == [
        "${NEXUS_BIND_ADDRESS:-127.0.0.1}:${NEXUS_API_PORT:-8000}:8000"
    ]
    assert service["secrets"] == ["nexus_api_key"]
    assert payload["secrets"]["nexus_api_key"]["file"].startswith("${NEXUS_API_KEY_FILE:?")
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp:size=256m,mode=1777"]
    assert service["pids_limit"] == 512
    assert service["mem_limit"] == "${NEXUS_MEMORY_LIMIT:-4g}"


def test_server_and_publisher_scripts_are_valid_and_executable() -> None:
    server = ROOT / "scripts/nexus-server"
    publisher = ROOT / "scripts/publish-private-images"

    for script in (server, publisher):
        subprocess.run(["bash", "-n", str(script)], check=True)
        assert script.stat().st_mode & stat.S_IXUSR
    help_result = subprocess.run(
        [str(server), "--help"], check=True, capture_output=True, text=True
    )
    for command in (
        "install",
        "update",
        "rollback",
        "enable-auto-update",
        "logs",
        "rotate-key",
        "uninstall",
    ):
        assert command in help_result.stdout
    text = server.read_text(encoding="utf-8")
    expected_header = "Authorization: " + "Bearer" + " " + "$" + "key"
    assert expected_header in text


def _write_fake_runtime(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "active-image"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -e
state=${NEXUS_TEST_STATE:?}
if [[ "$1 $2" == "compose version" || "$1" == "info" ]]; then exit 0; fi
if [[ "$1" == "pull" ]]; then exit 0; fi
if [[ "$1 $2" == "image inspect" ]]; then
  image=${@: -1}
  args="$*"
  app='ghcr.io/lucapohl-angel/nexus-ml-v2'
  runtime='ghcr.io/lucapohl-angel/nexus-ml-v2-runtime'
  stable_digest='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  bad_digest='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  runtime_digest='dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
  if [[ "$args" == *'RepoDigests'* ]]; then
    if [[ "$image" == *':bad' ]]; then
      printf '%s@sha256:%s\\n' "$app" "$bad_digest"
    else
      printf '%s@sha256:%s\\n' "$app" "$stable_digest"
    fi
  elif [[ "$args" == *'org.opencontainers.image.source'* ]]; then
    printf '%s\\n' 'https://github.com/lucapohl-angel/N.E.X.U.S-ML-V2'
  elif [[ "$args" == *'org.opencontainers.image.revision'* ]]; then
    printf '%040d\\n' 0
  elif [[ "$args" == *'io.nexus.runtime.ref'* ]]; then
    printf '%s@sha256:%s\\n' "$runtime" "$runtime_digest"
  else
    if [[ "$image" == *@sha256:* ]]; then
      printf 'sha256:%s\\n' "${image##*@sha256:}"
    else
      printf 'sha256:%s\\n' "$stable_digest"
    fi
  fi
  exit 0
fi
if [[ "$1" == "inspect" ]]; then
  active=$(cat "$state" 2>/dev/null || true)
  printf 'sha256:%s\\n' "${active##*@sha256:}"
  exit 0
fi
if [[ "$1" == "compose" ]]; then
  shift
  env_file=''
  while [[ "${1:-}" == "--env-file" || "${1:-}" == "-f" ]]; do
    [[ "$1" == "--env-file" ]] && env_file="$2"
    shift 2
  done
  case "${1:-}" in
    config|logs|down|stop|restart) exit 0 ;;
    ps)
      if [[ "$*" == *"--quiet"* ]]; then printf 'fake-container\\n'; fi
      if [[ "$*" == *"--status running"* ]]; then printf 'nexus-api\\n'; fi
      exit 0
      ;;
    up)
      image=$(grep '^NEXUS_IMAGE=' "$env_file" | cut -d= -f2-)
      printf '%s\\n' "$image" >"$state"
      exit 0
      ;;
  esac
fi
exit 97
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    curl = fake_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -e
state=${NEXUS_TEST_STATE:?}
args="$*"
active=$(cat "$state" 2>/dev/null || true)
if [[ "$args" == *"/v2/health"* ]]; then
  bad_digest='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  [[ "$active" == *"sha256:$bad_digest"* ]] && exit 22
  printf '%s' '{"status":"ok","engine_loaded":true,"authentication_required":true}'
  exit 0
fi
if [[ "$args" == *"/v2/jobs/security-check"* ]]; then
  if [[ "$args" == *"Authorization: Bearer "* ]]; then printf '404'; else printf '401'; fi
  exit 0
fi
exit 96
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return fake_bin, state


def test_server_install_generates_key_and_pulls_private_stable_image(tmp_path: Path) -> None:
    fake_bin, state = _write_fake_runtime(tmp_path)
    env_file = tmp_path / "nexus.env"
    state.write_text("old-image\n", encoding="utf-8")
    result = subprocess.run(
        [str(ROOT / "scripts/nexus-server"), "install"],
        env={
            **os.environ,
            "NEXUS_ENV_FILE": str(env_file),
            "NEXUS_TEST_STATE": str(state),
            "NEXUS_STARTUP_TIMEOUT": "2",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line
    )
    key_file = Path(values["NEXUS_API_KEY_FILE"])
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    key = key_file.read_text(encoding="utf-8").strip()
    assert key.startswith("nxs_") and len(key) >= 47
    assert key not in env_file.read_text(encoding="utf-8")
    stable = f"{APP_REPOSITORY}@sha256:{STABLE_DIGEST}"
    assert values["NEXUS_IMAGE"] == stable
    assert values["NEXUS_CURRENT_IMAGE"] == stable
    assert values["NEXUS_UPDATE_CHANNEL"] == f"{APP_REPOSITORY}:stable"
    assert values["NEXUS_PREVIOUS_IMAGE"] == ""
    assert values["NEXUS_BIND_ADDRESS"] == "127.0.0.1"


def test_failed_image_update_restores_saved_known_good_digest(tmp_path: Path) -> None:
    fake_bin, state = _write_fake_runtime(tmp_path)
    env_file = tmp_path / "nexus.env"
    key_file = tmp_path / "nexus.key"
    key_file.write_text("nxs_" + "x" * 43 + "\n", encoding="utf-8")
    env_file.write_text(
        "\n".join(
            (
                f"NEXUS_API_KEY_FILE={key_file}",
                f"NEXUS_IMAGE={APP_REPOSITORY}@sha256:{CURRENT_DIGEST}",
                f"NEXUS_UPDATE_CHANNEL={APP_REPOSITORY}:stable",
                f"NEXUS_CURRENT_IMAGE={APP_REPOSITORY}@sha256:{CURRENT_DIGEST}",
                "NEXUS_PREVIOUS_IMAGE=",
                "NEXUS_BIND_ADDRESS=127.0.0.1",
                "NEXUS_API_PORT=8000",
                "NEXUS_PERFORMANCE_PROFILE=auto",
                "NEXUS_MAX_RETAINED_JOBS=64",
                "NEXUS_MAX_UPLOAD_BYTES=52428800",
                "NEXUS_MEMORY_LIMIT=4g",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    key_file.chmod(0o600)
    current = f"{APP_REPOSITORY}@sha256:{CURRENT_DIGEST}"
    state.write_text(current + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(ROOT / "scripts/nexus-server"),
            "update",
            "--image",
            f"{APP_REPOSITORY}:bad",
        ],
        env={
            **os.environ,
            "NEXUS_ENV_FILE": str(env_file),
            "NEXUS_TEST_STATE": str(state),
            "NEXUS_STARTUP_TIMEOUT": "1",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert state.read_text(encoding="utf-8").strip() == current
    assert "known-good digest succeeded" in result.stderr
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
    )
    assert values["NEXUS_CURRENT_IMAGE"] == current


def test_private_publish_workflow_uses_immutable_runtime_and_live_gate() -> None:
    workflow = (ROOT / ".github/workflows/publish-private-image.yaml").read_text(
        encoding="utf-8"
    )
    publisher = (ROOT / "scripts/publish-private-images").read_text(encoding="utf-8")

    assert "packages: write" in workflow
    assert "NEXUS_RUNTIME_IMAGE must be an immutable private runtime digest" in workflow
    assert "Verify candidate engine and authentication" in workflow
    assert "steps.build.outputs.digest" in workflow
    assert "CANDIDATE: ghcr.io/lucapohl-angel/nexus-ml-v2@" in workflow
    assert "build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8" in workflow
    assert "cache-to:" not in workflow
    assert "--approve-reviewed-runtime" in publisher
    assert "verify_runtime_asset_parity.py" in publisher
    assert "runtime_digest_ref" in publisher
    assert "require_private_package nexus-ml-v2-runtime" in publisher
    assert "require_private_package nexus-ml-v2" in publisher
    assert "Authorization: " + "Bearer" + " " + "${" + "key}" in publisher
    assert '--user "$(id -u):$(id -g)"' in publisher
    assert '--user "$(id -u):$(id -g)"' in workflow
    assert "Authorization: " + "Bearer" + " " + "$" + "key" in workflow
    assert 'RUNTIME_REPOSITORY:stable' in publisher
    assert 'APP_REPOSITORY:stable' in publisher
