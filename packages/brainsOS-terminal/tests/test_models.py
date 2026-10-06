"""Unit tests for brainsos_terminal.models and cli."""

import json
from unittest.mock import MagicMock, patch

from brainsos_terminal.models import fetch_litellm_models, format_models


def test_fetch_litellm_models_mocked():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "data": [
            {"id": "brainsos-core", "mode": "chat"},
            {"id": "qwen2.5:latest", "mode": "chat"},
        ]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = fetch_litellm_models(base_url="http://mock:4000/v1", api_key="sk-test")
        assert len(models) == 2
        assert models[0]["id"] == "brainsos-core"


def test_format_models():
    models = [{"id": "model-1", "mode": "chat"}, {"id": "model-2"}]
    out = format_models(models)
    assert "Registered LiteLLM Models:" in out
    assert "model-1" in out
    assert "model-2" in out
