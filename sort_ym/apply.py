from __future__ import annotations

import time

from yandex_music import Client, Playlist
from yandex_music.exceptions import BadRequestError, NetworkError

from .ymclient import with_retries


def _existing_playlists_by_title(client: Client) -> dict[str, Playlist]:
    playlists = with_retries(lambda: client.users_playlists_list())
    return {p.title: p for p in playlists if p.title}


def _existing_track_ids(client: Client, playlist: Playlist) -> set[str]:
    full = with_retries(lambda: client.users_playlists(playlist.kind))
    if full is None:
        return set()
    return {t.track_id for t in full.tracks}


def _get_or_create_playlist(client: Client, title: str, existing: dict[str, Playlist]) -> Playlist:
    if title in existing:
        return existing[title]
    try:
        playlist = with_retries(lambda: client.users_playlists_create(title, visibility="private"), max_attempts=1)
    except NetworkError:
        # Таймаут не значит, что запрос не дошёл до сервера - плейлист мог всё же
        # создаться. Перепроверяем по имени вместо слепого повтора (иначе - дубль плейлиста).
        fresh = _existing_playlists_by_title(client)
        if title in fresh:
            existing[title] = fresh[title]
            return fresh[title]
        raise
    existing[title] = playlist
    return playlist


def _insert_track_verified(
    client: Client,
    playlist: Playlist,
    row: dict,
    track_key: str,
    revision: int,
    max_attempts: int = 4,
) -> int:
    """Добавляет трек в плейлист, возвращает новую revision.

    users_playlists_insert_track - операция записи, а не чтения: при таймауте
    непонятно, применилась ли вставка на сервере. Слепой повтор такого вызова
    рискует добавить трек второй раз. Поэтому при сетевой ошибке перепроверяем
    реальное содержимое плейлиста и повторяем вставку, только если трека там
    действительно ещё нет.
    """
    for attempt in range(max_attempts):
        try:
            updated = with_retries(
                lambda: client.users_playlists_insert_track(
                    playlist.kind, row["id"], row["album_id"], revision=revision
                ),
                max_attempts=1,
            )
            return updated.revision if updated is not None and updated.revision is not None else revision
        except BadRequestError:
            # Детерминированный отказ сервера (например, невалидные данные трека) - ответ
            # точно получен, трек точно не вставлен. Повторять бессмысленно, пробрасываем сразу.
            raise
        except NetworkError as e:
            last_attempt = attempt == max_attempts - 1
            print(f"  сетевая ошибка при вставке трека ({e}), проверяю фактическое состояние плейлиста...")
            fresh = with_retries(lambda: client.users_playlists(playlist.kind))
            if fresh is not None:
                revision = fresh.revision or revision
                if track_key in {t.track_id for t in fresh.tracks}:
                    return revision
            if last_attempt:
                raise
            time.sleep(2.0 * (2**attempt))

    raise RuntimeError("unreachable")


def apply_classification(
    client: Client,
    rows: list[dict],
    delay: float,
    limit: int | None = None,
) -> None:
    if limit is not None:
        rows = rows[:limit]

    existing_playlists = _existing_playlists_by_title(client)

    by_playlist: dict[str, list[dict]] = {}
    for row in rows:
        by_playlist.setdefault(row["target_playlist"], []).append(row)

    for title, playlist_rows in by_playlist.items():
        playlist = _get_or_create_playlist(client, title, existing_playlists)
        already = _existing_track_ids(client, playlist)
        revision = playlist.revision or 1

        added = 0
        no_album = 0
        failed = 0
        for row in playlist_rows:
            track_key = f"{row['id']}:{row['album_id']}" if row["album_id"] else str(row["id"])
            if track_key in already:
                continue

            if row["album_id"] is None:
                # Самозалитые/пиратские треки без альбома - Яндекс не даёт вставить такой
                # трек в плейлист (albumId обязателен), это не временный сбой. Пропускаем.
                no_album += 1
                continue

            try:
                revision = _insert_track_verified(client, playlist, row, track_key, revision)
            except BadRequestError as e:
                print(f"  пропущен трек id={row['id']} ({row.get('title', '?')!r}): {e}")
                failed += 1
                continue

            already.add(track_key)
            added += 1
            time.sleep(delay)

        already_had = len(playlist_rows) - added - no_album - failed
        summary = f"{title}: добавлено {added}, уже было {already_had}"
        if no_album:
            summary += f", пропущено без альбома {no_album}"
        if failed:
            summary += f", ошибок {failed}"
        print(summary)
