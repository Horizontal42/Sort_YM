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
