"""OpenAI SDK Demo Agent: Tells jokes about Sam Altman.

Dynamically calls the LLM via the OpenAI SDK to generate a joke.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("brainsos.runners.openai.gpt_agent")

SYSTEM_PROMPT = (
    "You are GPT Demo Agent <gpt@brainsos.local>. "
    "When asked for a joke, tell a single short, witty, hilarious joke about Sam Altman, "
    "OpenAI, compute clusters, Worldcoin, or the tech industry. Keep it punchy."
)


async def handle_turn(request: Any, client: Any) -> str:
    """Executes a cognitive turn using the OpenAI SDK to generate a dynamic joke."""
    model = getattr(request, "model", None) or os.getenv("TEST_RUNNER_MODEL", "gemma2:2b")

    # Extract user prompt from conversation
    user_prompt = "Tell me a joke about Sam Altman!"
    conversation = getattr(request, "conversation", [])
    if conversation:
        last_msg = conversation[-1]
        msg_content = getattr(last_msg, "content", "")
        if msg_content:
            user_prompt = msg_content

    # Call LLM through the OpenAI SDK
    logger.info("Calling OpenAI SDK (model: %s) to generate Sam Altman joke...", model)
    completion = await client.chat.completions.create(
        model=model,
        max_tokens=256,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
    )
    if completion and completion.choices:
        reply = completion.choices[0].message.content
        if reply and reply.strip():
            return reply.strip()

    return "Sam Altman just raised another billion dollars while you were waiting for this punchline."
