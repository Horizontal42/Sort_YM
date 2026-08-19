from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path

from yandex_music import Client
from yandex_music.exceptions import NotFoundError

from .ymclient import with_retries

LYRICS_LANG_CACHE_FILE = "lyrics_lang.json"

RU_GENRE_HINTS = {
    "rusrap",
    "ruspop",
    "rusrock",
    "shanson",
    "bard",
    "author",
    "avtorskaya",
    "estrada",
}


def _script_counts(text: str) -> tuple[int, int]:
    cyrillic = 0
    latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        if "CYRILLIC" in name:
            cyrillic += 1
        elif "LATIN" in name:
            latin += 1
    return cyrillic, latin


def alphabet_heuristic(title: str, artists: list[str]) -> str | None:
    text = " ".join([title, *artists])
    cyrillic, latin = _script_counts(text)
    if cyrillic == 0 and latin == 0:
        if any(ch.isalpha() for ch in text):
            return "INT"
        return None
    if cyrillic > latin:
        return "RU"
    if latin > cyrillic:
        return "INT"
    return None


def genre_hint(genre_raw: str | None) -> str | None:
    if genre_raw and genre_raw.lower() in RU_GENRE_HINTS:
        return "RU"
    return None


def normalize_api_language(text_language: str | None) -> str | None:
    if not text_language:
        return None
    return "RU" if text_language.strip().lower() == "ru" else "INT"


def detect_language(
    title: str,
    artists: list[str],
    genre_raw: str | None,
    api_language: str | None,
) -> str:
    lang = normalize_api_language(api_language)
    if lang:
        return lang

    lang = genre_hint(genre_raw)
    if lang:
        return lang

    lang = alphabet_heuristic(title, artists)
    if lang:
        return lang

    return "UNKNOWN"


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_lang_cache(cache_dir: Path) -> dict[str, str | None]:
    cache_file = cache_dir / LYRICS_LANG_CACHE_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return {}


def _fetch_supplement(client: Client, track_id: str) -> tuple[str | None, str | None]:
    try:
        supplement = with_retries(lambda: client.track_supplement(track_id))
    except NotFoundError:
        return None, None
    if supplement is None or supplement.lyrics is None:
        return None, None
    return supplement.lyrics.text_language, supplement.lyrics.full_lyrics


def fetch_api_languages(
    client: Client,
    track_ids: list[str],
    cache_dir: Path,
    delay: float,
) -> dict[str, str | None]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / LYRICS_LANG_CACHE_FILE
    cache = load_lang_cache(cache_dir)

    text_cache_file = cache_dir / "lyrics_text.json"
    if text_cache_file.exists():
        text_cache = json.loads(text_cache_file.read_text(encoding="utf-8"))
    else:
        text_cache = {}

    missing = [tid for tid in track_ids if tid not in cache]
    if not missing:
        return cache

    print(f"Запрос языка текста песни для {len(missing)} треков...")
    for i, tid in enumerate(missing, 1):
        lang, text = _fetch_supplement(client, tid)
        cache[tid] = lang
        if text is not None:
            text_cache[tid] = text
        if i % 20 == 0:
            _atomic_write_json(cache_file, cache)
            _atomic_write_json(text_cache_file, text_cache)
            print(f"  обработано {i}/{len(missing)}")
        time.sleep(delay)

    _atomic_write_json(cache_file, cache)
    _atomic_write_json(text_cache_file, text_cache)
    return cache
