"""brainsOS: Hermes -> LiteLLM request shaping for unified Langfuse & Lens tracing (#295, #299, #375).

Hermes' ``observability/langfuse`` plugin records every LLM call and tool execution across both
Langfuse and LiteLLM Lens. This provider plugin re-registers Hermes' bundled ``custom`` provider
(used to reach the LiteLLM gateway) with an identical wire policy plus:

* ``"no-log": true`` — LiteLLM skips duplicate ``langfuse_otel`` root traces while proxy spend
  tracking (``_ProxyDBLogger``) and LiteLLM Lens spend shipping (``LensExporter``) still run.
* ``metadata.tags`` — ``["hermes", "brainsos"]`` for LiteLLM spend-log attribution.
* ``extra_headers["traceparent"]`` — W3C Trace Context ``00-<trace_id>-<span_id>-01`` so LiteLLM's
  ``spend_logs`` correlate 1:1 with the Hermes Lens OTLP ``gateway.request`` / ``chat`` spans even
  on streaming completions where the hook payload omits ``response.id``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import logging
import os
import secrets
from pathlib import Path
from typing import Any

import providers  # type: ignore[import-not-found]
from providers import _REGISTRY, register_provider  # type: ignore[attr-defined]

logger = logging.getLogger("brainsos.hermes.litellm_session")

# LiteLLM per-request flag (litellm_params["no-log"]): skips logging callbacks except proxy spend tracking.
NO_LOG_FIELD = "no-log"

_AGENT_KEY_ENV_MAP = {
    "bawtford": "BAWTFORD_LITELLM_KEY",
    "terrastella": "TERRASTELLA_LITELLM_KEY",
    "marvin": "MARVIN_LITELLM_KEY",
}


def _resolve_session_id(session_id: str | None) -> str:
    sid = (session_id or "").strip()
    if sid:
        return sid
    try:
        from agent.portal_tags import get_conversation_context  # type: ignore[import-not-found]

        ctx = get_conversation_context() or {}
        return str(ctx.get("session_id") or "").strip()
    except Exception:
        return ""


def _deterministic_trace_id(session_id: str | None) -> str:
    sid = _resolve_session_id(session_id) or "sessionless"
    seed = f"{sid}::{sid}"
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16].hex()


def _resolve_agent_virtual_key(session_id: str | None) -> str | None:
    """Resolve the tenant virtual key for a Hermes session_id (e.g. 'mail-bawtford-...')."""
    sid = _resolve_session_id(session_id).lower()
    for agent_id, env_var in _AGENT_KEY_ENV_MAP.items():
        if sid.startswith(f"mail-{agent_id}-") or f"-{agent_id}-" in sid or sid == agent_id:
            val = (os.environ.get(env_var) or "").strip()
            if val:
                return val
    default_vkey = (os.environ.get("BAWTFORD_LITELLM_KEY") or "").strip()
    return default_vkey or None


def _ensure_bundled_custom_provider() -> Any:
    base = _REGISTRY.get("custom")
    if base is not None:
        return base
    bundled_custom = Path(__file__).resolve().parent.parent / "custom" / "__init__.py"
    if not bundled_custom.is_file():
        bundled_custom = Path("/opt/hermes/plugins/model-providers/custom/__init__.py")
    if bundled_custom.is_file():
        try:
            spec = importlib.util.spec_from_file_location("_hermes_bundled_custom_provider", bundled_custom)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
        except Exception as exc:
            logger.debug("brainsOS litellm-session plugin: eager custom provider load failed: %s", exc)
    return _REGISTRY.get("custom")


_base = _ensure_bundled_custom_provider()

if _base is None:  # pragma: no cover - bundled provider missing
    logger.warning("brainsOS litellm-session plugin: bundled 'custom' provider not found; skipping")
else:
    _BaseCls = type(_base)

    class BrainsOSLiteLLMSessionProfile(_BaseCls):  # type: ignore[misc, valid-type]
        """``custom`` provider + LiteLLM tags + ``no-log`` + ``traceparent`` + per-agent virtual key."""

        def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
            body = dict(super().build_extra_body(session_id=session_id, **context) or {})
            metadata = dict(body.get("metadata") or {})
            metadata.setdefault("tags", ["hermes", "brainsos"])
            body["metadata"] = metadata
            body[NO_LOG_FIELD] = True
            return body

        def build_api_kwargs_extras(
            self,
            *,
            reasoning_config: dict | None = None,
            **context: Any,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            parent_fn = getattr(super(), "build_api_kwargs_extras", None)
            if callable(parent_fn):
                extra_body, top_level = parent_fn(reasoning_config=reasoning_config, **context)
                extra_body = dict(extra_body or {})
                top_level = dict(top_level or {})
            else:
                extra_body, top_level = {}, {}

            headers = dict(top_level.get("extra_headers") or {})
            sid = context.get("session_id")
            vkey = _resolve_agent_virtual_key(sid)
            if vkey:
                headers.setdefault("Authorization", f"Bearer {vkey}")

            # Propagate W3C traceparent so LiteLLM spend_logs link deterministically to Lens OTLP spans (#375).
            trace_id = _deterministic_trace_id(sid)
            transport_span_id = secrets.token_hex(8)
            headers.setdefault("traceparent", f"00-{trace_id}-{transport_span_id}-01")
            top_level["extra_headers"] = headers
            return extra_body, top_level

    def _wrap_custom_profile(profile_obj: Any) -> Any:
        if isinstance(profile_obj, BrainsOSLiteLLMSessionProfile):
            return profile_obj
        fields = {f.name: getattr(profile_obj, f.name) for f in dataclasses.fields(profile_obj) if f.init}
        return BrainsOSLiteLLMSessionProfile(**fields)

    register_provider(_wrap_custom_profile(_base))

    # Guard against bundled plugin alphabetical load order ('brainsos-litellm-session' < 'custom'):
    # if bundled 'custom' registers after us during _discover_providers(), keep it wrapped.
    _orig_register = getattr(providers, "register_provider", None)
    if callable(_orig_register) and not getattr(_orig_register, "_brainsos_wrapped", False):

        def _guarded_register_provider(profile_obj: Any) -> Any:
            if getattr(profile_obj, "name", None) == "custom" and not isinstance(
                profile_obj, BrainsOSLiteLLMSessionProfile
            ):
                profile_obj = _wrap_custom_profile(profile_obj)
            return _orig_register(profile_obj)

        _guarded_register_provider._brainsos_wrapped = True  # type: ignore[attr-defined]
        providers.register_provider = _guarded_register_provider  # type: ignore[attr-defined]

    logger.info("brainsOS litellm-session plugin: 'custom' provider configured (tags + no-log + traceparent)")
