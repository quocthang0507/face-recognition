"""Tests for WebSocket control messages sent by the dashboard."""

import json

import pytest

from src.main import _websocket_behavior_config


def test_websocket_behavior_config_parses_toggle_list() -> None:
    message = {
        "text": json.dumps(
            {
                "type": "behavior_config",
                "enabled_behaviors": ["SLEEPING", "CHEATING"],
            }
        )
    }

    assert _websocket_behavior_config(message) == ["SLEEPING", "CHEATING"]


def test_websocket_binary_frame_is_not_treated_as_config() -> None:
    assert _websocket_behavior_config({"bytes": b"jpeg"}) is None


def test_websocket_behavior_config_requires_string_list() -> None:
    message = {
        "text": json.dumps(
            {"type": "behavior_config", "enabled_behaviors": ["SLEEPING", 123]}
        )
    }

    with pytest.raises(ValueError, match="danh sách chuỗi"):
        _websocket_behavior_config(message)
