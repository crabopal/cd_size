"""Локальное окно: страница и API только на 127.0.0.1."""

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from cdsize import __version__
from cdsize.reader import FormatError, open_database, resolve_database_path
from cdsize.report import render_html, render_json, render_text

HOST = "127.0.0.1"
DEFAULT_PORT = 47321
PORT_TRIES = 11


def ui_html_path():
    candidates = []
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
        candidates.extend((root / "ui.html", root / "cdsize" / "ui.html"))
    candidates.append(Path(__file__).resolve().parent / "ui.html")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("ui.html")


def load_ui():
    text = ui_html_path().read_text(encoding="utf-8")
    return text.replace("{{VERSION}}", __version__)


def program_home():
    env = os.environ.get("CDSIZE_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def write_address(url):
    folder = program_home()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "адрес.txt").write_text(url + "\n", encoding="utf-8")


def places():
    items = [{"name": "Домашний каталог", "path": str(Path.home())}]
    env = os.environ.get("CDSIZE_HOME")
    if env:
        items.append({"name": "Папка программы", "path": str(Path(env))})
    examples = _examples_dir()
    if examples is not None:
        items.append({"name": "Примеры", "path": str(examples)})
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                items.append({"name": f"Диск {letter}:", "path": str(root)})
    else:
        items.append({"name": "Корень /", "path": "/"})
    return items


def list_directory(path):
    directory = Path(path)
    if not directory.is_dir():
        raise OSError(f"нет каталога {directory}")
    entries = []
    try:
        children = list(directory.iterdir())
    except OSError:
        raise
    for child in children:
        name = child.name
        if name.startswith("."):
            continue
        try:
            if child.is_dir():
                entries.append({
                    "name": name,
                    "path": str(child),
                    "dir": True,
                    "has_db": (child / "1Cv8.1CD").is_file(),
                    "is_1cd": False,
                })
            elif child.is_file():
                is_1cd = child.suffix.lower() == ".1cd"
                entries.append({
                    "name": name,
                    "path": str(child),
                    "dir": False,
                    "has_db": False,
                    "is_1cd": is_1cd,
                })
        except OSError:
            continue
    entries.sort(key=lambda item: (not item["dir"], item["name"].casefold()))
    parent = directory.parent
    parent_path = None if parent == directory else str(parent)
    return {"path": str(directory), "parent": parent_path, "entries": entries}


def inspect_path(path, sort="size", match=None, limit=None, count_records=True):
    database = open_database(resolve_database_path(path), count_records=count_records)
    return json.loads(render_json(database, sort=sort, match=match, limit=limit))


def export_report(path, fmt, sort="size", match=None, limit=None, count_records=True):
    database = open_database(resolve_database_path(path), count_records=count_records)
    if fmt == "json":
        return "application/json; charset=utf-8", render_json(database, sort=sort, match=match, limit=limit).encode("utf-8")
    if fmt == "html":
        return "text/html; charset=utf-8", render_html(database, sort=sort, match=match, limit=limit).encode("utf-8")
    return "text/plain; charset=utf-8", render_text(database, sort=sort, match=match, limit=limit).encode("utf-8")


def create_server(host=HOST, port=DEFAULT_PORT):
    if host != HOST:
        raise OSError("сервер слушает только 127.0.0.1")
    handler = _make_handler()
    attempts = [0] if port == 0 else list(range(port, port + PORT_TRIES))
    error = None
    for candidate in attempts:
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            error = exc
    raise error


def open_window(port=DEFAULT_PORT, open_browser=True, initial_path=None, host=HOST):
    """Поднимает сервер, пишет адрес.txt и при необходимости открывает браузер."""
    server = create_server(host, port)
    actual = server.server_address[1]
    url = f"http://{HOST}:{actual}/"
    if initial_path:
        url += "?open=" + quote(str(initial_path))
    write_address(url)
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    return server, url


def serve(port=DEFAULT_PORT, open_browser=True, initial_path=None, host=HOST):
    server, url = open_window(port=port, open_browser=open_browser, initial_path=initial_path, host=host)
    print(f"cdsize {__version__}: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _examples_dir():
    candidates = []
    env = os.environ.get("CDSIZE_HOME")
    if env:
        candidates.append(Path(env) / "examples")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "examples")
    candidates.append(Path.cwd() / "examples")
    candidates.append(Path(__file__).resolve().parents[1] / "examples")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _make_handler():
    ui = load_ui().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._bytes(200, "text/html; charset=utf-8", ui)
                return
            if parsed.path == "/api/places":
                self._json(200, {"version": __version__, "places": places()})
                return
            if parsed.path == "/api/list":
                self._list(parse_qs(parsed.query))
                return
            if parsed.path == "/api/export":
                self._export(parse_qs(parsed.query))
                return
            self._json(404, {"error": "неизвестный адрес"})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/api/inspect":
                self._json(404, {"error": "неизвестный адрес"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "некорректный JSON"})
                return
            path = payload.get("path") or ""
            if not str(path).strip():
                self._json(400, {"error": "не указан путь к базе"})
                return
            sort = payload.get("sort") or "size"
            match = payload.get("match") or None
            limit = payload.get("limit")
            records = payload.get("records", True)
            try:
                report = inspect_path(path, sort=sort, match=match, limit=limit, count_records=bool(records))
            except (FormatError, OSError) as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, report)

        def _list(self, query):
            raw = _first(query, "path")
            if not raw:
                self._json(400, {"error": "не указан каталог"})
                return
            try:
                payload = list_directory(raw)
            except OSError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, payload)

        def _export(self, query):
            path = _first(query, "path")
            if not path:
                self._json(400, {"error": "не указан путь к базе"})
                return
            fmt = (_first(query, "format") or "text").lower()
            if fmt not in ("text", "json", "html"):
                self._json(400, {"error": "неизвестный формат"})
                return
            sort = _first(query, "sort") or "size"
            match = _first(query, "match") or None
            limit_text = _first(query, "limit")
            limit = int(limit_text) if limit_text else None
            records = (_first(query, "records") or "1") != "0"
            try:
                content_type, body = export_report(path, fmt, sort=sort, match=match, limit=limit, count_records=records)
            except (FormatError, OSError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
                return
            filename = {"text": "cdsize.txt", "json": "cdsize.json", "html": "cdsize.html"}[fmt]
            self._bytes(200, content_type, body, extra={"Content-Disposition": f'attachment; filename="{filename}"'})

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._bytes(status, "application/json; charset=utf-8", body)

        def _bytes(self, status, content_type, body, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _first(query, key):
    values = query.get(key)
    if not values:
        return ""
    return values[0]
