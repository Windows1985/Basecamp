"""
Touchscreen UI controller for Basecamp — 240×320 IPS SPI display (ILI9341/ST7789).

In mock mode (MOCK_HARDWARE=True) renders to a 480×640 pygame window so the UI
is fully interactive on a development machine.  All three layouts (IDLE,
BEDTIME_PROMPT, MORNING) are contained here.

sleepmode.py drives this module by calling:
  screen.tick()                       — every second (clock / animation update)
  screen.get_pending_action()         — every second (returns touch result or None)
"""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

log = logging.getLogger("screen")

# ── Color palette (all RGB tuples) ─────────────────────────────────────────────
_BG          = (5,   8,  16)
_WHITE       = (255, 255, 255)
_MUTED       = (153, 153, 153)   # 60 % white
_SECONDARY   = (102, 102, 102)   # 40 % white
_TEAL        = (0,   229, 160)
_AMBER       = (245, 166,  35)
_RED         = (255,  77, 109)
_CARD_BG     = (13,  17,  23)
_BORDER      = (26,  31,  46)
_TIMEOUT_BAR = (77,  77,  77)   # ~30 % white

# Component score accent colours
_ARCH_CLR = (123, 143, 247)
_CONT_CLR = _TEAL
_BRTH_CLR = (74,  144, 217)
_ENV_CLR  = _AMBER


def _score_color(score: float):
    if score >= 75:
        return _TEAL
    if score >= 50:
        return _AMBER
    return _RED


# ── Optional imports ───────────────────────────────────────────────────────────
try:
    import pygame as _pg
    _PYGAME_OK = True
except ImportError:
    _pg = None
    _PYGAME_OK = False

try:
    from PIL import Image as _PILImage
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class BasecampScreen:
    """
    Manages the 240×320 touchscreen display and touch input.

    Parameters
    ----------
    mock    : True renders to a 2× pygame window; False drives the SPI display
    db_path : SQLite path for IDLE sensor readings (defaults to config.DB_PATH)
    """

    W = 240
    H = 320
    _BEDTIME_TIMEOUT_S = 300.0   # 5 minutes

    def __init__(self, mock: bool = False, db_path: str = None):
        self.mock      = mock
        self._db_path  = db_path
        self._headless = False

        # pygame surfaces
        self._surface = None   # 240×320 offscreen (always rendered to)
        self._window  = None   # actual display window

        # Backlight
        self._backlight = False

        # Layout state
        self._current_layout    = None   # 'idle' | 'bedtime_prompt' | 'morning' | None
        self._prompt_start_time = None   # monotonic when BEDTIME_PROMPT shown
        self._dot_idx           = 0      # loading animation frame

        # Morning display data
        self._session_data = {}
        self._score        = None
        self._loading      = True

        # Sensor reading cache for IDLE
        self._last_sensor_mono = 0.0
        self._sensor_cache     = {}

        # Action / touch queues
        self._touch_queue    : list = []   # (x, y) from simulate_touch()
        self._pending_actions: list = []   # resolved action strings

        # Hit-rects (240×320 coordinate space)
        self._not_yet_rect = None
        self._yes_rect     = None
        self._log_rect     = None

        # Real-hardware GPIO / SPI
        self._gpio       = None
        self._bl_pin     = None
        self._gpio_ready = False
        self._spi_device = None

        self._init_pygame()
        self._init_gpio()
        self._init_spi()
        self._init_rects()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_pygame(self):
        if not _PYGAME_OK:
            log.warning("pygame unavailable — BasecampScreen running headless")
            self._headless = True
            return
        try:
            _pg.init()
            self._surface = _pg.Surface((self.W, self.H))
            self._surface.fill(_BG)

            if self.mock:
                try:
                    from server.config import SCREEN_MOCK_SCALE
                    scale = SCREEN_MOCK_SCALE
                except (ImportError, AttributeError):
                    scale = 2
                self._window = _pg.display.set_mode((self.W * scale, self.H * scale))
                _pg.display.set_caption("Basecamp Display")
            else:
                if not os.environ.get("DISPLAY"):
                    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
                self._window = _pg.display.set_mode((self.W, self.H))
                _pg.display.set_caption("Basecamp")

            log.info("pygame display initialised (%s)",
                     "mock 480x640" if self.mock else "240x320")
        except Exception as e:
            log.error("pygame init failed: %s", e)
            self._headless = True

    def _init_gpio(self):
        if self.mock:
            return
        try:
            import RPi.GPIO as GPIO
            from server.config import SCREEN_BACKLIGHT_PIN
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(SCREEN_BACKLIGHT_PIN, GPIO.OUT, initial=GPIO.LOW)
            self._gpio       = GPIO
            self._bl_pin     = SCREEN_BACKLIGHT_PIN
            self._gpio_ready = True
        except Exception:
            pass

    def _init_spi(self):
        if self.mock:
            return
        try:
            from luma.lcd.device import ili9341
            from luma.core.interface.serial import spi
            from server.config import (
                SCREEN_SPI_PORT, SCREEN_SPI_DEVICE,
                SCREEN_DC_PIN, SCREEN_RESET_PIN,
            )
            serial = spi(
                port=SCREEN_SPI_PORT,
                device=SCREEN_SPI_DEVICE,
                gpio_DC=SCREEN_DC_PIN,
                gpio_RST=SCREEN_RESET_PIN,
                bus_speed_hz=32_000_000,
            )
            self._spi_device = ili9341(serial, width=self.W, height=self.H)
            log.info("luma.lcd ILI9341 SPI display initialised")
        except Exception as e:
            log.debug("luma.lcd unavailable (%s) — framebuffer only", e)
            self._spi_device = None

    def _init_rects(self):
        if not _PYGAME_OK:
            return
        # Hit-rects are pure data — no display needed
        self._not_yet_rect = _pg.Rect(20, 170, 200, 50)   # x=20..220, y=170..220
        self._yes_rect     = _pg.Rect(20, 235, 200, 65)   # x=20..220, y=235..300
        self._log_rect     = _pg.Rect(0,  265, 240, 55)   # x=0..240,  y=265..320

    # ── Font helpers ──────────────────────────────────────────────────────────

    def _font(self, size: int, bold: bool = False, mono: bool = False):
        if not _PYGAME_OK or self._headless:
            return None
        try:
            family = "monospace" if mono else "sans"
            return _pg.font.SysFont(family, size, bold=bold)
        except Exception:
            try:
                return _pg.font.Font(None, size)
            except Exception:
                return None

    # ── Backlight ─────────────────────────────────────────────────────────────

    def turn_on(self):
        """Switch backlight on."""
        self._backlight = True
        if self.mock:
            print("[BACKLIGHT ON]")
            return
        if self._gpio_ready:
            try:
                self._gpio.output(self._bl_pin, self._gpio.HIGH)
            except Exception as e:
                log.debug("Backlight ON error: %s", e)

    def turn_off(self):
        """Switch backlight off and clear display to black."""
        self._backlight = False
        if self.mock:
            print("[BACKLIGHT OFF]")
        elif self._gpio_ready:
            try:
                self._gpio.output(self._bl_pin, self._gpio.LOW)
            except Exception as e:
                log.debug("Backlight OFF error: %s", e)
        if not self._headless and self._surface:
            try:
                self._surface.fill(_BG)
                self._flush()
            except Exception:
                pass

    # ── Display flush ─────────────────────────────────────────────────────────

    def _flush(self):
        """Push the 240×320 surface to the window (and SPI device on real hardware)."""
        if self._headless or not self._surface or not self._window:
            return
        try:
            if self.mock:
                try:
                    from server.config import SCREEN_MOCK_SCALE
                    scale = SCREEN_MOCK_SCALE
                except (ImportError, AttributeError):
                    scale = 2
                scaled = _pg.transform.scale(self._surface, (self.W * scale, self.H * scale))
                self._window.blit(scaled, (0, 0))
            else:
                self._window.blit(self._surface, (0, 0))
                self._flush_spi()
            _pg.display.flip()
        except Exception as e:
            log.debug("Flush error: %s", e)

    def _flush_spi(self):
        """Send 240×320 surface to SPI display via Pillow bridge."""
        if not _PIL_OK or not self._spi_device:
            return
        try:
            raw = _pg.image.tostring(self._surface, "RGB")
            img = _PILImage.frombytes("RGB", (self.W, self.H), raw)
            self._spi_device.display(img)
        except Exception as e:
            log.debug("SPI flush error: %s", e)

    # ── Drawing primitives ────────────────────────────────────────────────────

    def _rounded_rect(self, surf, color, rect, radius=8, border_color=None, border=0):
        try:
            _pg.draw.rect(surf, color, rect, border_radius=radius)
            if border and border_color:
                _pg.draw.rect(surf, border_color, rect, border, border_radius=radius)
        except Exception:
            _pg.draw.rect(surf, color, rect)

    def _text(self, surf, text: str, font, color,
              center=None, topleft=None, topright=None):
        if font is None or surf is None:
            return
        try:
            img  = font.render(str(text), True, color)
            rect = img.get_rect()
            if center:
                rect.center = center
            elif topleft:
                rect.topleft = topleft
            elif topright:
                rect.topright = topright
            surf.blit(img, rect)
        except Exception:
            pass

    def _truncate(self, text: str, font, max_px: int) -> str:
        """Trim text to fit within max_px pixels wide."""
        if font is None:
            return text[:24]
        try:
            while len(text) > 1 and font.size(text)[0] > max_px:
                text = text[:-1]
            return text
        except Exception:
            return text[:24]

    # ── Sensor data ───────────────────────────────────────────────────────────

    def _sensor_values(self):
        """Return (co2_ppm, temp_c, humidity_pct) from DB (30 s cache) or defaults."""
        mono = time.monotonic()
        if mono - self._last_sensor_mono < 30.0 and self._sensor_cache:
            c = self._sensor_cache
            return c["co2"], c["temp"], c["hum"]
        self._last_sensor_mono = mono

        db = self._db_path
        if db is None:
            try:
                from server.config import DB_PATH
                db = DB_PATH
            except Exception:
                return 400.0, 20.0, 50.0
        try:
            from server.db import get_connection
            conn = get_connection(db)
            try:
                row = conn.execute(
                    "SELECT co2_ppm, temperature, humidity "
                    "FROM sensor_readings ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
            if row:
                self._sensor_cache = {
                    "co2":  float(row["co2_ppm"]    or 400),
                    "temp": float(row["temperature"] or 20.0),
                    "hum":  float(row["humidity"]    or 50.0),
                }
                c = self._sensor_cache
                return c["co2"], c["temp"], c["hum"]
        except Exception:
            pass
        return 400.0, 20.0, 50.0

    # ── Layout: IDLE ──────────────────────────────────────────────────────────

    def show_idle(self):
        """Render the IDLE layout (clock + environment readings)."""
        self._current_layout = "idle"
        self._render_idle()

    def _render_idle(self):
        if self._headless:
            return
        try:
            surf = self._surface
            surf.fill(_BG)

            now     = time.localtime()
            _DAYS   = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
            _MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                       "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
            time_str = time.strftime("%H:%M", now)
            date_str = f"{_DAYS[now.tm_wday]} {now.tm_mday:02d} {_MONTHS[now.tm_mon - 1]}"

            f_time  = self._font(48, bold=True, mono=True)
            f_date  = self._font(11)
            f_val   = self._font(18, mono=True)
            f_label = self._font(11)
            f_brand = self._font(9)

            # Time and date — upper half
            self._text(surf, time_str, f_time, _WHITE, center=(self.W // 2, 75))
            self._text(surf, date_str, f_date, _MUTED, center=(self.W // 2, 108))

            # Thin divider
            _pg.draw.line(surf, _BORDER, (20, 130), (220, 130), 1)

            # Sensor values
            co2, temp, hum = self._sensor_values()
            co2_clr  = _WHITE if co2 <= 800 else (_AMBER if co2 <= 1200 else _RED)
            temp_clr = _WHITE if 18 <= temp <= 21 else _AMBER

            cols   = (60, 120, 180)
            labels = ("CO2", "TEMP", "HUM")
            vals   = (f"{co2:.0f}", f"{temp:.1f}c", f"{hum:.0f}%")
            colors = (co2_clr, temp_clr, _WHITE)

            for cx, lbl, val, clr in zip(cols, labels, vals, colors):
                self._text(surf, lbl, f_label, _SECONDARY, center=(cx, 158))
                self._text(surf, val, f_val,   clr,        center=(cx, 180))

            # Brand watermark
            self._text(surf, "basecamp", f_brand, _SECONDARY, center=(self.W // 2, 310))

            self._flush()
        except Exception as e:
            log.error("IDLE render error: %s", e)

    # ── Layout: BEDTIME_PROMPT ────────────────────────────────────────────────

    def show_bedtime_prompt(self):
        """
        Render the BEDTIME_PROMPT layout and start the 5-minute timeout.
        Non-blocking — caller polls get_pending_action() for 'yes'/'not_yet'/'timeout'.
        """
        self._current_layout    = "bedtime_prompt"
        self._prompt_start_time = time.monotonic()
        self._render_bedtime_prompt()

    def _render_bedtime_prompt(self):
        if self._headless:
            return
        try:
            surf = self._surface
            surf.fill(_BG)

            now     = time.localtime()
            _DAYS   = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
            _MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                       "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
            time_str = time.strftime("%H:%M", now)
            date_str = f"{_DAYS[now.tm_wday]} {now.tm_mday:02d} {_MONTHS[now.tm_mon - 1]}"

            f_time = self._font(48, bold=True, mono=True)
            f_date = self._font(11)
            f_ask  = self._font(16)
            f_btn  = self._font(13)
            f_yes  = self._font(16, bold=True)

            # Time (centred y=40) and date (y=72)
            self._text(surf, time_str, f_time, _WHITE, center=(self.W // 2, 40))
            self._text(surf, date_str, f_date, _MUTED, center=(self.W // 2, 72))

            # Question
            self._text(surf, "Ready to sleep?", f_ask, _WHITE, center=(self.W // 2, 120))

            # Separator
            _pg.draw.line(surf, _BORDER, (20, 155), (220, 155), 1)

            # NOT YET button — y=170..220
            ny_rect = _pg.Rect(20, 170, 200, 50)
            self._rounded_rect(surf, _CARD_BG, ny_rect, radius=8,
                               border_color=_BORDER, border=1)
            self._text(surf, "NOT YET", f_btn, _MUTED, center=ny_rect.center)

            # YES button — y=235..300
            yes_rect = _pg.Rect(20, 235, 200, 65)
            self._rounded_rect(surf, _TEAL, yes_rect, radius=8)
            self._text(surf, "YES", f_yes, _BG, center=yes_rect.center)

            # Timeout bar: drains from full width (0 s) to empty (300 s)
            if self._prompt_start_time is not None:
                elapsed  = time.monotonic() - self._prompt_start_time
                fraction = max(0.0, 1.0 - elapsed / self._BEDTIME_TIMEOUT_S)
                bar_w    = int(self.W * fraction)
                if bar_w > 0:
                    _pg.draw.rect(surf, _TIMEOUT_BAR, _pg.Rect(0, 315, bar_w, 5))

            self._flush()
        except Exception as e:
            log.error("BEDTIME_PROMPT render error: %s", e)

    # ── Layout: MORNING ───────────────────────────────────────────────────────

    def show_morning(self, session_data: dict):
        """
        Render the MORNING layout.

        session_data keys: score, duration_hours, bed_entry, bed_exit,
        architecture_score, continuity_score, breathing_score, environment_score,
        positive_factors, negative_factors.

        If score is None: show loading state with animated dots.
        """
        self._current_layout = "morning"
        self._session_data   = session_data
        self._score          = session_data.get("score")
        self._loading        = self._score is None
        self._render_morning()

    def update_morning_score(self, score, session_data: dict):
        """Switch from loading state to score display once batch pipeline completes."""
        self._score          = score
        self._session_data   = session_data
        self._loading        = False
        self._current_layout = "morning"
        self._render_morning()

    def _render_morning(self):
        if self._headless:
            return
        try:
            if self._loading:
                self._render_morning_loading()
            else:
                self._render_morning_score()
        except Exception as e:
            log.error("MORNING render error: %s", e)

    def _render_morning_loading(self):
        surf = self._surface
        surf.fill(_BG)

        f_calc = self._font(16)
        f_dot  = self._font(20)
        f_dur  = self._font(13)

        self._text(surf, "Calculating...", f_calc, _MUTED, center=(self.W // 2, 130))

        # One dot cycles: frame 0→1→2→...
        dots = ("* . .", ". * .", ". . *")
        self._text(surf, dots[self._dot_idx % 3], f_dot, _TEAL, center=(self.W // 2, 162))

        dur = self._session_data.get("duration_hours")
        if dur is not None:
            self._text(surf, f"{float(dur):.1f}h sleep", f_dur, _MUTED,
                       center=(self.W // 2, 195))
        self._flush()

    def _render_morning_score(self):
        surf = self._surface
        surf.fill(_BG)
        d = self._session_data

        f_big   = self._font(72, bold=True, mono=True)
        f_lbl   = self._font(10)
        f_dur   = self._font(14, mono=True)
        f_times = self._font(11)
        f_clbl  = self._font(9)
        f_cval  = self._font(20, mono=True)
        f_fact  = self._font(10)
        f_hint  = self._font(9)

        # Score number — centred at y=78, colour by range
        score_n = int(round(self._score)) if self._score is not None else 0
        s_clr   = _score_color(score_n)
        self._text(surf, str(score_n), f_big, s_clr, center=(self.W // 2, 78))

        # "RECOVERY SCORE" label
        self._text(surf, "RECOVERY SCORE", f_lbl, _MUTED, center=(self.W // 2, 125))

        # Separator
        _pg.draw.line(surf, _BORDER, (20, 140), (220, 140), 1)

        # Sleep info row (y=148)
        dur     = float(d.get("duration_hours") or 0.0)
        b_entry = str(d.get("bed_entry", ""))
        b_exit  = str(d.get("bed_exit",  ""))
        e_str   = b_entry[11:16] if len(b_entry) > 15 else b_entry[:5]
        x_str   = b_exit[11:16]  if len(b_exit)  > 15 else b_exit[:5]

        self._text(surf, f"{dur:.1f}h",      f_dur,   _WHITE, topleft=(20, 148))
        self._text(surf, f"{e_str}-{x_str}", f_times, _MUTED, topright=(220, 148))

        # 2×2 component score grid
        cards = [
            ("ARCH", d.get("architecture_score", 0), _ARCH_CLR),
            ("CONT", d.get("continuity_score",   0), _CONT_CLR),
            ("BRTH", d.get("breathing_score",    0), _BRTH_CLR),
            ("ENV",  d.get("environment_score",  0), _ENV_CLR),
        ]
        grid_pos = [(15, 175), (125, 175), (15, 221), (125, 221)]

        for (gx, gy), (lbl, val, clr) in zip(grid_pos, cards):
            card = _pg.Rect(gx, gy, 100, 36)
            self._rounded_rect(surf, _CARD_BG, card, radius=4)
            # Left accent border
            _pg.draw.rect(surf, clr, _pg.Rect(gx, gy, 3, 36), border_radius=4)
            self._text(surf, lbl, f_clbl, _MUTED, topleft=(gx + 7, gy + 4))
            val_s = str(int(round(val))) if val is not None else "-"
            self._text(surf, val_s, f_cval, clr, topleft=(gx + 7, gy + 14))

        # Positive / negative factors
        positives = d.get("positive_factors") or []
        negatives = d.get("negative_factors") or []

        if positives:
            pt = self._truncate(str(positives[0]), f_fact, 196)
            self._text(surf, f"+ {pt}", f_fact, _TEAL, topleft=(20, 265))
        if negatives:
            nt = self._truncate(str(negatives[0]), f_fact, 196)
            self._text(surf, f"- {nt}", f_fact, _RED, topleft=(20, 280))

        self._text(surf, "tap for full log", f_hint, _SECONDARY, topright=(220, 305))

        self._flush()

    # ── Touch / action ────────────────────────────────────────────────────────

    def simulate_touch(self, x: int, y: int):
        """Inject a synthetic touch at (x, y) in 240×320 space — for tests and mock mode."""
        self._touch_queue.append((x, y))

    def get_pending_action(self):
        """
        Return the next pending action or None.

        Checks (in order):
          1. BEDTIME_PROMPT timeout (300 s)
          2. Touches injected via simulate_touch()
          3. Pre-queued actions from previous processing
          4. Live pygame mouse / QUIT events

        Returns: 'yes' | 'not_yet' | 'dismiss' | 'log' | 'timeout' | None
        """
        # 1. Bedtime timeout
        if (self._current_layout == "bedtime_prompt"
                and self._prompt_start_time is not None
                and time.monotonic() - self._prompt_start_time >= self._BEDTIME_TIMEOUT_S):
            self._current_layout = None
            return "timeout"

        # 2. Injected / simulated touches
        while self._touch_queue:
            x, y = self._touch_queue.pop(0)
            action = self._resolve_touch(x, y)
            if action:
                return action

        # 3. Pre-queued (from QUIT events in tick)
        if self._pending_actions:
            return self._pending_actions.pop(0)

        # 4. Live pygame events
        if not self._headless and _PYGAME_OK:
            return self._poll_pygame()

        return None

    def _resolve_touch(self, x: int, y: int):
        """Map a touch at (x, y) in 240×320 space to an action string."""
        if self._current_layout == "bedtime_prompt":
            pt = (x, y)
            if self._yes_rect and self._yes_rect.collidepoint(pt):
                return "yes"
            if self._not_yet_rect and self._not_yet_rect.collidepoint(pt):
                return "not_yet"
            # Rect-free fallback (headless / no pygame)
            if 20 <= x <= 220 and 235 <= y <= 300:
                return "yes"
            if 20 <= x <= 220 and 170 <= y <= 220:
                return "not_yet"
            return None

        if self._current_layout == "morning":
            if self._log_rect and self._log_rect.collidepoint((x, y)):
                return "log"
            if y >= 265:
                return "log"
            return "dismiss"

        return None

    def _poll_pygame(self):
        """Drain the pygame event queue; return first recognised action."""
        try:
            for event in _pg.event.get():
                if event.type == _pg.QUIT:
                    return "dismiss"
                if event.type == _pg.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    if self.mock:
                        try:
                            from server.config import SCREEN_MOCK_SCALE
                            scale = SCREEN_MOCK_SCALE
                        except (ImportError, AttributeError):
                            scale = 2
                        x, y = mx // scale, my // scale
                    else:
                        x, y = mx, my
                    action = self._resolve_touch(x, y)
                    if action:
                        return action
        except Exception:
            pass
        return None

    # ── Tick — called every second by sleepmode.py ────────────────────────────

    def tick(self):
        """
        Advance animations and re-render the current layout.
        Updates: clock (IDLE/BEDTIME_PROMPT), timeout bar (BEDTIME_PROMPT),
        loading dots (MORNING loading state).
        """
        if self._headless:
            return
        try:
            self._dot_idx = (self._dot_idx + 1) % 3

            if self._current_layout == "idle":
                self._render_idle()
            elif self._current_layout == "bedtime_prompt":
                self._render_bedtime_prompt()
            elif self._current_layout == "morning" and self._loading:
                self._render_morning_loading()
        except Exception as e:
            log.debug("tick error: %s", e)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        """Turn off backlight, release GPIO, quit pygame."""
        self.turn_off()
        if self._gpio_ready:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
        if not self._headless and _PYGAME_OK:
            try:
                _pg.quit()
            except Exception:
                pass
        self._headless = True
