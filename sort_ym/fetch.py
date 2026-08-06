from __future__ import annotations

import json
import time
from pathlib import Path

from yandex_music import Client, Track

from .ymclient import chunked, with_retries

TRACKS_CACHE_FILE = "tracks.json"
ARTIST_GENRES_CACHE_FILE = "artist_genres.json"


def _track_genre(track: Track) -> str | None:
    for album in track.albums:
        if album.genre:
            return album.genre
    return None


def _serialize(track: Track) -> dict:
    # album_id, album_title и year берутся из одного и того же albums[0] - иначе название
    # альбома может разъехаться с его id (у трека может быть несколько альбомов).
    album = track.albums[0] if track.albums else None
    return {
        "id": track.id,
        "album_id": album.id if album else None,
        "album_title": (album.title or "") if album else "",
        "year": album.year if album else None,
        "title": track.title or "",
        "artists": [a.name for a in track.artists if a.name],
        "artist_ids": [a.id for a in track.artists if a.name and a.id is not None],
        "genre_raw": _track_genre(track),
        "lyrics_available": bool(track.lyrics_available),
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_tracks_cache(cache_dir: Path) -> dict[str, dict]:
    cache_file = cache_dir / TRACKS_CACHE_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return {}


def fetch_liked_tracks(
    client: Client,
    cache_dir: Path,
    batch_size: int,
    batch_delay: float,
) -> dict[str, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / TRACKS_CACHE_FILE
    cache = load_tracks_cache(cache_dir)

    likes = with_retries(lambda: client.users_likes_tracks())
    if likes is None:
        print("Не удалось получить список лайкнутых треков.")
        return cache

    all_ids = likes.tracks_ids
    # "not in cache" - трек ещё не загружен; "artist_ids"/"year" not in cache[tid] - трек загружен
    # старой версией кэша (до добавления этих полей) и должен быть докачан повторно. Проверяем
    # наличие ключа, а не правдивость значения - year легитимно может быть None у части альбомов,
    # и тогда такой трек перекачивался бы при каждом fetch.
    missing_ids = [
        tid
        for tid in all_ids
        if tid not in cache or "artist_ids" not in cache[tid] or "year" not in cache[tid]
    ]

    print(f"Лайкнутых треков: {len(all_ids)}, новых для загрузки: {len(missing_ids)}")

    for batch in chunked(missing_ids, batch_size):
        tracks = with_retries(lambda: client.tracks(batch))
        if len(tracks) != len(batch):
            print(
                f"  предупреждение: запрошено {len(batch)} треков, получено {len(tracks)} - "
                "часть могла быть удалена из каталога Яндекса, попробуем ещё раз при следующем fetch"
            )
        # Кэшируем по исходному id из списка лайков (likes.tracks_ids), а не по track.track_id,
        # пересчитанному из albums[0] вернувшегося Track - для трека, доступного на нескольких
        # альбомах, "основной" альбом в ответе может отличаться от того, под которым трек лайкнут.
        # Иначе такой трек тут же попадает под stale-очистку ниже как "больше не лайкнутый".
        for original_id, track in zip(batch, tracks):
            cache[original_id] = _serialize(track)
        _atomic_write_json(cache_file, cache)
        print(f"  загружено {len(cache)}/{len(all_ids)}")
        time.sleep(batch_delay)

    stale = set(cache) - set(all_ids)
    for tid in stale:
        del cache[tid]
    if stale:
        _atomic_write_json(cache_file, cache)
        print(f"  убрано из кэша (больше не лайкнуто): {len(stale)}")

    return cache


def load_artist_genres(cache_dir: Path) -> dict[str, dict]:
    cache_file = cache_dir / ARTIST_GENRES_CACHE_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return {}


def fetch_artist_genres(
    client: Client,
    cache_dir: Path,
    batch_size: int,
    batch_delay: float,
) -> dict[str, dict]:
    """Догружает жанры артистов (Artist.genres - несколько тегов, точнее одного альбомного genre_raw).

    client.artists() - батч-эндпоинт (как client.tracks()), поэтому даже на тысячу с лишним
    уникальных артистов уходит около десятка запросов, а не один на артиста.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / ARTIST_GENRES_CACHE_FILE
    cache = load_artist_genres(cache_dir)

    tracks_cache = load_tracks_cache(cache_dir)
    # aid может быть None - у части треков сторонней/пиратской загрузки артист в API Яндекса
    # не привязан к id (есть только имя). Такие пропускаем, их жанр возьмём только по треку.
    all_artist_ids = {
        str(aid)
        for t in tracks_cache.values()
        for aid in t.get("artist_ids", [])
        if aid is not None
    }
    missing_ids = sorted(aid for aid in all_artist_ids if aid not in cache)

    if not missing_ids:
        return cache

    print(f"Уникальных артистов: {len(all_artist_ids)}, новых для загрузки: {len(missing_ids)}")

    for batch in chunked(missing_ids, batch_size):
        artists = with_retries(lambda: client.artists(batch))
        for artist in artists:
            cache[str(artist.id)] = {
                "name": artist.name or "",
                "genres": list(artist.genres or []),
            }
        _atomic_write_json(cache_file, cache)
        print(f"  загружено {len(cache)}/{len(all_artist_ids)}")
        time.sleep(batch_delay)

    return cache
