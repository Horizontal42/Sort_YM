[Русский](ARCHITECTURE.ru.md)

# Architecture

A Python console utility that reads Yandex Music liked tracks and sorts them into playlists named
`Genre — RU` / `Genre — INT`, using the unofficial `yandex-music` library.

## Structure

```
sort_ym/
  config.py     — reads config.toml (throttle, small_group_min, cache/token paths)
  auth.py       — OAuth device-flow, token storage in .token
  ymclient.py   — Client construction, batching lists, retrying network errors
  fetch.py      — likes -> full Track -> cache/tracks.json; track artists ->
                  client.artists() -> cache/artist_genres.json (both fetched incrementally)
  genres.py     — the real Yandex genre tree; classify_track — resolves track genre and artist
                  genres into a single sub-genre (root_id); ROOT_BUCKET — sub-genre -> 11 top-level buckets
  language.py   — hybrid language detection (lyrics API / genre hint / alphabet)
  classify.py   — (sub-genre | top-level bucket, language) -> playlist name
  report.py     — two-pass report row building, writes out/report.csv, summaries
  apply.py      — playlist creation + idempotent track insertion
  cli.py        — auth / fetch / report / apply commands

tests/
  test_genres.py — classify_track, dominant, bucket_for, genre tree
  test_language.py — language detection
  test_report.py — two-pass collapsing of small sub-genre groups
  test_fetch.py, test_apply.py — track/artist cache, apply idempotency

cache/  — API cache (in .gitignore)
out/    — reports (in .gitignore)
```

## Data flow

```
auth  → .token
fetch → users_likes_tracks() → client.tracks(batch) → cache/tracks.json (+ artist_ids)
      → client.artists(batch) over unique artist_ids → cache/artist_genres.json
report → genres.load_or_fetch_catalog() → cache/genre_catalog.json
       → language.fetch_api_languages() → cache/lyrics_lang.json
       → build_rows(): pass 1 — classify_track() per track (genre_raw + artist genres)
                        pass 2 — groups < small_group_min collapse into the top-level bucket
       → out/report.csv (dry-run, account unchanged)
apply --yes → users_playlists_create / users_playlists_insert_track
```

## Key decisions

- **Track genre** is only available through the album (`Track.albums[0].genre`) — the track itself
  has no genre field, so it's one string per track, often generic (`rock`, `alternative`). Bucketing
  is done through the real `client.genres()` tree (parent → sub-genres), not a guessed slug list —
  the `ROOT_BUCKET` table in `genres.py` relies on confirmed ids, not assumptions. Genres without a
  match fall into the `other` bucket and are printed in `report`'s output for manual table extension.

- **Sub-genre classification (`genres.classify_track`)**: track genre is one string per album and
  often generic. An artist (`client.artists()`, a batch endpoint) can have several tags, more
  precise than a single album genre. `classify_track(genre_raw, artist_genre_lists, catalog)`
  resolves both signals into a single sub-genre (`root_id`, e.g. `punk`/`indie`/`allrock`) at the
  **track** level, not the artist level — so the same artist with tracks of different character ends
  up in different playlists:
  1. Signals agree (track genre is among the artist's genres) → use it — granular per track.
  2. Track has no genre → use the most frequent (`dominant`) genre among the track's artists.
  3. Artist(s) have no tags → use the track's genre.
  4. Conflict: the album tag is generic/"umbrella" (`GENERIC_SLUGS`: `rock`, `alternative`, `pop`,
     ... — Yandex's low-confidence default) → the artist's genre wins (`dominant` over the combined
     tags of all the track's artists, tie-break by order of appearance). The album tag is
     precise/specific (`numetal`, `dnb`, ...) → it wins — likely a genuine genre experiment by the
     artist rather than noise worth correcting.

  The result (`fine`) is collapsed in a two-pass process in `report.build_rows`: first the sizes of
  `(fine, lang)` groups are counted, then groups smaller than `config.small_group_min` move to the
  parent top-level bucket via `genres.coarse_of(fine)` (a thin wrapper over `ROOT_BUCKET`). The pass
  is single (not iterative) — `coarse_of` is deterministic from `fine`, so there's no re-counting of
  sizes or looping.

- **Language** is determined hybrid, in priority order:
  1. `client.track_supplement(track_id).lyrics.text_language` — the only field in the library with
     the actual lyrics language. It's only present in the deprecated `track_supplement` method, not
     in the newer `tracks_lyrics()` — that one returns the text but not the language. Used
     deliberately despite the library's own deprecation notice.
  2. A genre-slug hint (`rusrap`, `shanson`, `bard`, ...).
  3. An alphabet heuristic on the title/artist (Cyrillic vs Latin, `unicodedata`).
  4. Otherwise — `UNKNOWN` → a separate "Undetermined" playlist.

- **Track identifiers**: a track has a composite `track_id` (`"id:album_id"`, used as the cache key
  and to check against tracks already in a playlist) and separate `id`/`album_id` (needed as
  separate parameters for `track_supplement`, `tracks_lyrics`, and `users_playlists_insert_track`).

- **`apply` idempotency**: before adding tracks to a playlist, its current contents are read
  (`users_playlists(kind)`), and tracks already present are skipped. Re-running `apply` is safe and
  creates no duplicates. Likes are never touched, nothing is ever deleted.

- **Throttling and resumability**: every network loop (fetching tracks, languages) pauses between
  requests (`config.toml`, `[throttle]`) and writes the cache atomically (temp file + rename) after
  each batch — an interrupted run can simply be restarted, and already-fetched data is not
  requested again.

## Storage

- `.token` — the account's OAuth token (not committed).
- `cache/tracks.json` — liked track metadata, including `artist_ids` (the track's artist ids).
- `cache/artist_genres.json` — `{artist_id: {name, genres: [slug, ...]}}`, one or more genres per
  artist.
- `cache/genre_catalog.json` — a flat snapshot of Yandex's genre tree (id -> title, root_id).
- `cache/lyrics_lang.json` — lyrics language per track (id -> language code | null).
- `out/report.csv` — a preview of the playlist breakdown before `apply` (including the
  `fine_bucket` column — the sub-genre before any collapsing into a top-level bucket).
