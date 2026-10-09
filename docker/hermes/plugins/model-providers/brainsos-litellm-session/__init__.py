"""brainsOS: propagate the Hermes session id to LiteLLM Langfuse traces (Ticket #295).

Hermes' bundled ``custom`` provider (used to reach the LiteLLM gateway) does not forward the
agent session to the upstream request, so LiteLLM's Langfuse callback records every generation
with ``session_id = NULL``. LiteLLM reads ``metadata.session_id`` / ``metadata.tags`` from the
request body, so this user provider plugin re-registers ``custom`` with an identical wire policy
plus that metadata. Hermes loads ``$HERMES_HOME/plugins/model-providers/*`` after bundled
providers, and ``register_provider`` is last-writer-wins.

Main-loop LLM calls pass ``session_id`` (the canonical ``mail-<agent>-<thread>`` key sent by the
brainsOS worker via ``POST /v1/runs``); auxiliary calls without a session are left untouched.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from providers import _REGISTRY, register_provider  # type: ignore[attr-defined]

logger = logging.getLogger("brainsos.hermes.litellm_session")

_base = _REGISTRY.get("custom")

if _base is None:  # pragma: no cover - bundled provider missing
    logger.warning("brainsOS litellm-session plugin: bundled 'custom' provider not found; skipping")
else:
    _BaseCls = type(_base)

    class BrainsOSLiteLLMSessionProfile(_BaseCls):  # type: ignore[misc, valid-type]
        """``custom`` provider + LiteLLM tags (session_id omitted to prevent LiteLLM root trace fragmentation)."""

        def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
            body = dict(super().build_extra_body(session_id=session_id, **context) or {})
            metadata = dict(body.get("metadata") or {})
            metadata.setdefault("tags", ["hermes", "brainsos"])
            body["metadata"] = metadata
            return body

    _fields = {f.name: getattr(_base, f.name) for f in dataclasses.fields(_base) if f.init}
    register_provider(BrainsOSLiteLLMSessionProfile(**_fields))
    logger.info("brainsOS litellm-session plugin: 'custom' provider configured with hermes tags")
