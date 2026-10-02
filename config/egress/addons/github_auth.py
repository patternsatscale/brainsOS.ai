# ==============================================================================
# brainsOS: Multi-Tenant GitHub Egress In-Transit Credential Injection Addon
# Intercepts outbound requests to github.com and api.github.com from agent sandboxes.
# Authorizes requests strictly by client container IP on brainsos-internal.
# Injects fine-grained credentials in-transit:
#   - github.com (Git Smart HTTP): Authorization: Basic <GITHUB_BASIC_AUTH_CINDY>
#   - api.github.com (REST/GraphQL): Authorization: Bearer <GITHUB_TOKEN_CINDY>
# Rejects unauthorized tenant containers with HTTP 403 Forbidden.
# Redacts injected tokens from memory flows so they never display in mitmweb console.
# ==============================================================================

import logging
import os
import socket
import time
from mitmproxy import http

logger = logging.getLogger("brainsos-egress-github-auth")


class GitHubAuthAddon:
    def __init__(self):
        self.github_token_cindy = os.environ.get("GITHUB_TOKEN_CINDY", "")
        self.github_basic_auth_cindy = os.environ.get("GITHUB_BASIC_AUTH_CINDY", "")
        if self.github_token_cindy and not self.github_basic_auth_cindy:
            import base64
            auth_str = f"x-access-token:{self.github_token_cindy}"
            self.github_basic_auth_cindy = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

        self._cindy_ips = set()
        self._last_dns_check = 0.0
        self._dns_ttl = 15.0  # refresh container IP every 15 seconds

    def _resolve_cindy_ips(self) -> set:
        now = time.time()
        if self._cindy_ips and (now - self._last_dns_check) < self._dns_ttl:
            return self._cindy_ips

        ips = set()
        hostnames = [
            "brainsos-agent-cindy-pawford",
            "brainsos-agent-bawtford",
            "agent-bawtford",
            "bawtford",
        ]
        for host in hostnames:
            try:
                ip = socket.gethostbyname(host)
                if ip:
                    ips.add(ip)
            except Exception:
                pass

        if ips:
            self._cindy_ips = ips
            self._last_dns_check = now

        return self._cindy_ips

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host.lower()
        if host not in ("github.com", "api.github.com"):
            return

        client_address = getattr(flow.client_conn, "peername", None) or getattr(flow.client_conn, "address", None)
        client_ip = client_address[0] if client_address else ""
        cindy_ips = self._resolve_cindy_ips()

        # Check if caller matches Cindy Pawford container
        if client_ip and client_ip in cindy_ips:
            if host == "github.com":
                if self.github_basic_auth_cindy:
                    flow.request.headers["Authorization"] = f"Basic {self.github_basic_auth_cindy}"
                    logger.info(f"[AUTH-INJECT] Injected Git Basic Auth for Cindy Pawford ({client_ip}) -> {flow.request.url}")
                else:
                    logger.warning("[AUTH-WARN] GITHUB_BASIC_AUTH_CINDY is not configured")
            elif host == "api.github.com":
                if self.github_token_cindy:
                    flow.request.headers["Authorization"] = f"Bearer {self.github_token_cindy}"
                    logger.info(f"[AUTH-INJECT] Injected API Bearer Token for Cindy Pawford ({client_ip}) -> {flow.request.url}")
                else:
                    logger.warning("[AUTH-WARN] GITHUB_TOKEN_CINDY is not configured")
            return

        # Unauthorized tenant container: reject with 403 Forbidden
        logger.warning(
            f"[AUTH-DENY] Rejected unauthorized GitHub egress request from {client_ip} to {flow.request.url}"
        )
        flow.response = http.Response.make(
            403,
            b"403 Forbidden: Egress credential injection not permitted for this tenant.\n",
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    def response(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host.lower()
        if host in ("github.com", "api.github.com"):
            if "Authorization" in flow.request.headers:
                flow.request.headers["Authorization"] = "[INJECTED_CINDY_TOKEN]"

    def error(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host.lower()
        if host in ("github.com", "api.github.com"):
            if "Authorization" in flow.request.headers:
                flow.request.headers["Authorization"] = "[INJECTED_CINDY_TOKEN]"


addons = [GitHubAuthAddon()]
