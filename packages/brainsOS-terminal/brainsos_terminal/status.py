"""Internal Platform Service Health Probing."""

import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SERVICES: List[Tuple[str, Any, str]] = [
    ("LiteLLM Gateway", "http://litellm:4000/v1/models", "HTTP"),
    ("Caddy Gateway", "http://caddy:80", "HTTP"),
    ("Tool Egress Firewall", "http://brainsos-net-egress-proxy:8081", "HTTP"),
    ("Hermes Runner", "http://runner-hermes:8642", "HTTP"),
    ("OpenAI Runner", "http://runner-openai:8002", "HTTP"),
    ("Mail Server (SMTP)", ("brainsos-net-mail-server", 25), "TCP"),
    ("Mail Server (IMAP)", ("brainsos-net-mail-server", 143), "TCP"),
]


def check_http(url: str, auth_key: str = "", timeout: float = 3.0) -> Tuple[bool, str]:
    """Probe an HTTP/HTTPS endpoint."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "brainsos-status/1.0"})
        if auth_key:
            req.add_header("Authorization", f"Bearer {auth_key}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        # 401, 403, 404, 405 indicate server is up and responding
        if e.code in (401, 403, 404, 405):
            return True, f"HTTP {e.code}"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:30]


def check_tcp(host: str, port: int, timeout: float = 2.0) -> Tuple[bool, str]:
    """Probe a raw TCP socket."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True, "OPEN"
    except Exception as e:
        return False, str(e)[:30]


def probe_all_services(
    services: Optional[List[Tuple[str, Any, str]]] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Probe all configured services and return structured results."""
    if services is None:
        services = DEFAULT_SERVICES
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    results = []
    for name, target, stype in services:
        if stype == "HTTP":
            auth = api_key if "litellm" in str(target) else ""
            ok, msg = check_http(target, auth_key=auth)
        else:
            host, port = target
            ok, msg = check_tcp(host, port)

        results.append(
            {
                "name": name,
                "type": stype,
                "target": target,
                "online": ok,
                "details": msg,
            }
        )
    return results


def format_status_report(results: List[Dict[str, Any]]) -> str:
    """Format probe results into an ANSI-styled report."""
    BOLD = "\033[1m"
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    CYAN = "\033[0;36m"
    DIM = "\033[2m"
    NC = "\033[0m"

    lines = [
        f"\n{CYAN}{BOLD}brainsOS Platform Internal Service Health{NC}",
        f"{DIM}{'─' * 70}{NC}",
        f"{BOLD}{'SERVICE':<28} {'TYPE':<8} {'STATUS':<14} {'DETAILS'}{NC}",
        f"{DIM}{'─' * 70}{NC}",
    ]

    for r in results:
        status_str = f"{GREEN}ONLINE{NC}" if r["online"] else f"{RED}OFFLINE{NC}"
        lines.append(
            f"{BOLD}{r['name']:<28}{NC} {r['type']:<8} {status_str:<22} {DIM}{r['details']}{NC}"
        )

    lines.append(f"{DIM}{'─' * 70}{NC}\n")
    return "\n".join(lines)


def main():
    results = probe_all_services()
    print(format_status_report(results))


if __name__ == "__main__":
    main()
