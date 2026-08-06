from yandex_music.exceptions import BadRequestError, TimedOutError

from sort_ym import apply as apply_mod
from sort_ym import classify


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
        # Сервер никогда не возвращает albumId у треков плейлиста - track_id всегда голый id
        # (проверено вживую), поэтому фейк тоже хранит только id, без ":album_id".
        self.playlists = {100: FakePlaylist(100, "Рок — RU", revision=5, tracks=[FakeTrackShort("1")])}
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

    def users_playlists_delete_track(self, kind, from_, to, revision=1):
        p = self.playlists[kind]
        del p.tracks[from_:to]
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
        self.playlist.tracks = [FakeTrackShort(str(i)) for (i, a) in self.server_tracks]
        return self.playlist

    def users_playlists_insert_track(self, kind, track_id, album_id, revision=1):
        self.insert_calls += 1
        self.server_tracks.append((track_id, album_id))
        if self.insert_calls == 1:
            raise TimedOutError()
        self.playlist.revision += 1
        self.playlist.tracks = [FakeTrackShort(str(i)) for (i, a) in self.server_tracks]
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


def test_apply_skips_tracks_without_album_id():
    # Самозалитые/пиратские треки без альбома - Яндекс не даёт вставить такой трек в
    # плейлист (albumId обязателен). Должны пропускаться без попытки вставки и без падения.
    client = FakeClient()
    rows = [
        {"target_playlist": "Поп — INT", "id": 1, "album_id": None, "title": "no album"},
        {"target_playlist": "Поп — INT", "id": 2, "album_id": 20, "title": "has album"},
    ]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.inserted == [(200, 2, 20, 1)], "трек без альбома не должен уходить в insert_track"


class BadRequestClient(FakeClient):
    """insert_track кидает BadRequestError (детерминированный отказ) на конкретном треке."""

    def __init__(self, bad_track_id):
        super().__init__()
        self.playlists = {200: FakePlaylist(200, "Поп — INT", revision=1, tracks=[])}
        self.next_kind = 201
        self._bad_track_id = bad_track_id

    def users_playlists_insert_track(self, kind, track_id, album_id, revision=1):
        if track_id == self._bad_track_id:
            raise BadRequestError({"name": "wrong-json", "message": "Invalid JSON rules"})
        return super().users_playlists_insert_track(kind, track_id, album_id, revision)


def test_apply_continues_after_bad_request_on_single_track():
    client = BadRequestClient(bad_track_id=1)
    rows = [
        {"target_playlist": "Поп — INT", "id": 1, "album_id": 10, "title": "broken"},
        {"target_playlist": "Поп — INT", "id": 2, "album_id": 20, "title": "ok"},
    ]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.inserted == [(200, 2, 20, 1)], "второй трек должен вставиться, несмотря на ошибку первого"


class NoneOnceClient(FakeClient):
    """users_playlists возвращает None (сбой разбора ответа) на первой попытке, затем нормальные данные."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def users_playlists(self, kind):
        self.calls += 1
        if self.calls == 1:
            return None
        return super().users_playlists(kind)


def test_apply_retries_on_none_response_instead_of_treating_as_empty_playlist(monkeypatch):
    # Регрессия: client.users_playlists() тихо возвращает None при любом сбое разбора ответа
    # (не только когда плейлиста реально не существует). Раньше это трактовалось как "плейлист
    # пуст", и apply вставлял поверх уже существующих треков дубли.
    monkeypatch.setattr(apply_mod.time, "sleep", lambda s: None)
    client = NoneOnceClient()
    rows = [{"target_playlist": "Рок — RU", "id": 1, "album_id": 10}]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.inserted == [], "трек уже был в плейлисте, дубль вставляться не должен"


class AlwaysNoneClient(FakeClient):
    def users_playlists(self, kind):
        return None


def test_apply_raises_instead_of_silently_treating_persistent_none_as_empty(monkeypatch):
    monkeypatch.setattr(apply_mod.time, "sleep", lambda s: None)
    client = AlwaysNoneClient()
    rows = [{"target_playlist": "Рок — RU", "id": 1, "album_id": 10}]

    try:
        apply_mod.apply_classification(client, rows, delay=0)
        assert False, "должно было упасть, а не молча решить, что плейлист пуст"
    except RuntimeError:
        pass


def test_find_duplicate_ranges_no_duplicates():
    assert apply_mod.find_duplicate_ranges(["1:10", "2:20", "3:30"]) == []


def test_find_duplicate_ranges_single_contiguous_block():
    ids = ["1:10", "2:20", "3:30", "1:10", "2:20", "3:30"]
    assert apply_mod.find_duplicate_ranges(ids) == [(3, 6)]


def test_find_duplicate_ranges_scattered_and_triple():
    ids = ["1:10", "1:10", "2:20", "1:10", "3:30"]
    assert apply_mod.find_duplicate_ranges(ids) == [(1, 2), (3, 4)]


def test_dedupe_playlists_dry_run_does_not_delete():
    client = FakeClient()
    client.playlists[100].tracks = [FakeTrackShort("1:10"), FakeTrackShort("2:20"), FakeTrackShort("1:10")]

    apply_mod.dedupe_playlists(client, delay=0, dry_run=True)

    assert len(client.playlists[100].tracks) == 3, "дубли не должны удаляться в dry-run режиме"


def test_with_label_appends_suffix():
    assert classify.with_label("Рок — RU", "Друг") == "Рок — RU (Друг)"


def test_apply_classification_uses_labeled_playlist_without_touching_shared_one():
    # --label в cli.py переписывает target_playlist до вызова apply_classification -
    # сама функция про метки ничего не знает, просто группирует по строке target_playlist.
    client = FakeClient()
    rows = [{"target_playlist": classify.with_label("Рок — RU", "Друг"), "id": 5, "album_id": 50}]

    apply_mod.apply_classification(client, rows, delay=0)

    assert client.created == ["Рок — RU (Друг)"]
    assert client.inserted == [(200, 5, 50, 1)]


def test_dedupe_playlists_removes_duplicate_block():
    client = FakeClient()
    client.playlists[100].tracks = [
        FakeTrackShort("1:10"),
        FakeTrackShort("2:20"),
        FakeTrackShort("1:10"),
        FakeTrackShort("2:20"),
    ]

    apply_mod.dedupe_playlists(client, delay=0, dry_run=False)

    remaining = [t.track_id for t in client.playlists[100].tracks]
    assert remaining == ["1:10", "2:20"], "должна остаться только первая копия каждого трека"
