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
import logging
from typing import Any

from providers import _REGISTRY, register_provider  # type: ignore[attr-defined]

logger = logging.getLogger("brainsos.hermes.litellm_session")

# LiteLLM per-request flag (litellm_params["no-log"]): skips logging callbacks except proxy spend tracking.
NO_LOG_FIELD = "no-log"

_base = _REGISTRY.get("custom")

if _base is None:  # pragma: no cover - bundled provider missing
    logger.warning("brainsOS litellm-session plugin: bundled 'custom' provider not found; skipping")
else:
    _BaseCls = type(_base)

    class BrainsOSLiteLLMSessionProfile(_BaseCls):  # type: ignore[misc, valid-type]
        """``custom`` provider + LiteLLM tags + ``no-log`` (Hermes owns the Langfuse trace)."""

        def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
            body = dict(super().build_extra_body(session_id=session_id, **context) or {})
            metadata = dict(body.get("metadata") or {})
            metadata.setdefault("tags", ["hermes", "brainsos"])
            body["metadata"] = metadata
            body[NO_LOG_FIELD] = True
            return body

    _fields = {f.name: getattr(_base, f.name) for f in dataclasses.fields(_base) if f.init}
    register_provider(BrainsOSLiteLLMSessionProfile(**_fields))
    logger.info("brainsOS litellm-session plugin: 'custom' provider configured (tags + no-log)")
