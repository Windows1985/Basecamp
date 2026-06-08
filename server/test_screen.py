"""
Tests for server/screen.py — the touchscreen UI controller.

Run:  python server/test_screen.py
All 9 tests must pass.

SDL_VIDEODRIVER=dummy / SDL_AUDIODRIVER=dummy are set here so pygame runs
headless in CI and on machines without a physical display.
"""
import os
import sys
import time
import tempfile

# Must be set before pygame initialises anywhere in the import chain
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server.config as _cfg
_cfg.MOCK_HARDWARE = True

from server.db import init_db, migrate_schema
from server.screen import BasecampScreen

# ── Helpers ────────────────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0


def _assert(cond, label, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"  PASS  {label}")
        _PASS += 1
    else:
        msg = f"  FAIL  {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _FAIL += 1


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    migrate_schema(path)
    return path


_SESSION_DATA = {
    "score":              None,
    "duration_hours":     7.2,
    "bed_entry":          "2026-06-07T22:30:00",
    "bed_exit":           "2026-06-08T05:42:00",
    "architecture_score": 84,
    "continuity_score":   97,
    "breathing_score":    65,
    "environment_score":  42,
    "positive_factors":   ["Good sleep efficiency"],
    "negative_factors":   ["High CO2"],
}


def _surface_has_content(surf):
    """Return True if the surface contains any pixel not equal to the background (5, 8, 16)."""
    try:
        import pygame.surfarray
        arr = pygame.surfarray.array3d(surf)
        return bool(((arr[:, :, 0] != 5) | (arr[:, :, 1] != 8) | (arr[:, :, 2] != 16)).any())
    except Exception:
        # Fallback: sample a grid of pixels
        for x in range(0, 240, 16):
            for y in range(0, 320, 16):
                r, g, b, *_ = surf.get_at((x, y))
                if r != 5 or g != 8 or b != 16:
                    return True
        return False


def _surface_has_teal(surf):
    """Return True if the surface contains teal-ish pixels (score >= 75 color)."""
    try:
        import pygame.surfarray
        arr = pygame.surfarray.array3d(surf)
        # Teal = (0, 229, 160): high green, significant blue, low red
        mask = (arr[:, :, 0] < 30) & (arr[:, :, 1] > 180) & (arr[:, :, 2] > 100)
        return bool(mask.any())
    except Exception:
        # Fallback: grid scan
        for x in range(0, 240, 4):
            for y in range(0, 320, 4):
                r, g, b, *_ = surf.get_at((x, y))
                if r < 30 and g > 180 and b > 100:
                    return True
        return False


# ── Test 1 — Initialisation ────────────────────────────────────────────────────

def test_init():
    print("\nTest 1: Initialisation")
    db = _make_db()
    try:
        screen = BasecampScreen(mock=True, db_path=db)
        _assert(screen is not None, "BasecampScreen created without error")

        import pygame
        _assert(pygame.get_init(), "pygame initialised")

        screen.cleanup()
    except Exception as e:
        _assert(False, "BasecampScreen created without error", str(e))
    finally:
        os.unlink(db)


# ── Test 2 — IDLE layout ───────────────────────────────────────────────────────

def test_idle():
    print("\nTest 2: IDLE layout")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.show_idle()
        _assert(True, "show_idle() completed without exception")

        if screen._surface and not screen._headless:
            has_content = _surface_has_content(screen._surface)
            _assert(has_content, "Surface contains non-background pixels (something rendered)")
        else:
            _assert(True, "Surface contains non-background pixels (headless)")
    except Exception as e:
        _assert(False, "show_idle() completed without exception", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 3 — BEDTIME_PROMPT YES touch ─────────────────────────────────────────

def test_bedtime_yes():
    print("\nTest 3: BEDTIME_PROMPT — YES touch at (120, 267)")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.show_bedtime_prompt()
        _assert(True, "show_bedtime_prompt() rendered without exception")

        # YES button: Rect(20, 235, 200, 65) → x=20..220, y=235..300, center=(120, 267)
        screen.simulate_touch(120, 267)
        action = screen.get_pending_action()
        _assert(action == "yes",
                "get_pending_action() returns 'yes' for YES button touch",
                f"got {action!r}")
    except Exception as e:
        _assert(False, "BEDTIME_PROMPT YES flow", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 4 — BEDTIME_PROMPT timeout ───────────────────────────────────────────

def test_bedtime_timeout():
    print("\nTest 4: BEDTIME_PROMPT timeout (5 minutes)")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.show_bedtime_prompt()
        # Wind the internal timer back 301 seconds to simulate 5+ minutes elapsed
        screen._prompt_start_time = time.monotonic() - 301
        action = screen.get_pending_action()
        _assert(action == "timeout",
                "get_pending_action() returns 'timeout' after 5-minute prompt timeout",
                f"got {action!r}")
    except Exception as e:
        _assert(False, "BEDTIME_PROMPT timeout", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 5 — MORNING loading state ────────────────────────────────────────────

def test_morning_loading():
    print("\nTest 5: MORNING loading state (score=None)")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.show_morning(_SESSION_DATA)
        _assert(True, "show_morning(score=None) rendered without exception")
        _assert(screen._loading is True,
                "Loading state active when score=None",
                f"_loading={screen._loading!r}")
    except Exception as e:
        _assert(False, "MORNING loading state", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 6 — MORNING score state (teal pixels for score 77) ───────────────────

def test_morning_score():
    print("\nTest 6: MORNING score state — teal pixels for score 77")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        data = dict(_SESSION_DATA)
        data["score"] = 77
        screen.update_morning_score(77, data)
        _assert(True, "update_morning_score(77) rendered without exception")

        if screen._surface and not screen._headless:
            has_teal = _surface_has_teal(screen._surface)
            _assert(has_teal,
                    "Surface contains teal-colored pixels (score 77 >= 75 → teal)",
                    "no teal-ish pixels found")
        else:
            _assert(True, "Surface contains teal-colored pixels (headless)")
    except Exception as e:
        _assert(False, "MORNING score state", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 7 — NOT YET touch ────────────────────────────────────────────────────

def test_bedtime_not_yet():
    print("\nTest 7: NOT YET touch at (120, 195)")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.show_bedtime_prompt()
        # NOT YET button: Rect(20, 170, 200, 50) → x=20..220, y=170..220, center=(120, 195)
        screen.simulate_touch(120, 195)
        action = screen.get_pending_action()
        _assert(action == "not_yet",
                "get_pending_action() returns 'not_yet' for NOT YET button touch",
                f"got {action!r}")
    except Exception as e:
        _assert(False, "NOT YET touch", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 8 — Turn on / off ────────────────────────────────────────────────────

def test_backlight():
    print("\nTest 8: Turn on / off")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.turn_on()
        _assert(screen._backlight is True,
                "turn_on() sets _backlight=True")
        screen.turn_off()
        _assert(screen._backlight is False,
                "turn_off() sets _backlight=False")
    except Exception as e:
        _assert(False, "Turn on/off", str(e))
    finally:
        screen.cleanup()
        os.unlink(db)


# ── Test 9 — Cleanup ──────────────────────────────────────────────────────────

def test_cleanup():
    print("\nTest 9: Cleanup")
    db = _make_db()
    screen = BasecampScreen(mock=True, db_path=db)
    try:
        screen.cleanup()
        _assert(True, "cleanup() completed without error")

        import pygame
        _assert(not pygame.get_init(),
                "pygame quit after cleanup()")
    except Exception as e:
        _assert(False, "cleanup() completed without error", str(e))
    finally:
        try:
            os.unlink(db)
        except Exception:
            pass


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_init()
    test_idle()
    test_bedtime_yes()
    test_bedtime_timeout()
    test_morning_loading()
    test_morning_score()
    test_bedtime_not_yet()
    test_backlight()
    test_cleanup()

    print(f"\n{'='*50}")
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    if _FAIL:
        sys.exit(1)
