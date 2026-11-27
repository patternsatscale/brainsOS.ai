"""Lightweight OpenBao KV v2 client for host System API -> control secrets storage."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Dict, Mapping, Optional

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


def _resolve_control_openbao_dir(repo_root: str, file_env: Mapping[str, str]) -> str:
    explicit = (file_env.get("BRAINSOS_OPENBAO_DATA_DIR") or "").strip()
    if explicit:
        return explicit if os.path.isabs(explicit) else os.path.abspath(os.path.join(repo_root, explicit))
    ctrl = (file_env.get("BRAINSOS_CONTROL_PLANE_DIR") or "").strip()
    if ctrl:
        base = ctrl if os.path.isabs(ctrl) else os.path.abspath(os.path.join(repo_root, ctrl))
        return os.path.join(base, "openbao")
    data_dir = (file_env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")).strip()
    if not os.path.isabs(data_dir):
        data_dir = os.path.abspath(os.path.join(repo_root, data_dir))
    return os.path.join(data_dir, "control_plane", "openbao")


def _load_root_token(openbao_dir: str) -> str:
    seal_path = os.path.join(openbao_dir, ".seal.json")
    if not os.path.isfile(seal_path):
        return ""
    try:
        with open(seal_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("root_token") or "").strip()
    except Exception:
        return ""


def _http_get_kv(addr: str, token: str, mount_path: str = DEFAULT_MOUNT_PATH) -> Dict[str, str]:
    url = f"{addr.rstrip('/')}/v1/{mount_path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": token}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if getattr(resp, "status", 200) != 200:
                return {}
            body = json.loads(resp.read().decode("utf-8"))
            raw = body.get("data", {}).get("data", {})
            return {str(k): str(v) for k, v in raw.items() if v is not None} if isinstance(raw, dict) else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise


def _http_put_kv(addr: str, token: str, merged: Mapping[str, str], mount_path: str = DEFAULT_MOUNT_PATH) -> None:
    url = f"{addr.rstrip('/')}/v1/{mount_path.lstrip('/')}"
    payload = json.dumps({"data": dict(merged)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        if getattr(resp, "status", 200) not in (200, 204):
            raise RuntimeError(f"OpenBao HTTP {resp.status} storing secrets")


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
    bao_dir = _resolve_control_openbao_dir(repo_root, env_map)
    token = (openbao_token or env_map.get("OPENBAO_TOKEN") or _load_root_token(bao_dir)).strip()

    if addr and token:
        existing = _http_get_kv(addr, token)
        merged = {**existing}
        for k, v in filtered.items():
            if v:
                merged[k] = v
            else:
                merged.pop(k, None)
        _http_put_kv(addr, token, merged)
        return True

    if env_map.get("BRAINSOS_STAGE") == "test" or not token:
        return False

    # Portable zero-host-port path across macOS Docker Desktop & Linux hosts:
    # invoke bao CLI inside the running container with secret JSON over stdin.
    container = (env_map.get("BRAINSOS_OPENBAO_CONTAINER") or DEFAULT_CONTAINER).strip()
    existing_exec = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "BAO_ADDR=http://127.0.0.1:8200",
            "-e",
            f"BAO_TOKEN={token}",
            container,
            "bao",
            "kv",
            "get",
            "-format=json",
            "secret/tools",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    existing = {}
    if existing_exec.returncode == 0 and existing_exec.stdout.strip():
        try:
            parsed = json.loads(existing_exec.stdout)
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
            "-e",
            "BAO_ADDR=http://127.0.0.1:8200",
            "-e",
            f"BAO_TOKEN={token}",
            container,
            "bao",
            "kv",
            "put",
            "secret/tools",
            "-",
        ],
        input=json.dumps(merged),
        capture_output=True,
        text=True,
        timeout=5,
    )
    return put_exec.returncode == 0
