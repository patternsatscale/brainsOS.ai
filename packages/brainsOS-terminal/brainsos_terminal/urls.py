"""Service URL and Credential Directory."""

import os
from typing import Dict, List, Optional


def get_service_directory(env: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Resolve active service names, public URLs, localhost fallbacks, and auth info."""
    if env is None:
        env = dict(os.environ)

    domain = env.get("BRAINSOS_DOMAIN", "brainsos.local")
    mail_domain = env.get("BRAINSOS_MAIL_DOMAIN", f"mail.{domain}")
    caddy_http = env.get("CADDY_HTTP_PORT", "80")
    code_port = env.get("CODE_SERVER_PORT", "8443")
    code_user = env.get("OPERATOR_USER", "operator")
    code_pass = env.get("CODE_SERVER_PASSWORD", "brainsos_operator_secret")

    litellm_port = env.get("LITELLM_PORT", "4000")
    litellm_key = env.get(
        "OPENAI_API_KEY",
        env.get("OPERATOR_LITELLM_KEY", env.get("LITELLM_MASTER_KEY", "sk-brainsos-master-key")),
    )

    sogo_port = env.get("SOGO_PORT", "20000")
    admin_mail_pass = env.get("ADMIN_MAIL_PASSWORD", "admin_mail_pass")

    hermes_runner_port = env.get("HERMES_RUNNER_PORT", "8642")
    openai_runner_port = env.get("OPENAI_RUNNER_PORT", "8002")
    agent_queue_port = env.get("AGENT_QUEUE_PORT", "8000")

    langfuse_port = env.get("LANGFUSE_PORT", "3001")
    langfuse_user = env.get("LANGFUSE_INIT_USER_EMAIL", f"admin@{domain}")
    langfuse_pass = env.get("LANGFUSE_INIT_USER_PASSWORD", "brainsos_admin_secret")

    egress_port = env.get("TOOL_EGRESS_WEB_PORT", "8081")
    egress_pass = env.get("TOOL_EGRESS_WEB_PASSWORD", "brainsos_tool_egress_secret")

    return [
        {
            "name": "Landing Page Portal",
            "public_url": f"https://{domain}",
            "local_url": f"http://localhost:{caddy_http}",
            "auth": "(public)",
        },
        {
            "name": "Operator IDE (VS Code)",
            "public_url": f"https://editor.{domain}",
            "local_url": f"http://localhost:{code_port}",
            "auth": f"user: {code_user} | pass: {code_pass}",
        },
        {
            "name": "Webmail & SOGo Groupware",
            "public_url": f"https://{mail_domain}",
            "local_url": f"http://localhost:{sogo_port}",
            "auth": f"user: admin@{domain} | pass: {admin_mail_pass}",
        },
        {
            "name": "LiteLLM Proxy Admin UI",
            "public_url": f"https://proxy.{domain}/ui",
            "local_url": f"http://localhost:{litellm_port}/ui",
            "auth": f"key: {litellm_key}",
        },
        {
            "name": "Langfuse Observability",
            "public_url": f"https://langfuse.{domain}",
            "local_url": f"http://localhost:{langfuse_port}",
            "auth": f"user: {langfuse_user} | pass: {langfuse_pass}",
        },
        {
            "name": "Tool Egress Firewall UI",
            "public_url": f"https://efw.{domain}",
            "local_url": f"http://localhost:{egress_port}",
            "auth": f"user: admin | pass: {egress_pass}",
        },
        {
            "name": "LiteLLM OpenAI Gateway",
            "public_url": "http://litellm:4000/v1",
            "local_url": f"http://localhost:{litellm_port}/v1",
            "auth": f"Bearer {litellm_key}",
        },
        {
            "name": "Hermes Dynamic Runner",
            "public_url": "http://runner-hermes:8642",
            "local_url": f"http://localhost:{hermes_runner_port}",
            "auth": "(internal network)",
        },
        {
            "name": "OpenAI Stateless Runner",
            "public_url": "http://runner-openai:8002",
            "local_url": f"http://localhost:{openai_runner_port}",
            "auth": "(internal network)",
        },
        {
            "name": "Agent Turn Queue IPC",
            "public_url": "http://agent-queue:8000",
            "local_url": f"http://localhost:{agent_queue_port}",
            "auth": "(internal network)",
        },
    ]


def format_urls_directory(env: Optional[Dict[str, str]] = None) -> str:
    """Format the service directory into ANSI styled multi-line output."""
    if env is None:
        env = dict(os.environ)

    domain = env.get("BRAINSOS_DOMAIN", "brainsos.local")
    mail_domain = env.get("BRAINSOS_MAIL_DOMAIN", f"mail.{domain}")

    BOLD = "\033[1m"
    CYAN = "\033[0;36m"
    YELLOW = "\033[1;33m"
    DIM = "\033[2m"
    NC = "\033[0m"

    width = 78
    sep_line = f"{CYAN}{'═' * width}{NC}"

    lines = [
        sep_line,
        f"{CYAN}{BOLD}  brainsOS Platform Service Directory & Ingress Gateway{NC}",
        f"{DIM}  Target Domain: {BOLD}{domain}{DIM} | Email Host: {BOLD}{mail_domain}{DIM}{NC}",
        f"{DIM}  Context: brainsOS System Terminal{NC}",
        sep_line,
    ]

    services = get_service_directory(env)
    for i, s in enumerate(services):
        if i == 6:
            lines.append(f"{DIM}── Internal Microservices & Agent IPC {'─' * (width - 40)}{NC}")
            lines.append("")
        lines.append(f"  {BOLD}● {s['name']}{NC}")
        lines.append(f"    {DIM}Public:{NC}    {CYAN}{s['public_url']}{NC}")
        if s.get("local_url") and s["local_url"] != "-":
            lines.append(f"    {DIM}Localhost:{NC} {DIM}{s['local_url']}{NC}")
        lines.append(f"    {DIM}Auth:{NC}      {YELLOW}{s['auth']}{NC}")
        lines.append("")

    lines.append(sep_line)
    lines.append(
        f"{DIM}Hint: In this terminal, run '{BOLD}make status{NC}{DIM}' to probe service health or '{BOLD}make models{NC}{DIM}' to list LLM models.{NC}\n"
    )
    return "\n".join(lines)


def main():
    print(format_urls_directory())


if __name__ == "__main__":
    main()

