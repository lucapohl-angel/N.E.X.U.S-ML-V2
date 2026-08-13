from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_docker_image_runs_non_root_and_contains_only_code_and_profiles() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["nexus-api", "--host", "0.0.0.0", "--port", "8000"]' in dockerfile
    assert "NEXUS_REQUIRE_API_KEY=true" in dockerfile
    assert "NEXUS_RUNTIME_ASSETS_ROOT=/runtime-assets" in dockerfile
    assert "COPY profiles ./profiles" in dockerfile
    assert "COPY data" not in dockerfile
    assert "COPY catalogs" not in dockerfile
    assert "review_dataset" not in dockerfile
    assert "recognition_prototypes" not in dockerfile


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


def test_compose_requires_secret_assets_and_applies_container_hardening() -> None:
    payload = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = payload["services"]["nexus-api"]

    assert service["environment"]["NEXUS_API_KEY_FILE"] == "/run/secrets/nexus_api_key"
    assert service["environment"]["NEXUS_REQUIRE_API_KEY"] == "true"
    assert service["environment"]["NEXUS_RUNTIME_ASSETS_ROOT"] == "/runtime-assets"
    assert service["ports"] == [
        "${NEXUS_BIND_ADDRESS:-127.0.0.1}:${NEXUS_API_PORT:-8000}:8000"
    ]
    assert service["volumes"] == [
        "${NEXUS_RUNTIME_ASSETS_DIR:?Set NEXUS_RUNTIME_ASSETS_DIR to the extracted "
        "private runtime bundle}:/runtime-assets:ro"
    ]
    assert service["secrets"] == ["nexus_api_key"]
    assert payload["secrets"]["nexus_api_key"]["file"].startswith("${NEXUS_API_KEY_FILE:?")
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp:size=256m,mode=1777"]
    assert service["pids_limit"] == 512
    assert service["mem_limit"] == "${NEXUS_MEMORY_LIMIT:-4g}"


def test_server_script_has_valid_shell_syntax_and_is_executable() -> None:
    script = ROOT / "scripts/nexus-server"

    subprocess.run(["bash", "-n", str(script)], check=True)
    assert script.stat().st_mode & stat.S_IXUSR
    help_result = subprocess.run(
        [str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for command in ("install", "update", "logs", "rotate-key", "uninstall"):
        assert command in help_result.stdout
    text = script.read_text(encoding="utf-8")
    expected_header = "Authorization: Bearer " + "$" + "key"
    assert expected_header in text


def test_server_script_generates_a_private_random_key_without_docker(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1 $2\" = \"compose version\" ]; then exit 0; fi\n"
        "if [ \"$1\" = \"info\" ]; then exit 0; fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env_file = tmp_path / "nexus.env"
    result = subprocess.run(
        [str(ROOT / "scripts/nexus-server"), "install"],
        env={
            **os.environ,
            "NEXUS_ENV_FILE": str(env_file),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert env_file.is_file()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line
    )
    key_file = Path(values["NEXUS_API_KEY_FILE"])
    assert key_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    key = key_file.read_text(encoding="utf-8").strip()
    assert key.startswith("nxs_")
    assert len(key) >= 47
    assert key not in env_file.read_text(encoding="utf-8")
    assert values["NEXUS_BIND_ADDRESS"] == "127.0.0.1"
    assert "runtime assets are missing" in result.stderr
