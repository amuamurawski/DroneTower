"""Unit tests for the STOMP frame handling."""

from __future__ import annotations

from custom_components.dronetower_amu.api import _parse_frame, _unescape

NUL = "\x00"


def test_parse_connected_frame():
    command, headers, body = _parse_frame(
        "CONNECTED\nversion:1.2\nheart-beat:5000,5000\n\n"
    )
    assert command == "CONNECTED"
    assert headers["version"] == "1.2"
    assert headers["heart-beat"] == "5000,5000"
    assert body == ""


def test_parse_message_frame_keeps_event_type_header():
    raw = (
        "MESSAGE\n"
        "event-type:CheckinEvent\n"
        "destination:/websocket/topic/x\n"
        "content-type:text/plain;charset=UTF-8\n"
        "subscription:sub-0\n"
        "content-length:20\n"
        "\n"
        '{"checkin":{"id":1}}'
    )
    command, headers, body = _parse_frame(raw)
    assert command == "MESSAGE"
    assert headers["event-type"] == "CheckinEvent"
    assert body == '{"checkin":{"id":1}}'


def test_parse_frame_ignores_heartbeat_and_padding():
    assert _parse_frame("\n") is None
    assert _parse_frame("") is None
    assert _parse_frame("\n\n\r") is None


def test_parse_frame_tolerates_leading_heartbeat():
    command, _, _ = _parse_frame("\nMESSAGE\nevent-type:CheckinEvent\n\nbody")
    assert command == "MESSAGE"


def test_repeated_header_keeps_first_occurrence():
    _, headers, _ = _parse_frame("MESSAGE\nx:first\nx:second\n\n")
    assert headers["x"] == "first"


def test_header_unescaping():
    assert _unescape(r"a\cb") == "a:b"
    assert _unescape(r"a\nb") == "a\nb"
    assert _unescape(r"a\\b") == "a\\b"
