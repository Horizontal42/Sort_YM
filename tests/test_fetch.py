import json
from pathlib import Path

from sort_ym import fetch


class FakeArtist:
    def __init__(self, id_, name, genres=None):
        self.id = id_
        self.name = name
        self.genres = genres


class FakeAlbum:
    def __init__(self, id_, genre=None, title="", year=None):
        self.id = id_
        self.genre = genre
        self.title = title
        self.year = year


class FakeTrack:
    def __init__(self, id_, albums, title="Title", artists=None, lyrics_available=False):
        self.id = id_
        self.albums = albums
        self.title = title
        self.artists = artists or [FakeArtist(1, "Artist")]
        self.lyrics_available = lyrics_available


class FakeLikes:
    def __init__(self, tracks_ids):
        self.tracks_ids = tracks_ids


class FakeClient:
    """Симулирует трек, у которого "основной" альбом в ответе tracks()
    отличается от альбома, под которым трек значится в списке лайков -
    это реальное поведение API Яндекса для треков на нескольких альбомах."""

    def __init__(self, likes_ids, tracks_by_batch, artists_by_batch=None):
        self._likes_ids = likes_ids
        self._tracks_by_batch = tracks_by_batch
        self._artists_by_batch = artists_by_batch or {}

    def users_likes_tracks(self):
        return FakeLikes(self._likes_ids)

    def tracks(self, batch):
        return self._tracks_by_batch[tuple(batch)]

    def artists(self, batch):
        return self._artists_by_batch[tuple(sorted(batch))]


def test_fetch_caches_under_original_liked_id_not_recomputed_track_id(tmp_path: Path):
    # Трек лайкнут как "100:10", но Track.albums[0].id из ответа API - 999 (другой альбом).
    track = FakeTrack(id_=100, albums=[FakeAlbum(999, genre="pop")])
    client = FakeClient(
        likes_ids=["100:10"],
        tracks_by_batch={("100:10",): [track]},
    )

    cache = fetch.fetch_liked_tracks(client, tmp_path, batch_size=100, batch_delay=0)

    assert "100:10" in cache, "трек должен кэшироваться под id из списка лайков"
    assert "100:999" not in cache, "не должен пересчитывать ключ из albums[0] вернувшегося Track"
    assert cache["100:10"]["id"] == 100
    assert cache["100:10"]["genre_raw"] == "pop"


def test_fetch_does_not_purge_track_with_mismatched_album_as_stale(tmp_path: Path):
    # Регрессия: раньше такой трек кэшировался под "неправильным" ключом track.track_id,
    # который не совпадал с likes.tracks_ids, и тут же удалялся как "больше не лайкнутый".
    track = FakeTrack(id_=100, albums=[FakeAlbum(999)])
    client = FakeClient(
        likes_ids=["100:10"],
        tracks_by_batch={("100:10",): [track]},
    )

    cache = fetch.fetch_liked_tracks(client, tmp_path, batch_size=100, batch_delay=0)

    assert len(cache) == 1, f"трек не должен быть вычищен как stale сразу после загрузки: {cache}"


def test_fetch_stores_artist_ids(tmp_path: Path):
    track = FakeTrack(id_=100, albums=[FakeAlbum(10)], artists=[FakeArtist(7, "Artist A")])
    client = FakeClient(likes_ids=["100:10"], tracks_by_batch={("100:10",): [track]})

    cache = fetch.fetch_liked_tracks(client, tmp_path, batch_size=100, batch_delay=0)

    assert cache["100:10"]["artist_ids"] == [7]


def test_fetch_skips_artist_with_no_id(tmp_path: Path):
    # Регрессия: некоторые треки (сторонняя/пиратская загрузка) имеют артиста с именем,
    # но без id в каталоге Яндекса (Artist.id is None). Раньше None попадал в artist_ids,
    # затем str(None) = "None" улетал в client.artists() и API отвечал BadRequestError.
    track = FakeTrack(id_=100, albums=[FakeAlbum(10)], artists=[FakeArtist(None, "Unlinked Artist")])
    client = FakeClient(likes_ids=["100:10"], tracks_by_batch={("100:10",): [track]})

    cache = fetch.fetch_liked_tracks(client, tmp_path, batch_size=100, batch_delay=0)

    assert cache["100:10"]["artist_ids"] == [], "артист без id не должен попадать в artist_ids"


def test_fetch_artist_genres_ignores_none_ids_in_old_cache(tmp_path: Path):
    # Защита на уровне fetch_artist_genres даже если в tracks.json уже есть None
    # (например, кэш был написан до фикса выше).
    cache_dir = tmp_path
    tracks_cache = {
        "100:10": {"id": 100, "album_id": 10, "title": "T1", "artists": ["Unlinked"], "artist_ids": [None], "genre_raw": "pop", "lyrics_available": False},
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps(tracks_cache, ensure_ascii=False), encoding="utf-8"
    )

    def boom(batch):
        raise AssertionError(f"не должен запрашивать None как id артиста: {batch}")

    client = FakeClient(likes_ids=[], tracks_by_batch={})
    client.artists = boom

    result = fetch.fetch_artist_genres(client, cache_dir, batch_size=100, batch_delay=0)

    assert result == {}


def test_fetch_re_downloads_old_cache_entries_missing_artist_ids(tmp_path: Path):
    # Старый формат кэша (до добавления artist_ids) должен быть докачан повторно.
    cache_dir = tmp_path
    cache_dir.mkdir(exist_ok=True)
    old_entry = {
        "id": 100,
        "album_id": 10,
        "title": "Old",
        "artists": ["Artist A"],
        "genre_raw": "pop",
        "lyrics_available": False,
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps({"100:10": old_entry}, ensure_ascii=False), encoding="utf-8"
    )

    track = FakeTrack(id_=100, albums=[FakeAlbum(10)], artists=[FakeArtist(7, "Artist A")])
    client = FakeClient(likes_ids=["100:10"], tracks_by_batch={("100:10",): [track]})

    cache = fetch.fetch_liked_tracks(client, cache_dir, batch_size=100, batch_delay=0)

    assert "artist_ids" in cache["100:10"], "запись без artist_ids должна быть докачана заново"
    assert cache["100:10"]["artist_ids"] == [7]


def test_fetch_re_downloads_old_cache_entries_missing_year(tmp_path: Path):
    # Старый формат кэша (до добавления album_title/year, но уже с artist_ids) должен
    # быть докачан повторно.
    cache_dir = tmp_path
    cache_dir.mkdir(exist_ok=True)
    old_entry = {
        "id": 100,
        "album_id": 10,
        "title": "Old",
        "artists": ["Artist A"],
        "artist_ids": [7],
        "genre_raw": "pop",
        "lyrics_available": False,
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps({"100:10": old_entry}, ensure_ascii=False), encoding="utf-8"
    )

    track = FakeTrack(
        id_=100,
        albums=[FakeAlbum(10, title="Iowa", year=2001)],
        artists=[FakeArtist(7, "Artist A")],
    )
    client = FakeClient(likes_ids=["100:10"], tracks_by_batch={("100:10",): [track]})

    cache = fetch.fetch_liked_tracks(client, cache_dir, batch_size=100, batch_delay=0)

    assert cache["100:10"]["year"] == 2001
    assert cache["100:10"]["album_title"] == "Iowa"


def test_fetch_does_not_redownload_entries_with_legitimately_unknown_year(tmp_path: Path):
    # Регрессия: year=None легитимен (у альбома действительно нет года), и такая запись
    # не должна перекачиваться при каждом fetch - проверяем наличие ключа, а не значение.
    cache_dir = tmp_path
    cache_dir.mkdir(exist_ok=True)
    entry = {
        "id": 100,
        "album_id": 10,
        "album_title": "Unknown Year Album",
        "year": None,
        "title": "T1",
        "artists": ["Artist A"],
        "artist_ids": [7],
        "genre_raw": "pop",
        "lyrics_available": False,
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps({"100:10": entry}, ensure_ascii=False), encoding="utf-8"
    )

    def boom(batch):
        raise AssertionError(f"не должен перекачивать трек с легитимно неизвестным годом: {batch}")

    client = FakeClient(likes_ids=["100:10"], tracks_by_batch={})
    client.tracks = boom

    cache = fetch.fetch_liked_tracks(client, cache_dir, batch_size=100, batch_delay=0)

    assert cache["100:10"]["year"] is None


def test_fetch_artist_genres_batches_and_caches(tmp_path: Path):
    cache_dir = tmp_path
    tracks_cache = {
        "100:10": {"id": 100, "album_id": 10, "title": "T1", "artists": ["A"], "artist_ids": [7], "genre_raw": "pop", "lyrics_available": False},
        "200:20": {"id": 200, "album_id": 20, "title": "T2", "artists": ["B"], "artist_ids": [9], "genre_raw": "rock", "lyrics_available": False},
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps(tracks_cache, ensure_ascii=False), encoding="utf-8"
    )

    client = FakeClient(
        likes_ids=[],
        tracks_by_batch={},
        artists_by_batch={("7", "9"): [FakeArtist(7, "Artist A", genres=["indie"]), FakeArtist(9, "Artist B", genres=["rock", "punk"])]},
    )

    result = fetch.fetch_artist_genres(client, cache_dir, batch_size=100, batch_delay=0)

    assert result["7"] == {"name": "Artist A", "genres": ["indie"]}
    assert result["9"] == {"name": "Artist B", "genres": ["rock", "punk"]}

    persisted = fetch.load_artist_genres(cache_dir)
    assert persisted == result


def test_fetch_artist_genres_skips_already_cached(tmp_path: Path):
    cache_dir = tmp_path
    tracks_cache = {
        "100:10": {"id": 100, "album_id": 10, "title": "T1", "artists": ["A"], "artist_ids": [7], "genre_raw": "pop", "lyrics_available": False},
    }
    (cache_dir / fetch.TRACKS_CACHE_FILE).write_text(
        json.dumps(tracks_cache, ensure_ascii=False), encoding="utf-8"
    )
    (cache_dir / fetch.ARTIST_GENRES_CACHE_FILE).write_text(
        json.dumps({"7": {"name": "Artist A", "genres": ["indie"]}}, ensure_ascii=False), encoding="utf-8"
    )

    def boom(batch):
        raise AssertionError("не должен запрашивать уже закэшированного артиста")

    client = FakeClient(likes_ids=[], tracks_by_batch={})
    client.artists = boom

    result = fetch.fetch_artist_genres(client, cache_dir, batch_size=100, batch_delay=0)

    assert result == {"7": {"name": "Artist A", "genres": ["indie"]}}
