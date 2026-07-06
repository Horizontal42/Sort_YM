from __future__ import annotations

import json
import time
from pathlib import Path

from yandex_music import Client, Track

from .ymclient import chunked, with_retries

TRACKS_CACHE_FILE = "tracks.json"


def _track_genre(track: Track) -> str | None:
    for album in track.albums:
        if album.genre:
            return album.genre
    return None


def _serialize(track: Track) -> dict:
    album_id = track.albums[0].id if track.albums else None
    return {
        "id": track.id,
        "album_id": album_id,
        "title": track.title or "",
        "artists": [a.name for a in track.artists if a.name],
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
    missing_ids = [tid for tid in all_ids if tid not in cache]

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
