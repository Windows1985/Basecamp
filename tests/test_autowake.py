"""Tests for AutoWake state machine in server/screen.py."""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# BasecampScreen requires pygame; import just enough to test AutoWake.
# We mock the screen object so pygame is not needed.
from unittest.mock import MagicMock


def _make_autowake(timeout_s=2):
    """Create an AutoWake with a mock screen and short timeout for tests."""
    from server.screen import AutoWake
    mock_screen = MagicMock()
    return AutoWake(mock_screen, idle_timeout_s=timeout_s), mock_screen


class TestAutoWakeStates:
    def test_initial_state_is_idle(self):
        aw, _ = _make_autowake()
        assert aw.state == "idle"

    def test_bed_exit_transitions_to_awake(self):
        aw, screen = _make_autowake()
        aw.bed_exit()
        assert aw.state == "awake"
        screen.turn_on.assert_called_once()

    def test_sleep_start_transitions_to_sleep_active(self):
        aw, screen = _make_autowake()
        aw.sleep_start()
        assert aw.state == "sleep_active"
        screen.turn_off.assert_called_once()

    def test_bed_exit_from_sleep_active_wakes_screen(self):
        aw, screen = _make_autowake()
        aw.sleep_start()
        aw.bed_exit()
        assert aw.state == "awake"

    def test_idle_timeout_transitions_awake_to_idle(self):
        aw, screen = _make_autowake(timeout_s=0)
        aw.bed_exit()
        assert aw.state == "awake"
        # tick() with zero timeout should fire immediately
        aw.tick()
        assert aw.state == "idle"
        assert screen.turn_off.called

    def test_tick_does_not_fire_before_timeout(self):
        aw, screen = _make_autowake(timeout_s=60)
        aw.bed_exit()
        aw.tick()
        assert aw.state == "awake"

    def test_tap_from_idle_wakes(self):
        aw, screen = _make_autowake()
        assert aw.state == "idle"
        aw.tap()
        assert aw.state == "awake"

    def test_tap_during_sleep_active_is_ignored(self):
        aw, screen = _make_autowake()
        aw.sleep_start()
        aw.tap()
        assert aw.state == "sleep_active"

    def test_sleep_start_from_awake_turns_off(self):
        aw, screen = _make_autowake()
        aw.bed_exit()
        screen.reset_mock()
        aw.sleep_start()
        assert aw.state == "sleep_active"
        screen.turn_off.assert_called_once()

    def test_multiple_bed_exits_reset_timer(self):
        aw, screen = _make_autowake(timeout_s=60)
        aw.bed_exit()
        first_mono = aw._wake_mono
        time.sleep(0.05)
        aw.bed_exit()
        assert aw._wake_mono > first_mono
        assert aw.state == "awake"
