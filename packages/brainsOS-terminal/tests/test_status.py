"""Unit tests for brainsos_terminal.status."""

from unittest.mock import MagicMock, patch

from brainsos_terminal.status import check_http, check_tcp, format_status_report, probe_all_services


def test_check_http_success():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        ok, msg = check_http("http://example.com")
        assert ok is True
        assert msg == "HTTP 200"


def test_check_tcp_success():
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value = mock_sock
        ok, msg = check_tcp("127.0.0.1", 25)
        assert ok is True
        assert msg == "OPEN"
        mock_sock.connect.assert_called_once_with(("127.0.0.1", 25))


def test_probe_all_services_mocked():
    services = [
        ("Test HTTP", "http://test.local", "HTTP"),
        ("Test TCP", ("127.0.0.1", 1234), "TCP"),
    ]
    with patch("brainsos_terminal.status.check_http", return_value=(True, "HTTP 200")), \
         patch("brainsos_terminal.status.check_tcp", return_value=(False, "Connection refused")):
        results = probe_all_services(services=services)
        assert len(results) == 2
        assert results[0]["online"] is True
        assert results[1]["online"] is False


def test_format_status_report():
    results = [
        {"name": "Service A", "type": "HTTP", "online": True, "details": "HTTP 200"},
        {"name": "Service B", "type": "TCP", "online": False, "details": "timed out"},
    ]
    report = format_status_report(results)
    assert "brainsOS Platform Internal Service Health" in report
    assert "Service A" in report
    assert "ONLINE" in report
    assert "Service B" in report
    assert "OFFLINE" in report
