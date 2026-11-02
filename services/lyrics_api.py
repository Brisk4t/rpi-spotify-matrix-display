# Purpose: Lyrics fetching module, using the built-in Spotify client or LibreLyrics.
import time
import threading
import logging
from typing import Optional

from services.spotify_lyrics import SpotifyLyricsClient, LyricsRateLimited

try:
    from librelyrics import LibreLyrics
    from librelyrics.exceptions import RateLimitError, LyricsNotFound
except ImportError:
    # librelyrics is an optional extra and requires Python 3.10+
    LibreLyrics = None

LYRICS_PROVIDERS = ['builtin', 'librelyrics']

logger = logging.getLogger(__name__)

class LyricsFetcher:
    def __init__(self, config):
        self.config = config
        self._fetch = None
        self.last_track_id: Optional[str] = None
        self.last_lyrics: Optional[dict] = None
        self.rate_limit_until = 0.0
        self._fetching_lyrics_id: Optional[str] = None

        self._setup_provider()

    def _setup_provider(self):
        sp_dc = self.config.get('Spotify', 'sp_dc', fallback=None)
        provider = self.config.get('Spotify', 'lyrics_provider', fallback='builtin').strip().lower()
        if provider not in LYRICS_PROVIDERS:
            logger.warning(f"Unknown lyrics_provider '{provider}', using builtin")
            provider = 'builtin'

        if not self.config.getboolean('Spotify', 'lyrics', fallback=False):
            logger.info("Lyrics fetching disabled. Set lyrics = true in config.ini to enable it.")
        elif not (sp_dc and len(sp_dc) > 100):
            logger.info("Lyrics fetching disabled. Please provide your sp_dc cookie in config.ini.")
            logger.info("- See https://github.com/akashrchandran/syrics/wiki/Finding-sp_dc")
        elif provider == 'librelyrics':
            if LibreLyrics is None:
                logger.warning("Lyrics fetching disabled. LibreLyrics is not installed (requires Python 3.10+). Use lyrics_provider = builtin instead.")
                return
            try:
                ll = LibreLyrics(config={'plugins': {'spotify': {'sp_dc': sp_dc}}})
                self._fetch = lambda track_id: self._fetch_librelyrics(ll, track_id)
                logger.info("LibreLyrics initialized successfully")
            except Exception as e:
                logger.error(f"LibreLyrics failed to initialize: {e}", exc_info=True)
        else:
            self._fetch = SpotifyLyricsClient(sp_dc).get_lyrics
            logger.info("Built-in Spotify lyrics client ready")

    @staticmethod
    def _fetch_librelyrics(ll, track_id: str) -> dict:
        """Fetches with LibreLyrics and converts the result to Spotify's lyrics format."""
        try:
            res = ll.fetch(f"https://open.spotify.com/track/{track_id}")
        except RateLimitError as e:
            raise LyricsRateLimited(str(e), getattr(e, 'retry_after', None))
        except LyricsNotFound:
            return {}

        lines = []
        for line in res.lyrics:
            lines.append({
                'startTimeMs': line.start_ms if line.start_ms is not None else 0,
                'words': line.text
            })
        is_synced = any(line.start_ms is not None for line in res.lyrics)
        return {
            'lyrics': {
                'lines': lines,
                'syncType': 'LINE_SYNCED' if is_synced else 'UNSYNCED'
            }
        }

    def get_lyrics(self, track_id: str, track_name: str = "", allow_fetch: bool = True) -> Optional[dict]:
        if not self._fetch or not track_id:
            return {}

        if track_id != self.last_track_id:
            if not allow_fetch or self._fetching_lyrics_id == track_id or time.time() < self.rate_limit_until:
                return None

            self._fetching_lyrics_id = track_id

            def fetch_thread():
                try:
                    self.last_lyrics = self._fetch(track_id)
                    if self.last_lyrics:
                        logger.info("Lyrics fetched ✅")
                    else:
                        logger.info("Lyrics not found ❌")
                except LyricsRateLimited as e:
                    retry = e.retry_after or 30
                    self.rate_limit_until = time.time() + retry
                    logger.warning(f"Lyrics rate limited ❌ (retry in {retry}s): {e}")
                    self.last_lyrics = {}
                except Exception as e:
                    logger.error(f"Lyrics exception ❌: {e}")
                    self.last_lyrics = {}
                finally:
                    self.last_track_id = track_id
                    self._fetching_lyrics_id = None

            threading.Thread(target=fetch_thread, daemon=True).start()
            return None

        return self.last_lyrics
