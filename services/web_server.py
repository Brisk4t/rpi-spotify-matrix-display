# Purpose: Serves a small web page for changing display settings, config.ini and Spotify authorization without SSH.
import base64
import hmac
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from player.display_settings import DisplaySettings, COLOR_PROFILES, RANGES
from utils.file_utils import write_atomic

logger = logging.getLogger(__name__)

CONFIG_PATH = 'config.ini'
PAGE_PATH = Path(__file__).with_name('web_ui.html')
MAX_BODY_BYTES = 64 * 1024

HARDWARE_MAPPINGS = ['regular', 'regular-pi1', 'adafruit-hat', 'adafruit-hat-pwm', 'classic', 'classic-pi1', 'compute-module']

# config.ini settings editable from the page: (section, key, label, kind[, options]).
# Secrets are never sent to the browser, and leaving them empty keeps the current value.
CONFIG_FIELDS = [
    ('Spotify', 'client_id', 'Client ID', 'text'),
    ('Spotify', 'client_secret', 'Client secret', 'secret'),
    ('Spotify', 'sp_dc', 'sp_dc cookie (lyrics)', 'secret'),
    ('Spotify', 'fetch_interval', 'Fetch interval (s)', 'int'),
    ('Spotify', 'idle_fetch_interval', 'Idle fetch interval (s)', 'float'),
    ('Spotify', 'device_whitelist', 'Device whitelist', 'text'),
    ('Player', 'target_fps', 'Target FPS', 'int'),
    ('Player', 'dedicated_lyrics', 'Dedicated lyrics', 'bool'),
    ('Player', 'always_fullscreen', 'Always fullscreen', 'bool'),
    ('Player', 'fullscreen_delay', 'Fullscreen delay (s)', 'float'),
    ('Player', 'shutdown_delay', 'Shutdown delay (s)', 'float'),
    ('Player', 'text_scroll_speed', 'Text scroll speed', 'float'),
    ('Player', 'text_scroll_delay', 'Text scroll delay (s)', 'float'),
    ('Matrix', 'hardware_mapping', 'Hardware mapping', 'select', HARDWARE_MAPPINGS),
    ('Matrix', 'gpio_slowdown', 'GPIO slowdown', 'int'),
    ('HomeAssistant', 'enabled', 'Enabled', 'bool'),
    ('HomeAssistant', 'mqtt_host', 'MQTT host', 'text'),
    ('HomeAssistant', 'mqtt_port', 'MQTT port', 'int'),
    ('HomeAssistant', 'mqtt_username', 'MQTT username', 'text'),
    ('HomeAssistant', 'mqtt_password', 'MQTT password', 'secret'),
    ('Web', 'password', 'Web page password', 'secret'),
]


def update_config_file(path: str, changes: dict):
    """
    Sets keys in an INI file while keeping its comments and layout, which configparser.write would drop.
    changes maps section -> {key: value}. Missing keys are added to the end of their section.
    """
    lines = Path(path).read_text().splitlines()
    pending = {section: {key.lower(): value for key, value in values.items()} for section, values in changes.items()}
    out = []

    def add_missing(section):
        missing = pending.pop(section, None)
        if not missing:
            return
        # Keep the blank lines that separate this section from the next one
        blanks = []
        while out and not out[-1].strip():
            blanks.append(out.pop())
        out.extend(f"{key} = {value}" for key, value in missing.items())
        out.extend(blanks)

    section = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            add_missing(section)
            section = stripped[1:-1].strip()
        elif section in pending and '=' in stripped and not stripped.startswith((';', '#')):
            key = stripped.split('=', 1)[0].strip().lower()
            if key in pending[section]:
                line = f"{key} = {pending[section].pop(key)}"
        out.append(line)
    add_missing(section)

    for section, values in pending.items():
        out.extend(['', f"[{section}]"])
        out.extend(f"{key} = {value}" for key, value in values.items())

    write_atomic(path, '\n'.join(out) + '\n')


def restart_app():
    """Replaces this process with a fresh copy, so config.ini changes apply with or without systemd."""
    logger.info("Restarting to apply new settings...")
    for handler in logging.getLogger().handlers:
        handler.flush()
    os.execv(sys.executable, [sys.executable] + sys.argv)


class WebServer:
    """
    Runs a ThreadingHTTPServer in a daemon thread. It sleeps until a request arrives,
    so it costs nothing while the page is closed.
    """
    def __init__(self, config, settings: DisplaySettings, spotify_module):
        self.config = config
        self.settings = settings
        self.spotify_module = spotify_module
        self.port = config.getint('Web', 'port', fallback=8000)
        self.password = config.get('Web', 'password', fallback='')

    def start(self):
        handler = type('Handler', (RequestHandler,), {'app': self})
        try:
            server = ThreadingHTTPServer(('', self.port), handler)
        except OSError as e:
            logger.error(f"Web server could not start on port {self.port}: {e}")
            return
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"Web settings page running on port {self.port} 🌐")

    def state(self):
        fields = []
        for section, key, label, kind, *options in CONFIG_FIELDS:
            field = {'id': f"{section}.{key}", 'section': section, 'label': label, 'kind': kind}
            value = self.config.get(section, key, fallback='')
            if kind == 'secret':
                field['is_set'] = bool(value) and not value.startswith('<')
            elif kind == 'bool':
                field['value'] = value.strip().lower() in ('1', 'yes', 'true', 'on')
            else:
                field['value'] = value
            if options:
                field['options'] = options[0]
            fields.append(field)

        spotify = self.spotify_module
        client_id = self.config.get('Spotify', 'client_id', fallback='')
        return {
            'display': self.settings.as_dict(),
            'ranges': RANGES,
            'profiles': list(COLOR_PROFILES),
            'auth': {
                'configured': bool(client_id) and not client_id.startswith('<'),
                'authorized': spotify.is_authorized,
                'url': spotify.get_authorize_url(),
            },
            'fields': fields,
        }

    def save_config(self, values: dict):
        fields = {f"{section}.{key}": (label, kind) for section, key, label, kind, *options in CONFIG_FIELDS}
        changes = {}
        for field_id, value in values.items():
            if field_id not in fields:
                raise ValueError(f"Unknown setting: {field_id}")
            label, kind = fields[field_id]
            if kind == 'bool':
                value = 'true' if value is True else 'false'
            else:
                value = str(value).strip()
                # An empty number would fail to parse at startup, and an empty secret means unchanged
                if kind in ('secret', 'int', 'float') and not value:
                    continue
                try:
                    if kind == 'int':
                        int(value)
                    elif kind == 'float':
                        float(value)
                except ValueError:
                    raise ValueError(f"{label} must be a {'whole ' if kind == 'int' else ''}number")
            if '\n' in value or '\r' in value:
                raise ValueError(f"{label} must be a single line")

            section, key = field_id.split('.', 1)
            # configparser treats % as interpolation, so escape it
            changes.setdefault(section, {})[key] = value.replace('%', '%%')

        update_config_file(CONFIG_PATH, changes)


class RequestHandler(BaseHTTPRequestHandler):
    app: WebServer = None

    def log_message(self, format, *args):
        logger.debug(format % args)

    def _send(self, status, body, content_type='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        password = self.app.password
        if not password:
            return True
        header = self.headers.get('Authorization', '')
        if header.startswith('Basic '):
            try:
                given = base64.b64decode(header[6:]).decode().partition(':')[2]
            except Exception:
                return False
            return hmac.compare_digest(given.encode(), password.encode())
        return False

    def _check_auth(self):
        if self._authorized():
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Spotify Matrix"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def do_GET(self):
        if not self._check_auth():
            return
        if self.path == '/':
            self._send(200, PAGE_PATH.read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/state':
            self._send(200, self.app.state())
        else:
            self._send(404, {'error': 'Not found'})

    def do_POST(self):
        if not self._check_auth():
            return
        # Requiring JSON makes browsers send a CORS preflight first, which this server never approves,
        # so other websites can't change settings through your browser
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            self._send(415, {'error': 'Expected application/json'})
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY_BYTES:
            self._send(413, {'error': 'Request too large'})
            return

        try:
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")

            if self.path == '/api/display':
                self.app.settings.update(**body)
                self._send(200, {'display': self.app.settings.as_dict()})
            elif self.path == '/api/auth':
                self.app.spotify_module.authorize(str(body.get('url', '')))
                self._send(200, {'ok': True})
            elif self.path == '/api/config':
                self.app.save_config(body)
                self._send(200, {'ok': True})
                threading.Timer(0.5, restart_app).start()
            elif self.path == '/api/restart':
                self._send(200, {'ok': True})
                threading.Timer(0.5, restart_app).start()
            else:
                self._send(404, {'error': 'Not found'})
        except Exception as e:
            logger.warning(f"Web request to {self.path} failed: {e}")
            self._send(400, {'error': str(e)})
