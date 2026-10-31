# Purpose: Minimal Spotify lyrics client using the sp_dc cookie. Needs only requests, so it runs on Python 3.9.
# Ported from the lyrics path of librelyrics-spotify (https://github.com/libre-lyrics/librelyrics-spotify).
import hashlib
import hmac
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Spotify rotates the TOTP secret; this community-maintained list is the one librelyrics-spotify uses
SECRETS_URL = "https://code.thetadev.de/ThetaDev/spotify-secrets/raw/branch/main/secrets/secretDict.json"
TOKEN_URL = "https://open.spotify.com/api/token"
LYRICS_URL = "https://spclient.wg.spotify.com/color-lyrics/v2/track/{}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class LyricsRateLimited(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class SpotifyLyricsClient:
    """
    Fetches lyrics from Spotify's web player API. The access token is cached until it expires,
    and the TOTP secret is re-fetched when a token request fails in case it was rotated.
    """
    def __init__(self, sp_dc: str):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.session.cookies.set("sp_dc", sp_dc)
        self.secret: Optional[bytes] = None
        self.secret_version: Optional[str] = None
        self.access_token: Optional[str] = None
        self.token_expires = 0.0

    def _load_secret(self):
        resp = self.session.get(SECRETS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        version = list(data)[-1]
        self.secret = "".join(str(v ^ ((i % 33) + 9)) for i, v in enumerate(data[version])).encode()
        self.secret_version = version

    def _totp(self) -> str:
        counter = int(time.time() // 30)
        digest = hmac.new(self.secret, counter.to_bytes(8, "big"), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
        return str(code % 10**6).zfill(6)

    def _refresh_token(self):
        if not self.secret:
            self._load_secret()

        code = self._totp()
        params = {
            "reason": "init",
            "productType": "web-player",
            "totp": code,
            "totpVer": self.secret_version,
            "totpServer": code,
        }
        resp = self.session.get(TOKEN_URL, params=params, timeout=10)
        if resp.status_code != 200:
            self.secret = None
            raise RuntimeError(f"Spotify lyrics token request failed: HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("accessToken") or data.get("isAnonymous"):
            raise RuntimeError("Spotify rejected the sp_dc cookie. It may have expired, so copy a new one.")
        self.access_token = data["accessToken"]
        expires_ms = data.get("accessTokenExpirationTimestampMs") or (time.time() + 3600) * 1000
        self.token_expires = expires_ms / 1000 - 60

    def get_lyrics(self, track_id: str) -> dict:
        """Returns {'lyrics': {...}} in Spotify's format, or {} when the track has no lyrics."""
        for attempt in range(2):
            if not self.access_token or time.time() >= self.token_expires:
                self._refresh_token()

            resp = self.session.get(
                LYRICS_URL.format(track_id),
                params={"format": "json", "market": "from_token"},
                headers={"Authorization": f"Bearer {self.access_token}", "App-Platform": "WebPlayer"},
                timeout=10,
            )
            if resp.status_code == 200:
                lyrics = resp.json().get("lyrics")
                return {"lyrics": lyrics} if lyrics else {}
            if resp.status_code == 404:
                return {}
            if resp.status_code == 429:
                try:
                    retry_after = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    retry_after = None
                raise LyricsRateLimited(f"HTTP 429 for {track_id}", retry_after)
            if resp.status_code == 401:
                # The token was revoked early, so get a fresh one and try once more
                self.access_token = None
                continue
            break

        raise RuntimeError(f"Spotify lyrics request failed: HTTP {resp.status_code}")
