"""Unit tests for brainsos_terminal.urls."""

from brainsos_terminal.urls import format_urls_directory, get_service_directory


def test_get_service_directory_defaults():
    env = {
        "BRAINSOS_DOMAIN": "test.local",
        "BRAINSOS_MAIL_DOMAIN": "mail.test.local",
        "CADDY_HTTP_PORT": "8080",
        "CODE_SERVER_PORT": "9443",
        "OPERATOR_USER": "testuser",
        "CODE_SERVER_PASSWORD": "secretpassword",
        "OPENAI_API_KEY": "sk-test-key",
    }
    services = get_service_directory(env)
    assert len(services) == 11

    names = [s["name"] for s in services]
    assert "Landing Page Portal" in names
    assert "Operator IDE (VS Code)" in names
    assert "LiteLLM Proxy Admin UI" in names
    assert "LiteLLM OpenAI Gateway" in names
    assert "LiteLLM Lens (Telemetry)" in names
    assert "Langfuse Observability" in names

    lens_only_services = get_service_directory({**env, "BRAINSOS_TELEMETRY_BACKEND": "lens"})
    lens_only_names = [s["name"] for s in lens_only_services]
    assert "LiteLLM Lens (Telemetry)" in lens_only_names
    assert "Langfuse Observability" not in lens_only_names

    ide_entry = next(s for s in services if s["name"] == "Operator IDE (VS Code)")
    assert ide_entry["public_url"] == "https://editor.test.local"
    assert ide_entry["local_url"] == "http://localhost:9443"
    assert "testuser" in ide_entry["auth"]


def test_format_urls_directory():
    env = {"BRAINSOS_DOMAIN": "app.local"}
    out = format_urls_directory(env)
    assert "brainsOS Platform Service Directory" in out
    assert "app.local" in out
    assert "Landing Page Portal" in out
    assert "make status" in out
