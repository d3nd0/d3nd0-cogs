from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse

_SUPPORTED_BASE_DOMAINS = {"suno.com", "suno.ai"}

_AUDIO_URL_RE = re.compile(r'"audio_url":"([^"]+)"')
_CANONICAL_URL_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
_DESCRIPTION_RE = re.compile(r'<meta name="description" content="([^"]+)"')
_DISPLAY_NAME_RE = re.compile(r'"display_name":"([^"]+)"')
_IMAGE_URL_RE = re.compile(r'"image_large_url":"([^"]+)"')
_OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]+)"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]+)"')
_PAGE_TITLE_RE = re.compile(r"<title>([^<]+)</title>")
_SONG_ID_RE = re.compile(r"/song/([0-9a-fA-F-]{36})")


@dataclass(frozen=True, slots=True)
class SunoSong:
    canonical_url: str
    audio_url: str
    title: str
    artist: str
    image_url: str | None = None
    song_id: str | None = None


def is_supported_suno_url(url: str) -> bool:
    parsed = urlparse(url.strip().strip("<>"))
    if parsed.scheme not in {"http", "https"}:
        return False
    return _base_domain(parsed.netloc) in _SUPPORTED_BASE_DOMAINS


def parse_suno_html(html: str, fallback_url: str) -> SunoSong:
    canonical_url = _extract_html_string(_CANONICAL_URL_RE, html) or fallback_url
    song_id = _extract_song_id(canonical_url) or _extract_song_id(fallback_url)

    audio_url = _extract_json_string(_AUDIO_URL_RE, html)
    if not audio_url and song_id:
        audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"

    if not audio_url:
        raise ValueError("Could not locate a playable Suno audio URL.")

    title = (
        _extract_html_string(_OG_TITLE_RE, html)
        or _extract_html_string(_PAGE_TITLE_RE, html)
        or "Unknown Suno Track"
    )
    if title.endswith(" | Suno"):
        title = title[: -len(" | Suno")].strip()

    artist = _extract_json_string(_DISPLAY_NAME_RE, html) or _extract_artist_from_description(html)
    if not artist:
        artist = "Suno"

    image_url = _extract_json_string(_IMAGE_URL_RE, html) or _extract_html_string(_OG_IMAGE_RE, html)

    return SunoSong(
        canonical_url=canonical_url,
        audio_url=audio_url,
        title=title,
        artist=artist,
        image_url=image_url,
        song_id=song_id,
    )


def _base_domain(netloc: str) -> str:
    host = netloc.lower().split(":", maxsplit=1)[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _extract_artist_from_description(html: str) -> str | None:
    description = _extract_html_string(_DESCRIPTION_RE, html)
    if not description or " by " not in description:
        return None
    _, after_by = description.split(" by ", maxsplit=1)
    return after_by.split(" (@", maxsplit=1)[0].strip() or None


def _extract_html_string(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return unescape(match.group(1)).strip()


def _extract_json_string(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return json.loads(f'"{match.group(1)}"')


def _extract_song_id(value: str) -> str | None:
    match = _SONG_ID_RE.search(value)
    if match:
        return match.group(1)
    return None
