from __future__ import annotations

import json
import time
from pathlib import Path

from yandex_music import Client
from yandex_music.exceptions import NotFoundError

from . import language
from .ymclient import with_retries

LYRICS_TEXT_CACHE_FILE = "lyrics_text.json"


def ru_lyric_track_ids(
    tracks_cache: dict[str, dict],
    lang_cache: dict[str, str | None],
    all_languages: bool = False,
) -> list[str]:
    """Числовые id треков, у которых вообще есть текст.

    По умолчанию - только RU: на незнакомом языке текст песни несёт для языковой модели меньше
    сигнала, чем разбор трека, который слушатель понимает дословно. all_languages=True снимает
    языковой фильтр, оставляя только lyrics_available (иначе track_supplement заведомо вернёт
    запись без lyrics). Дедупликация нужна потому, что один и тот же трек может быть лайкнут с
    разных альбомов: ключи tracks_cache при этом разные, а числовой id (и, соответственно, ключ
    кэша текстов) - один.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for t in tracks_cache.values():
        if not t.get("lyrics_available"):
            continue
        tid = str(t["id"])
        if tid in seen:
            continue
        if not all_languages:
            lang = language.detect_language(t["title"], t["artists"], t["genre_raw"], lang_cache.get(tid))
            if lang != "RU":
                continue
        seen.add(tid)
        ids.append(tid)
    return ids


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_lyrics_cache(cache_dir: Path) -> dict[str, str | None]:
    cache_file = cache_dir / LYRICS_TEXT_CACHE_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return {}


def _fetch_one_lyrics(client: Client, track_id: str) -> str | None:
    try:
        supplement = with_retries(lambda: client.track_supplement(track_id))
    except NotFoundError:
        return None
    if supplement is None or supplement.lyrics is None:
        return None
    return supplement.lyrics.full_lyrics


def fetch_lyrics_text(
    client: Client,
    track_ids: list[str],
    cache_dir: Path,
    delay: float,
) -> dict[str, str | None]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / LYRICS_TEXT_CACHE_FILE
    cache = load_lyrics_cache(cache_dir)

    missing = [tid for tid in track_ids if tid not in cache]
    if not missing:
        return cache

    print(f"Запрос текста песни для {len(missing)} треков...")
    for i, tid in enumerate(missing, 1):
        cache[tid] = _fetch_one_lyrics(client, tid)
        if i % 20 == 0:
            _atomic_write_json(cache_file, cache)
            print(f"  загружено {i}/{len(missing)}")
        time.sleep(delay)

    _atomic_write_json(cache_file, cache)
    without_text = sum(1 for tid in track_ids if cache.get(tid) is None)
    print(f"  готово: {len(track_ids)} треков, без текста {without_text}")
    return cache
