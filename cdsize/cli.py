"""Командная строка cdsize."""

import argparse
import sys

from cdsize import __version__
from cdsize.app import DEFAULT_PORT, serve
from cdsize.reader import FormatError, open_database
from cdsize.report import render_html, render_json, render_text


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cdsize",
        description="Размеры таблиц файловой базы 1С (1Cv8.1CD). Только чтение.",
    )
    parser.add_argument("path", nargs="?", help="файл 1Cv8.1CD или каталог базы")
    parser.add_argument("--json", action="store_true", help="отчёт в JSON")
    parser.add_argument("--html", action="store_true", help="отчёт в HTML")
    parser.add_argument("--sort", choices=("size", "name", "records"), default="size", help="порядок строк")
    parser.add_argument("--match", help="оставить таблицы, в имени которых есть эта строка")
    parser.add_argument("--limit", type=int, help="не больше N таблиц")
    parser.add_argument("--no-records", action="store_true", help="не считать занятые строки")
    parser.add_argument("--version", action="store_true", help="показать версию")
    parser.add_argument("--app", action="store_true", help="открыть локальное окно")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт окна (по умолчанию 47321)")
    return parser


def main(argv=None):
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"cdsize {__version__}")
        return 0
    if _open_window(args):
        try:
            return serve(port=args.port, open_browser=not args.no_browser, initial_path=args.path)
        except OSError as exc:
            print(f"cdsize: {exc}", file=sys.stderr)
            return 2
    if not args.path:
        print("cdsize: для отчёта нужен путь к 1Cv8.1CD или каталогу базы", file=sys.stderr)
        return 2
    try:
        database = open_database(args.path, count_records=not args.no_records)
    except FormatError as exc:
        print(f"cdsize: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"cdsize: {exc}", file=sys.stderr)
        return 2
    kwargs = {"sort": args.sort, "match": args.match, "limit": args.limit}
    if args.json:
        sys.stdout.write(render_json(database, **kwargs))
    elif args.html:
        sys.stdout.write(render_html(database, **kwargs))
    else:
        sys.stdout.write(render_text(database, **kwargs))
    return 0


def _open_window(args):
    if args.app:
        return True
    if args.path:
        return False
    report = bool(args.json or args.html or args.match or args.limit is not None or args.no_records)
    return not report


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
