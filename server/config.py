DB_PATH = "data/basecamp.db"
CSI_UDP_PORT = 5006
CSI_UDP_HOST = "0.0.0.0"
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK_SECONDS = 30
SILENCE_THRESHOLD = 0.01
SNORE_THRESHOLD = 0.05
SNORE_FREQ_LOW = 60
SNORE_FREQ_HIGH = 500
RADAR_SERIAL_PORT = "/dev/ttyAMA0"
RADAR_BAUD_RATE = 256000
MIN_SLEEP_HOURS = 4
I2C_BUS = 1
SHT40_ADDR = 0x44
BH1750_ADDR = 0x23
SCD40_ADDR = 0x62
SGP40_ADDR = 0x59
DS3231_ADDR = 0x68   # RTC module; provides offline timekeeping (fake-hwclock must be disabled)
NTFY_TOPIC = "basecamp-recovery"
NTFY_SERVER = "https://ntfy.sh"
RECOVERY_WEIGHTS = {
    "architecture": 0.40,
    "continuity": 0.25,
    "breathing": 0.20,
    "environment": 0.15,
}

MOCK_HARDWARE = True

# Node power: both ESP32 nodes draw from Pi USB-A ports (no hub).
# Combined peak ~0.8A, within Pi 4's 1.2A USB budget.
NODE2_USB_POWER = True   # Node 2 powered from Pi USB-A via 5m 20AWG cable

# Screen and button GPIO
SCREEN_ROTATION = 90
SCREEN_BACKLIGHT_PIN = 22   # GPIO 22 (GPIO 24 is SPI DC -- conflicts with touchscreen)
BUTTON_PIN = 26

# Auto-wake: screen and glow LED come on at bed exit, off after idle
SCREEN_IDLE_TIMEOUT_S = 60   # seconds before backlight turns off after bed exit

# Recovery glow LED GPIO (RGB common-cathode, via resistors)
GLOW_R_PIN = 16
GLOW_G_PIN = 20
GLOW_B_PIN = 21

# Glow colour thresholds (score out of 100; divided by 10 for 0-10 display scale)
GLOW_GREEN_THRESHOLD = 70   # score >= 70 -> green (>=7/10)
GLOW_AMBER_THRESHOLD = 40   # score 40-69 -> amber (4-6.9/10); below 40 -> red

# Sleep mode timing
BEDTIME_WINDOW_START = 21
BEDTIME_WINDOW_END = 0
PRESENCE_ARM_MINUTES = 2
BEDTIME_PROMPT_TIMEOUT_MINUTES = 5
BEDTIME_SNOOZE_MINUTES = 30
AUTO_RECORD_MINUTES = 15
WAKE_ABSENCE_MINUTES = 15
WAKE_EARLIEST_HOUR = 5

# Pipeline / model
ANOMALY_MIN_NIGHTS = 60
AUDIO_RETENTION_DAYS = 7

# Watchdog / health
WATCHDOG_INTERVAL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 60

# Sleep stage classifier thresholds
MOVEMENT_THRESHOLD_LOW  = 0.05
MOVEMENT_THRESHOLD_HIGH = 0.30
DEEP_BREATHING_MIN      = 10
DEEP_BREATHING_MAX      = 15
REGULARITY_THRESHOLD_HIGH = 0.70
REGULARITY_THRESHOLD_LOW  = 0.40
DEEP_RUN_MIN_WINDOWS    = 4
STAGING_MIN_NIGHTS_ML   = 14

# Touchscreen display
SCREEN_WIDTH       = 240
SCREEN_HEIGHT      = 320
SCREEN_SPI_PORT    = 0
SCREEN_SPI_DEVICE  = 0
SCREEN_DC_PIN      = 24
SCREEN_RESET_PIN   = 25
# SCREEN_BACKLIGHT_PIN = 22  (already defined above)
TOUCH_CS_PIN       = 7
TOUCH_IRQ_PIN      = 17
TOUCH_X_MIN        = 200
TOUCH_X_MAX        = 3800
TOUCH_Y_MIN        = 200
TOUCH_Y_MAX        = 3800
SCREEN_FPS         = 10
SCREEN_MOCK_SCALE  = 2
