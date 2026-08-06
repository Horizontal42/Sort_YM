from __future__ import annotations

import argparse

from . import apply as apply_mod
from . import auth, classify, digest, fetch, genres, language, report
from .config import load_config
from .ymclient import make_client


def cmd_auth(args: argparse.Namespace) -> None:
    cfg = load_config()
    auth.device_login(cfg.token_file)


def cmd_fetch(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)
    fetch.fetch_liked_tracks(client, cfg.cache_dir, cfg.batch_size, cfg.fetch_batch_delay)
    fetch.fetch_artist_genres(client, cfg.cache_dir, cfg.batch_size, cfg.fetch_batch_delay)


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)
    artist_genres = fetch.load_artist_genres(cfg.cache_dir)

    ids_needing_lang = [str(t["id"]) for t in tracks_cache.values() if t["lyrics_available"]]
    lang_cache = language.fetch_api_languages(client, ids_needing_lang, cfg.cache_dir, cfg.lyrics_request_delay)

    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)
    out_file = report.write_report(rows, cfg.out_dir)

    print("\nРаспределение по плейлистам:")
    for name, n in sorted(report.summarize(rows).items()):
        print(f"  {name}: {n}")

    other = report.other_breakdown(rows)
    if other:
        print("\nНе распознанные жанры (попали в 'Разное'), можно дополнить sort_ym/genres.py:")
        for genre_raw, n in sorted(other.items(), key=lambda kv: -kv[1]):
            print(f"  {genre_raw}: {n}")

    print(f"\nОтчёт сохранён: {out_file}")


def cmd_apply(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Это изменит ваш аккаунт. Добавьте флаг --yes для подтверждения.")

    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)
    artist_genres = fetch.load_artist_genres(cfg.cache_dir)
    lang_cache = language.load_lang_cache(cfg.cache_dir)
    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    apply_mod.apply_classification(client, rows, cfg.apply_request_delay, limit=args.limit)


def cmd_digest(args: argparse.Namespace) -> None:
    cfg = load_config()

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_catalog(cfg.cache_dir)
    if not catalog:
        raise SystemExit("Нет снимка дерева жанров. Сначала запустите: python -m sort_ym report")

    artist_genres = fetch.load_artist_genres(cfg.cache_dir)
    lang_cache = language.load_lang_cache(cfg.cache_dir)  # только кэш, без сети
    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    top = args.top if args.top is not None else cfg.digest_top_artists
    top_albums = args.top_albums if args.top_albums is not None else cfg.digest_top_albums
    text = digest.render_digest(rows, tracks_cache, artist_genres, top, top_albums)
    out_file = digest.write_digest(text, cfg.out_dir)

    print("\nЖанры:")
    for g in digest.genre_stats(rows):
        print(f"  {classify.BUCKET_LABELS.get(g['bucket'], g['bucket'])}: {g['tracks']}")

    print(f"\nДайджест сохранён: {out_file}")


def cmd_dedupe(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)
    apply_mod.dedupe_playlists(client, cfg.apply_request_delay, dry_run=not args.yes)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sort_ym", description="Сортировка лайкнутых треков Яндекс.Музыки по жанру и языку")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="войти через device-flow и сохранить токен")
    sub.add_parser("fetch", help="загрузить лайкнутые треки в локальный кэш")
    sub.add_parser("report", help="посчитать распределение по плейлистам и сохранить out/report.csv (ничего не меняет в аккаунте)")

    p_apply = sub.add_parser("apply", help="создать плейлисты и добавить треки")
    p_apply.add_argument("--yes", action="store_true", help="подтвердить внесение изменений в аккаунт")
    p_apply.add_argument("--limit", type=int, default=None, help="ограничить количество треков (для пробного запуска)")

    p_dedupe = sub.add_parser("dedupe", help="найти и убрать повторные вставки одного трека в плейлистах")
    p_dedupe.add_argument("--yes", action="store_true", help="подтвердить удаление дублей (без флага - только отчёт)")

    p_digest = sub.add_parser(
        "digest",
        help="сводка библиотеки (топ-исполнители, жанры, десятилетия, топ-альбомы) в out/digest.md - для вставки в чат с LLM",
    )
    p_digest.add_argument("--top", type=int, default=None, help="сколько исполнителей показать поимённо (по умолчанию из config.toml)")
    p_digest.add_argument("--top-albums", type=int, default=None, help="сколько альбомов показать поимённо (по умолчанию из config.toml)")

    args = parser.parse_args(argv)

    commands = {
        "auth": cmd_auth,
        "fetch": cmd_fetch,
        "report": cmd_report,
        "apply": cmd_apply,
        "dedupe": cmd_dedupe,
        "digest": cmd_digest,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
