import pytest

from sort_ym import report

CATALOG: dict = {}  # classify_track с пустыми artist_genre_lists использует только genre_raw


def _track(id_, title, artists, genre_raw, artist_ids=None):
    return {
        "id": id_,
        "album_id": id_ * 10,
        "title": title,
        "artists": artists,
        "artist_ids": artist_ids or [],
        "genre_raw": genre_raw,
        "lyrics_available": False,
    }


def test_small_fine_group_collapses_to_coarse_bucket():
    # 15 "punk"-треков (>= small_group_min=12) остаются отдельным под-жанром,
    # 2 "indie"-трека (< 12) схлопываются в родительскую крупную корзину "indie-alt".
    tracks_cache = {}
    for i in range(15):
        tid = f"{i}:{i}"
        tracks_cache[tid] = _track(i, f"Punk track {i}", ["Punk Artist"], "punk")

    for i in range(15, 17):
        tid = f"{i}:{i}"
        tracks_cache[tid] = _track(i, f"Indie track {i}", ["Indie Artist"], "indie")

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres={},
        small_group_min=12,
    )

    punk_rows = [r for r in rows if r["genre_raw"] == "punk"]
    indie_rows = [r for r in rows if r["genre_raw"] == "indie"]

    assert len(punk_rows) == 15
    assert all(r["bucket"] == "punk" for r in punk_rows), "крупная под-группа - отдельный плейлист"
    assert all(r["fine_bucket"] == "punk" for r in punk_rows)

    assert len(indie_rows) == 2
    assert all(r["bucket"] == "indie-alt" for r in indie_rows), "мелкая под-группа схлопнута в крупную корзину"
    assert all(r["fine_bucket"] == "indie" for r in indie_rows), "fine_bucket сохраняет исходную классификацию"


def test_write_report_uses_default_filename(tmp_path):
    rows = [{"title": "T", "artists": "A", "genre_raw": "punk", "fine_bucket": "punk", "bucket": "punk", "lang": "RU", "target_playlist": "Панк — RU", "id": 1, "album_id": 10}]

    out_file = report.write_report(rows, tmp_path)

    assert out_file.name == "report.csv" == report.REPORT_FILE
    assert out_file.exists()


def test_write_report_accepts_custom_filename_for_source_runs(tmp_path):
    rows = [{"title": "T", "artists": "A", "genre_raw": "punk", "fine_bucket": "punk", "bucket": "punk", "lang": "RU", "target_playlist": "Панк — RU", "id": 1, "album_id": 10}]

    out_file = report.write_report(rows, tmp_path, report.REPORT_SOURCE_FILE)

    assert out_file.name == "report_source.csv" == report.REPORT_SOURCE_FILE
    assert out_file.exists()


def test_order_playlist_preserves_source_order():
    # tracks_cache - dict, порядок вставки == порядок в источнике (см. source.py).
    # order="playlist" должен сохранить этот порядок вместо сортировки по target_playlist.
    tracks_cache = {
        "3:3": _track(3, "C", ["Z Artist"], "punk"),
        "1:1": _track(1, "A", ["A Artist"], "indie"),
        "2:2": _track(2, "B", ["M Artist"], "punk"),
    }

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres={},
        small_group_min=12,
        order="playlist",
    )

    assert [r["title"] for r in rows] == ["C", "A", "B"]


def test_order_grouped_sorts_by_target_playlist():
    tracks_cache = {
        "3:3": _track(3, "C", ["Z Artist"], "punk"),
        "1:1": _track(1, "A", ["A Artist"], "indie"),
        "2:2": _track(2, "B", ["M Artist"], "punk"),
    }

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres={},
        small_group_min=12,
        order="grouped",
    )

    assert rows == sorted(rows, key=lambda r: (r["target_playlist"], r["artists"], r["title"]))


def test_resolve_extra_columns_expands_single_group():
    assert report.resolve_extra_columns(["timestamp"]) == ["added_at"]


def test_resolve_extra_columns_all_expands_every_group_in_canonical_order():
    assert report.resolve_extra_columns(["all"]) == report.EXTRA_FIELDNAMES


def test_resolve_extra_columns_rejects_unknown_group():
    with pytest.raises(ValueError, match="bogus"):
        report.resolve_extra_columns(["bogus"])


def test_extra_columns_only_adds_requested_group():
    tracks_cache = {
        "1:1": {
            **_track(1, "T", ["A"], "punk", artist_ids=[42]),
            "added_at": "2026-01-01T00:00:00+00:00",
            "duration_ms": 123000,
            "track_version": "Remix",
            "album_version": None,
            "release_date": "2020-05-01T00:00:00+03:00",
            "album_likes_count": 10,
        },
    }
    artist_genres = {"42": {"name": "A", "genres": [], "counts": {"tracks": 5}, "ratings": {"month": 7}}}

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres=artist_genres,
        small_group_min=12,
        extra_columns=report.resolve_extra_columns(["timestamp"]),
    )

    row = rows[0]
    assert row["added_at"] == "2026-01-01T00:00:00+00:00"
    assert "duration_ms" not in row, "запрошена только группа timestamp - duration не должно быть в строке"


def test_extra_columns_all_adds_every_group():
    tracks_cache = {
        "1:1": {
            **_track(1, "T", ["A"], "punk", artist_ids=[42]),
            "added_at": "2026-01-01T00:00:00+00:00",
            "duration_ms": 123000,
            "track_version": "Remix",
            "album_version": None,
            "release_date": "2020-05-01T00:00:00+03:00",
            "album_likes_count": 10,
        },
    }
    artist_genres = {"42": {"name": "A", "genres": [], "counts": {"tracks": 5}, "ratings": {"month": 7}}}

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres=artist_genres,
        small_group_min=12,
        extra_columns=report.resolve_extra_columns(["all"]),
    )

    row = rows[0]
    assert row["added_at"] == "2026-01-01T00:00:00+00:00"
    assert row["duration_ms"] == 123000
    assert row["track_version"] == "Remix"
    assert row["release_date"] == "2020-05-01T00:00:00+03:00"
    assert row["artist_track_count"] == 5
    assert row["artist_rating_month"] == 7


def test_write_report_extra_columns_writes_only_selected_header(tmp_path):
    rows = [{"title": "T", "artists": "A", "genre_raw": "punk", "fine_bucket": "punk", "bucket": "punk", "lang": "RU", "target_playlist": "Панк — RU", "id": 1, "album_id": 10, "added_at": "x"}]

    out_file = report.write_report(rows, tmp_path, extra_columns=report.resolve_extra_columns(["timestamp"]))

    header = out_file.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "added_at" in header
    assert "artist_rating_day" not in header


def test_collapse_is_single_pass_and_terminates():
    # Группа ровно на границе порога (== small_group_min) НЕ схлопывается (строгое <).
    tracks_cache = {
        f"{i}:{i}": _track(i, f"T{i}", ["Artist"], "punk") for i in range(12)
    }

    rows = report.build_rows(
        tracks_cache=tracks_cache,
        lang_cache={},
        genre_catalog=CATALOG,
        artist_genres={},
        small_group_min=12,
    )

    assert all(r["bucket"] == "punk" for r in rows)
