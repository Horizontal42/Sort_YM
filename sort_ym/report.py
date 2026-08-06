from __future__ import annotations

import csv
from pathlib import Path

from . import classify, genres, language

FIELDNAMES = ["title", "artists", "genre_raw", "fine_bucket", "bucket", "lang", "target_playlist", "id", "album_id"]

REPORT_FILE = "report.csv"
REPORT_SOURCE_FILE = "report_source.csv"


def build_rows(
    tracks_cache: dict[str, dict],
    lang_cache: dict[str, str | None],
    genre_catalog: dict[str, dict],
    artist_genres: dict[str, dict],
    small_group_min: int,
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
        rows.append(
            {
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
        )
    rows.sort(key=lambda r: (r["target_playlist"], r["artists"], r["title"]))
    return rows


def write_report(rows: list[dict], out_dir: Path, filename: str = REPORT_FILE) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / filename
    with out_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
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
