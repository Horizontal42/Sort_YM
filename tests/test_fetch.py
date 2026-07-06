from pathlib import Path

from sort_ym import fetch


class FakeArtist:
    def __init__(self, name):
        self.name = name


class FakeAlbum:
    def __init__(self, id_, genre=None):
        self.id = id_
        self.genre = genre


class FakeTrack:
    def __init__(self, id_, albums, title="Title", artists=None, lyrics_available=False):
        self.id = id_
        self.albums = albums
        self.title = title
        self.artists = artists or [FakeArtist("Artist")]
        self.lyrics_available = lyrics_available


class FakeLikes:
    def __init__(self, tracks_ids):
        self.tracks_ids = tracks_ids


class FakeClient:
    """Симулирует трек, у которого "основной" альбом в ответе tracks()
    отличается от альбома, под которым трек значится в списке лайков -
    это реальное поведение API Яндекса для треков на нескольких альбомах."""

    def __init__(self, likes_ids, tracks_by_batch):
        self._likes_ids = likes_ids
        self._tracks_by_batch = tracks_by_batch

    def users_likes_tracks(self):
        return FakeLikes(self._likes_ids)

    def tracks(self, batch):
        return self._tracks_by_batch[tuple(batch)]


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
