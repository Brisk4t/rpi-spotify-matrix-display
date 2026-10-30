# Purpose: Holds adjustable display settings (power, brightness, contrast, saturation, color profile) and applies them to frames.
import threading

# Per-channel (R, G, B) gains
COLOR_PROFILES = {
    'Neutral': (1.0, 1.0, 1.0),
    'Warm': (1.0, 0.85, 0.65),
    'Cool': (0.8, 0.9, 1.0),
    'Night': (1.0, 0.4, 0.15),
}

# Rec. 601 luma weights, the gray each pixel moves towards when desaturated
LUMA = (0.299, 0.587, 0.114)

class DisplaySettings:
    """
    Thread-safe display settings that can be changed at runtime (e.g. from Home Assistant).
    Saturation is applied with a color matrix, contrast and color profile with a single lookup table;
    both are only rebuilt on change.
    Brightness is applied by the matrix hardware, or in the lookup table when software_brightness is set.
    """
    def __init__(self, config, software_brightness: bool = False):
        self.software_brightness = software_brightness
        self.on = True
        self.brightness = 100 if software_brightness else max(1, min(100, config.getint('Matrix', 'brightness', fallback=100)))
        self.contrast = max(0, min(200, config.getint('Matrix', 'contrast', fallback=100)))
        self.saturation = max(0, min(200, config.getint('Matrix', 'saturation', fallback=100)))
        profile = config.get('Matrix', 'color_profile', fallback='Neutral')
        self.color_profile = profile if profile in COLOR_PROFILES else 'Neutral'
        self.version = 0
        self._lock = threading.Lock()

        self._matrix = None
        self._lut = None
        self._lut_version = None
        self._last_src = None
        self._last_out = None
        self._last_version = None

    def update(self, **changes):
        """Applies setting changes and bumps the version so the display refreshes."""
        with self._lock:
            for key, value in changes.items():
                setattr(self, key, value)
            self.version += 1

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
