"""Lightweight OpenBao KV v2 client for host System API -> control secrets storage."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional

TOOL_SECRET_KEYS = (
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "GITHUB_TOKEN",
)
DUMMY_PLACEHOLDER = "in-transit-openbao-managed"
DEFAULT_CONTAINER = "brainsos-control-secrets"
DEFAULT_MOUNT_PATH = "secret/data/tools"
DEFAULT_SEAL_PATH = "/etc/brainsos/openbao-seal.json"
DEFAULT_WRITER_TOKEN_PATH = "/etc/brainsos/openbao-system-api.token"


def _resolve_abs(base: str, raw: str) -> str:
    expanded = os.path.expanduser(raw.strip())
    return os.path.abspath(expanded) if os.path.isabs(expanded) else os.path.abspath(os.path.join(base, expanded))


def _resolve_data_roots(repo_root: str, file_env: Mapping[str, str]) -> tuple[str, ...]:
    roots = []
    raw_data = (file_env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")).strip()
    data_abs = _resolve_abs(repo_root, raw_data)
    roots.append(data_abs)
    for key in ("BRAINSOS_CONTROL_PLANE_DIR", "BRAINSOS_OPENBAO_DATA_DIR"):
        raw = (file_env.get(key) or "").strip()
        if raw:
            roots.append(_resolve_abs(repo_root, raw))
    return tuple(dict.fromkeys(os.path.realpath(r) for r in roots))


def _is_inside_data_dir(candidate_path: str, data_roots: tuple[str, ...]) -> bool:
    cand_real = os.path.realpath(os.path.expanduser(candidate_path))
    for root in data_roots:
        try:
            if os.path.commonpath([cand_real, root]) == root:
                return True
        except ValueError:
            continue
    return False


def _resolve_control_openbao_dir(repo_root: str, file_env: Mapping[str, str]) -> str:
    explicit = (file_env.get("BRAINSOS_OPENBAO_DATA_DIR") or "").strip()
    if explicit:
        return _resolve_abs(repo_root, explicit)
    ctrl = (file_env.get("BRAINSOS_CONTROL_PLANE_DIR") or "").strip()
    if ctrl:
        return os.path.join(_resolve_abs(repo_root, ctrl), "openbao")
    data_dir = (file_env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")).strip()
    return os.path.join(_resolve_abs(repo_root, data_dir), "control_plane", "openbao")


def _resolve_openbao_ca_file(repo_root: str, file_env: Mapping[str, str]) -> str:
    for key in ("OPENBAO_CACERT", "BAO_CACERT", "OPENBAO_CA_FILE"):
        val = (file_env.get(key) or "").strip()
        if val:
            return _resolve_abs(repo_root, val)
    tls_dir = (file_env.get("BRAINSOS_OPENBAO_TLS_DIR") or "").strip()
    if tls_dir:
        return os.path.join(_resolve_abs(repo_root, tls_dir), "ca.crt")
    ctrl = (file_env.get("BRAINSOS_CONTROL_PLANE_DIR") or "").strip()
    if ctrl:
        return os.path.join(_resolve_abs(repo_root, ctrl), "openbao_tls", "ca.crt")
    data_dir = (file_env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")).strip()
    return os.path.join(_resolve_abs(repo_root, data_dir), "control_plane", "openbao_tls", "ca.crt")


def _build_ssl_context(repo_root: str, file_env: Mapping[str, str]) -> ssl.SSLContext:
    ca_file = _resolve_openbao_ca_file(repo_root, file_env)
    if ca_file and os.path.isfile(ca_file) and os.path.getsize(ca_file) > 0:
        return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()


def _load_external_token(repo_root: str, file_env: Mapping[str, str]) -> str:
    data_roots = _resolve_data_roots(repo_root, file_env)
    home_cfg = os.path.join(os.path.expanduser("~"), ".config", "brainsos")

    token_candidates = []
    explicit_tok = (file_env.get("BRAINSOS_OPENBAO_WRITER_TOKEN_FILE") or "").strip()
    if explicit_tok:
        token_candidates.append(_resolve_abs(repo_root, explicit_tok))
    else:
        token_candidates.extend(
            [
                DEFAULT_WRITER_TOKEN_PATH,
                os.path.join(home_cfg, "openbao-system-api.token"),
            ]
        )

    for tok_path in token_candidates:
        if _is_inside_data_dir(tok_path, data_roots):
            continue
        if os.path.isfile(tok_path):
            try:
                with open(tok_path, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    return tok
            except OSError:
                continue

    seal_candidates = []
    explicit_seal = (file_env.get("BRAINSOS_OPENBAO_SEAL_FILE") or "").strip()
    if explicit_seal:
        seal_candidates.append(_resolve_abs(repo_root, explicit_seal))
    else:
        seal_candidates.extend(
            [
                DEFAULT_SEAL_PATH,
                os.path.join(home_cfg, "openbao-seal.json"),
            ]
        )

    for seal_path in seal_candidates:
        if _is_inside_data_dir(seal_path, data_roots):
            continue
        if os.path.isfile(seal_path):
            try:
                with open(seal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tok = str(data.get("root_token") or "").strip()
                if tok:
                    return tok
            except Exception:
                continue
    return ""


def _http_get_kv(
    addr: str,
    token: str,
    mount_path: str = DEFAULT_MOUNT_PATH,
    *,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Dict[str, str]:
    url = f"{addr.rstrip('/')}/v1/{mount_path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": token}, method="GET")
    open_kwargs: Dict[str, Any] = {"timeout": 3.0}
    if url.lower().startswith("https://") and ssl_context is not None:
        open_kwargs["context"] = ssl_context
    try:
        with urllib.request.urlopen(req, **open_kwargs) as resp:
            if getattr(resp, "status", 200) != 200:
                return {}
            body = json.loads(resp.read().decode("utf-8"))
            raw = body.get("data", {}).get("data", {})
            return {str(k): str(v) for k, v in raw.items() if v is not None} if isinstance(raw, dict) else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise


def _http_put_kv(
    addr: str,
    token: str,
    merged: Mapping[str, str],
    mount_path: str = DEFAULT_MOUNT_PATH,
    *,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> None:
    url = f"{addr.rstrip('/')}/v1/{mount_path.lstrip('/')}"
    payload = json.dumps({"data": dict(merged)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
        method="POST",
    )
    open_kwargs: Dict[str, Any] = {"timeout": 3.0}
    if url.lower().startswith("https://") and ssl_context is not None:
        open_kwargs["context"] = ssl_context
    with urllib.request.urlopen(req, **open_kwargs) as resp:
        if getattr(resp, "status", 200) not in (200, 204):
            raise RuntimeError(f"OpenBao HTTP {resp.status} storing secrets")


def _discover_container_https_addr(container: str) -> str:
    try:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                container,
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            for tok in proc.stdout.strip().split():
                ip = tok.strip()
                if ip:
                    return f"https://{ip}:8200"
    except Exception:
        pass
    return ""


def put_tool_secrets(
    repo_root: str,
    updates: Mapping[str, str],
    *,
    file_env: Optional[Mapping[str, str]] = None,
    openbao_addr: Optional[str] = None,
    openbao_token: Optional[str] = None,
) -> bool:
    """Persist third-party tool secrets into segregated OpenBao KV v2 (`secret/data/tools`).

    Returns True when stored in OpenBao, False when OpenBao is disabled or unavailable.
    """
    filtered = {k: v for k, v in updates.items() if k in TOOL_SECRET_KEYS}
    if not filtered:
        return False

    env_map: Dict[str, str] = dict(os.environ)
    if file_env:
        env_map.update({k: v for k, v in file_env.items() if v != ""})

    addr = (openbao_addr or env_map.get("OPENBAO_ADDR") or "").strip()
    token = (openbao_token or env_map.get("OPENBAO_TOKEN") or _load_external_token(repo_root, env_map)).strip()
    if not token:
        return False

    ssl_ctx = _build_ssl_context(repo_root, env_map)

    if addr:
        existing = _http_get_kv(addr, token, ssl_context=ssl_ctx)
        merged = {**existing}
        for k, v in filtered.items():
            if v:
                merged[k] = v
            else:
                merged.pop(k, None)
        _http_put_kv(addr, token, merged, ssl_context=ssl_ctx)
        return True

    if env_map.get("BRAINSOS_STAGE") == "test":
        return False

    container = (env_map.get("BRAINSOS_OPENBAO_CONTAINER") or DEFAULT_CONTAINER).strip()
    discovered_addr = _discover_container_https_addr(container)
    if discovered_addr:
        try:
            existing = _http_get_kv(discovered_addr, token, ssl_context=ssl_ctx)
            merged = {**existing}
            for k, v in filtered.items():
                if v:
                    merged[k] = v
                else:
                    merged.pop(k, None)
            _http_put_kv(discovered_addr, token, merged, ssl_context=ssl_ctx)
            return True
        except Exception:
            pass

    # Portable zero-host-port path (e.g. macOS Docker Desktop):
    # pass token and JSON strictly via stdin into a 077 .vault-token file (never via container env vars or exec -e).
    get_exec = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            (
                'umask 077; d=$(mktemp -d); trap "rm -rf \\"$d\\"" EXIT; '
                'IFS= read -r tok && printf "%s" "$tok" > "$d/.vault-token"; '
                'HOME="$d" BAO_ADDR=https://127.0.0.1:8200 BAO_CACERT=/openbao/tls/ca.crt '
                "bao kv get -format=json secret/tools"
            ),
        ],
        input=f"{token}\n",
        capture_output=True,
        text=True,
        timeout=5,
    )
    existing = {}
    if get_exec.returncode == 0 and get_exec.stdout.strip():
        try:
            parsed = json.loads(get_exec.stdout)
            raw = parsed.get("data", {}).get("data", {})
            if isinstance(raw, dict):
                existing = {str(k): str(v) for k, v in raw.items() if v is not None}
        except Exception:
            existing = {}

    merged = {**existing}
    for k, v in filtered.items():
        if v:
            merged[k] = v
        else:
            merged.pop(k, None)

    put_exec = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            (
                'umask 077; d=$(mktemp -d); trap "rm -rf \\"$d\\"" EXIT; '
                'IFS= read -r tok && printf "%s" "$tok" > "$d/.vault-token"; '
                'HOME="$d" BAO_ADDR=https://127.0.0.1:8200 BAO_CACERT=/openbao/tls/ca.crt '
                "bao kv put secret/tools -"
            ),
        ],
        input=f"{token}\n{json.dumps(merged)}\n",
        capture_output=True,
        text=True,
        timeout=5,
    )
    return put_exec.returncode == 0
