from __future__ import annotations

import csv
from pathlib import Path

from . import classify, genres, language

FIELDNAMES = ["title", "artists", "genre_raw", "fine_bucket", "bucket", "lang", "target_playlist", "id", "album_id"]

# Сырые поля API, которых нет в базовом отчёте - подключаются группами через --extra
# (см. обсуждение в чате: added_at из TrackShort.timestamp, остальное - из Track/Album/Artist).
# Порядок в EXTRA_FIELDNAMES - канонический порядок колонок в CSV независимо от порядка групп в --extra.
EXTRA_GROUPS: dict[str, list[str]] = {
    "timestamp": ["added_at"],
    "duration": ["duration_ms"],
    "version": ["track_version", "album_version"],
    "album": ["release_date", "album_likes_count"],
    "artist": [
        "artist_track_count",
        "artist_direct_albums",
        "artist_also_albums",
        "artist_also_tracks",
        "artist_rating_month",
        "artist_rating_week",
        "artist_rating_day",
    ],
}
EXTRA_FIELDNAMES = [col for cols in EXTRA_GROUPS.values() for col in cols]


def resolve_extra_columns(group_names: list[str]) -> list[str]:
    """--extra timestamp album -> ["added_at", "release_date", "album_likes_count"] (канонический порядок).

    "all" - алиас на все группы сразу.
    """
    names = list(EXTRA_GROUPS) if "all" in group_names else group_names
    unknown = set(names) - set(EXTRA_GROUPS)
    if unknown:
        raise ValueError(f"неизвестные группы --extra: {sorted(unknown)}, доступны: {list(EXTRA_GROUPS)} или 'all'")
    selected = {col for name in names for col in EXTRA_GROUPS[name]}
    return [col for col in EXTRA_FIELDNAMES if col in selected]


REPORT_FILE = "report.csv"
REPORT_SOURCE_FILE = "report_source.csv"


def _extra_row_fields(t: dict, artist_genres: dict[str, dict], columns: list[str]) -> dict:
    # Счётчики/рейтинг берём у первого артиста трека - у треков с несколькими артистами
    # остальные не имеют выделенной колонки (см. обсуждение в чате).
    artist_ids = t.get("artist_ids", [])
    artist = artist_genres.get(str(artist_ids[0])) if artist_ids else None
    counts = (artist or {}).get("counts") or {}
    ratings = (artist or {}).get("ratings") or {}
    all_values = {
        "added_at": t.get("added_at"),
        "duration_ms": t.get("duration_ms"),
        "track_version": t.get("track_version") or "",
        "album_version": t.get("album_version") or "",
        "release_date": t.get("release_date"),
        "album_likes_count": t.get("album_likes_count"),
        "artist_track_count": counts.get("tracks"),
        "artist_direct_albums": counts.get("direct_albums"),
        "artist_also_albums": counts.get("also_albums"),
        "artist_also_tracks": counts.get("also_tracks"),
        "artist_rating_month": ratings.get("month"),
        "artist_rating_week": ratings.get("week"),
        "artist_rating_day": ratings.get("day"),
    }
    return {col: all_values[col] for col in columns}


def build_rows(
    tracks_cache: dict[str, dict],
    lang_cache: dict[str, str | None],
    genre_catalog: dict[str, dict],
    artist_genres: dict[str, dict],
    small_group_min: int,
    order: str = "grouped",
    extra_columns: list[str] | None = None,
) -> list[dict]:
    # Проход 1: под-жанр (fine) и язык на каждый трек, размеры групп (fine, lang) фиксируем сразу.
    prelim = []
    group_sizes: dict[tuple[str, str], int] = {}
    for t in tracks_cache.values():
        artist_lists = [
            artist_genres[str(aid)]["genres"]
            for aid in t.get("artist_ids", [])
            if str(aid) in artist_genres
        ]
        fine = genres.classify_track(t["genre_raw"], artist_lists, genre_catalog)
        api_lang = lang_cache.get(str(t["id"]))
        lang = language.detect_language(t["title"], t["artists"], t["genre_raw"], api_lang)

        prelim.append((t, fine, lang))
        key = (fine, lang)
        group_sizes[key] = group_sizes.get(key, 0) + 1

    # Проход 2 (одиночный, не итеративный): мелкие под-жанровые группы схлопываем в
    # родительскую крупную корзину. coarse_of детерминирована от fine, поэтому повторного
    # пересчёта размеров и зацикливания тут не бывает.
    rows = []
    for t, fine, lang in prelim:
        if group_sizes[(fine, lang)] < small_group_min:
            bucket = genres.coarse_of(fine)
        else:
            bucket = fine
        playlist = classify.playlist_name(bucket, lang)
        row = {
            "title": t["title"],
            "artists": ", ".join(t["artists"]),
            "genre_raw": t["genre_raw"] or "",
            "fine_bucket": fine,
            "bucket": bucket,
            "lang": lang,
            "target_playlist": playlist,
            "id": t["id"],
            "album_id": t["album_id"],
        }
        if extra_columns:
            row.update(_extra_row_fields(t, artist_genres, extra_columns))
        rows.append(row)

    # "playlist" - порядок как в источнике (tracks_cache сохраняет порядок плейлиста, см. source.py);
    # "grouped" (по умолчанию) - принудительная сортировка по целевому плейлисту, как раньше.
    if order == "grouped":
        rows.sort(key=lambda r: (r["target_playlist"], r["artists"], r["title"]))
    elif order != "playlist":
        raise ValueError(f"неизвестный order: {order!r}, ожидается 'grouped' или 'playlist'")
    return rows


def write_report(rows: list[dict], out_dir: Path, filename: str = REPORT_FILE, extra_columns: list[str] | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / filename
    fieldnames = FIELDNAMES + extra_columns if extra_columns else FIELDNAMES
    with out_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_file


def summarize(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["target_playlist"]] = counts.get(r["target_playlist"], 0) + 1
    return counts


def other_breakdown(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        if r["bucket"] == "other" and r["genre_raw"]:
            counts[r["genre_raw"]] = counts.get(r["genre_raw"], 0) + 1
    return counts
