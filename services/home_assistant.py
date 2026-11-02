# Purpose: Exposes display controls to Home Assistant via MQTT discovery.
import json
import logging

from player.display_settings import DisplaySettings, COLOR_PROFILES, RANGES

logger = logging.getLogger(__name__)

class HomeAssistantBridge:
    """
    Publishes a light (on/off + brightness), contrast and saturation numbers and a color profile select
    to Home Assistant using MQTT discovery, and applies incoming commands to DisplaySettings.
    State is published on every settings change, including changes made from the web page.
    """
    def __init__(self, config, settings: DisplaySettings):
        self.settings = settings
        self.host = config.get('HomeAssistant', 'mqtt_host', fallback='homeassistant.local')
        self.port = config.getint('HomeAssistant', 'mqtt_port', fallback=1883)
        self.username = config.get('HomeAssistant', 'mqtt_username', fallback='') or None
        self.password = config.get('HomeAssistant', 'mqtt_password', fallback='') or None
        self.discovery_prefix = config.get('HomeAssistant', 'discovery_prefix', fallback='homeassistant')
        self.device_id = config.get('HomeAssistant', 'device_id', fallback='spotify_matrix')
        self.device_name = config.get('HomeAssistant', 'device_name', fallback='Spotify Matrix')

        base = self.device_id
        self.status_topic = f"{base}/status"
        self.light_command = f"{base}/light/set"
        self.light_state = f"{base}/light/state"
        self.contrast_command = f"{base}/contrast/set"
        self.contrast_state = f"{base}/contrast/state"
        self.saturation_command = f"{base}/saturation/set"
        self.saturation_state = f"{base}/saturation/state"
        self.profile_command = f"{base}/color_profile/set"
        self.profile_state = f"{base}/color_profile/state"
        self.client = None

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.error("Home Assistant support requires paho-mqtt. Install it with: .venv/bin/pip install paho-mqtt")
            return

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.device_id)
        if self.username:
            self.client.username_pw_set(self.username, self.password)
        self.client.will_set(self.status_topic, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.settings.add_listener(lambda settings: self._publish_state())
        self.client.connect_async(self.host, self.port)
        self.client.loop_start()
        logger.info(f"Connecting to Home Assistant MQTT broker at {self.host}:{self.port}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error(f"Home Assistant MQTT connection failed: {reason_code}")
            return
        logger.info("Connected to Home Assistant MQTT broker 🏠")
        # Older versions retained commands, which would overwrite settings changed elsewhere on every restart
        commands = (self.light_command, self.contrast_command, self.saturation_command, self.profile_command)
        for topic in commands:
            client.publish(topic, None, retain=True)
        client.subscribe([(self.light_command, 0), (self.contrast_command, 0), (self.saturation_command, 0),
                          (self.profile_command, 0), (f"{self.discovery_prefix}/status", 0)])
        self._publish_discovery()
        client.publish(self.status_topic, "online", retain=True)
        self._publish_state()

    def _publish_discovery(self):
        device = {"identifiers": [self.device_id], "name": self.device_name, "model": "rpi-spotify-matrix-display"}
        common = {"availability_topic": self.status_topic, "device": device}
        entities = {
            "light/display": {
                "name": None,
                "unique_id": f"{self.device_id}_display",
                "schema": "json",
                "command_topic": self.light_command,
                "state_topic": self.light_state,
                "supported_color_modes": ["brightness"],
                "brightness_scale": 100,
            },
            "number/contrast": {
                "name": "Contrast",
                "unique_id": f"{self.device_id}_contrast",
                "command_topic": self.contrast_command,
                "state_topic": self.contrast_state,
                "min": RANGES['contrast'][0],
                "max": RANGES['contrast'][1],
                "step": 5,
                "unit_of_measurement": "%",
                "mode": "slider",
                "icon": "mdi:contrast-box",
            },
            "number/saturation": {
                "name": "Saturation",
                "unique_id": f"{self.device_id}_saturation",
                "command_topic": self.saturation_command,
                "state_topic": self.saturation_state,
                "min": RANGES['saturation'][0],
                "max": RANGES['saturation'][1],
                "step": 5,
                "unit_of_measurement": "%",
                "mode": "slider",
                "icon": "mdi:palette-swatch",
            },
            "select/color_profile": {
                "name": "Color profile",
                "unique_id": f"{self.device_id}_color_profile",
                "command_topic": self.profile_command,
                "state_topic": self.profile_state,
                "options": list(COLOR_PROFILES),
                "icon": "mdi:palette",
            },
        }
        for path, payload in entities.items():
            component, object_id = path.split('/')
            topic = f"{self.discovery_prefix}/{component}/{self.device_id}/{object_id}/config"
            self.client.publish(topic, json.dumps({**payload, **common}), retain=True)

    def _publish_state(self):
        s = self.settings
        light = {"state": "ON" if s.on else "OFF", "brightness": s.brightness, "color_mode": "brightness"}
        self.client.publish(self.light_state, json.dumps(light), retain=True)
        self.client.publish(self.contrast_state, str(s.contrast), retain=True)
        self.client.publish(self.saturation_state, str(s.saturation), retain=True)
        self.client.publish(self.profile_state, s.color_profile, retain=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            if not payload:
                return
            if msg.topic == f"{self.discovery_prefix}/status":
                # Home Assistant restarted, so announce the entities again
                if payload == "online":
                    self._publish_discovery()
                    self._publish_state()
                return

            if msg.topic == self.light_command:
                command = json.loads(payload)
                changes = {}
                if "state" in command:
                    changes["on"] = command["state"] == "ON"
                if "brightness" in command:
                    changes["brightness"] = command["brightness"]
                self.settings.update(**changes)
            elif msg.topic == self.contrast_command:
                self.settings.update(contrast=payload)
            elif msg.topic == self.saturation_command:
                self.settings.update(saturation=payload)
            elif msg.topic == self.profile_command:
                self.settings.update(color_profile=payload)
        except Exception as e:
            logger.error(f"Invalid Home Assistant command on {msg.topic}: {e}")
