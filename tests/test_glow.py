"""Tests for server/glow.py -- colour mapping and LED state transitions."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from server.glow import score_to_color, GlowLED, _COLOR_GREEN, _COLOR_AMBER, _COLOR_RED, _COLOR_OFF


# ---------------------------------------------------------------------------
# Colour mapping
# ---------------------------------------------------------------------------

class TestScoreToColor:
    def test_green_at_threshold(self):
        assert score_to_color(70) == _COLOR_GREEN

    def test_green_above_threshold(self):
        assert score_to_color(95) == _COLOR_GREEN
        assert score_to_color(100) == _COLOR_GREEN

    def test_amber_at_threshold(self):
        assert score_to_color(40) == _COLOR_AMBER

    def test_amber_middle(self):
        assert score_to_color(55) == _COLOR_AMBER

    def test_amber_just_below_green(self):
        assert score_to_color(69) == _COLOR_AMBER

    def test_red_below_amber(self):
        assert score_to_color(39) == _COLOR_RED
        assert score_to_color(0) == _COLOR_RED

    def test_red_just_below_threshold(self):
        assert score_to_color(39.9) == _COLOR_RED


# ---------------------------------------------------------------------------
# GlowLED state transitions
# ---------------------------------------------------------------------------

class TestGlowLED:
    def setup_method(self):
        self.led = GlowLED(mock=True)

    def test_initial_state_is_off(self):
        assert self.led._current == _COLOR_OFF
        assert self.led._on is False

    def test_wake_without_score_defaults_to_green(self):
        self.led.wake()
        assert self.led._on is True
        assert self.led._current == _COLOR_GREEN

    def test_wake_with_high_score_is_green(self):
        self.led.set_score(80)
        self.led.wake()
        assert self.led._current == _COLOR_GREEN

    def test_wake_with_mid_score_is_amber(self):
        self.led.set_score(55)
        self.led.wake()
        assert self.led._current == _COLOR_AMBER

    def test_wake_with_low_score_is_red(self):
        self.led.set_score(30)
        self.led.wake()
        assert self.led._current == _COLOR_RED

    def test_sleep_turns_off(self):
        self.led.set_score(90)
        self.led.wake()
        self.led.sleep()
        assert self.led._on is False
        assert self.led._current == _COLOR_OFF

    def test_off_turns_off(self):
        self.led.set_score(90)
        self.led.wake()
        self.led.off()
        assert self.led._on is False
        assert self.led._current == _COLOR_OFF

    def test_score_update_takes_effect_on_next_wake(self):
        self.led.set_score(80)
        self.led.wake()
        assert self.led._current == _COLOR_GREEN
        self.led.sleep()
        self.led.set_score(20)
        self.led.wake()
        assert self.led._current == _COLOR_RED

    def test_cleanup_turns_led_off(self):
        self.led.set_score(80)
        self.led.wake()
        self.led.cleanup()
        assert self.led._current == _COLOR_OFF
