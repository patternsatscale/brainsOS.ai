"""Unit and integration tests for Ticket #340 (Gitea Source Control & VS Code SCM) and Ticket #334 (Hermes WebUI routing)."""

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_APPS = REPO_ROOT / "docker" / "compose" / "compose.apps.yml"
COMPOSE_APPLIANCE = REPO_ROOT / "docker" / "compose" / "compose.appliance.yml"
COMPOSE_AGENTS = REPO_ROOT / "docker" / "compose" / "compose.agents.yml"
CADDYFILE = REPO_ROOT / "config" / "caddy" / "Caddyfile"
CADDYFILE_APPLIANCE = REPO_ROOT / "config" / "caddy" / "Caddyfile.appliance"
SETUP_GIT = REPO_ROOT / "scripts" / "setup" / "setup-git.sh"
EDITOR_ENTRYPOINT = REPO_ROOT / "docker" / "editor" / "entrypoint.sh"


def test_compose_apps_defines_gitea_service():
    """Verify compose.apps.yml defines the containerized Gitea service with Authentik SSO headers."""
    data = yaml.safe_load(COMPOSE_APPS.read_text(encoding="utf-8"))
    services = data.get("services", {})
    assert "gitea" in services, "gitea service must be defined in compose.apps.yml"

    gitea = services["gitea"]
    assert gitea["image"] == "gitea/gitea:1.22"
    assert gitea["container_name"] == "brainsos-app-git"
    assert "no-new-privileges:true" in gitea.get("security_opt", [])
    assert "127.0.0.1:${GITEA_HTTP_PORT:-3002}:3000" in gitea.get("ports", [])

    networks = gitea.get("networks", {})
    assert "brainsos-ingress-net" in networks
    assert "brainsos-ide-net" in networks
    assert "brainsos-internal-net" in networks
    aliases = networks["brainsos-internal-net"].get("aliases", [])
    for expected_alias in ("gitea", "git", "brainsos-git", "brainsos-app-git"):
        assert expected_alias in aliases

    env_list = gitea.get("environment", [])
    env_joined = "\n".join(env_list) if isinstance(env_list, list) else str(env_list)
    assert "GITEA__database__DB_TYPE=sqlite3" in env_joined
    assert "GITEA__server__ROOT_URL=https://${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}/git/" in env_joined
    assert "GITEA__security__REVERSE_PROXY_AUTHENTICATION_USER=X-Authentik-Username" in env_joined
    assert "GITEA__security__REVERSE_PROXY_AUTHENTICATION_EMAIL=X-Authentik-Email" in env_joined
    assert "GITEA__security__REVERSE_PROXY_AUTHENTICATION_FULL_NAME=X-Authentik-Name" in env_joined
    assert "GITEA__service__ENABLE_REVERSE_PROXY_AUTHENTICATION=true" in env_joined
    assert "GITEA__service__ENABLE_REVERSE_PROXY_AUTO_REGISTRATION=true" in env_joined
    assert "GITEA__ui__DEFAULT_THEME=gitea-dark" in env_joined


def test_compose_appliance_resets_gitea_ports():
    """Verify compose.appliance.yml resets gitea host ports to enforce Single-Origin Port 443."""
    raw = COMPOSE_APPLIANCE.read_text(encoding="utf-8")
    assert "gitea:\n    ports: !reset []" in raw


def test_compose_agents_hermes_webui_and_search_keys():
    """Verify compose.agents.yml binds Hermes dashboard to 0.0.0.0 and forwards web search API keys (#334)."""
    data = yaml.safe_load(COMPOSE_AGENTS.read_text(encoding="utf-8"))
    hermes = data["services"]["runner-hermes"]
    env_joined = "\n".join(hermes.get("environment", []))

    assert "HERMES_DASHBOARD_HOST=0.0.0.0" in env_joined
    assert "HERMES_DASHBOARD_PORT=9119" in env_joined
    for key_var in ("FIRECRAWL_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "BRAVE_SEARCH_API_KEY"):
        assert f"{key_var}=${{{key_var}:-}}" in env_joined


def test_caddyfiles_route_git_and_hermes_runner():
    """Verify both Caddyfile and Caddyfile.appliance route /git/* to gitea:3000 and /runner* to runner-hermes:9119."""
    for caddy_path in (Caddyfile := CADDYFILE, CADDYFILE_APPLIANCE):
        content = caddy_path.read_text(encoding="utf-8")
        assert "@git_no_slash path /git" in content, f"Missing @git_no_slash in {caddy_path}"
        assert "redir @git_no_slash /git/ 308" in content, f"Missing /git/ redirect in {caddy_path}"
        assert "handle /git/*" in content, f"Missing handle /git/* in {caddy_path}"
        assert "uri strip_prefix /git" in content, f"Missing uri strip_prefix /git in {caddy_path}"
        assert "reverse_proxy gitea:3000" in content, f"Missing reverse_proxy gitea:3000 in {caddy_path}"
        assert "header_up X-Authentik-Username {header.X-Authentik-Username}" in content
        assert "header_up X-Authentik-Email {header.X-Authentik-Email}" in content
        assert "header_up X-Authentik-Name {header.X-Authentik-Name}" in content
        assert "reverse_proxy runner-hermes:9119" in content, f"Missing runner-hermes:9119 in {caddy_path}"
        assert "runner-hermes:8787" not in content, f"Stale runner-hermes:8787 found in {caddy_path}"


def test_setup_git_syntax_and_dry_run(tmp_path: Path):
    """Verify setup-git.sh passes bash -n and supports --dry-run."""
    syntax = subprocess.run(
        ["bash", "-n", str(SETUP_GIT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    env_file = tmp_path / ".env"
    env_file.write_text(
        'BRAINSOS_URL="ec2-1-2-3-4.compute-1.amazonaws.com"\n'
        'BRAINSOS_LOCAL_DOMAIN="ops.brainsos.ai"\n'
        'BRAINSOS_SUPERUSER_USERNAME="jsm"\n',
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "BRAINSOS_DATA_DIR": str(tmp_path / "data"),
    }
    proc = subprocess.run(
        [str(SETUP_GIT), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "GITEA_ROOT_URL=https://ec2-1-2-3-4.compute-1.amazonaws.com/git/" in proc.stdout
    assert "GITEA_PRIMARY_USER=jsm" in proc.stdout
    assert "GIT_REMOTE_URL=http://gitea:3000/jsm/agent-box.git" in proc.stdout


def test_setup_git_seed_only_initializes_repo_and_gitignore(tmp_path: Path):
    """Verify setup-git.sh --seed-only initializes /data as a main-branch Git repo with strict .gitignore."""
    data_dir = tmp_path / "data"
    (data_dir / "souls").mkdir(parents=True)
    (data_dir / "souls" / "bawtford.md").write_text("# Bawtford Soul\n", encoding="utf-8")
    (data_dir / "control_plane").mkdir(parents=True)
    (data_dir / "control_plane" / "secret.db").write_text("sqlite-bytes", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text(
        'BRAINSOS_SUPERUSER_USERNAME="operator"\n'
        'BRAINSOS_SUPERUSER_NAME="Operator User"\n'
        'BRAINSOS_LOCAL_DOMAIN="local.brainsos.ai"\n',
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "BRAINSOS_DATA_DIR": str(data_dir),
    }
    proc = subprocess.run(
        [str(SETUP_GIT), "--seed-only"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (data_dir / "git").is_dir()
    assert (data_dir / ".gitignore").is_file()
    assert (data_dir / ".git").is_dir()

    branch = subprocess.run(
        ["git", "-C", str(data_dir), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main"

    tracked = subprocess.run(
        ["git", "-C", str(data_dir), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "souls/bawtford.md" in tracked
    assert "README.md" in tracked
    assert "control_plane/secret.db" not in tracked


def test_editor_entrypoint_configures_git_and_scm():
    """Verify docker/editor/entrypoint.sh enables VS Code Git SCM and safe.directory /data."""
    syntax = subprocess.run(
        ["bash", "-n", str(EDITOR_ENTRYPOINT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    content = EDITOR_ENTRYPOINT.read_text(encoding="utf-8")
    assert 'd["git.enabled"] = True' in content
    assert 'd["git.path"] = "/usr/bin/git"' in content
    assert 'd["git.autofetch"] = True' in content
    assert 'd["git.confirmSync"] = False' in content
    assert 'd["git.enableSmartCommit"] = True' in content
    assert 'd["scm.alwaysShowRepositories"] = True' in content
    assert "git config --global --add safe.directory /data" in content
    assert "git config --global init.defaultBranch main" in content
