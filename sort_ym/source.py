"""Эфемерный источник треков: чужой (или свой) плейлист по ссылке.

Ничего не пишет на диск - данные внешнего плейлиста живут только в памяти одного запуска
(см. ARCHITECTURE - истории по внешним источникам нет, в отличие от cache/tracks.json для лайков).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

from yandex_music import Client, Playlist
from yandex_music.exceptions import NotFoundError, UnauthorizedError

from . import fetch
from .ymclient import chunked, with_retries

HOST_RE = re.compile(r"^(?:www\.)?music\.yandex\.[a-z]{2,3}$", re.IGNORECASE)
# "lk." (личный кабинет) - префикс у ссылок на персональные плейлисты (например, "Мне нравится"),
# в отличие от чистого uuid у редакционных плейлистов - подтверждено вживую через client.playlist():
# без префикса API отвечает NotFoundError, префикс - часть самого uuid, а не что-то, что надо отрезать.
UUID_RE = re.compile(r"^(?:lk\.)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

_LINK_HINT = (
    "Ожидается ссылка вида https://music.yandex.ru/users/<логин>/playlists/<номер> - "
    "откройте плейлист в веб-плеере Яндекс.Музыки и скопируйте адрес из строки браузера."
)


class SourceError(Exception):
    """Ссылка непонятна или плейлист недоступен - текст уже готов для показа пользователю."""


@dataclass(frozen=True)
class PlaylistRef:
    url: str
    user_id: str | None = None
    kind: str | None = None
    uuid: str | None = None  # форма /playlists/<uuid>


@dataclass(frozen=True)
class SourceInfo:
    url: str
    title: str
    owner: str
    track_count: int


class SourceData(NamedTuple):
    info: SourceInfo
    tracks: dict[str, dict]  # форма == fetch.serialize_track()
    artist_genres: dict[str, dict]  # форма == fetch.load_artist_genres()


def parse_playlist_url(url: str) -> PlaylistRef:
    """https://music.yandex.ru/users/<логин>/playlists/<kind> или /playlists/<uuid> -> PlaylistRef.

    Библиотека yandex_music не умеет разбирать ссылки сама - парсинг целиком на нашей стороне.
    """
    raw = url.strip()
    if not raw:
        raise SourceError(f"Пустая ссылка на плейлист. {_LINK_HINT}")

    if "//" not in raw:
        raw = f"https://{raw}"

    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if not HOST_RE.match(host):
        raise SourceError(f"Это не похоже на ссылку Яндекс.Музыки: '{url}'. {_LINK_HINT}")

    parts = [unquote(p) for p in parsed.path.split("/") if p]

    if len(parts) == 4 and parts[0] == "users" and parts[2] == "playlists" and parts[3].isdigit():
        return PlaylistRef(url=url, user_id=parts[1], kind=parts[3])

    if len(parts) == 2 and parts[0] == "playlists" and UUID_RE.match(parts[1]):
        return PlaylistRef(url=url, uuid=parts[1])

    raise SourceError(f"Не удалось разобрать ссылку на плейлист: '{url}'. {_LINK_HINT}")


def _owner_label(playlist: Playlist) -> str:
    owner = playlist.owner
    if owner is None:
        return "неизвестен"
    return owner.login or owner.name or str(owner.uid)


def _load_playlist(client: Client, ref: PlaylistRef) -> Playlist:
    """Читает плейлист по ref. with_retries не повторяет NotFoundError/UnauthorizedError -
    оба финальные ответы сервера, а не сетевой сбой, лишние попытки на приватный плейлист не нужны.
    """
    try:
        if ref.uuid:
            playlist = with_retries(lambda: client.playlist(ref.uuid))
        else:
            playlist = with_retries(lambda: client.users_playlists(ref.kind, user_id=ref.user_id))
    except NotFoundError:
        raise SourceError(
            f"Плейлист не найден: {ref.url}\n"
            "Проверьте ссылку - возможно, плейлист удалён, переименован владельцем или "
            "ссылка скопирована не полностью."
        )
    except UnauthorizedError:
        raise SourceError(
            f"Нет доступа к плейлисту: {ref.url}\n"
            "Скорее всего он приватный (виден только владельцу) - попросите владельца сделать "
            "его публичным. Если доступ точно есть, мог истечь токен: python -m sort_ym auth"
        )

    if playlist is None:
        raise SourceError(
            f"Не удалось прочитать плейлист по ссылке {ref.url} - API вернул пустой ответ. "
            "Повторите позже."
        )

    return playlist


def fetch_playlist_tracks(
    client: Client,
    ref: PlaylistRef,
    batch_size: int,
    batch_delay: float,
) -> tuple[SourceInfo, dict[str, dict]]:
    playlist = _load_playlist(client, ref)

    info = SourceInfo(
        url=ref.url,
        title=playlist.title or "без названия",
        owner=_owner_label(playlist),
        track_count=playlist.track_count or 0,
    )

    short = playlist.tracks or []
    if not short:
        if info.track_count == 0:
            raise SourceError(f"Плейлист «{info.title}» пуст - анализировать нечего.")
        if ref.uuid:
            raise SourceError(
                f"Плейлист «{info.title}» открылся, но список треков по ссылке этого вида "
                "получить не удалось. Откройте плейлист в веб-плеере и скопируйте ссылку вида "
                "https://music.yandex.ru/users/<логин>/playlists/<номер>."
            )
        raise SourceError(
            f"Плейлист «{info.title}»: API сообщает о {info.track_count} треках, но список "
            "треков не вернул. Повторите позже."
        )

    # Дедуп с сохранением порядка - чужие плейлисты чаще лайков содержат один трек дважды.
    ids = list(dict.fromkeys(t.track_id for t in short))
    added_at_by_id = {t.track_id: t.timestamp for t in short}

    print(f"Треков в плейлисте «{info.title}»: {len(ids)}")

    tracks: dict[str, dict] = {}
    missing = 0
    for batch in chunked(ids, batch_size):
        fetched = with_retries(lambda: client.tracks(batch))
        # Сопоставляем по id, а не позиционным zip(batch, fetched) - в чужом плейлисте заметно
        # вероятнее недоступные/удалённые треки, и укороченный ответ при zip тихо перепутал бы
        # треки между собой.
        by_id = {str(t.id): t for t in fetched}
        for requested_id in batch:
            track = by_id.get(requested_id.split(":")[0])
            if track is None:
                missing += 1
                continue
            tracks[requested_id] = fetch.serialize_track(track, added_at=added_at_by_id.get(requested_id))
        print(f"  загружено {len(tracks)}/{len(ids)}")
        time.sleep(batch_delay)

    if missing:
        print(f"  недоступно в каталоге: {missing}")

    return info, tracks


def fetch_artist_genres_map(
    client: Client,
    artist_ids: list[str],
    batch_size: int,
    batch_delay: float,
) -> dict[str, dict]:
    """Как fetch.fetch_artist_genres, но без чтения/записи кэша - только в память."""
    result: dict[str, dict] = {}
    for batch in chunked(artist_ids, batch_size):
        artists = with_retries(lambda: client.artists(batch))
        for artist in artists:
            result[str(artist.id)] = {
                "name": artist.name or "",
                "genres": list(artist.genres or []),
                "counts": artist.counts.to_dict() if artist.counts else None,
                "ratings": artist.ratings.to_dict() if artist.ratings else None,
            }
        time.sleep(batch_delay)
    return result


def load_source(client: Client, url: str, batch_size: int, batch_delay: float) -> SourceData:
    ref = parse_playlist_url(url)
    info, tracks = fetch_playlist_tracks(client, ref, batch_size, batch_delay)
    artist_genres = fetch_artist_genres_map(client, fetch.unique_artist_ids(tracks), batch_size, batch_delay)
    return SourceData(info=info, tracks=tracks, artist_genres=artist_genres)
