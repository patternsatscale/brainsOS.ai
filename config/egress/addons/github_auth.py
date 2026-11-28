# ==============================================================================
# brainsOS: OpenBao-Backed Zero-Trust Tool Egress Proxy Addon (#387)
#   1. Blocks SSRF targets (RFC1918, loopback, link-local, IMDSv4 & IMDSv6).
#   2. Authenticates to segregated OpenBao via read-only AppRole (in-memory cache).
#   3. Verifies TLS scheme, SNI == Host, and authorized agent container source IP
#      before injecting provider credentials in transit.
#   4. Redacts injected headers in flow logs/UI ([INJECTED_OPENBAO_SECRET]).
# ==============================================================================

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import posixpath
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

from mitmproxy import http

logger = logging.getLogger("brainsos-egress-auth")

DUMMY_PLACEHOLDER = "in-transit-openbao-managed"
REDACTED_MARKER = "[INJECTED_OPENBAO_SECRET]"

CREDENTIAL_HOSTS: Dict[str, Tuple[str, str, str]] = {
    "api.github.com": ("GITHUB_TOKEN", "Authorization", "Bearer {val}"),
    "github.com": ("GITHUB_TOKEN", "Authorization", "Basic {basic_github}"),
    "api.firecrawl.dev": ("FIRECRAWL_API_KEY", "Authorization", "Bearer {val}"),
    "api.tavily.com": ("TAVILY_API_KEY", "Authorization", "Bearer {val}"),
    "api.exa.ai": ("EXA_API_KEY", "x-api-key", "{val}"),
    "api.search.brave.com": ("BRAVE_SEARCH_API_KEY", "X-Subscription-Token", "{val}"),
}

SENSITIVE_HEADERS = ("Authorization", "Proxy-Authorization", "x-api-key", "X-Subscription-Token")
IMDSV6_NET = ipaddress.IPv6Network("fd00:ec2::254/128")
ULA_NET = ipaddress.IPv6Network("fc00::/7")
CGNAT_NET = ipaddress.IPv4Network("100.64.0.0/10")
DOCKER_BRIDGE_NET = ipaddress.IPv4Network("172.16.0.0/12")

_UNSET = object()
_SAFE_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


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


def _is_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for loopback, private, link-local, IMDSv4/IPv6, ULA, Docker bridge, multicast, or CGNAT IPs."""
    if isinstance(ip_obj, ipaddress.IPv6Address):
        if ip_obj.ipv4_mapped is not None:
            return _is_forbidden_ip(ip_obj.ipv4_mapped)
        if ip_obj.sixtofour is not None and _is_forbidden_ip(ip_obj.sixtofour):
            return True
        if ip_obj.teredo is not None:
            client_v4, server_v4 = ip_obj.teredo
            if _is_forbidden_ip(client_v4) or _is_forbidden_ip(server_v4):
                return True
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
        or not ip_obj.is_global
    ):
        return True
    if isinstance(ip_obj, ipaddress.IPv4Address):
        if ip_obj in CGNAT_NET or ip_obj in DOCKER_BRIDGE_NET:
            return True
    if isinstance(ip_obj, ipaddress.IPv6Address):
        if ip_obj in IMDSV6_NET or ip_obj in ULA_NET:
            return True
    return False


def _is_forbidden_peer_ip(
    addr_raw: str,
    *,
    host: str = "",
    allow_private_hosts: Optional[Iterable[str]] = None,
) -> Optional[str]:
    clean_host = (host or "").strip().lower().strip("[]")
    allowed_private = {h.strip().lower() for h in (allow_private_hosts or ()) if h.strip()}
    if clean_host and clean_host in allowed_private:
        return None
    clean_addr = (addr_raw or "").strip().strip("[]").split("%", 1)[0]
    if not clean_addr:
        return "Empty peer IP address"
    try:
        ip_obj = ipaddress.ip_address(clean_addr)
    except ValueError:
        return f"Invalid peer IP address '{addr_raw}'"
    if _is_forbidden_ip(ip_obj):
        return f"Connected peer '{ip_obj}' is forbidden by SSRF policy"
    return None


def is_blocked_destination(
    host: str,
    *,
    allow_private_hosts: Optional[Iterable[str]] = None,
    resolver: Optional[Any] = None,
) -> Optional[str]:
    """Check whether destination `host` is an SSRF-forbidden internal or metadata address."""
    clean_host = (host or "").strip().lower().strip("[]")
    if not clean_host:
        return "Empty destination host"

    allowed_private = {h.strip().lower() for h in (allow_private_hosts or ()) if h.strip()}
    if clean_host in allowed_private:
        return None

    if clean_host in ("localhost", "ip6-localhost", "ip6-loopback", "instance-data"):
        return f"Forbidden local hostname '{clean_host}'"

    # Literal IP check
    try:
        ip_lit = ipaddress.ip_address(clean_host.split("%", 1)[0])
        if _is_forbidden_ip(ip_lit):
            return f"Forbidden internal/metadata IP '{ip_lit}'"
        return None
    except ValueError:
        pass

    # DNS resolution check (all A/AAAA records; fail closed on DNS errors)
    lookup = resolver if resolver is not None else socket.getaddrinfo
    try:
        infos = lookup(clean_host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return f"DNS resolution failed for '{clean_host}': {exc}"

    if not infos:
        return f"DNS resolution returned no records for '{clean_host}'"

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr_raw = str(sockaddr[0]).split("%", 1)[0]
        try:
            ip_obj = ipaddress.ip_address(addr_raw)
        except ValueError:
            continue
        if _is_forbidden_ip(ip_obj):
            return f"Destination '{clean_host}' resolves to forbidden address '{ip_obj}'"
    return None


def _parse_approle_env_file(path: str) -> Tuple[str, str]:
    role_id = ""
    secret_id = ""
    if not path or not os.path.isfile(path):
        return role_id, secret_id
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "OPENBAO_ROLE_ID":
                    role_id = v
                elif k == "OPENBAO_SECRET_ID":
                    secret_id = v
    except OSError:
        pass
    return role_id, secret_id


class OpenBaoEgressAddon:
    """In-memory OpenBao AppRole credential injector & SSRF firewall addon."""

    def __init__(self) -> None:
        self.openbao_addr = (os.environ.get("OPENBAO_ADDR") or "").strip().rstrip("/")
        self.openbao_ca_file = (
            os.environ.get("OPENBAO_CACERT")
            or os.environ.get("OPENBAO_CA_FILE")
            or "/etc/ssl/openbao/ca.crt"
        ).strip()
        self.approle_env_path = (
            os.environ.get("OPENBAO_APPROLE_ENV") or "/run/secrets/openbao/egress-approle.env"
        ).strip()
        self.secret_path = (os.environ.get("OPENBAO_SECRET_PATH") or "secret/data/tools").strip().lstrip("/")
        raw_containers = os.environ.get(
            "TOOL_EGRESS_ALLOWED_CONTAINERS",
            "runner-hermes,runner-openai,runner-claude",
        )
        self.allowed_containers = [c.strip() for c in raw_containers.split(",") if c.strip()]
        raw_priv_allow = os.environ.get("TOOL_EGRESS_ALLOW_PRIVATE_HOSTS", "")
        self.allow_private_hosts = [h.strip().lower() for h in raw_priv_allow.split(",") if h.strip()]

        self._client_token: str = ""
        self._token_expires_at: float = 0.0
        self._secrets_cache: Dict[str, str] = {}
        self._secrets_expires_at: float = 0.0
        self._cache_ttl: float = 60.0

        self._allowed_ips: Set[str] = set()
        self._last_dns_check: float = 0.0
        self._dns_ttl: float = 15.0

    def _build_openbao_ssl_context(self) -> Optional[ssl.SSLContext]:
        if not self.openbao_addr.lower().startswith("https://"):
            return None
        if self.openbao_ca_file and os.path.isfile(self.openbao_ca_file) and os.path.getsize(self.openbao_ca_file) > 0:
            return ssl.create_default_context(cafile=self.openbao_ca_file)
        return ssl.create_default_context()

    def _get_approle_credentials(self) -> Tuple[str, str]:
        role_id = (os.environ.get("OPENBAO_ROLE_ID") or "").strip()
        secret_id = (os.environ.get("OPENBAO_SECRET_ID") or "").strip()
        if role_id and secret_id:
            return role_id, secret_id
        return _parse_approle_env_file(self.approle_env_path)

    def _login_approle(self) -> str:
        role_id, secret_id = self._get_approle_credentials()
        if not self.openbao_addr or not role_id or not secret_id:
            return ""
        parsed = urlparse(self.openbao_addr)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        req = urllib.request.Request(
            f"{self.openbao_addr}/v1/auth/approle/login",
            data=json.dumps({"role_id": role_id, "secret_id": secret_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        ctx = self._build_openbao_ssl_context()
        try:
            open_kwargs: Dict[str, Any] = {"timeout": 2.0}
            if ctx is not None:
                open_kwargs["context"] = ctx
            with urllib.request.urlopen(req, **open_kwargs) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                auth = data.get("auth", {})
                tok = str(auth.get("client_token") or "").strip()
                ttl = int(auth.get("lease_duration") or 1800)
                if tok:
                    self._client_token = tok
                    self._token_expires_at = time.time() + max(60, ttl - 30)
                return tok
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("[OPENBAO-WARN] AppRole login failed: %s", exc)
            return ""

    def _get_secrets(self) -> Dict[str, str]:
        now = time.time()
        if self._secrets_cache and now < self._secrets_expires_at:
            return self._secrets_cache

        loaded: Dict[str, str] = {}
        if self.openbao_addr:
            token = self._client_token if (self._client_token and now < self._token_expires_at) else self._login_approle()
            if token:
                req = urllib.request.Request(
                    f"{self.openbao_addr}/v1/{self.secret_path}",
                    headers={"X-Vault-Token": token},
                    method="GET",
                )
                ctx = self._build_openbao_ssl_context()
                try:
                    open_kwargs: Dict[str, Any] = {"timeout": 2.0}
                    if ctx is not None:
                        open_kwargs["context"] = ctx
                    with urllib.request.urlopen(req, **open_kwargs) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        raw = body.get("data", {}).get("data", {})
                        if isinstance(raw, dict):
                            loaded = {
                                str(k): str(v)
                                for k, v in raw.items()
                                if v is not None and str(v).strip() and str(v).strip() != DUMMY_PLACEHOLDER
                            }
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        self._client_token = ""
                    logger.warning("[OPENBAO-WARN] Secret read HTTP %s", exc.code)
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    logger.warning("[OPENBAO-WARN] Secret read failed: %s", exc)

        # Fallback only for secrets explicitly passed to egress container environment when OpenBao isn't present
        if not loaded:
            for env_key in (
                "GITHUB_TOKEN",
                "FIRECRAWL_API_KEY",
                "TAVILY_API_KEY",
                "EXA_API_KEY",
                "BRAVE_SEARCH_API_KEY",
            ):
                val = (os.environ.get(env_key) or "").strip()
                if val and val != DUMMY_PLACEHOLDER:
                    loaded[env_key] = val

        self._secrets_cache = loaded
        self._secrets_expires_at = now + self._cache_ttl
        return loaded

    def _resolve_allowed_ips(self) -> Set[str]:
        now = time.time()
        if self._allowed_ips and (now - self._last_dns_check) < self._dns_ttl:
            return self._allowed_ips

        ips: Set[str] = set()
        for host in self.allowed_containers:
            try:
                ip = socket.gethostbyname(host)
                if ip:
                    ips.add(ip)
            except OSError:
                pass

        if ips:
            self._allowed_ips = ips
            self._last_dns_check = now
        return self._allowed_ips

    def _validate_flow_destination(self, flow: http.HTTPFlow) -> Optional[str]:
        req_host = (getattr(flow.request, "host", None) or "").strip().lower()
        pretty_host = (getattr(flow.request, "pretty_host", None) or "").strip().lower()
        if not req_host and not pretty_host:
            return "Empty destination host"
        if req_host and pretty_host and req_host != pretty_host:
            return f"Request host '{req_host}' mismatches pretty_host '{pretty_host}'"

        target_host = pretty_host or req_host
        for candidate in dict.fromkeys(h for h in (req_host, pretty_host) if h):
            blocked = is_blocked_destination(candidate, allow_private_hosts=self.allow_private_hosts)
            if blocked:
                return blocked

        server_conn = getattr(flow, "server_conn", None)
        if server_conn is not None:
            peername = getattr(server_conn, "peername", None)
            if peername and isinstance(peername, (tuple, list)) and peername[0]:
                peer_err = _is_forbidden_peer_ip(
                    str(peername[0]),
                    host=target_host,
                    allow_private_hosts=self.allow_private_hosts,
                )
                if peer_err:
                    return peer_err
            address = getattr(server_conn, "address", None)
            if address and isinstance(address, (tuple, list)) and address[0]:
                addr_err = is_blocked_destination(
                    str(address[0]),
                    allow_private_hosts=self.allow_private_hosts,
                )
                if addr_err:
                    return addr_err
        return None

    def _verify_tls_and_sni(self, flow: http.HTTPFlow) -> Optional[str]:
        if (getattr(flow.request, "scheme", "") or "").lower() != "https":
            return "Credential injection requires verified HTTPS scheme"
        req_host = (getattr(flow.request, "host", None) or "").strip().lower()
        pretty_host = (getattr(flow.request, "pretty_host", None) or "").strip().lower()
        if not req_host or not pretty_host or req_host != pretty_host:
            return f"Request host '{req_host}' mismatches pretty_host '{pretty_host}'"
        server_conn = getattr(flow, "server_conn", None)
        raw_sni = getattr(server_conn, "sni", None)
        sni = str(raw_sni).strip().lower() if raw_sni is not None else ""
        if not sni:
            return "TLS SNI is required for credential injection"
        if sni != req_host or sni != pretty_host:
            return f"TLS SNI '{sni}' mismatch against host '{req_host}' / pretty_host '{pretty_host}'"
        return None

    def _load_proxy_tokens(self) -> Dict[str, str]:
        raw = (os.environ.get("TOOL_EGRESS_PROXY_TOKENS") or "").strip()
        tokens: Dict[str, str] = {}
        if not raw:
            return tokens
        for entry in re.split(r"[,;\s]+", raw):
            if not entry or ":" not in entry:
                continue
            tenant, tok = entry.split(":", 1)
            t_clean = tenant.strip()
            tok_clean = tok.strip()
            if t_clean and tok_clean:
                tokens[t_clean] = tok_clean
        return tokens

    @staticmethod
    def _proxy_secret() -> str:
        return (os.environ.get("TOOL_EGRESS_PROXY_SECRET") or "").strip()

    def _proxy_auth_required(self) -> bool:
        if self._load_proxy_tokens() or self._proxy_secret():
            return True
        return (os.environ.get("TOOL_EGRESS_REQUIRE_PROXY_AUTH") or "").strip().lower() in ("1", "true", "yes")

    def _verify_hmac_token_claims(
        self, token: str, expected_tenant: Optional[str] = None
    ) -> Optional[Tuple[str, Optional[Set[str]]]]:
        secret = self._proxy_secret()
        if not secret:
            return None

        if token.startswith("v2."):
            parts = token.split(".", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                return None
            _, payload_b64, sig_hex = parts
            expected_sig = hmac.new(
                secret.encode("utf-8"),
                f"v2.{payload_b64}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig_hex, expected_sig):
                return None
            try:
                padded = payload_b64 + ("=" * (-len(payload_b64) % 4))
                payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            except Exception:
                return None
            if not isinstance(payload, dict):
                return None
            tenant = str(payload.get("t") or "").strip()
            if not _SAFE_TENANT_ID_RE.match(tenant):
                return None
            if expected_tenant and tenant != expected_tenant:
                return None
            raw_exp = payload.get("exp")
            if isinstance(raw_exp, bool):
                return None
            try:
                exp_ts = int(raw_exp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            if exp_ts < int(time.time()):
                return None
            if "repos" not in payload or payload["repos"] is None:
                return tenant, None
            raw_repos = payload["repos"]
            if not isinstance(raw_repos, list):
                return None
            token_repos = {n for n in (_normalize_repo_slug(str(r)) for r in raw_repos) if n}
            return tenant, token_repos

        parts = token.split(".", 3)
        if len(parts) != 4 or parts[0] != "v1":
            return None
        _, tenant, exp_str, sig_hex = parts
        if not _SAFE_TENANT_ID_RE.match(tenant):
            return None
        if expected_tenant and tenant != expected_tenant:
            return None
        try:
            exp_ts = int(exp_str)
        except ValueError:
            return None
        if exp_ts < int(time.time()):
            return None
        expected_sig = hmac.new(
            secret.encode("utf-8"),
            f"{tenant}:{exp_ts}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_hex, expected_sig):
            return None
        return tenant, None

    def _verify_hmac_token(self, token: str, expected_tenant: Optional[str] = None) -> Optional[str]:
        res = self._verify_hmac_token_claims(token, expected_tenant=expected_tenant)
        return res[0] if res is not None else None

    def _verify_proxy_token_claims(self, raw_header: str) -> Optional[Tuple[str, Optional[Set[str]]]]:
        header = (raw_header or "").strip()
        if not header:
            return None
        tokens_map = self._load_proxy_tokens()

        if header.lower().startswith("bearer "):
            tok = header[7:].strip()
            if not tok:
                return None
            for tenant, expected in tokens_map.items():
                if hmac.compare_digest(tok, expected):
                    return tenant, None
            return self._verify_hmac_token_claims(tok)

        if header.lower().startswith("basic "):
            b64_part = header[6:].strip()
            try:
                decoded = base64.b64decode(b64_part, validate=True).decode("utf-8")
            except Exception:
                return None
            if ":" not in decoded:
                return None
            user, secret_tok = decoded.split(":", 1)
            user_clean = user.strip()
            tok_clean = secret_tok.strip()
            if user_clean in tokens_map and hmac.compare_digest(tok_clean, tokens_map[user_clean]):
                return user_clean, None
            return self._verify_hmac_token_claims(tok_clean, expected_tenant=user_clean or None)

        return None

    def _verify_proxy_token(self, raw_header: str) -> Optional[str]:
        res = self._verify_proxy_token_claims(raw_header)
        return res[0] if res is not None else None

    @staticmethod
    def _strip_proxy_auth(flow: http.HTTPFlow) -> str:
        headers = getattr(flow.request, "headers", None)
        if headers is None:
            return ""
        found_val = ""
        for key in list(headers.keys()):
            if str(key).lower() == "proxy-authorization":
                if not found_val:
                    found_val = str(headers.get(key) or "")
                del headers[key]
        return found_val

    def _authenticate_proxy_flow(self, flow: http.HTTPFlow) -> Tuple[bool, Optional[str]]:
        raw_auth = self._strip_proxy_auth(flow)
        client_conn = getattr(flow, "client_conn", None)
        conn_tenant = getattr(client_conn, "_brainsos_auth_tenant", None) if client_conn is not None else None
        conn_repos = getattr(client_conn, "_brainsos_allowed_repos", _UNSET) if client_conn is not None else _UNSET

        if raw_auth:
            verified = self._verify_proxy_token_claims(raw_auth)
            if not verified:
                return False, "Invalid Proxy-Authorization credential"
            tenant, token_repos = verified
            if conn_tenant and conn_tenant != tenant:
                return False, "Proxy-Authorization tenant mismatch on connection"
            if conn_repos is not _UNSET and conn_repos != token_repos:
                return False, "Proxy-Authorization repo allowlist mismatch on connection"
            if client_conn is not None:
                setattr(client_conn, "_brainsos_auth_tenant", tenant)
                setattr(client_conn, "_brainsos_allowed_repos", token_repos)
            setattr(flow, "_brainsos_allowed_repos", token_repos)
            return True, tenant

        if conn_tenant:
            if conn_repos is not _UNSET:
                setattr(flow, "_brainsos_allowed_repos", conn_repos)
            return True, str(conn_tenant)

        if self._proxy_auth_required():
            return False, "Missing Proxy-Authorization credential"

        return True, None

    def _check_github_allowed_repos(
        self,
        flow: http.HTTPFlow,
        host: str,
        tenant_id: Optional[str],
    ) -> Optional[str]:
        if host not in ("github.com", "api.github.com"):
            return None

        raw_token_repos = getattr(flow, "_brainsos_allowed_repos", _UNSET)
        if raw_token_repos is _UNSET:
            client_conn = getattr(flow, "client_conn", None)
            raw_token_repos = getattr(client_conn, "_brainsos_allowed_repos", None) if client_conn is not None else None
        token_repos: Optional[Set[str]] = raw_token_repos if isinstance(raw_token_repos, set) else None

        env_repos: Optional[Set[str]] = None
        t_env = f"GITHUB_ALLOWED_REPOS_{tenant_id.upper().replace('-', '_')}" if tenant_id else ""
        if t_env and t_env in os.environ:
            raw_t = (os.environ.get(t_env) or "").strip()
            env_repos = {n for n in (_normalize_repo_slug(item) for item in re.split(r"[,;\s]+", raw_t)) if n}
        else:
            raw_global = (os.environ.get("GITHUB_ALLOWED_REPOS") or "").strip()
            if raw_global:
                env_repos = {
                    n for n in (_normalize_repo_slug(item) for item in re.split(r"[,;\s]+", raw_global)) if n
                }

        allowed_set: Optional[Set[str]]
        if token_repos is not None and env_repos is not None:
            if "*" in token_repos and "*" in env_repos:
                allowed_set = {"*"}
            elif "*" in token_repos:
                allowed_set = env_repos
            elif "*" in env_repos:
                allowed_set = token_repos
            else:
                allowed_set = token_repos & env_repos
        elif token_repos is not None:
            allowed_set = token_repos
        else:
            allowed_set = env_repos

        if not allowed_set:
            return "GitHub repository access is disabled for this tenant (empty or unset GITHUB_ALLOWED_REPOS)"

        raw_path = getattr(flow.request, "path", None)
        if not raw_path:
            raw_path = urlparse(getattr(flow.request, "url", "") or "").path or "/"
        path_no_query = str(raw_path).split("?", 1)[0].split("#", 1)[0]
        if "\\" in path_no_query:
            return "Blocked backslash path in GitHub request"

        decoded = unquote(unquote(path_no_query))
        if "\\" in decoded:
            return "Blocked backslash path in decoded GitHub request"
        raw_segments = [seg for seg in decoded.split("/") if seg]
        if ".." in raw_segments:
            return f"Blocked path traversal segment in GitHub path '{path_no_query}'"

        norm_path = posixpath.normpath(decoded if decoded.startswith("/") else f"/{decoded}")
        if not norm_path.startswith("/") or ".." in norm_path.split("/"):
            return f"Blocked normalized GitHub path '{norm_path}'"

        if "*" in allowed_set:
            return None

        repo_slug = ""
        if host == "api.github.com":
            m_api = re.match(r"^/repos/([^/]+)/([^/]+)(?:/.*)?$", norm_path)
            if m_api:
                repo_slug = f"{m_api.group(1)}/{m_api.group(2)}".lower().removesuffix(".git")
        else:
            m_web = re.match(r"^/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", norm_path)
            if m_web:
                repo_slug = f"{m_web.group(1)}/{m_web.group(2)}".lower().removesuffix(".git")

        if not repo_slug or repo_slug not in allowed_set:
            return f"GitHub repository '{repo_slug or norm_path}' is not in GITHUB_ALLOWED_REPOS"
        return None

    def _authorize_egress_client(
        self,
        flow: http.HTTPFlow,
        host: str,
        authenticated_tenant: Optional[str] = None,
    ) -> Optional[str]:
        if authenticated_tenant:
            return None
        client_address = getattr(flow.client_conn, "peername", None) or getattr(flow.client_conn, "address", None)
        client_ip = str(client_address[0]) if client_address else ""
        allowed_ips = self._resolve_allowed_ips()
        if not client_ip or client_ip not in allowed_ips:
            return f"Rejected unauthorized egress credential request from {client_ip} -> {host}"
        return None

    def http_connect(self, flow: http.HTTPFlow) -> None:
        blocked_reason = self._validate_flow_destination(flow)
        if blocked_reason:
            logger.warning("[SSRF-BLOCK] CONNECT %s (%s)", blocked_reason, getattr(flow.request, "url", ""))
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Destination blocked by egress SSRF policy.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        auth_ok, auth_detail = self._authenticate_proxy_flow(flow)
        if not auth_ok:
            logger.warning("[PROXY-AUTH-DENY] CONNECT %s", auth_detail)
            flow.response = http.Response.make(
                407,
                b"407 Proxy Authentication Required.\n",
                {"Content-Type": "text/plain; charset=utf-8", "Proxy-Authenticate": 'Bearer realm="brainsos-egress"'},
            )

    def server_connect(self, data: Any) -> None:
        server = getattr(data, "server", None) or getattr(data, "server_conn", None)
        if server is None:
            return
        reason: Optional[str] = None
        peername = getattr(server, "peername", None)
        address = getattr(server, "address", None)
        sni_host = str(getattr(server, "sni", "") or "").strip().lower()
        addr_host = str(address[0]).strip().lower() if (address and isinstance(address, (tuple, list)) and address[0]) else ""
        target_host = sni_host or addr_host

        if peername and isinstance(peername, (tuple, list)) and peername[0]:
            reason = _is_forbidden_peer_ip(
                str(peername[0]),
                host=target_host,
                allow_private_hosts=self.allow_private_hosts,
            )
        if not reason and addr_host:
            reason = is_blocked_destination(
                addr_host,
                allow_private_hosts=self.allow_private_hosts,
            )
        if reason:
            logger.warning("[SSRF-BLOCK] server_connect %s", reason)
            server.error = reason
            kill_fn = getattr(data, "kill", None)
            if callable(kill_fn):
                kill_fn()

    def server_connected(self, data: Any) -> None:
        server = getattr(data, "server", None) or getattr(data, "server_conn", None)
        if server is None:
            return
        peername = getattr(server, "peername", None)
        address = getattr(server, "address", None)
        sni_host = str(getattr(server, "sni", "") or "").strip().lower()
        addr_host = (
            str(address[0]).strip().lower()
            if (address and isinstance(address, (tuple, list)) and address[0])
            else ""
        )
        target_host = sni_host or addr_host
        peer_ip = (
            str(peername[0]).strip()
            if (peername and isinstance(peername, (tuple, list)) and peername[0])
            else ""
        )
        reason = _is_forbidden_peer_ip(
            peer_ip,
            host=target_host,
            allow_private_hosts=self.allow_private_hosts,
        )
        if reason:
            logger.warning("[SSRF-BLOCK] server_connected %s", reason)
            server.error = reason
            kill_fn = getattr(data, "kill", None)
            if callable(kill_fn):
                kill_fn()

    def request(self, flow: http.HTTPFlow) -> None:
        # 1. Fail-closed SSRF guard across host, pretty_host, DNS, and post-connect peername
        blocked_reason = self._validate_flow_destination(flow)
        if blocked_reason:
            logger.warning("[SSRF-BLOCK] %s (%s)", blocked_reason, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Destination blocked by egress SSRF policy.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        # 2. Authenticate and strip Proxy-Authorization before any upstream forwarding
        auth_ok, tenant_or_err = self._authenticate_proxy_flow(flow)
        if not auth_ok:
            logger.warning("[PROXY-AUTH-DENY] %s -> %s", tenant_or_err, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Invalid or missing Proxy-Authorization token.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        host = (getattr(flow.request, "pretty_host", None) or getattr(flow.request, "host", None) or "").strip().lower()

        # 3. Only intercept credential injection for allowlisted HTTPS API providers
        rule = CREDENTIAL_HOSTS.get(host)
        if rule is None:
            return

        auth_err = self._authorize_egress_client(flow, host, authenticated_tenant=tenant_or_err)
        if auth_err:
            logger.warning("[AUTH-DENY] %s", auth_err)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Egress credential injection not permitted for this container.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        tls_err = self._verify_tls_and_sni(flow)
        if tls_err:
            logger.warning("[TLS-DENY] %s -> %s", tls_err, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Verified TLS host and SNI match required.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        repo_err = self._check_github_allowed_repos(flow, host, tenant_or_err)
        if repo_err:
            logger.warning("[REPO-DENY] %s -> %s", repo_err, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Repository not permitted by GITHUB_ALLOWED_REPOS.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        secret_name, header_name, fmt = rule
        secrets_map = self._get_secrets()
        secret_val = (secrets_map.get(secret_name) or "").strip()
        if not secret_val:
            return

        if "{basic_github}" in fmt:
            basic_tok = base64.b64encode(f"x-access-token:{secret_val}".encode("utf-8")).decode("utf-8")
            flow.request.headers[header_name] = fmt.format(basic_github=basic_tok)
        else:
            flow.request.headers[header_name] = fmt.format(val=secret_val)

        # Tavily uses Authorization: Bearer; scrub any api_key from JSON body so mitmweb never retains raw secrets
        if host == "api.tavily.com" and getattr(flow.request, "content", None):
            try:
                body_json = json.loads(flow.request.content.decode("utf-8"))
                if isinstance(body_json, dict) and "api_key" in body_json:
                    body_json.pop("api_key", None)
                    serialized = json.dumps(body_json)
                    if callable(getattr(flow.request, "set_text", None)):
                        flow.request.set_text(serialized)
                    else:
                        flow.request.content = serialized.encode("utf-8")
            except Exception:
                pass

    def _redact_headers(self, flow: http.HTTPFlow) -> None:
        host = (getattr(flow.request, "pretty_host", None) or getattr(flow.request, "host", None) or "").strip().lower()
        if host not in CREDENTIAL_HOSTS:
            return
        for hdr in SENSITIVE_HEADERS:
            if hdr in flow.request.headers:
                flow.request.headers[hdr] = REDACTED_MARKER
        if host == "api.tavily.com" and getattr(flow.request, "content", None):
            try:
                body_json = json.loads(flow.request.content.decode("utf-8"))
                if isinstance(body_json, dict) and "api_key" in body_json:
                    body_json.pop("api_key", None)
                    serialized = json.dumps(body_json)
                    if callable(getattr(flow.request, "set_text", None)):
                        flow.request.set_text(serialized)
                    else:
                        flow.request.content = serialized.encode("utf-8")
            except Exception:
                pass

    def response(self, flow: http.HTTPFlow) -> None:
        self._redact_headers(flow)

    def error(self, flow: http.HTTPFlow) -> None:
        self._redact_headers(flow)


addons = [OpenBaoEgressAddon()]
