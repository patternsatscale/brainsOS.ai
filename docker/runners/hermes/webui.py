"""Hermes Runner Interactive WebUI and Configuration Server (Port 8787)."""

import html as html_lib
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="brainsOS Hermes Runner WebUI", version="1.0.0")

CONFIG_DIR = Path((os.getenv("HERMES_HOME") or "").strip() or "/tmp/.hermes")
CONFIG_YAML_PATH = CONFIG_DIR / "config.yaml"
CONFIG_JSON_PATH = CONFIG_DIR / "config.json"


def _require_runner_auth(request: Request) -> None:
    expected = (os.getenv("RUNNER_AUTH_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Service Unavailable: RUNNER_AUTH_TOKEN is not configured")
    x_token = (request.headers.get("X-Runner-Token") or "").strip()
    auth_hdr = (request.headers.get("Authorization") or "").strip()
    bearer_tok = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
    provided = x_token or bearer_tok
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-Runner-Token / Authorization")


def load_yaml_config() -> Dict[str, Any]:
    if CONFIG_YAML_PATH.is_file():
        try:
            with open(CONFIG_YAML_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            return {"error": f"Failed to parse config.yaml: {e}"}
    return {}


def load_json_config() -> Dict[str, Any]:
    if CONFIG_JSON_PATH.is_file():
        try:
            with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": f"Failed to parse config.json: {e}"}
    return {}


class ConfigUpdateRequest(BaseModel):
    provider_base_url: str = "http://litellm:4000/v1"
    model_default: str = "brainsos-core"
    terminal_enabled: bool = True
    browser_enabled: bool = True
    web_search_enabled: bool = False
    tool_search_enabled: bool = False


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hermes-runner-webui", "port": 8787}


@app.get("/api/config")
async def get_config(request: Request):
    _require_runner_auth(request)
    yaml_cfg = load_yaml_config()
    json_cfg = load_json_config()
    return {
        "yaml": yaml_cfg,
        "json": json_cfg,
        "config_dir": str(CONFIG_DIR),
    }


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest, request: Request):
    _require_runner_auth(request)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Update config.yaml
    yaml_cfg = load_yaml_config()
    if "model" not in yaml_cfg or not isinstance(yaml_cfg["model"], dict):
        yaml_cfg["model"] = {}
    yaml_cfg["model"]["default"] = req.model_default
    yaml_cfg["model"]["base_url"] = req.provider_base_url

    if "providers" not in yaml_cfg or not isinstance(yaml_cfg["providers"], dict):
        yaml_cfg["providers"] = {}
    if "custom" not in yaml_cfg["providers"]:
        yaml_cfg["providers"]["custom"] = {}
    yaml_cfg["providers"]["custom"]["base_url"] = req.provider_base_url

    if "tools" not in yaml_cfg or not isinstance(yaml_cfg["tools"], dict):
        yaml_cfg["tools"] = {}
    yaml_cfg["tools"]["web_search"] = {"enabled": req.web_search_enabled}
    yaml_cfg["tools"]["tool_search"] = {"enabled": "on" if req.tool_search_enabled else "off"}

    with open(CONFIG_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_cfg, f, default_flow_style=False, sort_keys=False)

    # 2. Update config.json
    json_cfg = load_json_config()
    if "llm" not in json_cfg or not isinstance(json_cfg["llm"], dict):
        json_cfg["llm"] = {}
    json_cfg["llm"]["base_url"] = req.provider_base_url
    json_cfg["llm"]["model"] = req.model_default

    if "capabilities" not in json_cfg or not isinstance(json_cfg["capabilities"], dict):
        json_cfg["capabilities"] = {}
    json_cfg["capabilities"]["shell_enabled"] = req.terminal_enabled
    json_cfg["capabilities"]["browser_enabled"] = req.browser_enabled

    with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(json_cfg, f, indent=2)

    return {"status": "success", "message": "Hermes runner configuration updated successfully."}


@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    _require_runner_auth(request)
    yaml_cfg = load_yaml_config()
    json_cfg = load_json_config()

    default_model = html_lib.escape(str(yaml_cfg.get("model", {}).get("default", "brainsos-core")), quote=True)
    base_url = html_lib.escape(str(yaml_cfg.get("model", {}).get("base_url", "http://litellm:4000/v1")), quote=True)
    terminal_on = bool(json_cfg.get("capabilities", {}).get("shell_enabled", True))
    browser_on = bool(json_cfg.get("capabilities", {}).get("browser_enabled", True))
    web_search_on = bool(yaml_cfg.get("tools", {}).get("web_search", {}).get("enabled", False))

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>brainsOS • Hermes Runner WebUI</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; padding: 2rem; background: #07090E; color: #e1e2eb; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
    .wrap {{ max-width: 768px; margin: 0 auto; }}
    .card {{ background: rgba(17, 22, 34, 0.92); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 1.5rem; margin-bottom: 1.25rem; }}
    .hdr {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 1rem; margin-bottom: 1.5rem; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }}
    label.field {{ display: block; font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.35rem; }}
    input[type="text"] {{ width: 100%; box-sizing: border-box; background: #0B0E14; border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 0.5rem 0.75rem; color: #fff; font-size: 0.8rem; }}
    label.toggle {{ display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); margin-bottom: 0.6rem; }}
    button {{ padding: 0.65rem 1.4rem; border: 0; border-radius: 10px; background: #00f2fe; color: #000; font-weight: 700; cursor: pointer; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hdr">
      <div>
        <div class="mono" style="font-size:1.35rem;font-weight:700;">HERMES<span style="color:#00f2fe;">.RUNNER</span></div>
        <div class="mono" style="font-size:0.75rem;color:#94a3b8;">Runtime Configuration &amp; Tool Governance Dashboard</div>
      </div>
      <div class="mono" style="font-size:0.75rem;color:#34d399;">GATEWAY ONLINE</div>
    </header>
    <form id="cfg-form" onsubmit="saveConfig(event)">
      <div class="card">
        <h2 class="mono" style="font-size:0.75rem;text-transform:uppercase;color:#00f2fe;margin-top:0;">Inference Gateway (Rule 2)</h2>
        <div class="grid">
          <div>
            <label class="field mono" for="base_url">LiteLLM Base URL</label>
            <input id="base_url" type="text" value="{base_url}">
          </div>
          <div>
            <label class="field mono" for="default_model">Default Model Endpoint</label>
            <input id="default_model" type="text" value="{default_model}">
          </div>
        </div>
      </div>
      <div class="card">
        <h2 class="mono" style="font-size:0.75rem;text-transform:uppercase;color:#ec4899;margin-top:0;">Toolsets &amp; Sandboxed Capabilities</h2>
        <label class="toggle"><span>Interactive Terminal Execution</span><input id="tool_terminal" type="checkbox" {'checked' if terminal_on else ''}></label>
        <label class="toggle"><span>Automated Browser &amp; Scraping</span><input id="tool_browser" type="checkbox" {'checked' if browser_on else ''}></label>
        <label class="toggle"><span>External Web Search</span><input id="tool_search" type="checkbox" {'checked' if web_search_on else ''}></label>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span id="save-status" class="mono" style="font-size:0.75rem;color:#94a3b8;"></span>
        <button type="submit" class="mono">Save Configuration</button>
      </div>
    </form>
  </div>
  <script>
    async function saveConfig(e) {{
      e.preventDefault();
      const status = document.getElementById('save-status');
      status.innerText = "Saving...";
      const payload = {{
        provider_base_url: document.getElementById('base_url').value,
        model_default: document.getElementById('default_model').value,
        terminal_enabled: document.getElementById('tool_terminal').checked,
        browser_enabled: document.getElementById('tool_browser').checked,
        web_search_enabled: document.getElementById('tool_search').checked,
        tool_search_enabled: false
      }};
      try {{
        const resp = await fetch('/api/config', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }});
        status.innerText = resp.ok ? "Settings saved." : ("Error: HTTP " + resp.status);
      }} catch (err) {{
        status.innerText = "Network failure: " + err;
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_doc)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
