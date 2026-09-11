from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_oracle_deploy_script_uses_staging_env_file_for_every_compose_call():
    script = (REPO_ROOT / "scripts/deploy-oracle-staging.sh").read_text()

    assert "COMPOSE=(" in script
    assert "--env-file .env.oracle.staging" in script
    assert '-f "$COMPOSE_FILE"' in script
    assert 'FORTRESS_SKIP_IMAGE_PULL:-0' in script
    assert '"${COMPOSE[@]}" pull' in script
    assert '"${COMPOSE[@]}" up -d' in script
    assert '"${COMPOSE[@]}" ps' in script
    assert '"${COMPOSE[@]}" logs --tail=150 fortress-backend' in script

    active_lines = [
        line.strip()
        for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    direct_compose_calls = [
        line
        for line in active_lines
        if line.startswith("docker compose") and line != "docker compose"
    ]
    assert direct_compose_calls == []


def test_oracle_compose_keeps_runtime_env_file_and_internal_backend_port():
    compose = (REPO_ROOT / "docker-compose.oracle-staging.yml").read_text()

    assert "STAGING_API_DOMAIN: ${STAGING_API_DOMAIN:?Set staging API domain}" in compose
    assert "image: ${FORTRESS_IMAGE:?Set FORTRESS_IMAGE to an immutable image tag}" in compose
    assert "env_file:\n      - .env.oracle.staging" in compose
    assert '      - "8000"' in compose
    assert '      - "80:80"' in compose
    assert '      - "443:443"' in compose
    assert "restart: unless-stopped" in compose
    assert '"8000:8000"' not in compose
