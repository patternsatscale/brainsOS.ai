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
import ipaddress
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, Optional, Set, Tuple
from urllib.parse import urlparse

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

SENSITIVE_HEADERS = ("Authorization", "x-api-key", "X-Subscription-Token")
IMDSV6_NET = ipaddress.IPv6Network("fd00:ec2::254/128")
CGNAT_NET = ipaddress.IPv4Network("100.64.0.0/10")


def _is_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for loopback, private, link-local, IMDSv4/IPv6, multicast, or CGNAT IPs."""
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True
    if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in CGNAT_NET:
        return True
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in IMDSV6_NET:
        return True
    return False


def is_blocked_destination(
    host: str,
    *,
    allow_private_hosts: Optional[Iterable[str]] = None,
    resolver=socket.getaddrinfo,
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
        ip_lit = ipaddress.ip_address(clean_host)
        if _is_forbidden_ip(ip_lit):
            return f"Forbidden internal/metadata IP '{ip_lit}'"
        return None
    except ValueError:
        pass

    # DNS resolution check (all A/AAAA records)
    try:
        infos = resolver(clean_host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return None

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
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
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
                try:
                    with urllib.request.urlopen(req, timeout=2.0) as resp:
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

    def _verify_tls_and_sni(self, flow: http.HTTPFlow, host: str) -> Optional[str]:
        if (flow.request.scheme or "").lower() != "https":
            return "Credential injection requires verified HTTPS scheme"
        server_conn = getattr(flow, "server_conn", None)
        sni = getattr(server_conn, "sni", None)
        if sni and str(sni).strip().lower() != host:
            return f"TLS SNI '{sni}' mismatch against Host '{host}'"
        return None

    def request(self, flow: http.HTTPFlow) -> None:
        host = (flow.request.pretty_host or "").strip().lower()

        # 1. Fail-closed SSRF guard across all outbound proxied destinations
        blocked_reason = is_blocked_destination(host, allow_private_hosts=self.allow_private_hosts)
        if blocked_reason:
            logger.warning("[SSRF-BLOCK] %s (%s)", blocked_reason, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Destination blocked by egress SSRF policy.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        # 2. Only intercept credential injection for allowlisted HTTPS API providers
        rule = CREDENTIAL_HOSTS.get(host)
        if rule is None:
            return

        client_address = getattr(flow.client_conn, "peername", None) or getattr(flow.client_conn, "address", None)
        client_ip = str(client_address[0]) if client_address else ""
        allowed_ips = self._resolve_allowed_ips()

        if not client_ip or client_ip not in allowed_ips:
            logger.warning("[AUTH-DENY] Rejected unauthorized egress credential request from %s -> %s", client_ip, host)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Egress credential injection not permitted for this container.\n",
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        tls_err = self._verify_tls_and_sni(flow, host)
        if tls_err:
            logger.warning("[TLS-DENY] %s -> %s", tls_err, flow.request.url)
            flow.response = http.Response.make(
                403,
                b"403 Forbidden: Verified TLS host and SNI match required.\n",
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

        # Support Tavily JSON payload api_key replacement if caller sent dummy placeholder
        if host == "api.tavily.com" and flow.request.content:
            try:
                body_json = json.loads(flow.request.content.decode("utf-8"))
                if isinstance(body_json, dict) and body_json.get("api_key") in (DUMMY_PLACEHOLDER, "", None):
                    body_json["api_key"] = secret_val
                    flow.request.set_text(json.dumps(body_json))
            except Exception:
                pass

    def _redact_headers(self, flow: http.HTTPFlow) -> None:
        host = (flow.request.pretty_host or "").strip().lower()
        if host not in CREDENTIAL_HOSTS:
            return
        for hdr in SENSITIVE_HEADERS:
            if hdr in flow.request.headers:
                flow.request.headers[hdr] = REDACTED_MARKER

    def response(self, flow: http.HTTPFlow) -> None:
        self._redact_headers(flow)

    def error(self, flow: http.HTTPFlow) -> None:
        self._redact_headers(flow)


addons = [OpenBaoEgressAddon()]
