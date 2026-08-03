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

```
.venv\Scripts\python -m sort_ym auth                    # log in to a Yandex account via device-flow and save the token to .token
.venv\Scripts\python -m sort_ym fetch                   # download liked tracks (cache/tracks.json) and their artists' genres (cache/artist_genres.json); does not change the account
.venv\Scripts\python -m sort_ym report                  # compute genre and language per track, save out/report.csv (does not change the account)
.venv\Scripts\python -m sort_ym apply --limit 20 --yes  # dry run: create playlists and add the first 20 tracks
.venv\Scripts\python -m sort_ym apply --yes             # create playlists and add all tracks (changes the account)
```

On repeated runs `fetch` only downloads new tracks, and `apply` does not duplicate tracks already added.

## Full cache cleanup

To start over from scratch (re-fetch everything), delete the `cache/` folder:

```
Remove-Item -Recurse -Force cache
```

The cache consists of four files:
- `cache/tracks.json` — liked tracks and their metadata (including artist ids);
- `cache/artist_genres.json` — genre tags for each artist (an artist can have several);
- `cache/genre_catalog.json` — a snapshot of Yandex's genre tree as of the last run;
- `cache/lyrics_lang.json` — detected lyrics language per track.

Deleting `cache/` makes `fetch` and `report` re-fetch everything from scratch on the next run.

You can also delete the generated report:

```
Remove-Item -Recurse -Force out
```

It's just analysis output — deleting it doesn't affect the next `report` run.

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

## Handy things

- Run `apply` first with `--limit 20 --yes` and check the result in the app before running it
  against all ~2000 tracks.
- Delays between requests are configured in `config.toml` (`[throttle]`).
- The minimum sub-genre playlist size is `config.toml` (`[classify] small_group_min`).

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
```

Code structure and data flow are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Credits

Andrew Pimenov

## License

[MIT License](LICENSE)
