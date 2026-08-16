from sort_ym import digest, report

CATALOG: dict = {}  # classify_track с пустым catalog использует genre_raw как есть


_UNSET = object()


def _track(id_, title, artists, genre_raw, artist_ids=None, album_id=_UNSET, album_title="", year=None):
    return {
        "id": id_,
        "album_id": id_ * 10 if album_id is _UNSET else album_id,
        "album_title": album_title,
        "year": year,
        "title": title,
        "artists": artists,
        "artist_ids": artist_ids if artist_ids is not None else [],
        "genre_raw": genre_raw,
        "lyrics_available": False,
    }


def _rows(tracks_cache, small_group_min=1):
    return report.build_rows(tracks_cache, {}, CATALOG, {}, small_group_min)


def test_artist_stats_counts_by_name_even_without_ids():
    tracks_cache = {
        "1:10": _track(1, "T1", ["Artist A"], "punk", artist_ids=[]),
        "2:10": _track(2, "T2", ["Artist A"], "punk", artist_ids=[7]),
    }
    stats = digest.artist_stats(_rows(tracks_cache), tracks_cache, {})

    assert len(stats) == 1
    assert stats[0]["name"] == "Artist A"
    assert stats[0]["tracks"] == 2


def test_artist_stats_joins_tracks_without_album_id():
    # Ключ кэша не совпадает с "id:album_id" (реалистично для треков без альбома) -
    # склейка идёт по значениям, а не по ключу.
    tracks_cache = {"some-uuid": _track(1, "T1", ["Artist A"], "punk", artist_ids=[7], album_id=None)}
    stats = digest.artist_stats(_rows(tracks_cache), tracks_cache, {})

    assert stats == [{"name": "Artist A", "tracks": 1, "top_fine": "punk", "tags": []}]


def test_artist_stats_counts_collaboration_for_each_artist():
    tracks_cache = {"1:10": _track(1, "T1", ["Artist A", "Artist B"], "punk", artist_ids=[7, 8])}
    stats = digest.artist_stats(_rows(tracks_cache), tracks_cache, {})

    names = {s["name"]: s["tracks"] for s in stats}
    assert names == {"Artist A": 1, "Artist B": 1}


def test_long_tail_collapses_past_top_artists():
    tracks_cache = {}
    tid = 0
    for artist_idx in range(50):
        count = 50 - artist_idx  # Artist0 - 50 треков, ... Artist49 - 1 трек
        for _ in range(count):
            tid += 1
            tracks_cache[f"{tid}:{tid * 10}"] = _track(tid, f"T{tid}", [f"Artist{artist_idx}"], "punk")

    rows = _rows(tracks_cache)
    stats = digest.artist_stats(rows, tracks_cache, {})
    rest = stats[10:]
    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=0)

    assert "Artist0" in text
    assert "Artist9" in text
    assert "Artist10" not in text
    assert f"Ещё {len(rest)} исполнителей" in text
    assert str(sum(a["tracks"] for a in rest)) in text


def test_genre_stats_uses_coarse_of_fine_not_row_bucket():
    # punk (15 треков, >= порога) остаётся отдельным под-жанром в row["bucket"], indie (2, < порога)
    # схлопывается в indie-alt - при наивном подсчёте по row["bucket"] это были бы ДВЕ разные
    # строки, хотя coarse_of("punk") тоже "indie-alt" - это одна и та же крупная корзина.
    tracks_cache = {}
    for i in range(15):
        tracks_cache[f"{i}:{i * 10}"] = _track(i, f"P{i}", ["Punk Artist"], "punk")
    for i in range(15, 17):
        tracks_cache[f"{i}:{i * 10}"] = _track(i, f"I{i}", ["Indie Artist"], "indie")

    rows = _rows(tracks_cache, small_group_min=12)
    assert any(r["bucket"] == "punk" for r in rows), "sanity: punk остался отдельным под-жанром"
    assert any(r["bucket"] == "indie-alt" for r in rows), "sanity: indie схлопнулся"

    stats = digest.genre_stats(rows)
    assert {g["bucket"]: g["tracks"] for g in stats} == {"indie-alt": 17}


def test_fine_stats_unmapped_bucket_renders_as_raw_slug():
    tracks_cache = {"1:10": _track(1, "T1", ["Artist"], "totally-unknown-genre")}
    rows = _rows(tracks_cache)

    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=10)

    assert "totally-unknown-genre" in text


def test_decade_key_and_label():
    assert digest.decade_key(2011) == "2010"
    assert digest.decade_key(None) == digest.DECADE_UNKNOWN
    assert digest.decade_key(0) == digest.DECADE_UNKNOWN
    assert digest.decade_key(1) == digest.DECADE_UNKNOWN
    assert digest.decade_key(2150) == digest.DECADE_UNKNOWN
    assert digest.decade_label("2010") == "2010-е"
    assert digest.decade_label(digest.DECADE_UNKNOWN) == "Неизвестно"


def test_decade_stats_handles_missing_year_key_without_crashing():
    old_format_track = _track(1, "T1", ["Artist"], "punk")
    del old_format_track["year"]
    tracks_cache = {"1:10": old_format_track}

    stats = digest.decade_stats(_rows(tracks_cache), tracks_cache)

    assert stats == [{"key": digest.DECADE_UNKNOWN, "tracks": 1, "top_genres": [{"bucket": "indie-alt", "tracks": 1}]}]


def test_decade_stats_sorted_desc_with_unknown_last():
    tracks_cache = {
        "1:10": _track(1, "T1", ["A"], "punk", year=2015),
        "2:20": _track(2, "T2", ["B"], "punk", year=1995),
        "3:30": _track(3, "T3", ["C"], "punk", year=None),
    }
    stats = digest.decade_stats(_rows(tracks_cache), tracks_cache)

    assert [s["key"] for s in stats] == ["2010", "1990", digest.DECADE_UNKNOWN]


def test_decade_top_genres_truncated_to_three_largest():
    tracks_cache = {}
    tid = 0
    for genre_raw, n in {"punk": 10, "metal": 8, "rap": 6, "jazz": 4, "pop": 2}.items():
        for _ in range(n):
            tid += 1
            tracks_cache[f"{tid}:{tid * 10}"] = _track(tid, f"T{tid}", ["Artist"], genre_raw, year=2015)

    stats = digest.decade_stats(_rows(tracks_cache), tracks_cache)

    assert len(stats) == 1
    top = stats[0]["top_genres"]
    assert len(top) == 3
    assert sum(g["tracks"] for g in top) < stats[0]["tracks"]


def test_album_stats_skips_none_album_id_but_tracks_counted_elsewhere():
    tracks_cache = {
        "abc": _track(1, "T1", ["Artist"], "punk", album_id=None),
        "2:20": _track(2, "T2", ["Artist"], "punk", album_id=20, album_title="Album X"),
    }
    albums = digest.album_stats(tracks_cache)
    assert len(albums) == 1
    assert albums[0]["album_id"] == 20

    genre_total = sum(g["tracks"] for g in digest.genre_stats(_rows(tracks_cache)))
    assert genre_total == 2


def test_album_stats_title_tie_break_is_deterministic():
    # Оба названия встречаются по разу - при равенстве частот побеждает одно и то же
    # значение независимо от порядка треков на входе.
    a = {
        "1:10": _track(1, "T1", ["Artist"], "punk", album_id=10, album_title="Zeta"),
        "2:10": _track(2, "T2", ["Artist"], "punk", album_id=10, album_title="Alpha"),
    }
    b = {
        "2:10": a["2:10"],
        "1:10": a["1:10"],
    }

    assert digest.album_stats(a)[0]["title"] == "Alpha"
    assert digest.album_stats(b)[0]["title"] == "Alpha"


def test_album_stats_untitled_fallback():
    tracks_cache = {"1:10": _track(1, "T1", ["Artist"], "punk", album_id=42, album_title="")}

    albums = digest.album_stats(tracks_cache)

    assert albums[0]["title"] == "без названия (#42)"


def test_artist_tags_empty_when_only_misaligned_tracks():
    # 2 имени, 1 id - длины не совпадают, трек целиком пропускается для сопоставления тегов.
    tracks_cache = {"1:10": _track(1, "T1", ["Artist A", "Artist B"], "punk", artist_ids=[7])}
    ids_by_name = digest._artist_ids_by_name(tracks_cache)

    assert digest.artist_tags("Artist A", ids_by_name, {"7": {"name": "Artist B", "genres": ["rock"]}}) == []


def test_artist_tags_no_misattribution_from_misaligned_track():
    tracks_cache = {
        "1:10": _track(1, "T1", ["Artist A", "Artist B"], "punk", artist_ids=[9]),  # рассинхрон
        "2:20": _track(2, "T2", ["Artist B"], "punk", artist_ids=[9]),  # выровнен
    }
    ids_by_name = digest._artist_ids_by_name(tracks_cache)
    artist_genres = {"9": {"name": "Artist B", "genres": ["rock"]}}

    assert digest.artist_tags("Artist A", ids_by_name, artist_genres) == []
    assert digest.artist_tags("Artist B", ids_by_name, artist_genres) == ["rock"]


def test_artist_tags_unions_across_multiple_ids_for_same_name():
    tracks_cache = {
        "1:10": _track(1, "T1", ["Artist X"], "punk", artist_ids=[1]),
        "2:20": _track(2, "T2", ["Artist X"], "punk", artist_ids=[2]),
    }
    ids_by_name = digest._artist_ids_by_name(tracks_cache)
    artist_genres = {
        "1": {"name": "Artist X", "genres": ["punk", "rock"]},
        "2": {"name": "Artist X", "genres": ["rock", "ska"]},
    }

    assert digest.artist_tags("Artist X", ids_by_name, artist_genres) == ["punk", "rock", "ska"]


def test_artist_tags_truncated_to_limit():
    tracks_cache = {"1:10": _track(1, "T1", ["Artist X"], "punk", artist_ids=[1])}
    ids_by_name = digest._artist_ids_by_name(tracks_cache)
    artist_genres = {"1": {"name": "Artist X", "genres": ["a", "b", "c", "d"]}}

    assert digest.artist_tags("Artist X", ids_by_name, artist_genres, limit=3) == ["a", "b", "c"]


def test_default_wording_matches_likes_output():
    # Фиксирует путь без --source: render_digest(...) без явного wording не должен измениться
    # при добавлении Wording/playlist_wording для --source.
    tracks_cache = {"1:10": _track(1, "T1", ["Artist"], "punk")}
    rows = _rows(tracks_cache)

    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=10)

    assert text.startswith("# Дайджест музыкальной библиотеки")
    assert "Лайкнутых треков: 1" in text


def test_playlist_wording_does_not_mention_likes():
    tracks_cache = {"1:10": _track(1, "T1", ["Artist"], "punk")}
    rows = _rows(tracks_cache)
    wording = digest.playlist_wording("Мой плейлист", "friend", "https://music.yandex.ru/x")

    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=10, wording=wording)

    assert "Мой плейлист" in text
    assert "friend" in text
    assert "лайкнут" not in text.lower()


def test_digest_line_count_stays_bounded_on_large_library():
    tracks_cache = {}
    tid = 0
    genre_pool = [
        "punk", "indie", "metal", "rap", "electronics", "jazz",
        "classicalmusic", "pop", "folk", "soundtrack", "allrock",
    ]
    for artist_idx in range(1500):
        for _ in range(1 + artist_idx % 5):
            tid += 1
            tracks_cache[f"t{tid}"] = _track(
                tid,
                f"Track{tid}",
                [f"Artist{artist_idx}"],
                genre_pool[tid % len(genre_pool)],
                album_id=tid % 1000,
                album_title=f"Album{tid % 1000}",
                year=1960 + (tid % 60),
            )

    rows = _rows(tracks_cache)
    text = digest.render_digest(rows, tracks_cache, {}, top_artists=40, top_albums=15)

    assert len(text.splitlines()) < 250


ANALYSIS = {
    "100": {"mood": ["melancholy", "longing"], "themes": ["city", "memory"], "stance": "sincere", "pov": "confessional"},
    "200": {"mood": ["melancholy"], "themes": ["city"], "stance": "ironic", "pov": "narrative"},
    "300": {"error": "TimeoutError: модель зависла"},
}


def test_mood_stats_counts_every_mood_of_a_track():
    assert digest.mood_stats(ANALYSIS) == [
        {"mood": "melancholy", "tracks": 2},
        {"mood": "longing", "tracks": 1},
    ]


def test_theme_stats_limits_and_orders():
    assert digest.theme_stats(ANALYSIS, limit=1) == [{"theme": "city", "tracks": 2}]


def test_analyzed_entries_excludes_error_markers():
    assert len(digest.analyzed_entries(ANALYSIS)) == 2


def test_lyrics_block_is_compact():
    lines = digest.lyrics_block(ANALYSIS)

    assert lines[0] == "## Лирика (RU-подмножество)"
    assert len(lines) <= 7, "агрегат в digest.md должен оставаться компактным"
    assert any("melancholy 2" in line for line in lines)
    assert any("city 2" in line for line in lines)


def test_lyrics_block_empty_without_analysis():
    assert digest.lyrics_block({}) == []
    assert digest.lyrics_block({"300": {"error": "TimeoutError: ..."}}) == []


def test_render_digest_without_analysis_has_no_lyrics_section():
    # Обратная совместимость: без analysis дайджест прежний, как в test_default_wording_matches_likes_output.
    tracks_cache = {"100:1000": _track(100, "Тоска", ["Артист"], "rock")}
    rows = _rows(tracks_cache)

    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=10)

    assert "## Лирика" not in text


def test_render_digest_with_analysis_includes_lyrics_section():
    tracks_cache = {"100:1000": _track(100, "Тоска", ["Артист"], "rock")}
    rows = _rows(tracks_cache)

    text = digest.render_digest(rows, tracks_cache, {}, top_artists=10, top_albums=10, analysis=ANALYSIS)

    assert "## Лирика (RU-подмножество)" in text
