"""
Recovery glow LED controller.

Drives an RGB LED (common-cathode, through resistors) mounted in the O3 hole
in the lid, in front of the screen pod. Colour maps from the morning recovery
score (0-100):

    green  >= GLOW_GREEN_THRESHOLD (default 70)
    amber  >= GLOW_AMBER_THRESHOLD (default 40)
    red    <  GLOW_AMBER_THRESHOLD

LED turns on at bed exit alongside the screen backlight, and off when the
sleep session starts. GPIO pins are defined in server/config.py.
"""
import os
import sys
import logging
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

log = logging.getLogger("glow")

try:
    from server.config import (
        GLOW_R_PIN, GLOW_G_PIN, GLOW_B_PIN,
        GLOW_GREEN_THRESHOLD, GLOW_AMBER_THRESHOLD,
        MOCK_HARDWARE,
    )
except (ImportError, AttributeError):
    GLOW_R_PIN = 16
    GLOW_G_PIN = 20
    GLOW_B_PIN = 21
    GLOW_GREEN_THRESHOLD = 70
    GLOW_AMBER_THRESHOLD = 40
    MOCK_HARDWARE = True


# RGB tuples for each state (PWM not used; pins are simple on/off)
_COLOR_GREEN = (False, True,  False)
_COLOR_AMBER = (True,  True,  False)   # red + green = amber/yellow
_COLOR_RED   = (True,  False, False)
_COLOR_OFF   = (False, False, False)


def score_to_color(score: float):
    """Return (r_on, g_on, b_on) tuple for a recovery score 0-100."""
    if score >= GLOW_GREEN_THRESHOLD:
        return _COLOR_GREEN
    if score >= GLOW_AMBER_THRESHOLD:
        return _COLOR_AMBER
    return _COLOR_RED


class GlowLED:
    """
    Controls the RGB recovery-glow LED.

    In mock mode prints state changes to stdout.
    On real hardware drives three GPIO output pins.
    """

    def __init__(self, mock: bool = None):
        if mock is None:
            mock = MOCK_HARDWARE
        self._mock      = mock
        self._gpio      = None
        self._gpio_ready = False
        self._current   = _COLOR_OFF
        self._score     = None
        self._on        = False

        if not mock:
            self._init_gpio()

    def _init_gpio(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            for pin in (GLOW_R_PIN, GLOW_G_PIN, GLOW_B_PIN):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            self._gpio       = GPIO
            self._gpio_ready = True
        except Exception as e:
            log.warning("GPIO init failed for glow LED: %s", e)

    def _set_color(self, color):
        self._current = color
        if self._mock:
            names = {
                _COLOR_GREEN: "GREEN",
                _COLOR_AMBER: "AMBER",
                _COLOR_RED:   "RED",
                _COLOR_OFF:   "OFF",
            }
            print(f"[GLOW LED] {names.get(color, color)}")
            return
        if not self._gpio_ready:
            return
        r, g, b = color
        try:
            self._gpio.output(GLOW_R_PIN, self._gpio.HIGH if r else self._gpio.LOW)
            self._gpio.output(GLOW_G_PIN, self._gpio.HIGH if g else self._gpio.LOW)
            self._gpio.output(GLOW_B_PIN, self._gpio.HIGH if b else self._gpio.LOW)
        except Exception as e:
            log.debug("Glow LED output error: %s", e)

    def set_score(self, score: float):
        """Cache the recovery score so the correct colour shows on next wake."""
        self._score = score

    def wake(self):
        """Turn on at bed exit with the colour for the current score."""
        self._on = True
        if self._score is None:
            self._set_color(_COLOR_GREEN)
        else:
            self._set_color(score_to_color(self._score))

    def sleep(self):
        """Turn off when sleep session starts."""
        self._on = False
        self._set_color(_COLOR_OFF)

    def off(self):
        """Turn off (idle timeout or explicit off)."""
        self._on = False
        self._set_color(_COLOR_OFF)

    def cleanup(self):
        self.off()
        if self._gpio_ready:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
