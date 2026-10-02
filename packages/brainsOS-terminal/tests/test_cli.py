"""Unit tests for brainsos_terminal.cli."""

import sys
from unittest.mock import patch

from brainsos_terminal.cli import main


def test_cli_urls_dispatch():
    with patch.object(sys, "argv", ["brainsos", "urls"]), \
         patch("brainsos_terminal.cli.urls_main") as mock_urls:
        main()
        mock_urls.assert_called_once()


def test_cli_status_dispatch():
    with patch.object(sys, "argv", ["brainsos", "status"]), \
         patch("brainsos_terminal.cli.status_main") as mock_status:
        main()
        mock_status.assert_called_once()


def test_cli_models_dispatch():
    with patch.object(sys, "argv", ["brainsos", "models"]), \
         patch("brainsos_terminal.cli.models_main") as mock_models:
        main()
        mock_models.assert_called_once()
