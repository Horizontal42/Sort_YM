from yandex_music.exceptions import TimedOutError

from sort_ym import apply as apply_mod


class FakePlaylist:
    def __init__(self, kind, title, revision=1, tracks=None):
        self.kind = kind
        self.title = title
        self.revision = revision
        self.tracks = tracks or []


class FakeTrackShort:
    def __init__(self, track_id):
        self.track_id = track_id


class FakeClient:
    def __init__(self):
        self.playlists = {100: FakePlaylist(100, "Рок — RU", revision=5, tracks=[FakeTrackShort("1:10")])}
        self.created = []
        self.inserted = []
        self.next_kind = 200

    def users_playlists_list(self):
        return list(self.playlists.values())

    def users_playlists(self, kind):
        return self.playlists.get(kind)

    def users_playlists_create(self, title, visibility="private"):
        kind = self.next_kind
        self.next_kind += 1
        p = FakePlaylist(kind, title)
        self.playlists[kind] = p
        self.created.append(title)
        return p

    def users_playlists_insert_track(self, kind, track_id, album_id, revision=1):
        self.inserted.append((kind, track_id, album_id, revision))
        p = self.playlists[kind]
        p.revision = revision + 1
        return p


class FlakyClient:
    """insert_track кидает таймаут на первой попытке, но трек всё же
    успевает примениться на сервере (ответ теряется, а не сам запрос)."""

    def __init__(self):
        self.playlist = FakePlaylist(100, "Рок — RU", revision=5, tracks=[])
        self.insert_calls = 0
        self.server_tracks: list[tuple[int, int]] = []

    def users_playlists_list(self):
        return [self.playlist]

    def users_playlists(self, kind):
        self.playlist.tracks = [FakeTrackShort(f"{i}:{a}") for (i, a) in self.server_tracks]
        return self.playlist

    def users_playlists_insert_track(self, kind, track_id, album_id, revision=1):
        self.insert_calls += 1
        self.server_tracks.append((track_id, album_id))
        if self.insert_calls == 1:
            raise TimedOutError()
        self.playlist.revision += 1
        self.playlist.tracks = [FakeTrackShort(f"{i}:{a}") for (i, a) in self.server_tracks]
        return self.playlist


def test_apply_skips_existing_and_creates_only_missing_playlist():
    client = FakeClient()
    rows = [
        {"target_playlist": "Рок — RU", "id": 1, "album_id": 10},  # уже в плейлисте
        {"target_playlist": "Рок — RU", "id": 5, "album_id": 50},  # новый трек в существующий плейлист
        {"target_playlist": "Поп — INT", "id": 9, "album_id": 90},  # совсем новый плейлист
    ]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.created == ["Поп — INT"]
    assert client.inserted == [(100, 5, 50, 5), (200, 9, 90, 1)]


def test_apply_does_not_duplicate_track_on_timeout_after_server_applied_write():
    client = FlakyClient()
    rows = [{"target_playlist": "Рок — RU", "id": 1, "album_id": 10}]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.insert_calls == 1, "insert_track не должен вызываться повторно вслепую при таймауте"
    assert client.server_tracks == [(1, 10)], "трек должен оказаться в плейлисте ровно один раз"
