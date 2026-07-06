from __future__ import annotations

import argparse

from . import apply as apply_mod
from . import auth, fetch, genres, language, report
from .config import load_config
from .ymclient import make_client


def cmd_auth(args: argparse.Namespace) -> None:
    cfg = load_config()
    auth.device_login(cfg.token_file)


def cmd_fetch(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file))
    fetch.fetch_liked_tracks(client, cfg.cache_dir, cfg.batch_size, cfg.fetch_batch_delay)


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file))

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)

    ids_needing_lang = [str(t["id"]) for t in tracks_cache.values() if t["lyrics_available"]]
    lang_cache = language.fetch_api_languages(client, ids_needing_lang, cfg.cache_dir, cfg.lyrics_request_delay)

    rows = report.build_rows(tracks_cache, lang_cache, catalog)
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
    client = make_client(auth.get_token(cfg.token_file))

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)
    lang_cache = language.load_lang_cache(cfg.cache_dir)
    rows = report.build_rows(tracks_cache, lang_cache, catalog)

    apply_mod.apply_classification(client, rows, cfg.apply_request_delay, limit=args.limit)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sort_ym", description="Сортировка лайкнутых треков Яндекс.Музыки по жанру и языку")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="войти через device-flow и сохранить токен")
    sub.add_parser("fetch", help="загрузить лайкнутые треки в локальный кэш")
    sub.add_parser("report", help="посчитать распределение по плейлистам и сохранить out/report.csv (ничего не меняет в аккаунте)")

    p_apply = sub.add_parser("apply", help="создать плейлисты и добавить треки")
    p_apply.add_argument("--yes", action="store_true", help="подтвердить внесение изменений в аккаунт")
    p_apply.add_argument("--limit", type=int, default=None, help="ограничить количество треков (для пробного запуска)")

    args = parser.parse_args(argv)

    commands = {
        "auth": cmd_auth,
        "fetch": cmd_fetch,
        "report": cmd_report,
        "apply": cmd_apply,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
