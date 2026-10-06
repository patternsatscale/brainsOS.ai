"""Tests for the smart make interceptor module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from brainsos_terminal.make import (
    find_system_make,
    main,
    resolve_system_mk,
)


def test_find_system_make():
    make_bin = find_system_make()
    assert isinstance(make_bin, str)
    assert len(make_bin) > 0


def test_resolve_system_mk_env(tmp_path):
    custom_mk = tmp_path / "system.mk"
    custom_mk.write_text("help:\n\t@echo help\n")
    with patch.dict(os.environ, {"BRAINSOS_SYSTEM_MK": str(custom_mk)}):
        resolved = resolve_system_mk()
        assert resolved == str(custom_mk)


def test_resolve_system_mk_none():
    with patch.dict(os.environ, {"BRAINSOS_SYSTEM_MK": "/nonexistent/path.mk"}):
        # Unless /etc/brainsos/editor/system.mk exists on host
        res = resolve_system_mk()
        if not os.path.isfile("/etc/brainsos/editor/system.mk") and not os.path.isfile(
            "/etc/brainsos/system.mk"
        ):
            assert res is None


@patch("brainsos_terminal.make.execute_make")
@patch("brainsos_terminal.make.resolve_system_mk")
def test_main_no_args_shows_help(mock_resolve, mock_exec):
    mock_resolve.return_value = "/fake/system.mk"
    with patch("sys.argv", ["make"]):
        with patch("os.path.isfile", return_value=False):
            main()
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0][1]
            assert args == ["-f", "/fake/system.mk", "help"]


@patch("brainsos_terminal.make.execute_make")
@patch("brainsos_terminal.make.resolve_system_mk")
def test_main_delegates_to_system_mk(mock_resolve, mock_exec):
    mock_resolve.return_value = "/fake/system.mk"
    with patch("sys.argv", ["make", "urls"]):
        with patch("os.path.isfile", return_value=False):
            main()
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0][1]
            assert args == ["-f", "/fake/system.mk", "urls"]


@patch("subprocess.run")
@patch("brainsos_terminal.make.execute_make")
@patch("brainsos_terminal.make.resolve_system_mk")
def test_main_local_makefile_handled(mock_resolve, mock_exec, mock_subproc):
    mock_resolve.return_value = "/fake/system.mk"
    # Local dry-run succeeds
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_subproc.return_value = mock_res

    def isfile_side_effect(path):
        return path == "Makefile"

    with patch("sys.argv", ["make", "test"]):
        with patch("os.path.isfile", side_effect=isfile_side_effect):
            main()
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0][1]
            assert args == ["test"]
