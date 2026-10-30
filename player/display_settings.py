# Purpose: Holds adjustable display settings (power, brightness, contrast, saturation, color profile) and applies them to frames.
import json
import logging
import threading

from utils.file_utils import write_atomic

logger = logging.getLogger(__name__)

SETTINGS_PATH = 'settings.json'

# Per-channel (R, G, B) gains
COLOR_PROFILES = {
    'Neutral': (1.0, 1.0, 1.0),
    'Warm': (1.0, 0.85, 0.65),
    'Cool': (0.8, 0.9, 1.0),
    'Night': (1.0, 0.4, 0.15),
}

# Allowed (min, max) for the numeric settings
RANGES = {
    'brightness': (1, 100),
    'contrast': (0, 200),
    'saturation': (0, 200),
}

# Rec. 601 luma weights, the gray each pixel moves towards when desaturated
LUMA = (0.299, 0.587, 0.114)

class DisplaySettings:
    """
    Thread-safe display settings that can be changed at runtime (e.g. from Home Assistant or the web page).
    Starts from config.ini, then restores the last changes saved in settings.json.
    Saturation is applied with a color matrix, contrast and color profile with a single lookup table;
    both are only rebuilt on change.
    Brightness is applied by the matrix hardware, or in the lookup table when software_brightness is set.
    """
    def __init__(self, config, software_brightness: bool = False):
        self.software_brightness = software_brightness
        self.on = True
        self.brightness = 100
        self.contrast = 100
        self.saturation = 100
        self.color_profile = 'Neutral'
        self.version = 0
        self._lock = threading.Lock()
        self._listeners = []

        defaults = {
            'contrast': config.get('Matrix', 'contrast', fallback=100),
            'saturation': config.get('Matrix', 'saturation', fallback=100),
            'color_profile': config.get('Matrix', 'color_profile', fallback='Neutral'),
        }
        # The emulator always runs at full brightness, so its software brightness starts at 100
        if not software_brightness:
            defaults['brightness'] = config.get('Matrix', 'brightness', fallback=100)
        self._set_valid(defaults)

        try:
            with open(SETTINGS_PATH) as f:
                self._set_valid(json.load(f))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Could not load {SETTINGS_PATH}: {e}")

        self._matrix = None
        self._lut = None
        self._lut_version = None
        self._last_src = None
        self._last_out = None
        self._last_version = None

    def _set_valid(self, values):
        """Sets each valid value and skips invalid ones, for loading config and saved settings."""
        for key, value in values.items():
            try:
                setattr(self, key, self.validate(key, value))
            except ValueError as e:
                logger.warning(f"Ignoring display setting: {e}")

    @staticmethod
    def validate(key, value):
        """Returns the value converted and clamped for the setting, or raises ValueError."""
        if key in RANGES:
            low, high = RANGES[key]
            return max(low, min(high, int(float(value))))
        if key == 'on':
            if not isinstance(value, bool):
                raise ValueError(f"on must be true or false, got {value!r}")
            return value
        if key == 'color_profile':
            if value not in COLOR_PROFILES:
                raise ValueError(f"Unknown color profile: {value!r}")
            return value
        raise ValueError(f"Unknown display setting: {key!r}")

    def as_dict(self):
        with self._lock:
            return {key: getattr(self, key) for key in ('on', 'brightness', 'contrast', 'saturation', 'color_profile')}

    def add_listener(self, callback):
        """Registers callback(settings) to be called after every change."""
        self._listeners.append(callback)

    def update(self, **changes):
        """Validates and applies setting changes, saves them and bumps the version so the display refreshes."""
        changes = {key: self.validate(key, value) for key, value in changes.items()}
        with self._lock:
            for key, value in changes.items():
                setattr(self, key, value)
            self.version += 1

        state = self.as_dict()
        try:
            write_atomic(SETTINGS_PATH, json.dumps(state))
        except Exception as e:
            logger.error(f"Could not save {SETTINGS_PATH}: {e}")

        for callback in self._listeners:
            try:
                callback(self)
            except Exception as e:
                logger.error(f"Display settings listener failed: {e}")

    def _build_matrix(self):
        with self._lock:
            saturation = self.saturation / 100.0

        if saturation == 1.0:
            return None

        matrix = []
        for row in range(3):
            for col in range(3):
                weight = LUMA[col] * (1 - saturation)
                matrix.append(weight + saturation if row == col else weight)
            matrix.append(0)
        return tuple(matrix)

    def _build_lut(self):
        with self._lock:
            contrast = self.contrast / 100.0
            gains = COLOR_PROFILES[self.color_profile]
            scale = self.brightness / 100.0 if self.software_brightness else 1.0

        if contrast == 1.0 and scale == 1.0 and gains == (1.0, 1.0, 1.0):
            return None

        lut = []
        for gain in gains:
            for v in range(256):
                adjusted = ((v - 128) * contrast + 128) * gain * scale
                lut.append(max(0, min(255, int(adjusted))))
        return lut

    def apply(self, frame):
        """Returns the frame with saturation, contrast and color profile applied, reusing the result for unchanged frames."""
        version = self.version
        if frame is self._last_src and version == self._last_version:
            return self._last_out

        if self._lut_version != version:
            self._matrix = self._build_matrix()
            self._lut = self._build_lut()
            self._lut_version = version

        out = frame.convert('RGB', self._matrix) if self._matrix else frame
        out = out.point(self._lut) if self._lut else out
        self._last_src, self._last_version, self._last_out = frame, version, out
        return out
