"""Interactive CLI chat interface to fleet agents."""

import json
import os
import sys
import urllib.error
import urllib.request

AGENT_MAP = {
    "terrastella": {
        "url": "http://api.terrastella.brainsos.local/v1/chat/completions",
        "fallback": "http://host.docker.internal:8642/v1/chat/completions",
        "key_env": "HERMES_API_TERRASTELLA_KEY",
    },
    "marvin": {
        "url": "http://api.marvin.brainsos.local/v1/chat/completions",
        "fallback": "http://host.docker.internal:8643/v1/chat/completions",
        "key_env": "HERMES_API_MARVIN_KEY",
    },
    "bawtford": {
        "url": "http://api.bawtford.brainsos.local/v1/chat/completions",
        "fallback": "http://host.docker.internal:8644/v1/chat/completions",
        "key_env": "HERMES_API_BAWTFORD_KEY",
    },
}


def send_chat_message(agent: str, prompt: str) -> str:
    """Send a chat turn to an agent."""
    if agent not in AGENT_MAP:
        return f"Unknown agent: {agent}. Available: {', '.join(AGENT_MAP.keys())}"

    cfg = AGENT_MAP[agent]
    target_url = cfg["url"]
    auth_key = os.environ.get(cfg["key_env"], "")

    session_id = f"cli-{agent}-{os.getpid()}"
    payload = json.dumps(
        {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": prompt}],
            "metadata": {
                "session_id": session_id,
                "agent_id": agent,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        target_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
            "x-litellm-session-id": session_id,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices and "message" in choices[0]:
                return choices[0]["message"].get("content", "")
            return str(data)
    except urllib.error.HTTPError as e:
        return f"HTTP error {e.code}: {e.read().decode('utf-8')[:200]}"
    except Exception as e:
        return f"Connection error: {e}"


def main():
    if len(sys.argv) < 3:
        print("Usage: brainsos-chat <agent-name> <message>")
        print(f"Available agents: {', '.join(AGENT_MAP.keys())}")
        sys.exit(1)

    agent = sys.argv[1].lower()
    prompt = " ".join(sys.argv[2:])
    response = send_chat_message(agent, prompt)
    print(response)


if __name__ == "__main__":
    main()
