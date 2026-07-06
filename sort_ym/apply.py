from __future__ import annotations

import time

from yandex_music import Client, Playlist


def _existing_playlists_by_title(client: Client) -> dict[str, Playlist]:
    playlists = client.users_playlists_list()
    return {p.title: p for p in playlists if p.title}


def _existing_track_ids(client: Client, playlist: Playlist) -> set[str]:
    full = client.users_playlists(playlist.kind)
    if full is None:
        return set()
    return {t.track_id for t in full.tracks}


def _get_or_create_playlist(client: Client, title: str, existing: dict[str, Playlist]) -> Playlist:
    if title in existing:
        return existing[title]
    playlist = client.users_playlists_create(title, visibility="private")
    existing[title] = playlist
    return playlist


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
        for row in playlist_rows:
            track_key = f"{row['id']}:{row['album_id']}" if row["album_id"] else str(row["id"])
            if track_key in already:
                continue

            updated = client.users_playlists_insert_track(
                playlist.kind,
                row["id"],
                row["album_id"],
                revision=revision,
            )
            if updated is not None and updated.revision is not None:
                revision = updated.revision
            already.add(track_key)
            added += 1
            time.sleep(delay)

        skipped = len(playlist_rows) - added
        print(f"{title}: добавлено {added}, уже было {skipped}")
