"""LiteLLM Model Catalog Discovery."""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


def fetch_litellm_models(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> List[Dict[str, Any]]:
    """Query LiteLLM /v1/models endpoint."""
    if base_url is None:
        base_url = os.environ.get("OPENAI_API_BASE", "http://litellm:4000/v1")
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", [])
    except Exception as e:
        return [{"id": "error", "mode": str(e)}]


def format_models(models: List[Dict[str, Any]]) -> str:
    """Format model list into terminal output."""
    BOLD = "\033[1m"
    CYAN = "\033[0;36m"
    DIM = "\033[2m"
    NC = "\033[0m"

    lines = [f"{CYAN}{BOLD}Registered LiteLLM Models:{NC}"]
    for m in models:
        mid = m.get("id", "unknown")
        mode = m.get("mode")
        if mode:
            lines.append(f"  • {BOLD}{mid}{NC} {DIM}({mode}){NC}")
        else:
            lines.append(f"  • {BOLD}{mid}{NC}")
    return "\n".join(lines)


def main():
    models = fetch_litellm_models()
    print(format_models(models))


if __name__ == "__main__":
    main()
