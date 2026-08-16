[Русский](README.ru.md)

# Sort YM

Sorts your Yandex Music liked tracks into playlists named `Genre — RU` / `Genre — INT`.

```
$ python -m sort_ym report

Playlist breakdown:
  Rock — INT: 143
  Rock — RU: 287
  Rap — RU: 512
  ...

Report saved: out/report.csv
```

## Install

Requirements: Python 3.11+ (uses `tomllib` from the standard library), Windows/Linux/macOS, internet access.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

For development (tests):

```
.venv\Scripts\pip install -r requirements-dev.txt
```

## What it does

### Core commands

```
.venv\Scripts\python -m sort_ym auth                    # log in to a Yandex account via device-flow and save the token to .token
.venv\Scripts\python -m sort_ym fetch                   # download liked tracks (cache/tracks.json) and their artists' genres (cache/artist_genres.json); does not change the account
.venv\Scripts\python -m sort_ym report                  # compute genre and language per track, save out/report.csv (does not change the account)
.venv\Scripts\python -m sort_ym apply --limit 20 --yes  # dry run: create playlists and add the first 20 tracks
.venv\Scripts\python -m sort_ym apply --yes             # create playlists and add all tracks (changes the account)
.venv\Scripts\python -m sort_ym digest                  # library summary (top artists, genres) to out/digest.md - to paste into an LLM chat; no network used
.venv\Scripts\python -m sort_ym lyrics                  # download the lyrics text of Russian-language tracks (cache/lyrics_text.json); does not change the account
.venv\Scripts\python -m sort_ym analyze                 # analyze those lyrics with a local Ollama model (cache/lyrics_analysis.json); no internet, runs for hours, resumable
```

On repeated runs `fetch` only downloads new tracks, and `apply` does not duplicate tracks already added.

### Extra: another playlist instead of your likes

```
.venv\Scripts\python -m sort_ym report --source <url>                    # same, but for someone else's/another playlist by link
.venv\Scripts\python -m sort_ym digest --source <url>                    # digest of that playlist
.venv\Scripts\python -m sort_ym apply --source <url> --label Friend --yes  # sort its tracks into your own "Genre — RU (Friend)" playlists
```

See "Analyzing and sorting another playlist" below for details.

### Extra: fine-tuning report.csv

By default `report` groups/sorts tracks by target playlist with a base set of columns.
These flags change that — from most to least commonly useful:

```
.venv\Scripts\python -m sort_ym report --order playlist            # skip playlist-based sorting - keep source track order (as in likes/the --source playlist)
.venv\Scripts\python -m sort_ym report --timestamp                 # + when the track was added (added_at)
.venv\Scripts\python -m sort_ym report --album                     # + album release date and likes (release_date, album_likes_count)
.venv\Scripts\python -m sort_ym report --artist                    # + first artist's track counts/rating
.venv\Scripts\python -m sort_ym report --duration                  # + track length (duration_ms)
.venv\Scripts\python -m sort_ym report --version                   # + track/album version tags (remix, anniversary edition, etc.)
.venv\Scripts\python -m sort_ym report --timestamp --album         # flags can be combined
.venv\Scripts\python -m sort_ym report --extra --order playlist    # --extra = every extra column at once + source track order
```

## Full cache cleanup

To start over from scratch (re-fetch everything), delete the `cache/` folder:

```
Remove-Item -Recurse -Force cache
```

The cache consists of six files:
- `cache/tracks.json` — liked tracks and their metadata (including artist ids);
- `cache/artist_genres.json` — genre tags for each artist (an artist can have several);
- `cache/genre_catalog.json` — a snapshot of Yandex's genre tree as of the last run;
- `cache/lyrics_lang.json` — detected lyrics language per track;
- `cache/lyrics_text.json` — lyrics text of Russian-language tracks;
- `cache/lyrics_analysis.json` — per-track lyric analysis from the local model.

Deleting `cache/` makes `fetch` and `report` re-fetch everything from scratch on the next run.

You can also delete the generated reports (`out/report.csv`, `out/digest.md`):

```
Remove-Item -Recurse -Force out
```

It's just analysis output — deleting it doesn't affect the next `report`/`digest` run.

**Important:** the `.token` file (OAuth token) is not part of the cache and is not removed by clearing `cache/`. Clearing the cache does not log you out. To force re-authentication, delete `.token` separately:

```
Remove-Item .token
```

## How genre and language are determined

- **Genre** is determined at the **sub-genre** level (Rock, Punk, Indie, Alternative, Metal, ...,
  not just the 11 top-level buckets), combining two signals:
  1. The track's **album** genre (`genre_raw`) — a per-track signal.
  2. The **artist's** genres (`Artist.genres`, an artist can have several tags, more precise than
     a single album genre) — a per-artist signal.

  If the signals agree, the sub-genre is used as is. On conflict: if the album tag is generic
  ("umbrella-like", such as `rock`/`alternative`/`pop` — Yandex's typical low-confidence default),
  the artist's genre wins; if the album tag is precise/specific (`numetal`, `dnb`, `shanson`), it
  wins, because it's more likely a genuine genre experiment by the artist rather than noise. This
  way the same artist with tracks of different character (say, a rock track and a punk track) ends
  up in different playlists instead of everything being lumped into one "main" genre.

  Sub-genre groups smaller than `small_group_min` (12 tracks by default, `config.toml`) collapse
  into the parent top-level bucket (Pop, Rock, Metal, Rap, Electronic, Jazz & Blues, Classical,
  Folk & World, Indie & Alternative, Soundtracks, Other) to avoid playlists with 1-2 tracks.
  Implementation — `sort_ym/genres.py` (`classify_track`, `ROOT_BUCKET`) — the root table is easy
  to extend if Yandex returns an unfamiliar root genre.

- **Language** is a hybrid:
  1. If the track has lyrics — the real language from the API (`ru` → RU, otherwise → INT).
  2. Otherwise — a genre-based hint (`rusrap`, `shanson`, `bard`, ...).
  3. Otherwise — an alphabet heuristic on the title/artist (Cyrillic/Latin).
  4. If nothing matched — the track goes into `... — Undetermined`.

After `report`, the console also prints a list of unrecognized genres (that fell into "Other") so
the table in `sort_ym/genres.py` can be extended.

## Digest for an LLM

An LLM can't digest a full per-track dump of ~2000 tracks as well as a compact summary — so
`digest` doesn't export tracks line by line, it aggregates the library into a few sections with
hard size ceilings: at most 11 lines for top-level genres, ~34 for sub-genres, 3 for languages,
~13 for decades, and top artists/top albums are bounded by `config.toml`, not by library size.
Anything past the top collapses into a single sentence with aggregate numbers. The resulting file
stays a couple hundred lines at most, regardless of whether the library has 500 tracks or 10000.

Without `--source` the command is fully offline: no network calls, no `.token` needed, only the
already downloaded `cache/` (requires `report` to have run at least once, for
`cache/genre_catalog.json`). With `--source` (see "Analyzing another playlist" below) it needs
both network and a token, but does not require `fetch` to have run at all.

```
$ python -m sort_ym digest

Genres:
  Indie & Alternative: 680
  Rock: 590
  ...

Digest saved: out/digest.md
```

Example `out/digest.md` (abridged):

## Lyric analysis (Russian tracks)

`lyrics` downloads the lyrics text, `analyze` reads it with a local model and writes a per-track
profile: mood, themes, emotional arc, point of view, tone, plus a short description of what the
song is about and why it might resonate.

```
.venv\Scripts\python -m sort_ym lyrics    # lyrics text of Russian-language tracks
.venv\Scripts\python -m sort_ym analyze   # analysis via local Ollama, hours of local compute
.venv\Scripts\python -m sort_ym digest    # out/lyrics_digest.md + an aggregate block in out/digest.md
```

Only Russian-language tracks are analyzed. On a foreign-language track the meaning is carried by
the music and the vocal delivery rather than by parsed words, so a literal reading of the text
would add a signal the listener never actually perceives.

Requirements: Ollama running locally with the model named in `config.toml` under `[ollama]`
(`ollama list` to check). No internet is used — `analyze` never talks to Yandex.

Expect roughly 40 seconds per track — about three hours for a ~266-track library. The run is
interruptible: results are written after every single track, so Ctrl+C costs at most one track,
and re-running continues where it stopped. Tracks that timed out are retried on the next run.
Raising `prompt_version` in `config.toml` invalidates the whole cache and re-analyzes everything.

Example `out/digest.md` (abridged):

```
## Genres (top-level buckets)
- Indie & Alternative — 680 (34%): INT 571 / RU 108
- Rock — 590 (29%): INT 518 / RU 72
...

## Decades
- 2010s — 620 (31%): Rock 280, Indie & Alternative 200, Metal 90
...

## Top 40 artists
1. Billy Talent — 66 (Rock; rock, punk)
...
1140 more artists with 1-4 tracks, 1737 mentions total; 835 of them with a single track.

## Top 15 albums
1. Slipknot — Iowa (2001) — 12
...
1401 more albums with 1-3 liked tracks. Tracks from albums with 2+ liked tracks: 732 of 2005 (37%).
```

**Important:** the `year` and `album title` fields weren't in the track cache from the start — if
`cache/tracks.json` was created by an older version of `fetch`, the "Decades" and "Top albums"
sections will show "Unknown" until the next `python -m sort_ym fetch` run (it re-downloads the
whole cache once, then goes back to only fetching new tracks as usual).

## Analyzing another playlist

`report`, `digest`, and `apply` can work on any Yandex Music playlist — your own other playlist,
or someone else's public one — not just your likes, via the `--source` flag with a link.

Getting the link: open the playlist in the web player and copy the address bar — it looks like
`https://music.yandex.ru/users/<login>/playlists/<number>`.

```
python -m sort_ym report --source https://music.yandex.ru/users/vasya/playlists/1001
python -m sort_ym digest --source https://music.yandex.ru/users/vasya/playlists/1001
python -m sort_ym apply --source https://music.yandex.ru/users/vasya/playlists/1001 --label Vasya --yes
```

- **`--label <name>`** (`apply` only) — tracks land in separate playlists like "Rock — RU
  (Vasya)" instead of the shared "Rock — RU". Without `--label` they go into the same playlists as
  your own liked tracks of that genre/language — a deliberate default, but exactly why you should
  decide explicitly whether you want someone else's taste mixed into your own for a foreign source.
- **No caching, no history**: an external playlist's data is fetched fresh on every run and never
  saved to disk (unlike likes in `cache/tracks.json`) — by design. Re-running against the same
  link re-downloads everything from scratch.
- **Private playlists**: if the playlist is inaccessible (private, or your token expired), the
  command prints a clear error — either ask the owner to make it public, or re-authenticate
  (`python -m sort_ym auth`).
- **Slightly lower language accuracy**: an external source's language isn't refined through the
  lyrics API (a per-track request, and without caching it would be slow on every run) — only the
  existing `cache/lyrics_lang.json` plus the heuristics. Without `--label` a track can land in the
  wrong language playlist, and if you later like it, it ends up in both.
- There's no dry-run for `apply --source` (only `--limit`) — run `report --source` first to see
  the playlist breakdown before inserting anything for real.
- `report --source`/`digest --source` write to separate files —
  `out/report_source.csv`/`out/digest_source.md` — and never overwrite your main
  `out/report.csv`/`out/digest.md`.
- `report --source <url> --order playlist` — tracks in the CSV keep the same order as in the
  playlist itself, instead of being resorted by target playlist.

## Handy things

- Run `apply` first with `--limit 20 --yes` and check the result in the app before running it
  against all ~2000 tracks.
- Delays between requests are configured in `config.toml` (`[throttle]`).
- The minimum sub-genre playlist size is `config.toml` (`[classify] small_group_min`).
- How many artists/albums the digest names individually — `config.toml` (`[digest] top_artists`,
  `top_albums`) or the `digest` command's `--top`/`--top-albums` flags.

## Risks (unofficial API)

There is no official API for personal Yandex Music library access — this tool uses the
unofficial `yandex-music` library. The OAuth token in `.token` grants full access to your Yandex
account — keep it local and never publish it. The tool only performs safe actions (reading likes,
creating playlists, adding tracks) and never deletes anything.

## For developers

Python 3.11+, `yandex-music==3.0.0`, standard library (`tomllib`, `csv`, `unicodedata`).

```
.venv\Scripts\python -m pytest tests/ -v
.venv\Scripts\python -m sort_ym auth
.venv\Scripts\python -m sort_ym fetch
.venv\Scripts\python -m sort_ym report
.venv\Scripts\python -m sort_ym apply --limit 20 --yes
.venv\Scripts\python -m sort_ym digest
.venv\Scripts\python -m sort_ym report --source https://music.yandex.ru/users/vasya/playlists/1001
```

Code structure and data flow are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Credits

Andrew Pimenov

## License

[MIT License](LICENSE)
