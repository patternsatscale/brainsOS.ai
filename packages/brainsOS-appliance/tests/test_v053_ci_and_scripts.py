"""Unit and regression tests for M5 (#402, Features F22-F24): CI gates, heredocs, Cindy scripts, and host ops."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scan_unquoted_heredocs(script_paths: list[Path]) -> list[str]:
    header_re = re.compile(
        r"""(?:"?\$\{?PYTHON_BIN\}?"?|python3|python|node)\s+(?:-[A-Za-z0-9]*\s+)?<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1"""
    )
    violations: list[str] = []
    for sh in script_paths:
        lines = sh.read_text(encoding="utf-8", errors="ignore").splitlines()
        i = 0
        while i < len(lines):
            m = header_re.search(lines[i])
            if m:
                quote, tag = m.group(1), m.group(2)
                start = i + 1
                body = []
                i += 1
                while i < len(lines) and lines[i].strip() != tag:
                    body.append(lines[i])
                    i += 1
                if not quote and "$" in "\n".join(body):
                    disp = str(sh.relative_to(REPO_ROOT)) if sh.is_relative_to(REPO_ROOT) else str(sh)
                    violations.append(f"{disp}:{start} (<< {tag})")
            i += 1
    return violations


def test_all_scripts_have_no_unquoted_python_heredocs_or_c_interpolation():
    """F22: All shell scripts under scripts/ and packages/brainsOS-appliance/ quote Python/Node heredocs."""
    sh_files = sorted(
        list((REPO_ROOT / "scripts").rglob("*.sh"))
        + list((REPO_ROOT / "packages" / "brainsOS-appliance").rglob("*.sh"))
    )
    assert sh_files
    assert _scan_unquoted_heredocs(sh_files) == []

    # Verify hardened scripts have zero ${...} variable interpolation inside python3 -c "..."
    for rel in [
        "scripts/setup/setup-langfuse.sh",
        "scripts/setup/setup-lens.sh",
        "scripts/control/prune-logs.sh",
        "scripts/control/update.sh",
        "packages/brainsOS-appliance/scripts/harden-host.sh",
        "packages/brainsOS-appliance/scripts/firstboot.sh",
        "scripts/verify/verify-appliance-ingress.sh",
        "scripts/verify/verify-agent-telemetry.sh",
        "scripts/verify/verify-email-agent-loop.sh",
        "scripts/verify/verify-hermes.sh",
        "scripts/verify/verify-memories.sh",
        "scripts/verify/verify-prune-logs.sh",
        "scripts/verify/verify-tool-egress-proxy.sh",
        "scripts/apps/cindypawford/verify-cindy-agent.sh",
    ]:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        # Look for python3 -c "..." containing ${...}
        for m in re.finditer(r'(?:python3|"\$\{?(?:python_bin|PYTHON_BIN)\}?)"?\s+-c\s+"([^"]*)"', txt, re.DOTALL):
            assert "${" not in m.group(1), f"Interpolated python -c found in {rel}: {m.group(0)[:120]}"


def test_heredoc_gate_detects_synthetic_unquoted_violation(tmp_path: Path):
    """F22/F23: Verify the heredoc scanner catches unquoted heredocs with $ expansion."""
    bad_sh = tmp_path / "bad.sh"
    bad_sh.write_text('python3 - << EOF\nx = "${USER}"\nEOF\n', encoding="utf-8")
    good_sh = tmp_path / "good.sh"
    good_sh.write_text('python3 - << \'EOF\'\nimport os\nx = os.environ["USER"]\nEOF\n', encoding="utf-8")

    assert len(_scan_unquoted_heredocs([bad_sh])) == 1
    assert _scan_unquoted_heredocs([good_sh]) == []


def test_pre_commit_rule6_python_gate_fails_closed():
    """F23: Verify pre-commit.yml Rule-6 Python logic passes on valid compose JSON and fails closed on violations."""
    pre_commit_txt = (REPO_ROOT / ".github" / "workflows" / "pre-commit.yml").read_text(encoding="utf-8")
    assert "data/agents/" in pre_commit_txt
    assert "brainsos-(control-|infra-)?litellm-db" in pre_commit_txt
    assert "Reject Unquoted Python Heredocs with Shell Expansion" in pre_commit_txt

    # Extract the Rule-6 Python snippet from pre-commit.yml
    m = re.search(r'COMPOSE_JSON="\$\{COMPOSE_JSON\}" python3 - << \'PYEOF\'\n(.*?)\n\s+PYEOF', pre_commit_txt, re.DOTALL)
    assert m, "Rule-6 Python block not found in pre-commit.yml"
    lines = m.group(1).splitlines()
    min_indent = min((len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip()), default=0)
    gate_code = "\n".join(ln[min_indent:] for ln in lines)

    def _run_gate(payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", gate_code],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )

    valid_payload = {
        "services": {
            "runner-hermes": {"container_name": "brainsos-agent-runner-hermes", "environment": {"BRAINSOS_AGENT_ID": "test"}},
            "litellm-db": {"container_name": "brainsos-control-litellm-db", "networks": {"brainsos-control-net": {}}, "ports": None},
        }
    }
    assert _run_gate(valid_payload).returncode == 0

    # Fail closed if no DB matches
    assert _run_gate({"services": {"runner-hermes": valid_payload["services"]["runner-hermes"]}}).returncode != 0
    # Fail closed if unexpected service name matches DB regex
    bad_name = {
        "services": {
            "runner-hermes": valid_payload["services"]["runner-hermes"],
            "rogue-db": {"container_name": "brainsos-control-litellm-db", "networks": {"brainsos-control-net": {}}},
        }
    }
    assert _run_gate(bad_name).returncode != 0
    # Fail closed if DB attaches to ingress/internal
    bad_net = {
        "services": {
            "runner-hermes": valid_payload["services"]["runner-hermes"],
            "litellm-db": {"container_name": "brainsos-control-litellm-db", "networks": {"brainsos-control-net": {}, "brainsos-internal-net": {}}},
        }
    }
    assert _run_gate(bad_net).returncode != 0
    # Fail closed if DB exposes host port
    bad_port = {
        "services": {
            "runner-hermes": valid_payload["services"]["runner-hermes"],
            "litellm-db": {"container_name": "brainsos-control-litellm-db", "networks": {"brainsos-control-net": {}}, "ports": [{"published": "5432"}]},
        }
    }
    assert _run_gate(bad_port).returncode != 0
    # Fail closed if agent service receives DATABASE_URL
    bad_env = {
        "services": {
            "runner-hermes": {"container_name": "brainsos-agent-runner-hermes", "environment": {"DATABASE_URL": "postgres://x"}},
            "litellm-db": valid_payload["services"]["litellm-db"],
        }
    }
    assert _run_gate(bad_env).returncode != 0


def test_deploy_workflows_oidc_choice_pins_and_symlinks():
    """F23: deploy-sst.yml and deploy-infra.yml enforce OIDC, SHA pinning, stage choices, and symlink checks."""
    sha_re = re.compile(r"@[0-9a-f]{40}$")
    workflow_files = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflow_files
    for wf_path in workflow_files:
        raw = wf_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            m = re.search(r"uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):
                assert sha_re.search(m.group(1)), f"Unpinned action in {wf_path.name}: {m.group(1)}"

    for wf_rel, expected_opts in (
        (".github/workflows/deploy-sst.yml", ["production", "staging"]),
        (".github/workflows/deploy-infra.yml", ["production", "staging", "dev"]),
    ):
        raw = (REPO_ROOT / wf_rel).read_text(encoding="utf-8")
        assert "AWS_ACCESS_KEY_ID" not in raw
        assert "AWS_SECRET_ACCESS_KEY" not in raw
        assert "role-to-assume" in raw
        data = yaml.safe_load(raw)
        on_section = data.get("on", data.get(True, {}))
        stage_input = on_section["workflow_dispatch"]["inputs"]["stage"]
        assert stage_input["type"] == "choice"
        assert stage_input["options"] == expected_opts

    sst_raw = (REPO_ROOT / ".github/workflows/deploy-sst.yml").read_text(encoding="utf-8")
    assert "-type l" in sst_raw
    assert sst_raw.index("-type l") < sst_raw.index("build-archive-portal.py")


def test_preview_server_import_safe_and_blocks_escapes(tmp_path: Path, monkeypatch):
    """F23: preview-server.py imports cleanly with non-numeric argv, binds 127.0.0.1, and blocks traversal/symlinks."""
    preview_path = REPO_ROOT / "scripts" / "apps" / "cindypawford" / "preview-server.py"
    help_proc = subprocess.run([sys.executable, str(preview_path), "--help"], capture_output=True, text=True, check=False)
    assert help_proc.returncode == 0, help_proc.stderr

    monkeypatch.setattr(sys, "argv", ["pytest", "not-a-port"])
    mod = _load_module("preview_server_m5", preview_path)

    src_txt = preview_path.read_text(encoding="utf-8")
    assert '"0.0.0.0"' not in src_txt
    assert '"127.0.0.1"' in src_txt
    assert "super().translate_path" in src_txt

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP_SECRET", encoding="utf-8")
    site = tmp_path / "site"
    archive = tmp_path / "archive"
    info = tmp_path / "info"
    for d in (site, archive, info):
        d.mkdir()
    (site / "index.html").write_text("ok", encoding="utf-8")
    (site / "leak.txt").symlink_to(secret)

    mod.SITE_DIR = str(site)
    mod.ARCHIVE_DIR = str(archive)
    mod.INFO_DIR = str(info)

    handler = mod.CindyPreviewHandler.__new__(mod.CindyPreviewHandler)
    assert Path(handler.translate_path("/index.html")).resolve() == (site / "index.html").resolve()
    for bad in ("/../secret.txt", "/%2e%2e/secret.txt", "//secret.txt", "/archive/../../secret.txt", "/info/%2e%2e/%2e%2e/secret.txt", "/leak.txt"):
        assert Path(handler.translate_path(bad)).resolve() != secret.resolve()

    for bad_null, expected_root in (
        ("/index.html%00.txt", site),
        ("/index.html%2500.txt", site),
        ("/archive/foo%00bar", archive),
        ("/info/foo%2500bar", info),
    ):
        assert Path(handler.translate_path(bad_null)) == expected_root.resolve() / "__forbidden__"


def test_cindy_web_builder_blocks_traversal_symlinks_and_git(tmp_path: Path):
    """F23: cindy-web-builder.py rejects .., absolute paths, symlinks, .git, and .github."""
    builder_path = REPO_ROOT / "scripts" / "apps" / "cindypawford" / "cindy-web-builder.py"
    mod = _load_module("cindy_web_builder_m5", builder_path)

    canvas = tmp_path / "canvas"
    canvas.mkdir()
    mem = tmp_path / "memories"
    mem.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("orig", encoding="utf-8")
    (canvas / "sym.html").symlink_to(outside)

    for bad_target in ("../outside.html", "/etc/passwd", ".git/config", ".GIT/HEAD", ".github/workflows/evil.yml", "sym.html"):
        res = mod.execute_build(
            feature_name="Test Reject",
            specification="Should reject unsafe path",
            target_files=[bad_target],
            canvas_dir=str(canvas),
            memory_dir=str(mem),
            mock_files={bad_target: "pwned"},
        )
        assert res["status"] == "error", f"Did not reject {bad_target}"
        assert outside.read_text(encoding="utf-8") == "orig"

    ok_res = mod.execute_build(
        feature_name="Valid Feature",
        specification="Update index.html",
        target_files=["index.html"],
        canvas_dir=str(canvas),
        memory_dir=str(mem),
        mock_files={"index.html": "<!DOCTYPE html><html><body>ok</body></html>"},
    )
    assert ok_res["status"] == "success"
    assert (canvas / "index.html").is_file()


def test_republish_archives_blocks_git_github_and_symlinks(tmp_path: Path):
    """F23: republish-archives.sh refuses git archive trees containing .github, .git, or symlinks."""
    republish_sh = REPO_ROOT / "scripts" / "apps" / "cindypawford" / "republish-archives.sh"
    data_dir = tmp_path / "data"
    site_dir = data_dir / "agents" / "bawtford" / "apps" / "cindypawford" / "site"
    archive_dir = data_dir / "agents" / "bawtford" / "apps" / "cindypawford" / "archive"
    site_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    subprocess.run(["git", "-C", str(site_dir), "init", "--quiet", "--initial-branch=main"], check=True)
    (site_dir / "index.html").write_text("<h1>hello</h1>\n", encoding="utf-8")
    (site_dir / ".github" / "workflows").mkdir(parents=True)
    (site_dir / ".github" / "workflows" / "evil.yml").write_text("name: evil\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(site_dir), "add", "-f", "index.html", ".github/workflows/evil.yml"], check=True)
    subprocess.run(
        ["git", "-C", str(site_dir), "-c", "user.email=t@t.local", "-c", "user.name=t", "commit", "--quiet", "-m", "init"],
        check=True,
    )
    subprocess.run(["git", "-C", str(site_dir), "tag", "archive/cindy-2026-w01"], check=True)

    env = {**os.environ, "BRAINSOS_DATA_DIR": str(data_dir)}
    proc = subprocess.run(["bash", str(republish_sh)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert not (archive_dir / "2026-w01" / ".github").exists()


def test_build_archive_portal_escapes_all_fields_and_filters_urls():
    """F23: build-archive-portal.py escapes attributes with quote=True and blocks javascript:/data: URLs."""
    portal_path = REPO_ROOT / "scripts" / "apps" / "cindypawford" / "build-archive-portal.py"
    mod = _load_module("build_archive_portal_m5", portal_path)

    rendered = mod.render_timeline_entry(
        {
            "category": 'x" onclick="alert(1)',
            "title": "<script>alert(2)</script>",
            "description": "<img src=x onerror=alert(3)>",
            "pr_number": '1"><script>alert(4)</script>',
            "proposal": {"bars": [{"pct": "999;position:fixed", "color": 'red" onclick="alert(5)'}]},
        }
    )
    assert 'onclick="alert' not in rendered
    assert "<script>" not in rendered
    assert "<img " not in rendered

    tile = mod.render_era_tile(
        {
            "era": "not-an-int",
            "slug": 'bad" onclick="alert(6)',
            "emblem": "javascript:alert(7)",
            "era_url": 'javascript:alert(8)" onmouseover="alert(9)',
        }
    )
    assert "javascript:" not in tile
    assert 'onclick="alert' not in tile
    assert 'onmouseover="alert' not in tile

    board = mod.render_scoreboard(
        [{"era": 1, "slug": "../../etc", "era_url": "data:text/html,<script>alert(10)</script>"}],
        [{"title": "<svg onload=alert(11)>", "pr_number": '7"><script>alert(12)</script>'}],
    )
    assert "data:text/html" not in board
    assert "<svg" not in board
    assert "<script>" not in board

    for bad_rel in ("\\\\evil.com", "/\\evil.com", "\\/evil.com", "//evil.com"):
        assert mod.sanitize_url(bad_rel, allow_relative=True, fallback="#") == "#"
    assert mod.sanitize_url("./2024-genesis/index.html", allow_relative=True, fallback="#") == "./2024-genesis/index.html"

    unicode_entry = mod.render_timeline_entry({"title": "Unicode PR", "pr_number": "٣"})
    assert "PR #" not in unicode_entry
    unicode_board = mod.render_scoreboard([], [{"title": "Unicode PR", "pr_number": "٢"}])
    assert "PR #" not in unicode_board


def test_setup_host_quotes_forwarded_args_and_preserves_pull_model(tmp_path: Path):
    """F22: setup-host.sh forwards 0/1/N args via a single sg -c string without truncation or injection."""
    sh_path = REPO_ROOT / "scripts" / "setup" / "setup-host.sh"
    sh_txt = sh_path.read_text(encoding="utf-8")
    assert "@Q}" in sh_txt
    assert "${@@Q}" not in sh_txt, "Multi-word ${@@Q} inside double quotes causes sg -c to drop $2+"
    assert "printf '%q '" in sh_txt
    assert "shift" not in sh_txt.split("done", 1)[0]

    lines = sh_txt.splitlines()
    idx_0c = next(i for i, line in enumerate(lines) if "# 0C. Port Conflict Precheck" in line)
    head_txt = "\n".join(lines[:idx_0c])

    scratch = tmp_path / "repo with space"
    (scratch / "scripts" / "setup").mkdir(parents=True)
    (scratch / ".git").mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (fake_bin / "getent").write_text('#!/usr/bin/env bash\necho "docker:x:999:$(id -un)"\n', encoding="utf-8")

    sg_log = tmp_path / "sg_cmd.txt"
    (fake_bin / "sg").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$#" -ne 3 ] || [ "$2" != "-c" ]; then\n'
        '  echo "sg requires exactly 3 args (<group> -c <cmd>), got $#: $*" >&2\n'
        "  exit 99\n"
        "fi\n"
        f'printf "%s\\n" "$3" > "{sg_log}"\n'
        'exec /bin/sh -c "$3"\n',
        encoding="utf-8",
    )
    for f in fake_bin.iterdir():
        f.chmod(0o755)

    argv_log = tmp_path / "reexec_argv.json"
    epilogue = (
        "\nexport PULL_MODEL\n"
        f"'{sys.executable}' -c "
        '\'import json, os, sys; open(sys.argv[1], "w").write('
        'json.dumps({"pull_model": os.environ["PULL_MODEL"], "argv": sys.argv[2:]}))\' '
        f'"{argv_log}" "$@"\n'
    )

    probe = tmp_path / "pwned"
    cases = [
        ([], "false"),
        ([""], "false"),
        (["--pull-model"], "true"),
        (["arg with space", f"; touch {probe}", "--pull-model"], "true"),
        (["--pull-model", "", "arg with space", "it's", 'say "hi"', "$HOME", f"$(touch {probe})"], "true"),
    ]

    for variant, body in [
        ("bash4_at_q", head_txt + epilogue),
        ("bash32_printf_q", head_txt.replace("BASH_VERSINFO", "FAKE_BASH_VERSINFO") + epilogue),
    ]:
        sh_copy = scratch / "scripts" / "setup" / "setup-host.sh"
        sh_copy.write_text(body, encoding="utf-8")
        sh_copy.chmod(0o755)
        for args, expected_pull in cases:
            sg_log.unlink(missing_ok=True)
            argv_log.unlink(missing_ok=True)
            env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
            env.pop("BRAINSOS_DOCKER_REEXEC", None)
            proc = subprocess.run(
                ["bash", str(sh_copy), *args],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"{variant} failed for {args}: rc={proc.returncode} {proc.stderr}"
            assert not probe.exists(), f"Command injection executed via sg re-exec ({variant})!"
            assert sg_log.is_file(), f"sg wrapper was not invoked ({variant}); stderr={proc.stderr}"
            recorded = json.loads(argv_log.read_text(encoding="utf-8"))
            assert recorded["argv"] == args, f"{variant} argv truncated/corrupted: {recorded['argv']} != {args}"
            assert recorded["pull_model"] == expected_pull, f"{variant} PULL_MODEL mismatch: {recorded}"


def test_show_urls_named_temp_file_0600_and_destroy_cleans_env_bak(tmp_path: Path):
    """F24: show-urls.sh uses NamedTemporaryFile(0o600) without os.system; destroy.sh removes .env and .env.bak."""
    show_urls_txt = (REPO_ROOT / "scripts" / "control" / "show-urls.sh").read_text(encoding="utf-8")
    assert "/tmp/hosts.brainsos.new" not in show_urls_txt
    assert "os.system(" not in show_urls_txt
    assert "NamedTemporaryFile" in show_urls_txt
    assert "0o600" in show_urls_txt

    destroy_sh = REPO_ROOT / "scripts" / "control" / "destroy.sh"
    scratch = tmp_path / "repo"
    (scratch / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(destroy_sh, scratch / "scripts" / "control" / "destroy.sh")
    (scratch / ".env").write_text("SECRET=abc\n", encoding="utf-8")
    (scratch / ".env.bak").write_text("OLD_SECRET=xyz\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ("docker", "pkill", "git"):
        p = fake_bin / tool
        p.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        p.chmod(0o755)

    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        ["bash", str(scratch / "scripts" / "control" / "destroy.sh"), "--force"],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (scratch / ".env").exists()
    assert not (scratch / ".env.bak").exists()


def test_setup_wildcard_ssl_and_setup_git_and_langfuse_compose():
    """F22/F24: setup-wildcard-ssl.sh uses env-upsert.sh, setup-git.sh omits a+rwX, langfuse MinIO binds 127.0.0.1."""
    ssl_txt = (REPO_ROOT / "scripts" / "setup" / "setup-wildcard-ssl.sh").read_text(encoding="utf-8")
    assert "PYEOF" not in ssl_txt
    assert "env-upsert.sh" in ssl_txt

    git_txt = (REPO_ROOT / "scripts" / "setup" / "setup-git.sh").read_text(encoding="utf-8")
    assert "a+rwX" not in git_txt

    lf = yaml.safe_load((REPO_ROOT / "docker" / "langfuse" / "docker-compose.yml").read_text(encoding="utf-8"))
    for svc_name, svc in (lf.get("services") or {}).items():
        for p in svc.get("ports") or []:
            assert str(p).startswith("127.0.0.1:"), f"Non-loopback port in langfuse {svc_name}: {p}"


def test_provision_sh_pins_uv_sha256_and_scrubs_admin_history():
    """F24: provision.sh pins uv with SHA-256 checksums, retains uv removal, and scrubs /home/admin histories."""
    prov_txt = (REPO_ROOT / "packages" / "brainsOS-appliance" / "packer" / "provision.sh").read_text(encoding="utf-8")
    assert "astral.sh/uv/install.sh" not in prov_txt
    assert "uv self update" not in prov_txt
    assert "UV_VERSION=" in prov_txt
    assert re.search(r"\b[0-9a-f]{64}\b", prov_txt)
    assert "sha256sum -c" in prov_txt
    assert "rm -f /usr/local/bin/uv /usr/local/bin/uvx" in prov_txt
    assert "/home/admin/.*history" in prov_txt
    assert ".python_history" in prov_txt
    assert prov_txt.find("/home/admin/.*history") < prov_txt.rfind("snapshot_scan")


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--zone", "ok\nINJECT=1"],
        ["--zone", "ok\rINJECT=1"],
        ["--zone", "bad domain.com"],
        ["--zone", "brainsos.ai", "--prefix", "bad\nprefix"],
    ],
)
def test_setup_wildcard_ssl_rejects_control_chars_and_whitespace_upfront(tmp_path: Path, extra_args: list[str]):
    """F22: setup-wildcard-ssl.sh rejects newline/CR/whitespace in ZONE_NAME/APPLIANCE_PREFIX before Step 3/4."""
    scratch = tmp_path / "repo"
    (scratch / "scripts" / "setup").mkdir(parents=True)
    (scratch / "scripts" / "control").mkdir(parents=True)
    ssl_sh = scratch / "scripts" / "setup" / "setup-wildcard-ssl.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "setup" / "setup-wildcard-ssl.sh", ssl_sh)
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "env-upsert.sh", scratch / "scripts" / "control" / "env-upsert.sh")
    reload_marker = tmp_path / "reload_called"
    reload_sh = scratch / "scripts" / "control" / "reload-env.sh"
    reload_sh.write_text(f"#!/usr/bin/env bash\ntouch '{reload_marker}'\n", encoding="utf-8")
    reload_sh.chmod(0o755)
    env_file = scratch / ".env"
    env_file.write_text("BRAINSOS_STAGE=osx\n", encoding="utf-8")
    env_file.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)

    env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"}
    proc = subprocess.run(
        ["bash", str(ssl_sh), "--non-interactive", "--method", "direct", *extra_args],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert not reload_marker.exists()
    assert "INJECT" not in env_file.read_text(encoding="utf-8")


def test_generate_env_uses_mkstemp_0600_and_preserves_backup(tmp_path: Path):
    """F22/F24: generate-env.sh uses tempfile.mkstemp(0o600) + os.replace and backs up prior .env."""
    gen_src = REPO_ROOT / "scripts" / "control" / "generate-env.sh"
    txt = gen_src.read_text(encoding="utf-8")
    assert 'f"{target_path}.tmp"' not in txt
    assert "${REAL_ENV_FILE}.tmp" not in txt
    assert "tempfile.mkstemp" in txt
    assert "0o600" in txt
    assert "os.replace(temp_file, target_path)" in txt

    scratch = tmp_path / "repo"
    (scratch / "scripts" / "control").mkdir(parents=True)
    gen_dst = scratch / "scripts" / "control" / "generate-env.sh"
    shutil.copy2(gen_src, gen_dst)
    gen_dst.chmod(0o755)
    shutil.copy2(REPO_ROOT / ".env.example", scratch / ".env.example")

    env_file = scratch / ".env"
    env_file.write_text("BRAINSOS_DOMAIN=old.local\nCUSTOM_KEEP=before_regen\n", encoding="utf-8")
    env_file.chmod(0o600)

    proc = subprocess.run(
        ["bash", str(gen_dst), "--non-interactive", "--no-rebuild", "--domain", "new.local"],
        cwd=scratch,
        env={**os.environ, "BRAINSOS_REPO_ROOT": str(scratch), "BRAINSOS_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    new_txt = env_file.read_text(encoding="utf-8")
    assert "BRAINSOS_DOMAIN=new.local" in new_txt
    assert "CUSTOM_KEEP=before_regen" in new_txt

    bak_file = scratch / ".env.bak"
    assert bak_file.is_file()
    assert stat.S_IMODE(bak_file.stat().st_mode) == 0o600
    assert "BRAINSOS_DOMAIN=old.local" in bak_file.read_text(encoding="utf-8")
    ts_baks = list(scratch.glob(".env.bak-*"))
    assert len(ts_baks) == 1
    assert stat.S_IMODE(ts_baks[0].stat().st_mode) == 0o600
    assert not list(scratch.glob(".env.tmp*"))


def test_process_cindy_reset_rejects_dot_and_git_week_slugs(tmp_path: Path):
    """F23: process-cindy-reset.sh rejects '.', '.git', '.github' (case-insensitive) and '..' in --week-slug."""
    scratch = tmp_path / "repo"
    script_dst = scratch / "scripts" / "apps" / "cindypawford" / "process-cindy-reset.sh"
    script_dst.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "apps" / "cindypawford" / "process-cindy-reset.sh", script_dst)
    (scratch / "config").mkdir()
    (scratch / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")

    archive_dir = scratch / "data" / "agents" / "bawtford" / "apps" / "cindypawford" / "archive"
    archive_dir.mkdir(parents=True)
    sentinel = archive_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    for bad_slug in (".", ".git", ".GIT", ".github", ".GitHub", "../escape", "2026..w01"):
        proc = subprocess.run(
            ["bash", str(script_dst), "--force", "--week-slug", bad_slug],
            cwd=scratch,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, f"Expected rejection for --week-slug {bad_slug!r}"
        assert "Invalid week slug" in proc.stderr
        assert sentinel.exists()
