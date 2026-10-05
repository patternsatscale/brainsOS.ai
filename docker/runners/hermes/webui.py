"""Hermes Runner Interactive WebUI and Configuration Server (Port 8787)."""

import os
import json
import yaml
from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="brainsOS Hermes Runner WebUI", version="1.0.0")

CONFIG_DIR = Path(os.getenv("HERMES_HOME", "/root/.hermes"))
CONFIG_YAML_PATH = CONFIG_DIR / "config.yaml"
CONFIG_JSON_PATH = CONFIG_DIR / "config.json"


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
async def get_config():
    yaml_cfg = load_yaml_config()
    json_cfg = load_json_config()
    return {
        "yaml": yaml_cfg,
        "json": json_cfg,
        "config_dir": str(CONFIG_DIR),
    }


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
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
async def serve_ui():
    yaml_cfg = load_yaml_config()
    json_cfg = load_json_config()

    default_model = yaml_cfg.get("model", {}).get("default", "brainsos-core")
    base_url = yaml_cfg.get("model", {}).get("base_url", "http://litellm:4000/v1")
    terminal_on = json_cfg.get("capabilities", {}).get("shell_enabled", True)
    browser_on = json_cfg.get("capabilities", {}).get("browser_enabled", True)
    web_search_on = yaml_cfg.get("tools", {}).get("web_search", {}).get("enabled", False)

    html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <title>brainsOS • Hermes Runner WebUI</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ background: #07090E; color: #e1e2eb; font-family: 'Geist', sans-serif; }}
    .card {{ background: rgba(17, 22, 34, 0.85); backdrop-filter: blur(24px); border: 1px solid rgba(255,255,255,0.08); }}
  </style>
</head>
<body class="p-6 sm:p-10 min-h-screen flex flex-col justify-between">
  <div class="max-w-3xl mx-auto w-full">
    <!-- Header -->
    <header class="flex items-center justify-between border-b border-white/10 pb-5 mb-8">
      <div>
        <div class="flex items-center gap-3">
          <span class="font-mono text-2xl font-bold tracking-wider text-white">HERMES<span class="text-[#00f2fe]">.RUNNER</span></span>
          <span class="text-[10px] font-mono bg-[#00f2fe]/10 text-[#00f2fe] px-2 py-0.5 rounded border border-[#00f2fe]/20">WEBUI :8787</span>
        </div>
        <p class="font-mono text-xs text-slate-400 mt-1">Runtime Configuration &amp; Tool Governance Dashboard</p>
      </div>
      <div class="flex items-center gap-2 font-mono text-xs text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
        <span>GATEWAY ONLINE</span>
      </div>
    </header>

    <!-- Configuration Form -->
    <form id="cfg-form" onsubmit="saveConfig(event)" class="space-y-6">
      
      <!-- Section 1: Provider & LiteLLM Gateway -->
      <div class="card rounded-2xl p-6 shadow-xl">
        <h2 class="font-mono text-xs uppercase tracking-widest text-[#00f2fe] font-semibold mb-4">Inference Gateway (Rule 2)</h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block font-mono text-xs text-slate-400 mb-1">LiteLLM Base URL</label>
            <input id="base_url" type="text" value="{base_url}" class="w-full bg-[#0B0E14] border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-[#00f2fe] outline-none">
          </div>
          <div>
            <label class="block font-mono text-xs text-slate-400 mb-1">Default Model Endpoint</label>
            <input id="default_model" type="text" value="{default_model}" class="w-full bg-[#0B0E14] border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-[#00f2fe] outline-none">
          </div>
        </div>
      </div>

      <!-- Section 2: Capability & Tool Governance -->
      <div class="card rounded-2xl p-6 shadow-xl">
        <h2 class="font-mono text-xs uppercase tracking-widest text-[#ec4899] font-semibold mb-4">Toolsets &amp; Sandboxed Capabilities</h2>
        <div class="space-y-3">
          <label class="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5 cursor-pointer hover:bg-white/[0.04] transition-all">
            <div>
              <div class="text-xs font-semibold text-white">Interactive Terminal Execution</div>
              <div class="text-[11px] text-slate-400">Allows sandboxed bash commands in /workspace</div>
            </div>
            <input id="tool_terminal" type="checkbox" {'checked' if terminal_on else ''} class="w-4 h-4 accent-[#00f2fe]">
          </label>

          <label class="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5 cursor-pointer hover:bg-white/[0.04] transition-all">
            <div>
              <div class="text-xs font-semibold text-white">Automated Browser &amp; Scraping</div>
              <div class="text-[11px] text-slate-400">Headless browser actions routed via egress proxy</div>
            </div>
            <input id="tool_browser" type="checkbox" {'checked' if browser_on else ''} class="w-4 h-4 accent-[#00f2fe]">
          </label>

          <label class="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5 cursor-pointer hover:bg-white/[0.04] transition-all">
            <div>
              <div class="text-xs font-semibold text-white">External Web Search</div>
              <div class="text-[11px] text-slate-400">Toggles live DuckDuckGo/Brave web search tool</div>
            </div>
            <input id="tool_search" type="checkbox" {'checked' if web_search_on else ''} class="w-4 h-4 accent-[#00f2fe]">
          </label>
        </div>
      </div>

      <!-- Action Button -->
      <div class="flex items-center justify-between pt-2">
        <span id="save-status" class="font-mono text-xs text-slate-400"></span>
        <button type="submit" class="px-6 py-2.5 rounded-xl bg-[#00f2fe] hover:bg-[#38f8ff] text-black font-mono font-bold text-xs uppercase tracking-wider transition-all shadow-[0_0_15px_rgba(0,242,254,0.3)]">
          Save Configuration
        </button>
      </div>

    </form>
  </div>

  <footer class="text-center font-mono text-[11px] text-slate-600 mt-10">
    brainsOS • ASUS Ascent GX10 (ARM64) • Rule 4 Sandboxed
  </footer>

  <script>
    async function saveConfig(e) {{
      e.preventDefault();
      const status = document.getElementById('save-status');
      status.innerText = "Saving...";
      status.className = "font-mono text-xs text-[#00f2fe]";

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
        if (resp.ok) {{
          status.innerText = "✓ Settings saved to /root/.hermes. Run 'make runner-hermes' to burn.";
          status.className = "font-mono text-xs text-emerald-400";
        }} else {{
          status.innerText = "Error saving settings.";
          status.className = "font-mono text-xs text-rose-400";
        }}
      }} catch (err) {{
        status.innerText = "Network failure: " + err;
        status.className = "font-mono text-xs text-rose-400";
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8787)
