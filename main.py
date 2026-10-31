# Purpose: Entry point for the Raspberry Pi Spotify Matrix Display application.

import argparse
import configparser
import socket
import sys
import time
import warnings
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from services.spotify_api import SpotifyModule
from player.spotify_player import SpotifyPlayer
from player.display_settings import DisplaySettings
from utils.file_utils import write_atomic
from PIL import Image

logger = logging.getLogger(__name__)

CONFIG_TEMPLATE_PATH = 'config.ini.example'

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            RotatingFileHandler("matrix.log", maxBytes=5*1024*1024, backupCount=2),
            logging.StreamHandler(sys.stdout)
        ]
    )

def load_config(config_path: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()

    created = False
    if not Path(config_path).exists():
        if not Path(CONFIG_TEMPLATE_PATH).exists():
            logger.error(f"Configuration file not found: {config_path}")
            sys.exit(1)
        # First run: start from the template with the settings page on, so setup can be finished in a browser
        from services.web_server import update_config_file
        write_atomic(config_path, Path(CONFIG_TEMPLATE_PATH).read_text())
        update_config_file(config_path, {'Web': {'enabled': 'true'}})
        created = True
    
    config.read(config_path)
    if created:
        port = config.getint('Web', 'port', fallback=8000)
        logger.info(f"Created {config_path} from {CONFIG_TEMPLATE_PATH}. Finish setup at http://{socket.gethostname()}.local:{port}")
    return config


def setup_matrix(config: configparser.ConfigParser, is_emulated: bool):
    if is_emulated:
        try:
            from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions
            import pygame
        except ImportError:
            logger.error("❌ Error: Could not import 'RGBMatrixEmulator' module.")
            logger.info("💡 Install the emulator dependencies with: .venv/bin/pip install -e '.[emulator]'")
            sys.exit(1)
        
        # Clear RGBME's custom logger to prevent duplicate logs
        import logging
        logging.getLogger('RGBME').handlers.clear()
        
        # Workaround for Pygame built without PNG support (e.g., Python 3.14 alpha on macOS)
        # RGBMatrixEmulator attempts to load an icon.png which crashes Pygame if it only supports BMP
        original_load = pygame.image.load
        def safe_load(filepath, *args, **kwargs):
            try:
                return original_load(filepath, *args, **kwargs)
            except pygame.error as e:
                # Return a dummy 1x1 surface if load fails
                return pygame.Surface((1, 1))
        pygame.image.load = safe_load

    else:
        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
        except ImportError:
            logger.error("❌ Error: Could not import 'rgbmatrix' module.")
            logger.info("💡 This command is meant for running on a Raspberry Pi connected to an RGB matrix.")
            logger.info("   Use 'make emulate' to run the display within an emulator window.")
            sys.exit(1)
    
    options = RGBMatrixOptions()
    options.hardware_mapping = config.get('Matrix', 'hardware_mapping', fallback='regular')
    options.rows = 64
    options.cols = 64
    options.brightness = 100 if is_emulated else config.getint('Matrix', 'brightness', fallback=100)
    options.gpio_slowdown = config.getint('Matrix', 'gpio_slowdown', fallback=1)
    options.drop_privileges = False
    
    matrix = RGBMatrix(options=options)
    
    # Workaround for RGBMatrixEmulator bug where self.canvas is not initialized
    if is_emulated and not hasattr(matrix, 'canvas'):
        matrix.canvas = None
        
    return matrix


_warned_unsafe_set_image = False

def set_image(matrix, frame):
    """
    Pushes a frame to the matrix. rgbmatrix builds without the Makefile's pointer patch can't read images
    stored above 2 GB on 32-bit Pis, so those frames fall back to the slower safe copy instead of crashing.
    """
    global _warned_unsafe_set_image
    try:
        matrix.SetImage(frame)
    except OverflowError:
        if not _warned_unsafe_set_image:
            _warned_unsafe_set_image = True
            logger.warning("rgbmatrix can't read some frames directly, so they are copied slowly. "
                           "Rebuild it with: .venv/bin/pip uninstall -y rgbmatrix && make rpi-rgbmatrix")
        matrix.SetImage(frame, unsafe=False)


def main():
    parser = argparse.ArgumentParser(description='Raspberry Pi Spotify Matrix Display')
    parser.add_argument('-e', '--emulate', action='store_true', help='run within an emulator window')
    args = parser.parse_args()
    
    # Suppress Pillow 12 (2025-10-15) deprecation warning
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    try:
        setup_logging()
        config = load_config('config.ini')
        spotify_module = SpotifyModule(config, is_emulated=args.emulate)
        spotify_player = SpotifyPlayer(config, spotify_module)
        
        matrix = setup_matrix(config, args.emulate)
        
        # The emulator always runs at full brightness (see setup_matrix), so brightness is applied in software there
        settings = DisplaySettings(config, software_brightness=args.emulate)
        if config.getboolean('HomeAssistant', 'enabled', fallback=False):
            from services.home_assistant import HomeAssistantBridge
            HomeAssistantBridge(config, settings).start()
        if config.getboolean('Web', 'enabled', fallback=False):
            from services.web_server import WebServer
            WebServer(config, settings, spotify_module).start()
        
        off_frame = Image.new("RGB", (64, 64))
        target_fps = config.getint('Player', 'target_fps', fallback=60)
        target_frame_time = 1.0 / target_fps
        
        next_frame_time = time.perf_counter()
        last_time = next_frame_time
        last_frame = None
        last_frame_bytes = None
        settings_version = None

        while True:
            now = time.perf_counter()
            delta_time = now - last_time
            last_time = now

            if settings.version != settings_version:
                settings_version = settings.version
                if not args.emulate:
                    matrix.brightness = settings.brightness
                # Hardware brightness only applies to newly set pixels, so push the next frame again
                last_frame = last_frame_bytes = None

            if settings.on:
                frame = settings.apply(spotify_player.generate(delta_time))
            else:
                frame = off_frame

            if frame:
                # Only push frames that changed. The emulator handles its window events
                # while drawing, so it keeps receiving every frame.
                if frame is not last_frame or args.emulate:
                    frame_bytes = frame.tobytes()
                    if frame_bytes != last_frame_bytes or args.emulate:
                        set_image(matrix, frame)
                        last_frame_bytes = frame_bytes
                    last_frame = frame
            else:
                matrix.Clear()
                last_frame = last_frame_bytes = None
            
            now = time.perf_counter()
            sleep_time = next_frame_time - now
            
            if sleep_time > 0:
                time.sleep(sleep_time)
                next_frame_time += target_frame_time
            else:
                next_frame_time = now + target_frame_time
            
    except KeyboardInterrupt:
        logger.info(' Interrupted with Ctrl-C')


if __name__ == '__main__':
    main()
