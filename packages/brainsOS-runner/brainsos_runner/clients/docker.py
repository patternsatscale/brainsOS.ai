"""Ephemeral Docker Sandbox Runner Client for per-tenant isolated execution."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import yaml

from brainsos_runner.clients.base import RunnerClient
from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse

logger = logging.getLogger(__name__)

SAFE_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SAFE_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}$")
_SAFE_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SAFE_TENANT_KEY_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}_LITELLM_KEY$")
_FORBIDDEN_KEY_ENVS = frozenset(
    {
        "LITELLM_MASTER_KEY",
        "LANGFUSE_SECRET_KEY",
        "HERMES_LANGFUSE_SECRET_KEY",
        "LANGFUSE_OTEL_AUTH",
        "TOOL_EGRESS_PROXY_TOKENS",
        "TOOL_EGRESS_PROXY_SECRET",
    }
)


def _normalize_repo_slug(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.match(
        r"^(?:https?://github\.com/|git@github\.com:)([^/\s]+/[^/\s]+?)(?:\.git)?/?$",
        s,
        re.IGNORECASE,
    )
    if m:
        s = m.group(1)
    s = s.strip("/").lower()
    if s.endswith(".git"):
        s = s[:-4]
    return s.strip("/")


def _mint_proxy_token(
    tenant_id: str,
    secret: str,
    ttl_sec: int = 3600,
    allowed_repos: Optional[list[str]] = None,
) -> str:
    exp = int(time.time()) + max(60, ttl_sec)
    if allowed_repos is None:
        msg = f"{tenant_id}:{exp}".encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return f"v1.{tenant_id}.{exp}.{sig}"
    norm_repos = sorted({n for n in (_normalize_repo_slug(r) for r in allowed_repos) if n})
    payload = {"t": tenant_id, "exp": exp, "repos": norm_repos}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), f"v2.{payload_b64}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"v2.{payload_b64}.{sig}"


def _extract_tenant_proxy_token(
    tenant_id: str,
    allowed_repos: Optional[list[str]] = None,
) -> str:
    per_env = f"TOOL_EGRESS_PROXY_TOKEN_{tenant_id.upper().replace('-', '_')}"
    direct = os.getenv(per_env, "").strip()
    if direct:
        return direct

    raw_map = os.getenv("TOOL_EGRESS_PROXY_TOKENS", "").strip()
    if raw_map:
        for entry in re.split(r"[,;\s]+", raw_map):
            if not entry or ":" not in entry:
                continue
            t_id, tok = entry.split(":", 1)
            if t_id.strip() == tenant_id and tok.strip():
                return tok.strip()

    secret = os.getenv("TOOL_EGRESS_PROXY_SECRET", "").strip()
    if secret:
        return _mint_proxy_token(tenant_id, secret, allowed_repos=allowed_repos)

    return ""


def _strip_trailing_separators(raw_path: str) -> str:
    stripped = raw_path.rstrip("/\\")
    return stripped or raw_path


def _is_system_root_symlink(path: Path) -> bool:
    s = str(path)
    if s in ("/var", "/tmp", "/etc") and os.path.islink(s):
        return os.path.realpath(s) == f"/private{s}"
    return False


def _has_symlink_component(raw_path: str, *, anchor_roots: tuple[str, ...] = ()) -> bool:
    stripped = _strip_trailing_separators(raw_path)
    if os.path.islink(stripped):
        return True
    raw_abs = os.path.abspath(stripped)
    if os.path.islink(raw_abs):
        return True

    matched_anchor = False
    for anchor in anchor_roots:
        if not anchor:
            continue
        anchor_clean = _strip_trailing_separators(os.path.abspath(anchor))
        try:
            if os.path.commonpath([anchor_clean, raw_abs]) == anchor_clean:
                matched_anchor = True
                cur = Path(anchor_clean)
                for part in Path(raw_abs).relative_to(anchor_clean).parts:
                    cur = cur / part
                    if os.path.islink(cur):
                        return True
        except ValueError:
            continue

    if not matched_anchor:
        cur = Path(Path(raw_abs).anchor or "/")
        for part in Path(raw_abs).parts:
            if part == cur.anchor:
                continue
            cur = cur / part
            if os.path.islink(cur) and not _is_system_root_symlink(cur):
                return True
    return False


def _enforce_unconfigured_agent_path_boundary(
    stripped_path: str,
    real_path: str,
    clean_tenant: str,
    expected_leaf: str,
) -> None:
    for candidate in (os.path.abspath(stripped_path), real_path):
        parts = Path(candidate).parts
        for idx, part in enumerate(parts):
            low = part.lower()
            if low == "agents":
                if idx + 1 >= len(parts):
                    raise ValueError("Tenant containment violation: cannot mount agents root directory")
                path_tenant = parts[idx + 1]
                if not clean_tenant:
                    raise ValueError(
                        f"Tenant containment violation: tenant_id is required for agents path '{stripped_path}'"
                    )
                if path_tenant != clean_tenant:
                    raise ValueError(
                        f"Tenant containment violation: path '{stripped_path}' targets tenant "
                        f"'{path_tenant}' instead of '{clean_tenant}'"
                    )
                if idx + 2 >= len(parts) or parts[idx + 2] != expected_leaf:
                    raise ValueError(
                        f"Tenant containment violation: path '{stripped_path}' must reside under "
                        f"'agents/{clean_tenant}/{expected_leaf}'"
                    )
            elif low == "agent_workspaces" and expected_leaf == "workspace":
                if idx + 1 >= len(parts):
                    raise ValueError("Tenant containment violation: cannot mount agent_workspaces root directory")
                path_tenant = parts[idx + 1]
                if clean_tenant and path_tenant != clean_tenant:
                    raise ValueError(
                        f"Tenant containment violation: workspace '{stripped_path}' targets tenant "
                        f"'{path_tenant}' instead of '{clean_tenant}'"
                    )
            elif low == "agent_memories" and expected_leaf == "memories":
                if idx + 1 >= len(parts):
                    raise ValueError("Tenant containment violation: cannot mount agent_memories root directory")
                path_tenant = parts[idx + 1]
                if clean_tenant and path_tenant != clean_tenant:
                    raise ValueError(
                        f"Tenant containment violation: memory_dir '{stripped_path}' targets tenant "
                        f"'{path_tenant}' instead of '{clean_tenant}'"
                    )


def _resolve_trusted_agents_manifest() -> Optional[Path]:
    candidates: list[Path] = []
    settings_dir = os.getenv("BRAINSOS_SETTINGS_DIR", "").strip()
    if settings_dir:
        candidates.append(Path(settings_dir) / "agents.yaml")
    data_dir = os.getenv("BRAINSOS_DATA_DIR", "").strip()
    if data_dir:
        candidates.append(Path(data_dir) / "settings" / "agents.yaml")
    candidates.extend(
        [
            Path("data/settings/agents.yaml"),
            Path("config/default_settings/agents.yaml"),
            Path(__file__).resolve().parents[4] / "config" / "default_settings" / "agents.yaml",
        ]
    )
    for cand in candidates:
        try:
            if cand.is_file() and not cand.is_symlink():
                return cand
        except OSError:
            continue
    return None


def _load_trusted_agent_virtual_key_env(clean_tenant: str) -> str:
    manifest = _resolve_trusted_agents_manifest()
    if manifest is None:
        return ""
    try:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(doc, dict):
        return ""
    agents_raw = doc.get("agents")
    entries: list[dict[str, Any]] = []
    if isinstance(agents_raw, list):
        entries = [a for a in agents_raw if isinstance(a, dict)]
    elif isinstance(agents_raw, dict):
        for k, v in agents_raw.items():
            if isinstance(v, dict):
                entries.append({"id": k, **v})
    for entry in entries:
        if str(entry.get("id") or "").strip() == clean_tenant:
            routing = entry.get("routing")
            raw_key = entry.get("virtual_key_env") or (
                routing.get("virtual_key") if isinstance(routing, dict) else None
            )
            candidate = str(raw_key or "").strip()
            if (
                candidate
                and _SAFE_TENANT_KEY_ENV_RE.match(candidate)
                and candidate not in _FORBIDDEN_KEY_ENVS
            ):
                return candidate
            return ""
    return ""


def _parse_agent_response_payload(raw_text: str) -> Optional[AgentTurnResponse]:
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "run_id" in data and "status" in data:
            return AgentTurnResponse.model_validate(data)
    except Exception:
        return None
    return None


class EphemeralDockerRunnerClient(RunnerClient):
    """Client for launching isolated, on-demand per-tenant Docker runner containers."""

    def __init__(
        self,
        image: str,
        default_timeout_sec: int = 120,
        memory_limit: Optional[str] = "2g",
        cpu_limit: Optional[str] = "2.0",
        network: Optional[str] = "brainsos-internal-net",
        docker_cmd: str = "docker",
        command: Optional[list[str]] = None,
    ) -> None:
        self.image = image
        self.default_timeout_sec = default_timeout_sec
        self.memory_limit = memory_limit or "2g"
        self.cpu_limit = cpu_limit or "2.0"
        self.network = network or "brainsos-internal-net"
        self.docker_cmd = docker_cmd
        self.command = list(command) if command else None

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> str:
        clean = (tenant_id or "").strip()
        if not SAFE_TENANT_ID_RE.match(clean):
            raise ValueError(f"Tenant containment violation: invalid tenant_id '{tenant_id}'")
        return clean

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        clean = (run_id or "").strip()
        if not SAFE_RUN_ID_RE.match(clean) or ".." in clean:
            raise ValueError(f"Sandbox containment violation: invalid run_id '{run_id}'")
        return clean

    @staticmethod
    def _resolve_agents_root() -> str:
        agents_dir_env = os.getenv("BRAINSOS_AGENTS_DIR", "").strip()
        if agents_dir_env:
            return agents_dir_env
        data_dir_env = os.getenv("BRAINSOS_DATA_DIR", "").strip()
        if data_dir_env:
            return os.path.join(data_dir_env, "agents")
        return ""

    def _validate_workspace(self, workspace_dir: str, tenant_id: Optional[str] = None) -> Path:
        """Enforce Rule 1 (Memory Purity), Rule 4 (Host Sandboxing), and strict tenant containment."""
        raw_ws = str(workspace_dir or "").strip()
        if not raw_ws:
            raise ValueError("Workspace containment violation: workspace_dir cannot be empty")

        stripped_ws = _strip_trailing_separators(raw_ws)
        real_ws = os.path.realpath(stripped_ws)
        raw_lower = stripped_ws.lower()
        real_lower = real_ws.lower()

        # Inviolable Guardrail: Rule 4
        if "docker.sock" in raw_lower or "docker.sock" in real_lower:
            raise ValueError("Host sandboxing violation: Docker socket cannot be mounted into runner container")

        # Inviolable Guardrail: Rule 1
        raw_parts = [p.lower() for p in Path(stripped_ws).parts]
        real_parts = [p.lower() for p in Path(real_ws).parts]
        if any(p in ("memories", "agent_memories") for p in raw_parts + real_parts):
            raise ValueError("Memory purity violation: Agent /memories cannot be mounted into sandbox container")

        if ".." in Path(stripped_ws).parts:
            raise ValueError(f"Workspace containment violation: unsafe path '{workspace_dir}'")

        agents_root = self._resolve_agents_root()
        effective_tenant = (tenant_id if tenant_id is not None else os.getenv("BRAINSOS_AGENT_ID", "")).strip()

        if agents_root:
            if not effective_tenant:
                raise ValueError(
                    "Tenant containment violation: tenant_id is required when BRAINSOS_AGENTS_DIR or BRAINSOS_DATA_DIR is configured"
                )
            clean_tenant = self._validate_tenant_id(effective_tenant)
            agents_root_abs = _strip_trailing_separators(os.path.abspath(agents_root))
            agents_real = os.path.realpath(agents_root_abs)
            tenant_link = os.path.join(agents_real, clean_tenant)
            if os.path.islink(tenant_link):
                raise ValueError(f"Tenant containment violation: symlinked tenant root rejected ({tenant_link})")
            tenant_root = os.path.realpath(tenant_link)
            if os.path.commonpath([agents_real, tenant_root]) != agents_real or tenant_root == agents_real:
                raise ValueError(f"Tenant containment violation: invalid tenant root '{tenant_root}'")

            ws_link = os.path.join(tenant_root, "workspace")
            if os.path.islink(ws_link):
                raise ValueError(f"Tenant containment violation: symlinked workspace path rejected ({ws_link})")
            expected_ws = os.path.realpath(ws_link)

            if _has_symlink_component(raw_ws, anchor_roots=(agents_root_abs, agents_real, tenant_root)):
                raise ValueError(f"Tenant containment violation: symlinked workspace path rejected ({raw_ws})")
            if os.path.commonpath([expected_ws, real_ws]) != expected_ws:
                raise ValueError(
                    f"Tenant containment violation: workspace '{workspace_dir}' escapes '{expected_ws}'"
                )
            resolved = Path(real_ws)
            if not resolved.exists():
                resolved.mkdir(parents=True, exist_ok=True)
            return resolved

        # Unconfigured BRAINSOS_AGENTS_DIR / BRAINSOS_DATA_DIR mode
        clean_tenant = self._validate_tenant_id(effective_tenant) if effective_tenant else ""
        if _has_symlink_component(raw_ws):
            raise ValueError(f"Workspace containment violation: unsafe path '{workspace_dir}'")
        _enforce_unconfigured_agent_path_boundary(stripped_ws, real_ws, clean_tenant, "workspace")

        resolved = Path(real_ws)
        if not resolved.exists():
            resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _validate_memories(self, memory_dir: Optional[str], tenant_id: str) -> Optional[Path]:
        """Validate and resolve strictly per-tenant /memories mount path."""
        clean_tenant = self._validate_tenant_id(tenant_id)
        agents_root = self._resolve_agents_root()

        if memory_dir:
            raw_mem = str(memory_dir).strip()
            stripped_mem = _strip_trailing_separators(raw_mem)
            if "docker.sock" in stripped_mem.lower() or ".." in Path(stripped_mem).parts:
                raise ValueError(f"Tenant containment violation: unsafe memory_dir '{memory_dir}'")
            mem_real = os.path.realpath(stripped_mem)
            if "docker.sock" in mem_real.lower():
                raise ValueError(f"Tenant containment violation: unsafe memory_dir '{memory_dir}'")

            if agents_root:
                agents_root_abs = _strip_trailing_separators(os.path.abspath(agents_root))
                agents_real = os.path.realpath(agents_root_abs)
                tenant_link = os.path.join(agents_real, clean_tenant)
                if os.path.islink(tenant_link):
                    raise ValueError(f"Tenant containment violation: symlinked tenant root rejected ({tenant_link})")
                tenant_root = os.path.realpath(tenant_link)
                if os.path.commonpath([agents_real, tenant_root]) != agents_real or tenant_root == agents_real:
                    raise ValueError(f"Tenant containment violation: invalid tenant root '{tenant_root}'")

                mem_link = os.path.join(tenant_root, "memories")
                if os.path.islink(mem_link):
                    raise ValueError(f"Tenant containment violation: symlinked memories dir rejected ({mem_link})")
                expected_mem = os.path.realpath(mem_link)

                if _has_symlink_component(raw_mem, anchor_roots=(agents_root_abs, agents_real, tenant_root)):
                    raise ValueError(f"Tenant containment violation: symlinked memory_dir rejected ({raw_mem})")
                if os.path.commonpath([expected_mem, mem_real]) != expected_mem:
                    raise ValueError(
                        f"Tenant containment violation: memory_dir '{memory_dir}' escapes '{expected_mem}'"
                    )
            else:
                if _has_symlink_component(raw_mem):
                    raise ValueError(f"Tenant containment violation: symlinked memory_dir rejected ({raw_mem})")
                _enforce_unconfigured_agent_path_boundary(stripped_mem, mem_real, clean_tenant, "memories")

            Path(mem_real).mkdir(parents=True, exist_ok=True)
            return Path(mem_real)

        if agents_root:
            agents_root_abs = _strip_trailing_separators(os.path.abspath(agents_root))
            agents_real = os.path.realpath(agents_root_abs)
            tenant_link = os.path.join(agents_real, clean_tenant)
            if os.path.islink(tenant_link):
                raise ValueError(f"Tenant containment violation: symlinked tenant root rejected ({tenant_link})")
            tenant_root = os.path.realpath(tenant_link)
            if os.path.commonpath([agents_real, tenant_root]) != agents_real or tenant_root == agents_real:
                raise ValueError(f"Tenant containment violation: invalid tenant root '{tenant_root}'")

            candidate = os.path.join(tenant_root, "memories")
            if os.path.islink(candidate):
                raise ValueError(f"Tenant containment violation: symlinked memories dir rejected ({candidate})")
            mem_real = os.path.realpath(candidate)
            if os.path.commonpath([tenant_root, mem_real]) != tenant_root or mem_real == tenant_root:
                raise ValueError(f"Tenant containment violation: memories dir '{candidate}' escapes tenant root")
            Path(mem_real).mkdir(parents=True, exist_ok=True)
            return Path(mem_real)

        return None

    def _resolve_tenant_litellm_key(self, request: AgentTurnRequest, clean_tenant: str) -> str:
        explicit = str(request.extra_params.get("litellm_api_key") or "").strip()
        if explicit:
            return explicit

        default_tenant_env = f"{clean_tenant.upper().replace('-', '_')}_LITELLM_KEY"
        trusted_manifest_env = _load_trusted_agent_virtual_key_env(clean_tenant)

        allowed_envs: set[str] = set()
        if _SAFE_TENANT_KEY_ENV_RE.match(default_tenant_env) and default_tenant_env not in _FORBIDDEN_KEY_ENVS:
            allowed_envs.add(default_tenant_env)
        if trusted_manifest_env and trusted_manifest_env not in _FORBIDDEN_KEY_ENVS:
            allowed_envs.add(trusted_manifest_env)

        raw_extra_env = str(request.extra_params.get("virtual_key_env") or "").strip()
        validated_extra_env = ""
        if raw_extra_env:
            if raw_extra_env in allowed_envs:
                validated_extra_env = raw_extra_env
            else:
                logger.warning(
                    "Ignoring untrusted virtual_key_env '%s' for tenant '%s'",
                    raw_extra_env,
                    clean_tenant,
                )

        for candidate_env in dict.fromkeys(
            e for e in (validated_extra_env, trusted_manifest_env, default_tenant_env) if e
        ):
            if candidate_env in allowed_envs:
                val = os.getenv(candidate_env, "").strip()
                if val:
                    return val

        return ""

    def _resolve_allowed_repos_list(self, request: AgentTurnRequest, clean_tenant: str) -> list[str]:
        tenant_upper = clean_tenant.upper().replace("-", "_")
        tenant_env_names = (
            f"GITHUB_ALLOWED_REPOS_{tenant_upper}",
            f"{tenant_upper}_GITHUB_ALLOWED_REPOS",
        )

        if "github_allowed_repos" in request.extra_params:
            raw_extra = request.extra_params.get("github_allowed_repos")
            if isinstance(raw_extra, (list, tuple)):
                repos = [str(r).strip() for r in raw_extra if str(r).strip()]
                if repos:
                    return repos
                for env_name in tenant_env_names:
                    if env_name in os.environ:
                        raw_t = os.getenv(env_name, "").strip()
                        return [r.strip() for r in re.split(r"[,;\s]+", raw_t) if r.strip()]
                return []
            if isinstance(raw_extra, str):
                return [r.strip() for r in re.split(r"[,;\s]+", raw_extra) if r.strip()]

        for env_name in tenant_env_names:
            if env_name in os.environ:
                raw_t = os.getenv(env_name, "").strip()
                return [r.strip() for r in re.split(r"[,;\s]+", raw_t) if r.strip()]

        raw_global = os.getenv("GITHUB_ALLOWED_REPOS", "").strip()
        return [r.strip() for r in re.split(r"[,;\s]+", raw_global) if r.strip()]

    def _resolve_allowed_repos(self, request: AgentTurnRequest, clean_tenant: str) -> str:
        return ",".join(self._resolve_allowed_repos_list(request, clean_tenant))

    async def execute_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        """Launch ephemeral container, pipe request, await completion, and enforce hard cleanup."""
        timeout_sec = request.timeout_sec or self.default_timeout_sec

        try:
            clean_tenant = self._validate_tenant_id(request.agent_id)
            clean_run_id = self._validate_run_id(request.run_id)
            workspace_path = self._validate_workspace(request.workspace_dir, clean_tenant)
            memories_path = self._validate_memories(request.memory_dir, clean_tenant)
        except ValueError as err:
            logger.error("Sandbox containment validation failed: %s", err)
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=str(err),
            )

        sanitized_extras: dict[str, Any] = {
            k: v
            for k, v in request.extra_params.items()
            if k not in ("litellm_api_key", "egress_proxy_token", "virtual_key_env")
        }
        sanitized_request = request.model_copy(update={"extra_params": sanitized_extras})

        container_name = f"brainsos-sandbox-{clean_tenant}-{clean_run_id}-{int(time.time())}"
        request_file = workspace_path / f".brainsos_request_{clean_run_id}.json"
        ws_real = os.path.realpath(workspace_path)
        req_real = os.path.realpath(request_file)
        if (
            request_file.is_symlink()
            or os.path.commonpath([ws_real, req_real]) != ws_real
            or os.path.dirname(req_real) != ws_real
        ):
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Sandbox containment violation: unsafe request payload path '{request_file}'",
            )
        try:
            request_file.write_text(sanitized_request.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Failed to write request payload: {exc}",
            )

        litellm_url = (
            os.getenv("LITELLM_URL") or os.getenv("OPENAI_BASE_URL") or "http://litellm:4000/v1"
        ).rstrip("/")
        anthropic_url = os.getenv("ANTHROPIC_BASE_URL") or (
            litellm_url[:-3] if litellm_url.endswith("/v1") else litellm_url
        )
        tenant_litellm_key = self._resolve_tenant_litellm_key(request, clean_tenant)

        raw_proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "http://brainsos-net-egress-proxy:8082"
        parsed_proxy = urlparse(raw_proxy if "://" in raw_proxy else f"http://{raw_proxy}")
        proxy_host_port = parsed_proxy.hostname or "brainsos-net-egress-proxy"
        if parsed_proxy.port:
            proxy_host_port = f"{proxy_host_port}:{parsed_proxy.port}"

        allowed_repos_list = self._resolve_allowed_repos_list(request, clean_tenant)
        allowed_repos = ",".join(allowed_repos_list)

        proxy_token = (
            str(request.extra_params.get("egress_proxy_token") or "").strip()
            or _extract_tenant_proxy_token(clean_tenant, allowed_repos=allowed_repos_list)
        )
        if proxy_token:
            proxy_url = f"http://{quote(clean_tenant, safe='')}:{quote(proxy_token, safe='')}@{proxy_host_port}"
        else:
            proxy_url = f"http://{proxy_host_port}"

        no_proxy = os.getenv(
            "NO_PROXY",
            "localhost,127.0.0.1,host.docker.internal,litellm,brainsos-control-litellm,lens,brainsos-lens,brainsos-telemetry-lens",
        )

        cmd = [
            self.docker_cmd,
            "run",
            "--rm",
            "-i",
            "--name",
            container_name,
            "--label",
            f"brainsos.tenant={clean_tenant}",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            "--pids-limit=256",
            f"--network={self.network}",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user=10001:10001",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "-v",
            f"{workspace_path}:/workspace:rw",
        ]
        if memories_path is not None:
            cmd.extend(["-v", f"{memories_path}:/memories:rw"])

        env_vars: list[tuple[str, str]] = [
            ("BRAINSOS_RUN_ID", clean_run_id),
            ("BRAINSOS_AGENT_ID", clean_tenant),
            ("BRAINSOS_MODEL", request.model),
            ("BRAINSOS_REQUEST_FILE", f"/workspace/{request_file.name}"),
            ("HOME", "/tmp"),
            ("TMPDIR", "/tmp"),
            ("LITELLM_URL", litellm_url),
            ("OPENAI_BASE_URL", litellm_url),
            ("ANTHROPIC_BASE_URL", anthropic_url),
            ("BRAINSOS_TELEMETRY_BACKEND", "lens"),
            ("LENS_ENABLED", "true"),
            ("LANGFUSE_ENABLED", "false"),
            ("HTTP_PROXY", proxy_url),
            ("HTTPS_PROXY", proxy_url),
            ("NO_PROXY", no_proxy),
            ("no_proxy", no_proxy),
        ]
        if tenant_litellm_key:
            env_vars.extend(
                [
                    ("LITELLM_API_KEY", tenant_litellm_key),
                    ("OPENAI_API_KEY", tenant_litellm_key),
                    ("ANTHROPIC_API_KEY", tenant_litellm_key),
                ]
            )
        lens_endpoint = os.getenv("LENS_OTLP_ENDPOINT", "").strip()
        if lens_endpoint:
            env_vars.append(("LENS_OTLP_ENDPOINT", lens_endpoint))
        tracing_key = os.getenv("LITELLM_TRACING_KEY", "").strip()
        if tracing_key:
            env_vars.append(("LITELLM_TRACING_KEY", tracing_key))
        if proxy_token:
            env_vars.extend(
                [
                    ("TOOL_EGRESS_PROXY_TOKEN", proxy_token),
                    ("PROXY_AUTHORIZATION", f"Bearer {proxy_token}"),
                ]
            )
        if allowed_repos:
            env_vars.append(("GITHUB_ALLOWED_REPOS", allowed_repos))

        for k, v in env_vars:
            cmd.extend(["-e", f"{k}={v}"])

        cmd.append(self.image)
        if self.command:
            cmd.extend(self.command)

        proc = None
        timed_out = False
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=sanitized_request.model_dump_json().encode("utf-8")),
                timeout=float(timeout_sec),
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        except (asyncio.TimeoutError, TimeoutError):
            timed_out = True
            logger.warning("Sandbox container %s timed out after %ds, killing...", container_name, timeout_sec)
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    self.docker_cmd,
                    "kill",
                    container_name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
            except Exception as kill_err:
                logger.error("Failed to kill container %s: %s", container_name, kill_err)

            return AgentTurnResponse(
                run_id=request.run_id,
                status="timed_out",
                output_text="",
                error_message=f"Sandbox container execution timed out after {timeout_sec}s",
            )
        except Exception as exc:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Failed to spawn sandbox container: {exc}",
            )
        finally:
            # Clean up temporary request payload
            try:
                if request_file.exists():
                    request_file.unlink()
            except Exception:
                pass

            # Guarantee cleanup: remove any lingering container instance
            if timed_out or (proc and proc.returncode is None):
                try:
                    rm_proc = await asyncio.create_subprocess_exec(
                        self.docker_cmd,
                        "rm",
                        "-f",
                        container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await rm_proc.wait()
                except Exception:
                    pass

        # Attempt to parse structured response from stdout or response_file regardless of exit code
        parsed_resp = _parse_agent_response_payload(stdout)
        if parsed_resp is None:
            response_file = workspace_path / f".brainsos_response_{clean_run_id}.json"
            try:
                resp_real = os.path.realpath(response_file)
                if (
                    not response_file.is_symlink()
                    and os.path.commonpath([ws_real, resp_real]) == ws_real
                    and os.path.dirname(resp_real) == ws_real
                    and response_file.is_file()
                ):
                    parsed_resp = _parse_agent_response_payload(response_file.read_text(encoding="utf-8"))
                    response_file.unlink()
            except Exception:
                pass

        if proc.returncode == 0:
            if parsed_resp is not None:
                return parsed_resp
            return AgentTurnResponse(
                run_id=request.run_id,
                status="completed",
                output_text=stdout,
            )

        if parsed_resp is not None:
            if parsed_resp.status == "completed":
                return parsed_resp.model_copy(
                    update={
                        "status": "failed",
                        "error_message": parsed_resp.error_message
                        or stderr
                        or f"Sandbox container exited with code {proc.returncode}",
                    }
                )
            return parsed_resp

        return AgentTurnResponse(
            run_id=request.run_id,
            status="failed",
            output_text=stdout,
            error_message=stderr or f"Sandbox container exited with code {proc.returncode}",
        )
