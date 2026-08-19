[Русский](ARCHITECTURE.ru.md)

# Architecture

A Python console utility that reads Yandex Music liked tracks and sorts them into playlists named
`Genre — RU` / `Genre — INT`, using the unofficial `yandex-music` library.

## Structure

```
sort_ym/
  config.py     — reads config.toml (throttle, small_group_min, top_artists/top_albums,
                  cache/token paths)
  auth.py       — OAuth device-flow, token storage in .token
  ymclient.py   — Client construction, batching lists, retrying network errors
  fetch.py      — likes -> full Track -> cache/tracks.json (serialize_track); track artists ->
                  client.artists() -> cache/artist_genres.json (both fetched incrementally);
                  unique_artist_ids — unique artist ids from the track cache
  source.py     — ephemeral source: parses a link to an arbitrary playlist + loads its tracks/
                  artists into memory, never touches disk (see "--source" below)
  genres.py     — the real Yandex genre tree; classify_track — resolves track genre and artist
                  genres into a single sub-genre (root_id); ROOT_BUCKET — sub-genre -> 11 top-level buckets
  language.py   — hybrid language detection (lyrics API / genre hint / alphabet)
  lyrics.py     — text lyrics of RU-tracks: track_supplement().lyrics.full_lyrics ->
                  cache/lyrics_text.json (incrementally, atomic-write)
  analyze.py    — lyric analysis via local Ollama (/api/chat, think + JSON Schema) ->
                  cache/lyrics_analysis.json (written after each track)
  classify.py   — (sub-genre | top-level bucket, language) -> playlist name; with_label — source
                  label suffix for apply --source --label
  report.py     — two-pass report row building, writes out/report.csv, summaries
  apply.py      — playlist creation + idempotent track insertion
  digest.py     — aggregated library summary (top artists, genres, decades, top albums)
                  -> out/digest.md, fully offline without --source; Wording/playlist_wording —
                  digest text for likes vs an arbitrary playlist
  cli.py        — auth / fetch / report / apply / dedupe / digest commands; --source/--label
                  on report/apply/digest (see "Key decisions")

tests/
  test_genres.py — classify_track, dominant, bucket_for, genre tree
  test_language.py — language detection
  test_lyrics.py — lyrics text download, cache structure, resumability
  test_analyze.py — local Ollama integration, JSON Schema parsing, cache atomicity
  test_report.py — two-pass collapsing of small sub-genre groups
  test_fetch.py, test_apply.py — track/artist cache, apply idempotency
  test_digest.py — artist/album aggregation, long-tail collapsing, digest size bounds
  test_source.py — playlist URL parsing, matching client.tracks() response by id, handling
                  private/inaccessible playlists
  test_cli.py, test_config.py — --source/--label flag validation before any network access;
                  config.toml reading including [ollama] block

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
digest → genres.load_catalog() + language.load_lang_cache() (cache only, no network)
       → build_rows() → out/digest.md
lyrics  → ru_lyric_track_ids() → client.track_supplement() → cache/lyrics_text.json
analyze → cache/lyrics_text.json → Ollama /api/chat → cache/lyrics_analysis.json
digest  → + cache/lyrics_analysis.json → out/digest.md (aggregate block) + out/lyrics_digest.md

report/apply/digest --source <url> → source.parse_playlist_url() → (user_id, kind)
       → client.users_playlists(kind, user_id=...) → TrackShort[] → client.tracks(batch)
       → an in-memory dict (fetch.serialize_track shape, never written to disk)
       → client.artists(batch) → genres.load_or_fetch_catalog() (shared cache/genre_catalog.json)
       + language.load_lang_cache() (read-only) → build_rows()
       → out/report_source.csv | out/digest_source.md | apply → playlists on your own account
         (shared "Genre — RU/INT" or "... (label)" with --label)
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

- **Lyric analysis (`lyrics.py`, `analyze.py`)**: by default only Russian-language tracks are
  analyzed — the prompt and the narrative fields (`summary`/`resonance`/`key_line`) are written
  in Russian and were validated against a Russian-lyrics pilot run; quality on other languages is
  unverified. `sort_ym lyrics --all-languages` lifts the filter and fetches/analyzes every track
  with available lyrics regardless of detected language (`lyrics.ru_lyric_track_ids(...,
  all_languages=True)`). Text fetching and analysis are **two separate commands** on purpose: the fetch is network-bound against the deprecated `track_supplement`,
  the analysis is a multi-hour local GPU job, and a prompt or model change must be re-runnable
  without touching Yandex again. `analyze` and `digest` construct no `Client` at all.

  The Ollama call (`/api/chat`) combines `think: true` with a full JSON Schema in `format`:
  reasoning goes to a separate `message.thinking` field (never cached) while only the final
  answer is grammar-constrained, so the model reasons freely and the result still parses.
  `num_predict: -1` — a token cap would truncate mid-JSON and turn a slow answer into an invalid
  one; the bound is the request timeout instead. `temperature: 0.65`, not 0: at 0 the narrative
  fields flatten out.

  `themes` are free-form but pattern-constrained to English snake_case
  (`^[a-z0-9][a-z0-9_-]{2,29}$`) — in the pilot, an unconstrained field drifted between Russian and
  English inside a single run, making the values impossible to aggregate; the pattern makes
  Cyrillic mechanically unrepresentable at decode time. They are English for the same reason
  genre slugs and `ROOT_BUCKET` keys are: they are aggregation keys. `mood` is a closed enum that
  deliberately excludes irony/sarcasm — that axis is `stance`, and mixing the two produced
  compound values like `"aggressive/triumphant"`.

  Resumability: the cache is written atomically after **every single track** (not batched by 20
  as in `language.py`) — inference costs tens of seconds, so a crash must cost at most one track.
  An entry is reused only when `(model, prompt_version, lyrics_hash)` all match, so a corrected
  lyrics text or a bumped prompt invalidates exactly what it should. A timeout or a broken
  response is stored as an `error` marker and the batch continues; error entries are never
  considered fresh, so the next run retries precisely those tracks.

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

- **Library digest (`digest.py`)**: the `digest` command's output is meant to be pasted into an LLM
  chat, so it's built as a set of aggregates with fixed ceilings rather than a per-track dump — on a
  ~2000-track library that's ~150 lines, regardless of whether the library has 500 tracks or 10000
  (genre sections are bounded by the size of `ROOT_BUCKET`/`BUCKET_LABELS`; top artists and top
  albums are bounded by the `[digest]` config, not the library size; anything past the top is
  collapsed into a single sentence with aggregate numbers). Artists are counted **by name**, not via
  `zip(artists, artist_ids)` — `fetch.serialize_track` puts every named artist into `artists` but only
  those that also have an id into `artist_ids`, so the two lists can differ in length for a given
  track. For the same reason, an artist's own genre tags (`artist_tags`) are only looked up from
  tracks where the two lists' lengths match — otherwise an artist could end up with someone else's
  tags. Rows from `report.build_rows()` are joined back to `cache/tracks.json` by the `(id,
  album_id)` pair taken from the cache's **values**, not by reconstructing the key as
  `f"{id}:{album_id}"` — the cache key is the original id from `likes.tracks_ids`, and for
  album-less tracks it doesn't match that format. The album's year and title (`year`,
  `album_title`) are read from the same `albums[0]` as `album_id` — otherwise the title could end up
  paired with the wrong id. Old cache entries are backfilled with the same mechanism used for
  `artist_ids`: the migration checks whether the `year` key is **present**, not whether its value is
  truthy, otherwise tracks with a legitimately unknown year would be re-fetched on every `fetch` run.
  The command is fully offline — it never constructs a `Client`, unlike `report`/`apply`.

- **Arbitrary playlist by link (`source.py`, `--source` on `report`/`apply`/`digest`)**: an
  external source is **ephemeral** — its data is fetched into memory on every run and never
  written to disk (`source.py` imports no `json` and never touches `cache_dir` at all). The one
  exception is the shared `cache/genre_catalog.json` (Yandex's genre tree — a reference dataset,
  not a specific playlist's history), reused as usual via `genres.load_or_fetch_catalog`. Writes
  always target your own account: a foreign `user_id` is only ever passed into
  `client.users_playlists(kind, user_id=...)` (a read); no call in `apply.py`
  (`users_playlists_create`, `users_playlists_insert_track`) accepts one. The `yandex_music`
  library has no URL parser at all — `source.parse_playlist_url` parses
  `https://music.yandex.ru/users/<login>/playlists/<kind>` (plus a best-effort `/playlists/<uuid>`
  form via `client.playlist(uuid)`) itself, with no external dependency. `Playlist.tracks` is a
  list of `TrackShort` (no genre/album data); full `Track` objects are fetched with the same batch
  method used for likes, `client.tracks(...)`, but the response is matched back to the requested
  id by value (`by_id.get(...)`), not a positional `zip` — a foreign playlist is noticeably more
  likely to contain unavailable tracks, and a shortened response under `zip` would silently mix up
  track data (`Playlist.fetch_tracks()` is a trap — it just re-calls `users_playlists` and returns
  the same short objects, so it isn't used). `UnauthorizedError` extends `YandexMusicError`
  directly, not `NetworkError`, so `ymclient.with_retries` never catches or retries it — it used to
  be unhandled anywhere in the project; it's now caught in `source._load_playlist` (a private or
  inaccessible playlist) and by a top-level net in `cli.main()` (an expired token on any command).
  Language for an external source is not refined via `track_supplement` (one uncached network
  request per track on every run) — it falls back to the existing `cache/lyrics_lang.json` (read
  only) plus the heuristics; a track whose language disagrees with what the precise check would
  have picked can land in the wrong language playlist under `apply --source` without `--label`.

## Storage

- `.token` — the account's OAuth token (not committed).
- `cache/tracks.json` — liked track metadata, including `artist_ids` (the track's artist ids),
  `album_title` and `year` (the album's title and release year, `Album.title`/`Album.year`; `year`
  can be `null`), plus `added_at` (when the track was liked, `TrackShort.timestamp`),
  `duration_ms`, `track_version`/`album_version`, `release_date`, `album_likes_count` - raw API
  fields not used for classification but available via `report --extra` (see below).
- `cache/artist_genres.json` — `{artist_id: {name, genres: [slug, ...], counts, ratings}}`, one or
  more genres per artist; `counts`/`ratings` are `Artist.counts`/`Artist.ratings`, same
  `report --extra`-only purpose as `added_at` above.
- `cache/genre_catalog.json` — a flat snapshot of Yandex's genre tree (id -> title, root_id).
- `cache/lyrics_lang.json` — lyrics language per track (id -> language code | null).
- `cache/lyrics_text.json` — lyrics text per track (numeric id -> text | null, RU tracks only).
- `cache/lyrics_analysis.json` — per-track analysis record: `{track_id: {model, prompt_version,
  lyrics_hash, mood, themes, emotional_arc, pov, tone, description, error?}}`.
- `out/lyrics_digest.md` — full per-track reading grouped by primary mood.
- `config.toml` — includes `[ollama]` block with `host`, `model`, `prompt_version`, `timeout`,
  `keep_alive`.
- `out/report.csv` — a preview of the playlist breakdown before `apply` (including the
  `fine_bucket` column — the sub-genre before any collapsing into a top-level bucket).
  `report --order playlist` keeps source track order instead of sorting by target playlist;
  individual `--timestamp`/`--duration`/`--version`/`--album`/`--artist` flags (combinable) add
  that group's columns, `--extra` adds every group at once. Flag -> CSV columns mapping is
  `report.EXTRA_GROUPS`; `report.resolve_extra_columns()` expands the selected groups into a
  column list for the CLI.
- `out/digest.md` — a compact library summary for pasting into an LLM chat (top artists, top
  albums, genre/language/decade breakdowns).
- `out/report_source.csv`, `out/digest_source.md` — the same reports for a `--source` run; a
  single overwritten "last external source" slot, no history of other playlists is kept.
