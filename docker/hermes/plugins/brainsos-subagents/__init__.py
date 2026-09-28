"""brainsos-subagents plugin — brainsOS Generic Sub-Agent Dispatcher & Tool Registration.

Discovers declared subagents from subagents.json and dynamically registers native
Hermes tools with structured schemas, delegating execution to unpolluted sub-agent
personas with automated quality gates and OKF memory audit logging.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("brainsos-subagents")

__all__ = ["register"]


def find_subagents_config() -> Optional[List[Dict[str, Any]]]:
    """Find and load subagents.json from standard workspace search paths."""
    candidates = [
        Path("/opt/data/subagents.json"),
        Path("/workspace/subagents.json"),
        Path("/memories/subagents.json"),
        Path(__file__).resolve().parent / "subagents.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                with open(c, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception as e:
                logger.warning("Failed to parse %s: %s", c, e)
    return None


def create_tool_handler(subagent_def: Dict[str, Any]) -> Callable[..., str]:
    """Factory creating a native tool handler for a declared subagent."""
    sub_id = subagent_def.get("id", "subagent")
    tool_name = subagent_def.get("tool_name", f"invoke_{sub_id}")
    target_dir = subagent_def.get("target_dir", "/app/html")
    persona_path = subagent_def.get("persona")
    model = subagent_def.get("model", "cindy-active-coding-model")

    def handler(**kwargs: Any) -> str:
        logger.info("Invoking subagent '%s' (tool: %s) with params: %s", sub_id, tool_name, list(kwargs.keys()))

        # If this is a web developer subagent, invoke cindy-web-builder
        feature_name = kwargs.get("feature_name", "Autonomous Web Feature")
        specification = kwargs.get("specification", "")
        target_files = kwargs.get("target_files", ["index.html", "styles.css", "app.js"])
        design_tokens = kwargs.get("design_tokens", None)

        # Locate execution engine script
        script_candidates = [
            Path("/opt/hermes/scripts/apps/cindypawford/cindy-web-builder.py"),
            Path("/workspace/scripts/apps/cindypawford/cindy-web-builder.py"),
            Path(__file__).resolve().parents[4] / "scripts" / "apps" / "cindypawford" / "cindy-web-builder.py",
        ]
        builder_script = None
        for sc in script_candidates:
            if sc.exists():
                builder_script = sc
                break

        if builder_script:
            cmd = [
                sys.executable,
                str(builder_script),
                "--feature-name", str(feature_name),
                "--specification", str(specification),
                "--canvas-dir", str(target_dir),
                "--model", str(model),
            ]
            if target_files:
                cmd.append("--target-files")
                cmd.extend(target_files if isinstance(target_files, list) else [str(target_files)])
            if design_tokens:
                cmd.extend(["--design-tokens", json.dumps(design_tokens) if isinstance(design_tokens, (dict, list)) else str(design_tokens)])
            if persona_path:
                cmd.extend(["--persona-path", str(persona_path)])

            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if proc.returncode == 0:
                    try:
                        res_json = json.loads(proc.stdout)
                        return (
                            f"✅ Sub-Agent Execution Succeeded ({sub_id}):\n\n"
                            f"- Feature: {res_json.get('feature_name')}\n"
                            f"- Modified: {', '.join(res_json.get('modified_files', [])) or 'None'}\n"
                            f"- OKF Log: {res_json.get('log_path')}\n\n"
                            f"Diff Summary:\n{res_json.get('diff_summary') or 'No file diffs.'}"
                        )
                    except Exception:
                        return proc.stdout or "Sub-agent execution succeeded."
                else:
                    return f"❌ Sub-Agent Execution Failed ({sub_id}): {proc.stderr or proc.stdout}"
            except Exception as exc:
                return f"❌ Sub-Agent Error ({sub_id}): {exc}"

        return f"❌ Execution script for sub-agent '{sub_id}' could not be located."

    return handler


def build_tool_schema(subagent_def: Dict[str, Any]) -> Dict[str, Any]:
    """Construct JSON Schema from declared subagent parameters."""
    tool_name = subagent_def.get("tool_name", f"invoke_{subagent_def.get('id', 'subagent')}")
    description = subagent_def.get("description", f"Invoke subagent {subagent_def.get('name', tool_name)}")
    params_decl = subagent_def.get("parameters", {})

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for p_name, p_spec in params_decl.items():
        p_type = p_spec.get("type", "string")
        if p_type == "array":
            properties[p_name] = {
                "type": "array",
                "items": {"type": "string"},
                "description": p_spec.get("description", ""),
            }
        elif p_type == "object":
            properties[p_name] = {
                "type": "object",
                "description": p_spec.get("description", ""),
            }
        else:
            properties[p_name] = {
                "type": "string",
                "description": p_spec.get("description", ""),
            }

        if p_spec.get("required", False):
            required.append(p_name)

    return {
        "name": tool_name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def register(ctx: Any) -> None:
    """Register dynamic subagent tools with Hermes Agent plugin loader."""
    logger.info("Initializing brainsos-subagents plugin...")
    subagents = find_subagents_config()
    if not subagents:
        logger.info("No subagents.json found in active workspace; skipping tool registration.")
        return

    for sub in subagents:
        tool_name = sub.get("tool_name")
        if not tool_name:
            continue
        schema = build_tool_schema(sub)
        handler = create_tool_handler(sub)
        desc = sub.get("description", f"Invoke subagent {sub.get('name', tool_name)}")

        try:
            ctx.register_tool(
                name=tool_name,
                toolset="brainsos-subagents",
                schema=schema,
                handler=handler,
                description=desc,
                emoji="🤖",
            )
            logger.info("Registered subagent tool: %s (%s)", tool_name, sub.get("name"))
        except Exception as e:
            logger.warning("Failed to register subagent tool %s: %s", tool_name, e)
