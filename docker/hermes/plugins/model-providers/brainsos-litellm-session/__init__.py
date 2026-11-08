"""brainsOS: Hermes -> LiteLLM request shaping for unified Langfuse tracing (Tickets #295, #299).

Hermes' ``observability/langfuse`` plugin already records every LLM call as a ``LLM call N``
generation on the per-thread Hermes trace. If LiteLLM's Langfuse callback also logged those
requests, every call would appear twice (once as a disconnected root trace). This user provider
plugin re-registers Hermes' bundled ``custom`` provider (used to reach the LiteLLM gateway) with
an identical wire policy plus:

* ``"no-log": true`` — LiteLLM skips non-proxy logging callbacks (``langfuse_otel``) for this
  request while proxy cost/spend tracking callbacks still run. Callers that do not set it (IDE
  clients, direct API users) remain fully traced by LiteLLM.
* ``metadata.tags`` — ``["hermes", "brainsos"]`` for LiteLLM spend-log attribution.

``metadata.session_id`` is intentionally not forwarded. Hermes loads
``$HERMES_HOME/plugins/model-providers/*`` after bundled providers, and ``register_provider`` is
last-writer-wins.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import logging
import os
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
        """``custom`` provider + LiteLLM tags + ``no-log`` + per-agent virtual key attribution."""

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

            vkey = _resolve_agent_virtual_key(context.get("session_id"))
            if vkey:
                headers = dict(top_level.get("extra_headers") or {})
                headers.setdefault("Authorization", f"Bearer {vkey}")
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

    logger.info("brainsOS litellm-session plugin: 'custom' provider configured (tags + no-log)")
