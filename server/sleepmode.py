"""
Sleep mode state machine daemon — central conductor for Basecamp.

Controls the touchscreen, responds to radar presence, manages sleep sessions,
and triggers the morning batch pipeline.  Five logical states:
  IDLE → BEDTIME_PROMPT → RECORDING → MORNING → (back to IDLE)
A RECOVERY pass on startup handles sessions left mid-flight after a crash.
"""
import os
import sys
import signal
import threading
import time
import logging
import logging.handlers
import subprocess
from datetime import datetime, timedelta
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import (
    DB_PATH, MOCK_HARDWARE,
    SCREEN_BACKLIGHT_PIN, BUTTON_PIN,
    BEDTIME_WINDOW_START, BEDTIME_WINDOW_END,
    PRESENCE_ARM_MINUTES, BEDTIME_PROMPT_TIMEOUT_MINUTES,
    BEDTIME_SNOOZE_MINUTES, AUTO_RECORD_MINUTES,
    WAKE_ABSENCE_MINUTES, WAKE_EARLIEST_HOUR,
    MIN_SLEEP_HOURS, NTFY_SERVER, NTFY_TOPIC,
    WATCHDOG_INTERVAL_SECONDS, HEARTBEAT_INTERVAL_SECONDS,
)
from server.db import init_db, get_connection, migrate_schema

# ---------------------------------------------------------------------------
# Optional hardware imports
# ---------------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    _GPIO_AVAILABLE = True
except ImportError:
    _GPIO_AVAILABLE = False

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

try:
    import sdnotify as _sdnotify_mod
    _SDNOTIFY_AVAILABLE = True
except ImportError:
    _SDNOTIFY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/sleepmode.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("sleepmode")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# ---------------------------------------------------------------------------
# Clock abstraction — injectable for testing
# ---------------------------------------------------------------------------

class _RealClock:
    """Wall-clock and monotonic time using system calls."""

    def monotonic(self):
        return time.monotonic()

    def now(self):
        return datetime.now()

    def utcnow(self):
        return datetime.utcnow()


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class SleepState(Enum):
    IDLE            = "IDLE"
    BEDTIME_PROMPT  = "BEDTIME_PROMPT"
    RECORDING       = "RECORDING"
    MORNING         = "MORNING"


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

class Screen:
    """
    Manages display content and backlight.
    In MOCK_HARDWARE mode every call prints to stdout; touch events come from
    an in-process queue that tests (or mock simulation) can populate.
    """

    # Colour palette
    _BG    = (5, 8, 16)
    _WHITE = (255, 255, 255)
    _MUTED = (140, 140, 160)
    _TEAL  = (0, 229, 160)
    _AMBER = (255, 176, 0)
    _RED   = (255, 80, 80)

    def __init__(self, mock_hardware, backlight_pin, gpio_ready):
        self.mock_hw        = mock_hardware
        self._backlight_pin = backlight_pin
        self._gpio_ready    = gpio_ready
        self._touch_queue   = []      # populated by tests or mock simulation
        self._pg            = None
        self._yes_rect      = None
        self._not_yet_rect  = None
        self._dismiss_rect  = None

        if not mock_hardware and _PYGAME_AVAILABLE:
            try:
                # Use framebuffer on Pi; falls back to windowed display elsewhere.
                if not os.environ.get("DISPLAY"):
                    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
                pygame.init()
                self._pg = pygame.display.set_mode((320, 240))
                pygame.display.set_caption("Basecamp")
                log.info("pygame display initialised (320×240)")
            except Exception as e:
                log.error(f"pygame init failed: {e}")

    # ---- backlight ----------------------------------------------------

    def _set_backlight(self, on):
        if self.mock_hw:
            print(f"[SCREEN] {'ON' if on else 'OFF'}")
        elif self._gpio_ready and _GPIO_AVAILABLE:
            try:
                GPIO.output(self._backlight_pin, GPIO.HIGH if on else GPIO.LOW)
            except Exception as e:
                log.debug(f"Backlight GPIO error: {e}")

    def on(self):
        self._set_backlight(True)

    def off(self):
        self._set_backlight(False)
        if self._pg:
            try:
                self._pg.fill(self._BG)
                pygame.display.flip()
            except Exception:
                pass

    # ---- layouts ------------------------------------------------------

    def show_bedtime_prompt(self, time_str):
        if self.mock_hw:
            print(f"[SCREEN] BEDTIME_PROMPT  time={time_str}  [YES] [NOT YET]")
            return
        if not self._pg:
            return
        try:
            W, H = self._pg.get_size()
            self._pg.fill(self._BG)
            font_lg  = pygame.font.SysFont("monospace", 64, bold=True)
            font_md  = pygame.font.SysFont("monospace", 20)
            font_btn = pygame.font.SysFont("monospace", 18, bold=True)

            t = font_lg.render(time_str, True, self._WHITE)
            self._pg.blit(t, t.get_rect(centerx=W // 2, centery=H // 4))

            sub = font_md.render("Ready to sleep?", True, self._MUTED)
            self._pg.blit(sub, sub.get_rect(centerx=W // 2, centery=H // 2))

            self._not_yet_rect = pygame.Rect(20, H - 110, W - 40, 40)
            pygame.draw.rect(self._pg, self._MUTED, self._not_yet_rect, 2, border_radius=8)
            ny = font_btn.render("NOT YET", True, self._MUTED)
            self._pg.blit(ny, ny.get_rect(center=self._not_yet_rect.center))

            self._yes_rect = pygame.Rect(20, H - 60, W - 40, 40)
            pygame.draw.rect(self._pg, self._TEAL, self._yes_rect, border_radius=8)
            ye = font_btn.render("YES", True, self._BG)
            self._pg.blit(ye, ye.get_rect(center=self._yes_rect.center))

            pygame.display.flip()
        except Exception as e:
            log.error(f"show_bedtime_prompt render error: {e}")

    def show_morning(self, score, duration, entry_time, exit_time, loading=False):
        if duration is None:
            duration = 0.0
        if self.mock_hw:
            score_str = "..." if loading else (f"{score:.0f}" if score is not None else "—")
            print(
                f"[SCREEN] MORNING  score={score_str}  "
                f"duration={duration:.1f}h  {entry_time}→{exit_time}"
            )
            return
        if not self._pg:
            return
        try:
            W, H = self._pg.get_size()
            self._pg.fill(self._BG)
            font_huge  = pygame.font.SysFont("monospace", 88, bold=True)
            font_label = pygame.font.SysFont("monospace", 13)
            font_med   = pygame.font.SysFont("monospace", 19)
            font_small = pygame.font.SysFont("monospace", 11)

            if loading or score is None:
                score_text  = "..." if loading else "—"
                score_color = self._MUTED
            else:
                score_text  = f"{score:.0f}"
                score_color = self._TEAL if score >= 75 else (
                    self._AMBER if score >= 50 else self._RED
                )

            sc = font_huge.render(score_text, True, score_color)
            self._pg.blit(sc, sc.get_rect(centerx=W // 2, centery=H // 3))

            lbl_text = "CALCULATING..." if loading else "RECOVERY SCORE"
            lbl = font_label.render(lbl_text, True, self._MUTED)
            self._pg.blit(lbl, lbl.get_rect(centerx=W // 2, centery=H // 3 + 54))

            dur = font_med.render(f"{duration:.1f}h sleep", True, self._WHITE)
            self._pg.blit(dur, dur.get_rect(centerx=W // 2, centery=H // 3 + 78))

            e_str = str(entry_time)[11:16] if entry_time and len(str(entry_time)) > 15 else str(entry_time)[:5]
            x_str = str(exit_time)[11:16]  if exit_time  and len(str(exit_time))  > 15 else str(exit_time)[:5]
            times = font_small.render(f"{e_str} → {x_str}", True, self._MUTED)
            self._pg.blit(times, times.get_rect(centerx=W // 2, centery=H // 3 + 100))

            hint = font_small.render("Tap for morning log", True, self._MUTED)
            self._pg.blit(hint, hint.get_rect(centerx=W // 2, bottom=H - 6))

            self._dismiss_rect = pygame.Rect(0, 0, W, H)
            pygame.display.flip()
        except Exception as e:
            log.error(f"show_morning render error: {e}")

    # ---- touch --------------------------------------------------------

    def check_touch(self):
        """Return "YES", "NOT_YET", "DISMISS", or None."""
        if self._touch_queue:
            return self._touch_queue.pop(0)
        if self._pg:
            return self._poll_pygame()
        return None

    def simulate_touch(self, event):
        """Queue a synthetic touch event (for mock mode and tests)."""
        self._touch_queue.append(event)

    def _poll_pygame(self):
        try:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "DISMISS"
                if event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos
                    if self._yes_rect and self._yes_rect.collidepoint(pos):
                        return "YES"
                    if self._not_yet_rect and self._not_yet_rect.collidepoint(pos):
                        return "NOT_YET"
                    if self._dismiss_rect and self._dismiss_rect.collidepoint(pos):
                        return "DISMISS"
        except Exception:
            pass
        return None

    def quit(self):
        if self._pg:
            try:
                pygame.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main daemon
# ---------------------------------------------------------------------------

class SleepModeDaemon:
    """
    State machine that drives the Basecamp sleep lifecycle.

    Parameters
    ----------
    db_path         : path to the SQLite database
    mock_hardware   : override MOCK_HARDWARE flag (None = use config value)
    clock           : injectable _RealClock-compatible object (for testing)
    mock_auto_yes   : in mock mode, auto-inject YES after 10s in BEDTIME_PROMPT
    mock_auto_exit  : in mock mode, auto-trigger bed exit after 30s in RECORDING
    """

    def __init__(
        self,
        db_path=DB_PATH,
        mock_hardware=None,
        clock=None,
        mock_auto_yes=True,
        mock_auto_exit=True,
    ):
        self.db_path      = db_path
        self.mock_hw      = mock_hardware if mock_hardware is not None else MOCK_HARDWARE
        self._clock       = clock or _RealClock()
        self._mock_auto_yes  = mock_auto_yes
        self._mock_auto_exit = mock_auto_exit

        # Core state
        self.state               = SleepState.IDLE
        self._entered_state_mono = self._clock.monotonic()

        # IDLE / arming
        self._presence_start_mono = None   # start of continuous presence in IDLE
        self._snooze_until_mono   = None   # not-yet snooze deadline

        # BEDTIME_PROMPT
        self._bedtime_presence_start = None   # sustained presence timer
        self._prompt_mock_done       = False  # auto-YES simulation guard

        # RECORDING
        self._session_id          = None
        self._bed_entry_mono      = None   # monotonic time of bed entry
        self._bed_entry_dt        = None   # UTC ISO string of bed entry
        self._absence_start_mono  = None   # start of current absence period
        self._exit_mock_done      = False  # auto-exit simulation guard

        # MORNING
        self._bed_exit_dt         = None
        self._sleep_duration      = 0.0
        self._batch_proc          = None
        self._morning_mock_done   = False

        # Infrastructure
        self._gpio_ready          = False
        self._screen              = None
        self._button_held_since   = None
        self._last_watchdog_mono  = 0.0
        self._last_heartbeat_mono = 0.0
        self._running             = True
        self._notifier            = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def setup(self):
        init_db(self.db_path)
        migrate_schema(self.db_path)
        self._setup_gpio()
        self._screen = Screen(self.mock_hw, SCREEN_BACKLIGHT_PIN, self._gpio_ready)
        if _SDNOTIFY_AVAILABLE:
            try:
                self._notifier = _sdnotify_mod.SystemdNotifier()
            except Exception:
                pass
        self.recover_unfinished_sessions()
        self._load_state()

    def _setup_gpio(self):
        if self.mock_hw or not _GPIO_AVAILABLE:
            return
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(SCREEN_BACKLIGHT_PIN, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._gpio_ready = True
            log.info(f"GPIO: backlight=GPIO{SCREEN_BACKLIGHT_PIN}  button=GPIO{BUTTON_PIN}")
        except Exception as e:
            log.error(f"GPIO setup failed: {e}")

    def _cleanup(self):
        if self._gpio_ready:
            try:
                GPIO.output(SCREEN_BACKLIGHT_PIN, GPIO.LOW)
                GPIO.cleanup()
            except Exception:
                pass
        if self._screen:
            self._screen.quit()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO daemon_state (id, state, updated_at)
                       VALUES (1, ?, ?)""",
                    (self.state.value, self._clock.monotonic()),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.warning(f"State persist failed: {e}")

    def _load_state(self):
        try:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT state FROM daemon_state WHERE id=1"
                ).fetchone()
            finally:
                conn.close()
            if row:
                try:
                    restored = SleepState(row["state"])
                    # Only restore IDLE — other states are handled by recover_unfinished_sessions
                    if restored == SleepState.IDLE:
                        self.state = restored
                    log.info(f"Restored persisted state: {row['state']}")
                except ValueError:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Presence query
    # ------------------------------------------------------------------

    def _is_present(self):
        """Check recent radar_events to determine if subject is currently present."""
        cutoff = self._clock.utcnow() - timedelta(seconds=30)
        try:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT presence FROM radar_events "
                    "WHERE timestamp >= ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (cutoff.isoformat(),),
                ).fetchone()
            finally:
                conn.close()
            return bool(row and row["presence"])
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Bedtime window check
    # ------------------------------------------------------------------

    def _in_bedtime_window(self):
        hour  = self._clock.now().hour
        start = BEDTIME_WINDOW_START   # 21
        end   = BEDTIME_WINDOW_END     # 0
        if end == 0:
            return hour >= start
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end   # crosses midnight

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition_to(self, new_state):
        log.info(f"State: {self.state.value} → {new_state.value}")
        self.state               = new_state
        self._entered_state_mono = self._clock.monotonic()
        self._save_state()

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(self):
        """Process one cycle of the state machine. Called once per second."""
        now_mono = self._clock.monotonic()
        present  = self._is_present()

        self._watchdog_tick(now_mono)
        self._heartbeat_tick(now_mono)
        self._button_tick(now_mono)

        if self.state == SleepState.IDLE:
            self._tick_idle(present, now_mono)
        elif self.state == SleepState.BEDTIME_PROMPT:
            self._tick_bedtime_prompt(present, now_mono)
        elif self.state == SleepState.RECORDING:
            self._tick_recording(present, now_mono)
        elif self.state == SleepState.MORNING:
            self._tick_morning(now_mono)

    # ------------------------------------------------------------------
    # STATE: IDLE
    # ------------------------------------------------------------------

    def _tick_idle(self, present, now_mono):
        # Respect snooze from NOT YET
        if self._snooze_until_mono and now_mono < self._snooze_until_mono:
            return

        if not self._in_bedtime_window():
            self._presence_start_mono = None
            return

        if present:
            if self._presence_start_mono is None:
                self._presence_start_mono = now_mono
                log.debug("IDLE: presence arm timer started")
            elif (now_mono - self._presence_start_mono) >= PRESENCE_ARM_MINUTES * 60:
                log.info("IDLE: sustained presence detected → BEDTIME_PROMPT")
                self._presence_start_mono = None
                self._enter_bedtime_prompt()
        else:
            self._presence_start_mono = None

    # ------------------------------------------------------------------
    # STATE: BEDTIME_PROMPT
    # ------------------------------------------------------------------

    def _enter_bedtime_prompt(self):
        self._screen.on()
        ts = self._clock.now().strftime("%H:%M")
        self._screen.show_bedtime_prompt(ts)
        self._bedtime_presence_start = None
        self._prompt_mock_done       = False
        self._transition_to(SleepState.BEDTIME_PROMPT)

    def _tick_bedtime_prompt(self, present, now_mono):
        elapsed = now_mono - self._entered_state_mono

        # Touch / button input
        touch = self._screen.check_touch()
        if touch == "YES":
            self._on_yes_pressed()
            return
        if touch == "NOT_YET":
            self._on_not_yet_pressed()
            return

        # Mock: auto-inject YES after 10 s if enabled
        if self.mock_hw and self._mock_auto_yes and not self._prompt_mock_done:
            if elapsed >= 10:
                self._prompt_mock_done = True
                log.info("[MOCK] Simulating YES press")
                self._screen.simulate_touch("YES")
            return

        # Auto-start: 15 minutes of sustained presence without interaction
        if present:
            if self._bedtime_presence_start is None:
                self._bedtime_presence_start = now_mono
            elif (now_mono - self._bedtime_presence_start) >= AUTO_RECORD_MINUTES * 60:
                log.info("BEDTIME_PROMPT: 15 min sustained presence → auto-start RECORDING")
                self._on_yes_pressed()
                return
        else:
            self._bedtime_presence_start = None

        # 5-minute timeout (only when no sustained presence)
        if self._bedtime_presence_start is None and elapsed >= BEDTIME_PROMPT_TIMEOUT_MINUTES * 60:
            log.info("BEDTIME_PROMPT: timeout with no presence → IDLE")
            self._screen.off()
            self._transition_to(SleepState.IDLE)

    def _on_yes_pressed(self):
        self._screen.off()
        self._start_recording()

    def _on_not_yet_pressed(self):
        log.info(f"NOT YET — snoozing {BEDTIME_SNOOZE_MINUTES} minutes")
        self._screen.off()
        self._snooze_until_mono = self._clock.monotonic() + BEDTIME_SNOOZE_MINUTES * 60
        self._transition_to(SleepState.IDLE)

    # ------------------------------------------------------------------
    # STATE: RECORDING
    # ------------------------------------------------------------------

    def _start_recording(self):
        ts = self._clock.utcnow().isoformat()
        self._bed_entry_dt   = ts
        self._bed_entry_mono = self._clock.monotonic()
        self._absence_start_mono = None
        self._exit_mock_done     = False

        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    """INSERT INTO sleep_sessions
                       (bed_entry, bed_exit, duration_hours, status, created_at)
                       VALUES (?, NULL, NULL, 'RECORDING', ?)""",
                    (ts, time.time()),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id FROM sleep_sessions ORDER BY id DESC LIMIT 1"
                ).fetchone()
                self._session_id = row["id"] if row else None
            finally:
                conn.close()
            log.info(f"RECORDING: session_id={self._session_id}  bed_entry={ts}")
        except Exception as e:
            log.error(f"Failed to write bed_entry: {e}")

        self._transition_to(SleepState.RECORDING)

    def _tick_recording(self, present, now_mono):
        elapsed = now_mono - self._entered_state_mono

        # Mock: simulate bed exit after 30 s
        if self.mock_hw and self._mock_auto_exit and not self._exit_mock_done:
            if elapsed >= 30:
                self._exit_mock_done = True
                log.info("[MOCK] Simulating bed exit")
                self._do_bed_exit(now_mono)
                return

        sleep_hours = (now_mono - self._bed_entry_mono) / 3600.0 if self._bed_entry_mono else 0.0
        local_hour  = self._clock.now().hour

        if present:
            if self._absence_start_mono is not None:
                log.debug("RECORDING: presence returned — bathroom trip ended")
            self._absence_start_mono = None
        else:
            if self._absence_start_mono is None:
                self._absence_start_mono = now_mono
                log.debug("RECORDING: absence started (possible bathroom trip)")

            absence_minutes = (now_mono - self._absence_start_mono) / 60.0
            valid_exit = (
                absence_minutes >= WAKE_ABSENCE_MINUTES
                and local_hour  >= WAKE_EARLIEST_HOUR
                and sleep_hours >= MIN_SLEEP_HOURS
            )
            if valid_exit:
                log.info(
                    f"RECORDING: valid exit — absent {absence_minutes:.0f}min, "
                    f"hour={local_hour:02d}, sleep={sleep_hours:.1f}h"
                )
                self._do_bed_exit(now_mono)

    def _do_bed_exit(self, now_mono):
        ts = self._clock.utcnow().isoformat()
        sleep_hours = (
            (now_mono - self._bed_entry_mono) / 3600.0 if self._bed_entry_mono else 0.0
        )
        self._bed_exit_dt    = ts
        self._sleep_duration = sleep_hours

        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    """UPDATE sleep_sessions
                       SET bed_exit=?, duration_hours=?, status='PROCESSING'
                       WHERE id=?""",
                    (ts, round(sleep_hours, 4), self._session_id),
                )
                conn.commit()
            finally:
                conn.close()
            log.info(
                f"Session {self._session_id}: bed_exit={ts}  "
                f"duration={sleep_hours:.2f}h  status=PROCESSING"
            )
        except Exception as e:
            log.error(f"Failed to write bed_exit: {e}")

        self._enter_morning()

    # ------------------------------------------------------------------
    # STATE: MORNING
    # ------------------------------------------------------------------

    def _enter_morning(self):
        self._screen.on()
        self._screen.show_morning(
            score=None,
            duration=self._sleep_duration,
            entry_time=self._bed_entry_dt,
            exit_time=self._bed_exit_dt,
            loading=True,
        )
        self._morning_mock_done = False

        # Fire batch pipeline (non-blocking)
        try:
            self._batch_proc = subprocess.Popen(
                [sys.executable, "pipeline/batch.py",
                 "--session", str(self._session_id)],
                cwd=os.path.join(os.path.dirname(__file__), ".."),
            )
            log.info(
                f"Batch pipeline started for session {self._session_id} "
                f"(PID {self._batch_proc.pid})"
            )
        except Exception as e:
            log.error(f"Failed to start batch pipeline: {e}")
            self._batch_proc = None

        self._send_ntfy_wake()
        self._transition_to(SleepState.MORNING)

    def _tick_morning(self, now_mono):
        elapsed = now_mono - self._entered_state_mono

        # Mock: auto-dismiss after 5 s
        if self.mock_hw and not self._morning_mock_done:
            if elapsed >= 5:
                self._morning_mock_done = True
                log.info("[MOCK] Simulating morning dismiss")
                self._screen.simulate_touch("DISMISS")

        touch = self._screen.check_touch()
        if touch == "DISMISS":
            self._dismiss_morning()
            return

        # Poll for batch completion
        if self._batch_proc is not None and self._batch_proc.poll() is not None:
            retcode = self._batch_proc.poll()
            self._batch_proc = None
            if retcode == 0:
                self._on_batch_complete()
            else:
                self._on_batch_failed()

        # 30-minute timeout
        if elapsed >= 30 * 60:
            log.info("MORNING: 30-minute timeout → IDLE")
            self._dismiss_morning()

    def _on_batch_complete(self):
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "UPDATE sleep_sessions SET status='COMPLETE' WHERE id=?",
                    (self._session_id,),
                )
                row = conn.execute(
                    "SELECT total_score FROM recovery_scores "
                    "WHERE session_id=? ORDER BY timestamp DESC LIMIT 1",
                    (self._session_id,),
                ).fetchone()
                conn.commit()
            finally:
                conn.close()
            score = float(row["total_score"]) if row else None
            log.info(f"Batch complete — score={score}")
            self._screen.show_morning(
                score=score,
                duration=self._sleep_duration,
                entry_time=self._bed_entry_dt,
                exit_time=self._bed_exit_dt,
                loading=False,
            )
        except Exception as e:
            log.error(f"Batch completion update failed: {e}")

    def _on_batch_failed(self):
        log.warning(f"Batch pipeline failed for session {self._session_id}")
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "UPDATE sleep_sessions SET status='FAILED' WHERE id=?",
                    (self._session_id,),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.error(f"Failed to set status=FAILED: {e}")

    def _dismiss_morning(self):
        self._screen.off()
        self._session_id     = None
        self._bed_entry_mono = None
        self._bed_entry_dt   = None
        self._bed_exit_dt    = None
        self._batch_proc     = None
        self._transition_to(SleepState.IDLE)

    # ------------------------------------------------------------------
    # RECOVERY — called on every startup before IDLE
    # ------------------------------------------------------------------

    def recover_unfinished_sessions(self):
        """
        Find sessions left in RECORDING or PROCESSING after a crash.
        Called once during setup().
        """
        try:
            conn = get_connection(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT id, bed_entry, bed_exit, status FROM sleep_sessions "
                    "WHERE status IN ('RECORDING', 'PROCESSING') ORDER BY id ASC"
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:
            log.error(f"Recovery query failed: {e}")
            return

        for row in rows:
            session_id = row["id"]
            status     = row["status"]
            bed_entry  = row["bed_entry"]
            bed_exit   = row["bed_exit"]

            if status == "RECORDING":
                if bed_exit:
                    # Has an exit but wasn't processed
                    log.info(
                        f"Recovery: session {session_id} RECORDING with exit "
                        "→ PROCESSING, retriggering batch"
                    )
                    self._set_session_status(session_id, "PROCESSING")
                    self._trigger_batch(session_id)
                else:
                    entry_dt   = datetime.fromisoformat(bed_entry)
                    today_date = self._clock.now().date()
                    if entry_dt.date() == today_date:
                        log.info(
                            f"Recovery: session {session_id} is today's — "
                            "resuming RECORDING state"
                        )
                        self.state           = SleepState.RECORDING
                        self._session_id     = session_id
                        self._bed_entry_dt   = bed_entry
                        self._bed_entry_mono = self._clock.monotonic()
                        self._absence_start_mono = None
                        self._exit_mock_done     = False
                    else:
                        last_ts = self._get_last_radar_ts() or self._clock.utcnow().isoformat()
                        log.warning(
                            f"Recovery: session {session_id} is old ({entry_dt.date()}) "
                            f"with no exit — marking FAILED, bed_exit={last_ts}"
                        )
                        try:
                            conn2 = get_connection(self.db_path)
                            try:
                                conn2.execute(
                                    "UPDATE sleep_sessions SET bed_exit=?, status='FAILED' WHERE id=?",
                                    (last_ts, session_id),
                                )
                                conn2.commit()
                            finally:
                                conn2.close()
                        except Exception as e:
                            log.error(f"Recovery: failed to mark session {session_id} FAILED: {e}")

            elif status == "PROCESSING":
                log.info(
                    f"Recovery: session {session_id} PROCESSING → retriggering batch"
                )
                self._trigger_batch(session_id)

    def _trigger_batch(self, session_id):
        try:
            subprocess.Popen(
                [sys.executable, "pipeline/batch.py",
                 "--session", str(session_id)],
                cwd=os.path.join(os.path.dirname(__file__), ".."),
            )
            log.info(f"Batch triggered for session {session_id}")
        except Exception as e:
            log.error(f"Failed to trigger batch for session {session_id}: {e}")

    def _set_session_status(self, session_id, status):
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "UPDATE sleep_sessions SET status=? WHERE id=?",
                    (status, session_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.error(f"Failed to set session {session_id} status={status}: {e}")

    def _get_last_radar_ts(self):
        try:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT timestamp FROM radar_events ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
            return row["timestamp"] if row else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Button (physical GPIO)
    # ------------------------------------------------------------------

    def _button_tick(self, now_mono):
        if self.mock_hw or not self._gpio_ready:
            return
        try:
            down = GPIO.input(BUTTON_PIN) == GPIO.LOW  # active-low with pull-up

            if down:
                if self._button_held_since is None:
                    self._button_held_since = now_mono
                held = now_mono - self._button_held_since

                if self.state == SleepState.IDLE and held >= 3.0:
                    log.info("Physical: long press in IDLE → force BEDTIME_PROMPT")
                    self._button_held_since = None
                    self._enter_bedtime_prompt()
                elif self.state == SleepState.RECORDING and held >= 5.0:
                    log.info("Physical: long press in RECORDING → emergency stop")
                    self._button_held_since = None
                    self._emergency_stop()
            else:
                if self._button_held_since is not None:
                    held = now_mono - self._button_held_since
                    self._button_held_since = None
                    if held < 3.0:  # short press
                        if self.state == SleepState.BEDTIME_PROMPT:
                            self._on_yes_pressed()
                        elif self.state == SleepState.MORNING:
                            self._dismiss_morning()
        except Exception as e:
            log.debug(f"Button read error: {e}")

    def _emergency_stop(self):
        log.warning("Emergency stop — writing FAILED bed_exit")
        ts = self._clock.utcnow().isoformat()
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "UPDATE sleep_sessions SET bed_exit=?, status='FAILED' WHERE id=?",
                    (ts, self._session_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.error(f"Emergency stop DB write failed: {e}")
        self._screen.off()
        self._session_id     = None
        self._bed_entry_mono = None
        self._transition_to(SleepState.IDLE)

    # ------------------------------------------------------------------
    # Health / watchdog / heartbeat
    # ------------------------------------------------------------------

    def _watchdog_tick(self, now_mono):
        if now_mono - self._last_watchdog_mono >= WATCHDOG_INTERVAL_SECONDS:
            self._last_watchdog_mono = now_mono
            if self._notifier:
                try:
                    self._notifier.notify("WATCHDOG=1")
                except Exception:
                    pass

    def _heartbeat_tick(self, now_mono):
        if now_mono - self._last_heartbeat_mono >= HEARTBEAT_INTERVAL_SECONDS:
            self._last_heartbeat_mono = now_mono
            self._write_heartbeat()
            self._check_service_health()

    def _write_heartbeat(self):
        try:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    """INSERT INTO service_heartbeats (service_name, last_heartbeat, status)
                       VALUES ('sleepmode', ?, ?)
                       ON CONFLICT(service_name) DO UPDATE
                       SET last_heartbeat=excluded.last_heartbeat, status=excluded.status""",
                    (time.time(), self.state.value),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.debug(f"Heartbeat write failed: {e}")

    def _check_service_health(self):
        cutoff = time.time() - 120
        try:
            conn = get_connection(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT service_name, last_heartbeat FROM service_heartbeats "
                    "WHERE last_heartbeat < ?",
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                log.warning(
                    f"Service '{row['service_name']}' has not reported heartbeat "
                    "in >2 minutes"
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # ntfy notification
    # ------------------------------------------------------------------

    def _send_ntfy_wake(self):
        try:
            import requests
            entry_str = str(self._bed_entry_dt)[11:16] if self._bed_entry_dt else "?"
            body = (
                f"Good morning! Woke up at {str(self._bed_exit_dt)[11:16]}.\n"
                f"Sleep started at {entry_str} ({self._sleep_duration:.1f}h).\n"
                "Analysing your night..."
            )
            requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=body.encode(),
                headers={"Title": "Basecamp — Morning", "Tags": "zzz"},
                timeout=5,
            )
        except Exception:
            pass  # ntfy is best-effort

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self):
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: self.stop())

        self.setup()
        log.info(f"Sleepmode daemon started — state={self.state.value}")

        while self._running:
            try:
                self.tick()
            except Exception as e:
                log.error(f"Tick error: {e}", exc_info=True)
            time.sleep(1)

        self._cleanup()
        log.info("Sleepmode daemon stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    daemon = SleepModeDaemon()
    daemon.run()
