import pytest
from yandex_music.exceptions import NotFoundError, UnauthorizedError

from sort_ym import digest, report, source


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


class FakeTrackShort:
    def __init__(self, id_, album_id=None):
        self.id = id_
        self.album_id = album_id

    @property
    def track_id(self):
        return f"{self.id}:{self.album_id}" if self.album_id else f"{self.id}"


class FakeOwner:
    def __init__(self, uid=1, login="owner", name=None):
        self.uid = uid
        self.login = login
        self.name = name


class FakePlaylist:
    def __init__(self, title="Playlist", tracks=None, track_count=None, owner=None):
        self.title = title
        self.tracks = tracks or []
        self.track_count = track_count if track_count is not None else len(self.tracks)
        self.owner = owner if owner is not None else FakeOwner()


class FakeSourceClient:
    def __init__(self, playlist=None, tracks_by_batch=None, artists_by_batch=None, raises=None):
        self.playlist_obj = playlist
        self._tracks_by_batch = tracks_by_batch or {}
        self._artists_by_batch = artists_by_batch or {}
        self._raises = raises
        self.calls: list[dict] = []

    def users_playlists(self, kind, user_id=None):
        self.calls.append({"kind": kind, "user_id": user_id})
        if self._raises:
            raise self._raises
        return self.playlist_obj

    def playlist(self, uuid):
        if self._raises:
            raise self._raises
        return self.playlist_obj

    def tracks(self, batch):
        return self._tracks_by_batch[tuple(batch)]

    def artists(self, batch):
        return self._artists_by_batch.get(tuple(sorted(batch)), [])


ACCEPTED_URLS = [
    ("https://music.yandex.ru/users/vasya/playlists/1001", "vasya", "1001"),
    ("https://music.yandex.ru/users/vasya/playlists/1001/", "vasya", "1001"),
    ("http://music.yandex.ru/users/vasya/playlists/1001", "vasya", "1001"),
    ("music.yandex.ru/users/vasya/playlists/1001", "vasya", "1001"),
    ("https://www.music.yandex.ru/users/vasya/playlists/1001", "vasya", "1001"),
    ("https://MUSIC.YANDEX.RU/users/vasya/playlists/1001", "vasya", "1001"),
    ("https://music.yandex.com/users/vasya/playlists/1001", "vasya", "1001"),
    ("https://music.yandex.ru/users/vasya/playlists/1001?utm_source=share", "vasya", "1001"),
    ("https://music.yandex.ru/users/vasya/playlists/1001#about", "vasya", "1001"),
    ("https://music.yandex.ru/users/12345/playlists/1001", "12345", "1001"),
    ("https://music.yandex.ru/users/user.name-1/playlists/1001", "user.name-1", "1001"),
    ("https://music.yandex.ru/users/%D0%B2%D0%B0%D1%81%D1%8F/playlists/1001", "вася", "1001"),
]


@pytest.mark.parametrize("url,user_id,kind", ACCEPTED_URLS)
def test_parse_playlist_url_accepts_valid_links(url, user_id, kind):
    ref = source.parse_playlist_url(url)
    assert ref.user_id == user_id
    assert ref.kind == kind
    assert ref.uuid is None


def test_parse_playlist_url_accepts_uuid_form():
    ref = source.parse_playlist_url("https://music.yandex.ru/playlists/1e5a8f3c-1234-4abc-9def-0123456789ab")
    assert ref.uuid == "1e5a8f3c-1234-4abc-9def-0123456789ab"
    assert ref.user_id is None
    assert ref.kind is None


def test_parse_playlist_url_accepts_lk_prefixed_uuid_form():
    # "lk." (личный кабинет) - реальный префикс у ссылок на персональные плейлисты вроде "Мне
    # нравится" (подтверждено вживую через client.playlist()); префикс - часть самого uuid для
    # API, а не что-то, что нужно отрезать при парсинге.
    ref = source.parse_playlist_url(
        "https://music.yandex.ru/playlists/lk.dff9b654-af53-4c65-ab4a-d4ed5a0ae72d?utm_source=desktop"
    )
    assert ref.uuid == "lk.dff9b654-af53-4c65-ab4a-d4ed5a0ae72d"


REJECTED_URLS = [
    "",
    "   ",
    "https://example.com/users/vasya/playlists/1001",
    "https://music.yandex.ru/album/123",
    "https://music.yandex.ru/artist/123",
    "https://music.yandex.ru/users/vasya/playlists",
    "https://music.yandex.ru/users/vasya/playlists/abc",
    "https://music.yandex.ru/playlists/12345",
]


@pytest.mark.parametrize("url", REJECTED_URLS)
def test_parse_playlist_url_rejects_bad_links(url):
    with pytest.raises(source.SourceError, match="music.yandex.ru/users/"):
        source.parse_playlist_url(url)


def test_fetch_playlist_tracks_passes_foreign_user_id_through():
    short = FakeTrackShort(100, 10)
    playlist = FakePlaylist(tracks=[short])
    track = FakeTrack(100, albums=[FakeAlbum(10, title="Album", year=2001)], artists=[FakeArtist(7, "Artist A")])
    client = FakeSourceClient(playlist=playlist, tracks_by_batch={("100:10",): [track]})
    ref = source.PlaylistRef(url="u", user_id="somebody", kind="12345")

    source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)

    assert client.calls == [{"kind": "12345", "user_id": "somebody"}]


def test_fetch_playlist_tracks_dedupes_duplicate_track_ids():
    shorts = [FakeTrackShort(1, 10), FakeTrackShort(1, 10), FakeTrackShort(2, 20)]
    playlist = FakePlaylist(tracks=shorts)
    client = FakeSourceClient(
        playlist=playlist,
        tracks_by_batch={
            ("1:10",): [FakeTrack(1, albums=[FakeAlbum(10)])],
            ("2:20",): [FakeTrack(2, albums=[FakeAlbum(20)])],
        },
    )
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    info, tracks = source.fetch_playlist_tracks(client, ref, batch_size=1, batch_delay=0)

    assert set(tracks.keys()) == {"1:10", "2:20"}


def test_fetch_playlist_tracks_matches_response_by_id_not_position():
    # Запрошены два трека, ответ содержит только один (второй недоступен в каталоге) -
    # позиционный zip(batch, fetched) присвоил бы данные трека 2 ключу "1:10".
    shorts = [FakeTrackShort(1, 10), FakeTrackShort(2, 20)]
    playlist = FakePlaylist(tracks=shorts)
    client = FakeSourceClient(
        playlist=playlist,
        tracks_by_batch={("1:10", "2:20"): [FakeTrack(2, albums=[FakeAlbum(20)])]},
    )
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    info, tracks = source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)

    assert set(tracks.keys()) == {"2:20"}
    assert "1:10" not in tracks


def test_fetch_playlist_tracks_empty_with_zero_track_count_raises_playlist_empty():
    playlist = FakePlaylist(tracks=[], track_count=0)
    client = FakeSourceClient(playlist=playlist)
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    with pytest.raises(source.SourceError, match="пуст"):
        source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)


def test_fetch_playlist_tracks_empty_with_nonzero_track_count_raises_transient_error():
    playlist = FakePlaylist(tracks=[], track_count=50)
    client = FakeSourceClient(playlist=playlist)
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    with pytest.raises(source.SourceError, match="не вернул"):
        source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)


def test_fetch_playlist_tracks_empty_uuid_form_mentions_supported_link_shape():
    playlist = FakePlaylist(tracks=[], track_count=50)
    client = FakeSourceClient(playlist=playlist)
    ref = source.PlaylistRef(url="u", uuid="1e5a8f3c-1234-4abc-9def-0123456789ab")

    with pytest.raises(source.SourceError, match="music.yandex.ru/users/"):
        source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)


@pytest.mark.parametrize(
    "exc,match",
    [
        (NotFoundError("nope"), "не найден"),
        (UnauthorizedError("nope"), "Нет доступа"),
    ],
)
def test_load_playlist_maps_api_errors_to_source_error_without_retrying(exc, match):
    client = FakeSourceClient(raises=exc)
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    with pytest.raises(source.SourceError, match=match):
        source._load_playlist(client, ref)

    assert len(client.calls) == 1, "NotFoundError/UnauthorizedError не должны повторяться"


def test_load_playlist_none_response_raises_source_error():
    client = FakeSourceClient(playlist=None)
    ref = source.PlaylistRef(url="u", user_id="x", kind="1")

    with pytest.raises(source.SourceError, match="пустой ответ"):
        source._load_playlist(client, ref)


def test_fetch_artist_genres_map_batches_without_touching_disk(tmp_path):
    client = FakeSourceClient(
        artists_by_batch={("7", "9"): [FakeArtist(7, "A", genres=["indie"]), FakeArtist(9, "B", genres=["rock"])]}
    )

    result = source.fetch_artist_genres_map(client, ["7", "9"], batch_size=100, batch_delay=0)

    assert result == {"7": {"name": "A", "genres": ["indie"]}, "9": {"name": "B", "genres": ["rock"]}}
    assert list(tmp_path.iterdir()) == []  # ничего не записано на диск


def test_source_track_shape_matches_fetch_cache_shape(tmp_path):
    from sort_ym import fetch as fetch_mod

    expected_keys = {
        "id", "album_id", "album_title", "year", "title",
        "artists", "artist_ids", "genre_raw", "lyrics_available",
    }

    class FakeLikes:
        tracks_ids = ["100:10"]

    class FakeLikesClient:
        def users_likes_tracks(self):
            return FakeLikes()

        def tracks(self, batch):
            return [FakeTrack(100, albums=[FakeAlbum(10, title="Album", year=2001)], artists=[FakeArtist(7, "Artist A")])]

    liked_cache = fetch_mod.fetch_liked_tracks(FakeLikesClient(), tmp_path, batch_size=100, batch_delay=0)
    assert set(liked_cache["100:10"].keys()) == expected_keys

    short = FakeTrackShort(100, 10)
    playlist = FakePlaylist(title="Playlist X", tracks=[short])
    track = FakeTrack(100, albums=[FakeAlbum(10, title="Album", year=2001)], artists=[FakeArtist(7, "Artist A")])
    client = FakeSourceClient(playlist=playlist, tracks_by_batch={("100:10",): [track]})
    ref = source.PlaylistRef(url="https://example", user_id="x", kind="1")

    info, tracks = source.fetch_playlist_tracks(client, ref, batch_size=100, batch_delay=0)
    assert set(tracks["100:10"].keys()) == expected_keys

    rows = report.build_rows(tracks, {}, {}, {}, small_group_min=1)
    assert rows and rows[0]["target_playlist"]

    wording = digest.playlist_wording(info.title, info.owner, info.url)
    text = digest.render_digest(rows, tracks, {}, top_artists=5, top_albums=5, wording=wording)
    assert "Playlist X" in text
