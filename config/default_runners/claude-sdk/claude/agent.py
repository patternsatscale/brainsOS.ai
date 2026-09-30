"""Claude SDK Demo Agent: Tells jokes about Claude.

Dynamically calls the LLM via the Anthropic Claude SDK to generate a joke.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("brainsos.runners.claude.claude_agent")

SYSTEM_PROMPT = (
    "You are Claude Demo Agent <claude@brainsos.local>. "
    "When asked for a joke, tell a single short, witty, hilarious joke about Claude, "
    "Anthropic, Constitutional AI, or massive context windows. Keep it polite, harmless, and punchy."
)


async def handle_turn(request: Any, client: Any) -> str:
    """Executes a cognitive turn using the Anthropic Claude SDK to generate a dynamic joke."""
    model = getattr(request, "model", None) or os.getenv("CLAUDE_DEFAULT_MODEL", "gemma2:2b")

    # Extract user prompt from conversation
    user_prompt = "Tell me a joke about Claude!"
    conversation = getattr(request, "conversation", [])
    if conversation:
        last_msg = conversation[-1]
        msg_content = getattr(last_msg, "content", "")
        if msg_content:
            user_prompt = msg_content

    # Call LLM through the Anthropic Claude SDK
    logger.info("Calling Anthropic Claude SDK (model: %s) to generate Claude joke...", model)
    response = await client.messages.create(
        model=model,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if response and getattr(response, "content", None):
        for block in response.content:
            if getattr(block, "type", "") == "text" and block.text:
                return block.text.strip()

    return "Claude was asked to tell a short joke, but first generated a 10-page ethical safety review of humor."
