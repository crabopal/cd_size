"""Текст, JSON и HTML по размерам таблиц."""

import html
import json

from cdsize import __version__

COLUMNS = (
    ("name", "таблица"),
    ("purpose", "назначение"),
    ("occupied", "занято"),
    ("total", "всего"),
    ("data", "данные"),
    ("blob", "BLOB"),
    ("index", "индексы"),
    ("stream", "поток"),
    ("disk", "на диске"),
)


def format_size(value):
    if value is None:
        return ""
    number = int(value)
    if number < 1024:
        return f"{number} Б"
    scaled = float(number)
    for unit in ("КБ", "МБ", "ГБ", "ТБ"):
        scaled /= 1024.0
        if scaled < 1024.0 or unit == "ТБ":
            if abs(scaled - round(scaled)) < 1e-9:
                return f"{int(round(scaled))} {unit}"
            return f"{scaled:.1f} {unit}"
    return f"{number} Б"


def select_tables(database, sort="size", match=None, limit=None):
    rows = list(database.tables)
    if match:
        needle = match.casefold()
        rows = [row for row in rows if needle in row.name.casefold()]
    rows.sort(key=lambda row: _sort_key(row, sort))
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def totals_of(rows):
    def nullable(values):
        if not values or all(value is None for value in values):
            return None
        return sum(value or 0 for value in values)

    return {
        "occupied": nullable([row.occupied for row in rows]),
        "total": nullable([row.total for row in rows]),
        "data": sum(row.data for row in rows),
        "blob": sum(row.blob for row in rows),
        "index": sum(row.index for row in rows),
        "stream": sum(row.stream for row in rows),
        "disk": sum(row.disk for row in rows),
    }


def render_text(database, sort="size", match=None, limit=None):
    rows = select_tables(database, sort=sort, match=match, limit=limit)
    totals = totals_of(rows)
    lines = [
        f"cdsize {__version__}",
        f"Файл: {database.path}",
        f"Формат: {database.format_text}",
        f"Страница: {database.page_size}",
        f"Локаль: {database.locale or '—'}",
        (
            f"Страниц: {database.page_count} ({format_size(database.file_size)}), "
            f"свободно: {database.free_pages}"
        ),
    ]
    if database.warnings:
        lines.append("Предупреждения:")
        lines.extend(f"  {warning}" for warning in database.warnings)
    lines.append("")
    prepared = [_text_cells(row) for row in rows]
    prepared.append(_total_cells(totals))
    widths = [len(title) for _, title in COLUMNS]
    for cells in prepared:
        for index, cell in enumerate(cells):
            widths[index] = max(widths[index], len(cell))
    header = _join([title for _, title in COLUMNS], widths)
    lines.append(header)
    lines.append(_join(["-" * width for width in widths], widths, fill="-"))
    for cells in prepared[:-1]:
        lines.append(_join(cells, widths))
    lines.append(_join(prepared[-1], widths))
    return "\n".join(lines) + "\n"


def render_json(database, sort="size", match=None, limit=None):
    rows = select_tables(database, sort=sort, match=match, limit=limit)
    payload = {
        "product": "cdsize",
        "version": __version__,
        "path": database.path,
        "format": list(database.version),
        "format_text": database.format_text,
        "page_size": database.page_size,
        "pages": database.page_count,
        "file_size": database.file_size,
        "free_pages": database.free_pages,
        "locale": database.locale,
        "warnings": list(database.warnings),
        "tables": [_json_table(row) for row in rows],
        "totals": totals_of(rows),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_html(database, sort="size", match=None, limit=None):
    rows = select_tables(database, sort=sort, match=match, limit=limit)
    totals = totals_of(rows)
    body_rows = []
    for row in rows:
        cells = _html_cells(row)
        body_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    total_cells = _html_total(totals)
    warnings = ""
    if database.warnings:
        items = "".join(f"<li>{html.escape(item)}</li>" for item in database.warnings)
        warnings = f"<ul class=\"warnings\">{items}</ul>"
    headers = "".join(f"<th>{html.escape(title)}</th>" for _, title in COLUMNS)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>cdsize — {html.escape(database.path)}</title>
<style>
body {{ margin: 24px; font: 15px/1.45 "Segoe UI", "Liberation Sans", sans-serif; color: #1c1915; background: #f4f1ea; }}
h1 {{ font-size: 22px; margin: 0 0 8px; }}
.meta {{ color: #4a453c; margin-bottom: 16px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; }}
th, td {{ border-bottom: 1px solid #e4ddd0; padding: 6px 8px; text-align: left; }}
th {{ background: #efeae1; }}
td:nth-child(n+3), th:nth-child(n+3) {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.total td {{ font-weight: 650; }}
.warnings {{ color: #8c2f2f; }}
</style>
</head>
<body>
<h1>cdsize {html.escape(__version__)}</h1>
<p class="meta">Файл: {html.escape(database.path)}<br>
Формат {html.escape(database.format_text)}, страница {database.page_size}, локаль {html.escape(database.locale or "—")}<br>
Страниц: {database.page_count} ({html.escape(format_size(database.file_size))}), свободно: {database.free_pages}</p>
{warnings}
<table>
<thead><tr>{headers}</tr></thead>
<tbody>
{"".join(body_rows)}
<tr class="total">{"".join(f"<td>{cell}</td>" for cell in total_cells)}</tr>
</tbody>
</table>
</body>
</html>
"""


def _sort_key(row, sort):
    if sort == "name":
        return (row.name.casefold(),)
    if sort == "records":
        return (row.occupied is None, -(row.occupied or 0), row.name.casefold())
    return (-row.disk, -row.stream, row.name.casefold())


def _text_cells(row):
    return [
        row.name,
        row.purpose,
        _count(row.occupied),
        _count(row.total),
        format_size(row.data),
        format_size(row.blob),
        format_size(row.index),
        format_size(row.stream),
        format_size(row.disk),
    ]


def _total_cells(totals):
    return [
        "итого",
        "",
        _count(totals["occupied"]),
        _count(totals["total"]),
        format_size(totals["data"]),
        format_size(totals["blob"]),
        format_size(totals["index"]),
        format_size(totals["stream"]),
        format_size(totals["disk"]),
    ]


def _html_cells(row):
    return [html.escape(cell) for cell in _text_cells(row)]


def _html_total(totals):
    return [html.escape(cell) for cell in _total_cells(totals)]


def _json_table(row):
    return {
        "name": row.name,
        "purpose": row.purpose,
        "occupied": row.occupied,
        "total": row.total,
        "data": row.data,
        "blob": row.blob,
        "index": row.index,
        "stream": row.stream,
        "disk": row.disk,
    }


def _count(value):
    return "" if value is None else str(value)


def _join(cells, widths, fill=" "):
    parts = []
    for index, cell in enumerate(cells):
        if index >= 2:
            parts.append(cell.rjust(widths[index], fill))
        else:
            parts.append(cell.ljust(widths[index], fill))
    return "  ".join(parts)
