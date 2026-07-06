from __future__ import annotations

import csv
from pathlib import Path

from . import classify, genres, language

FIELDNAMES = ["title", "artists", "genre_raw", "bucket", "lang", "target_playlist", "id", "album_id"]


def build_rows(
    tracks_cache: dict[str, dict],
    lang_cache: dict[str, str | None],
    genre_catalog: dict[str, dict],
) -> list[dict]:
    rows = []
    for t in tracks_cache.values():
        bucket = genres.bucket_for(t["genre_raw"], genre_catalog)
        api_lang = lang_cache.get(str(t["id"]))
        lang = language.detect_language(t["title"], t["artists"], t["genre_raw"], api_lang)
        playlist = classify.playlist_name(bucket, lang)
        rows.append(
            {
                "title": t["title"],
                "artists": ", ".join(t["artists"]),
                "genre_raw": t["genre_raw"] or "",
                "bucket": bucket,
                "lang": lang,
                "target_playlist": playlist,
                "id": t["id"],
                "album_id": t["album_id"],
            }
        )
    rows.sort(key=lambda r: (r["target_playlist"], r["artists"], r["title"]))
    return rows


def write_report(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "report.csv"
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
