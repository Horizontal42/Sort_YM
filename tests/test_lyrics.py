import json
from pathlib import Path

import pytest
from yandex_music.exceptions import NotFoundError

from sort_ym import lyrics


def track(id_, title="Песня", artists=("Артист",), genre_raw="rock", lyrics_available=True):
    return {
        "id": id_,
        "album_id": 10,
        "title": title,
        "artists": list(artists),
        "artist_ids": [7],
        "genre_raw": genre_raw,
        "lyrics_available": lyrics_available,
    }


def test_ru_lyric_track_ids_keeps_ru_and_drops_int():
    tracks_cache = {
        "100:10": track(100, title="Тоска", artists=["Гражданская Оборона"]),
        "200:10": track(200, title="Come as You Are", artists=["Nirvana"]),
    }

    ids = lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={})

    assert ids == ["100"]


def test_ru_lyric_track_ids_trusts_api_language_over_alphabet():
    # Кириллическое название, но API говорит "en" - латиницы в тексте нет, а язык известен точно.
    tracks_cache = {"100:10": track(100, title="Тоска", artists=["Артист"])}

    ids = lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={"100": "en"})

    assert ids == []


def test_ru_lyric_track_ids_skips_tracks_without_lyrics():
    tracks_cache = {"100:10": track(100, title="Тоска", lyrics_available=False)}

    assert lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={}) == []


def test_ru_lyric_track_ids_deduplicates_same_numeric_id():
    # Один и тот же трек лайкнут с двух альбомов - числовой id общий, ключи кэша разные.
    tracks_cache = {
        "100:10": track(100, title="Тоска"),
        "100:20": track(100, title="Тоска"),
    }

    assert lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={}) == ["100"]


def test_ru_lyric_track_ids_all_languages_includes_int():
    tracks_cache = {
        "100:10": track(100, title="Тоска", artists=["Гражданская Оборона"]),
        "200:10": track(200, title="Come as You Are", artists=["Nirvana"]),
    }

    ids = lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={}, all_languages=True)

    assert ids == ["100", "200"]


def test_ru_lyric_track_ids_all_languages_still_gates_on_lyrics_available():
    tracks_cache = {"100:10": track(100, lyrics_available=False)}

    assert lyrics.ru_lyric_track_ids(tracks_cache, lang_cache={}, all_languages=True) == []


class FakeLyrics:
    def __init__(self, full_lyrics):
        self.full_lyrics = full_lyrics


class FakeSupplement:
    def __init__(self, full_lyrics):
        self.lyrics = FakeLyrics(full_lyrics) if full_lyrics is not None else None


class FakeClient:
    def __init__(self, texts):
        self._texts = texts
        self.requested: list[str] = []

    def track_supplement(self, track_id):
        self.requested.append(track_id)
        if track_id not in self._texts:
            raise NotFoundError("no such track")
        return FakeSupplement(self._texts[track_id])


def test_fetch_lyrics_text_caches_and_persists(tmp_path: Path):
    client = FakeClient({"100": "Первая строка\nВторая строка"})

    cache = lyrics.fetch_lyrics_text(client, ["100"], tmp_path, delay=0)

    assert cache["100"] == "Первая строка\nВторая строка"
    assert lyrics.load_lyrics_cache(tmp_path) == cache


def test_fetch_lyrics_text_skips_already_cached(tmp_path: Path):
    (tmp_path / lyrics.LYRICS_TEXT_CACHE_FILE).write_text(
        json.dumps({"100": "уже загружено"}, ensure_ascii=False), encoding="utf-8"
    )
    client = FakeClient({"100": "новый текст"})

    cache = lyrics.fetch_lyrics_text(client, ["100"], tmp_path, delay=0)

    assert client.requested == [], "уже закэшированный трек не должен запрашиваться снова"
    assert cache["100"] == "уже загружено"


def test_fetch_lyrics_text_stores_none_for_missing_track_and_does_not_retry(tmp_path: Path):
    # NotFoundError - окончательный ответ, а не сбой; None пишется в кэш как "текста нет",
    # иначе такой трек перезапрашивался бы при каждом запуске.
    client = FakeClient({})

    lyrics.fetch_lyrics_text(client, ["100"], tmp_path, delay=0)
    second_client = FakeClient({})
    cache = lyrics.fetch_lyrics_text(second_client, ["100"], tmp_path, delay=0)

    assert cache["100"] is None
    assert second_client.requested == []


def test_fetch_lyrics_text_stores_none_when_supplement_has_no_lyrics(tmp_path: Path):
    client = FakeClient({"100": None})

    cache = lyrics.fetch_lyrics_text(client, ["100"], tmp_path, delay=0)

    assert cache["100"] is None
