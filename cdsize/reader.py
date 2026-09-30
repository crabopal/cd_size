"""Чтение файловой базы 1Cv8.1CD через mmap. Файл только читается."""

import mmap
import struct
from pathlib import Path

from cdsize.brace import BraceError
from cdsize.schema import choose_row_size, kind_of, parse_table, row_size_candidates

NEW_FORMAT = (8, 3, 8)
PAGE_SIZES = (4096, 8192, 16384, 32768, 65536)
BLOCK_SIZE = 256
BLOCK_DATA = 250
OLD_SIGNATURE = b"1CDBOBV8"
DATA_SIGNATURE = b"\x1c\xfd"
FREE_SIGNATURE = b"\x1c\xff"


class FormatError(Exception):
    """Файл не является базой 1CD или его заголовок повреждён."""


class Database:
    def __init__(self, path, version, page_size, page_count, file_size, free_pages, locale, tables, warnings):
        self.path = str(path)
        self.version = version
        self.page_size = page_size
        self.page_count = page_count
        self.file_size = file_size
        self.free_pages = free_pages
        self.locale = locale
        self.tables = tables
        self.warnings = warnings

    @property
    def format_text(self):
        return ".".join(str(part) for part in self.version)

    @property
    def new_format(self):
        return self.version >= NEW_FORMAT


class TableInfo:
    def __init__(self, name, purpose, occupied, total, data, blob, index, data_disk, blob_disk, index_disk):
        self.name = name
        self.purpose = purpose
        self.occupied = occupied
        self.total = total
        self.data = data
        self.blob = blob
        self.index = index
        self.data_disk = data_disk
        self.blob_disk = blob_disk
        self.index_disk = index_disk

    @property
    def stream(self):
        return self.data + self.blob + self.index

    @property
    def disk(self):
        return self.data_disk + self.blob_disk + self.index_disk


class Stream:
    """Логическая длина и страницы объекта считаются отдельно."""

    def __init__(self, length=0, data_pages=None, alloc_pages=None, present=False):
        self.length = length
        self.data_pages = list(data_pages or [])
        self.alloc_pages = list(alloc_pages or [])
        self.present = present

    def disk_bytes(self, page_size):
        if not self.present:
            return 0
        return (1 + len(self.alloc_pages) + len(self.data_pages)) * page_size


def open_database(path, count_records=True):
    path = resolve_database_path(path)
    try:
        file = open(path, "rb")
    except OSError:
        raise
    try:
        try:
            mapping = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError as exc:
            raise FormatError("файл пуст или не отображается в память") from exc
        try:
            return _read_database(mapping, path, count_records)
        finally:
            mapping.close()
    finally:
        file.close()


def resolve_database_path(path):
    path = Path(path)
    if path.is_dir():
        candidate = path / "1Cv8.1CD"
        if not candidate.is_file():
            raise FormatError(f"в каталоге {path} нет файла 1Cv8.1CD")
        return candidate
    return path


def old_alloc_page_count(length, page_size):
    """Число страниц размещения старого формата. 0 при нулевой длине."""
    if length <= 0:
        return 0
    return (length - 1) // (1023 * page_size) + 1


def _read_database(mapping, path, count_records):
    file_size = len(mapping)
    if file_size < 24:
        raise FormatError("файл короче заголовка")
    if mapping[0:8] != b"1CDBMSV8":
        raise FormatError("неверная сигнатура: ожидается 1CDBMSV8")
    version = tuple(mapping[8:12])
    page_count = struct.unpack_from("<I", mapping, 12)[0]
    new_format = version >= NEW_FORMAT
    if new_format:
        page_size = struct.unpack_from("<I", mapping, 20)[0]
        if page_size not in PAGE_SIZES or page_size & (page_size - 1):
            raise FormatError(f"недопустимый размер страницы: {page_size}")
    else:
        page_size = 4096
    warnings = []
    expected = page_count * page_size
    if page_count == 0 or expected != file_size:
        warnings.append(
            f"число страниц в заголовке ({page_count}) не совпадает с размером файла "
            f"({file_size} байт, страница {page_size})"
        )
    if file_size < page_size * 3:
        raise FormatError("в файле нет страниц корня и свободных страниц")
    free_pages = _read_free_count(mapping, page_size, new_format, warnings)
    if new_format:
        locale, descriptions = _read_new_root(mapping, page_size, warnings)
    else:
        locale_len = 8 if version < (8, 1) else 32
        locale, descriptions = _read_old_root(mapping, page_size, locale_len, warnings)
    tables = []
    for text in descriptions:
        try:
            table = _table_from_description(mapping, page_size, new_format, text, count_records, warnings)
        except (BraceError, FormatError, UnicodeError, ValueError, struct.error) as exc:
            warnings.append(f"ошибка схемы таблицы: {exc}")
            continue
        if table is not None:
            tables.append(table)
    return Database(path, version, page_size, page_count, file_size, free_pages, locale, tables, warnings)


def _read_free_count(mapping, page_size, new_format, warnings):
    offset = page_size
    if new_format:
        signature = bytes(mapping[offset:offset + 2])
        if signature != FREE_SIGNATURE:
            warnings.append("объект свободных страниц без сигнатуры 0xFF1C")
        return struct.unpack_from("<I", mapping, offset + 4)[0]
    signature = bytes(mapping[offset:offset + 8])
    if signature != OLD_SIGNATURE:
        warnings.append("объект свободных страниц без сигнатуры 1CDBOBV8")
        return 0
    version = struct.unpack_from("<I", mapping, offset + 20)[0]
    length = struct.unpack_from("<I", mapping, offset + 8)[0]
    if version != 0:
        warnings.append("у объекта свободных страниц ненулевая версия")
    return length


def _read_new_root(mapping, page_size, warnings):
    stream = _read_object(mapping, 2, page_size, new_format=True, warnings=warnings, what="корень")
    if not stream.present:
        raise FormatError("нет корневого объекта")
    blob = _stream_bytes(mapping, page_size, stream, warnings, "корень")
    directory = _blob_chain(blob, 1, warnings, "каталог")
    if len(directory) < 36:
        raise FormatError("каталог корня короче локали и счётчика")
    locale = _text_bytes(directory[:32])
    count = struct.unpack_from("<I", directory, 32)[0]
    need = 36 + count * 4
    if count > 1_000_000 or len(directory) < need:
        raise FormatError("каталог корня повреждён")
    indexes = struct.unpack_from("<" + "I" * count, directory, 36)
    descriptions = []
    for index in indexes:
        raw = _blob_chain(blob, index, warnings, "описание")
        descriptions.append(_decode_bytes(raw))
    return locale, descriptions


def _read_old_root(mapping, page_size, locale_len, warnings):
    stream = _read_object(mapping, 2, page_size, new_format=False, warnings=warnings, what="корень")
    if not stream.present:
        raise FormatError("нет корневого объекта")
    data = _stream_bytes(mapping, page_size, stream, warnings, "корень")
    if len(data) < locale_len + 4:
        raise FormatError("корень короче локали")
    locale = _text_bytes(data[:locale_len])
    count = struct.unpack_from("<I", data, locale_len)[0]
    offset = locale_len + 4
    if count > 1_000_000 or len(data) < offset + count * 4:
        raise FormatError("корень повреждён")
    pages = struct.unpack_from("<" + "I" * count, data, offset)
    descriptions = []
    for page in pages:
        if not page:
            warnings.append("пустая ссылка на описание таблицы")
            continue
        try:
            stream = _read_object(mapping, page, page_size, new_format=False, warnings=warnings, what="описание")
            raw = _stream_bytes(mapping, page_size, stream, warnings, "описание")
        except FormatError as exc:
            warnings.append(f"ошибка схемы таблицы: {exc}")
            continue
        descriptions.append(_decode_utf16(raw))
    return locale, descriptions


def _table_from_description(mapping, page_size, new_format, text, count_records, warnings):
    cleaned = text.replace("\x00", "").replace("\ufeff", "").strip()
    if not cleaned:
        warnings.append("пустое описание таблицы")
        return None
    try:
        parsed = parse_table(cleaned)
    except BraceError as exc:
        warnings.append(f"ошибка схемы таблицы: {exc}")
        return None
    try:
        data_stream = _maybe_stream(mapping, parsed.data_page, page_size, new_format, warnings, parsed.name, "данные")
        blob_stream = _maybe_stream(mapping, parsed.blob_page, page_size, new_format, warnings, parsed.name, "BLOB")
        index_stream = _maybe_stream(mapping, parsed.index_page, page_size, new_format, warnings, parsed.name, "индексы")
    except FormatError as exc:
        warnings.append(f"{parsed.name}: {exc}")
        return TableInfo(parsed.name, kind_of(parsed.name), None, None, 0, 0, 0, 0, 0, 0)
    occupied, total = _count_rows(mapping, page_size, parsed, data_stream, count_records, warnings)
    return TableInfo(
        parsed.name,
        kind_of(parsed.name),
        occupied,
        total,
        data_stream.length,
        blob_stream.length,
        index_stream.length,
        data_stream.disk_bytes(page_size),
        blob_stream.disk_bytes(page_size),
        index_stream.disk_bytes(page_size),
    )


def _maybe_stream(mapping, page, page_size, new_format, warnings, table, what):
    if not page:
        return Stream()
    return _read_object(mapping, page, page_size, new_format, warnings, f"{table}: {what}")


def _count_rows(mapping, page_size, parsed, stream, count_records, warnings):
    if not count_records:
        return None, None
    candidates = row_size_candidates(parsed.fields, parsed.recordlock)
    if not candidates:
        warnings.append(f"{parsed.name}: неизвестный тип поля, число записей не посчитано")
        return None, None
    if stream.length == 0:
        return 0, 0
    row_size = choose_row_size(candidates, stream.length)
    if row_size is None:
        warnings.append(f"{parsed.name}: длина данных не делится на размер строки")
        return None, None
    total = stream.length // row_size
    occupied = 0
    for index in range(1, total):
        if _row_flag(mapping, page_size, stream, index * row_size) != 1:
            occupied += 1
    return occupied, total


def _row_flag(mapping, page_size, stream, offset):
    page_index = offset // page_size
    if page_index >= len(stream.data_pages):
        return 1
    page = stream.data_pages[page_index]
    position = page * page_size + (offset % page_size)
    if position < 0 or position >= len(mapping):
        return 1
    return mapping[position]


def _read_object(mapping, page, page_size, new_format, warnings, what):
    start = page * page_size
    if page <= 0 or start + 24 > len(mapping):
        raise FormatError(f"{what}: страница объекта вне файла")
    if new_format:
        return _read_new_object(mapping, start, page_size, warnings, what)
    return _read_old_object(mapping, start, page_size, warnings, what)


def _read_new_object(mapping, start, page_size, warnings, what):
    signature = bytes(mapping[start:start + 2])
    if signature not in (DATA_SIGNATURE, FREE_SIGNATURE):
        raise FormatError(f"{what}: неверная сигнатура объекта")
    fat = struct.unpack_from("<H", mapping, start + 2)[0]
    length = struct.unpack_from("<Q", mapping, start + 16)[0]
    slots = (page_size - 24) // 4
    numbers = list(struct.unpack_from("<" + "I" * slots, mapping, start + 24))
    if length == 0:
        return Stream(0, [], [], True)
    data_count = (length + page_size - 1) // page_size
    if fat == 0:
        data_pages = numbers[:data_count]
        alloc_pages = []
    elif fat == 1:
        per_page = page_size // 4
        alloc_count = (data_count + per_page - 1) // per_page
        alloc_pages = numbers[:alloc_count]
        data_pages = []
        for alloc in alloc_pages:
            data_pages.extend(_page_numbers(mapping, alloc, page_size, per_page, warnings, what))
        data_pages = data_pages[:data_count]
    else:
        warnings.append(f"{what}: уровень размещения {fat} не поддерживается")
        return Stream(length, [], [], True)
    if len(data_pages) < data_count:
        warnings.append(f"{what}: число страниц размещения меньше длины потока")
    return Stream(length, data_pages, alloc_pages, True)


def _read_old_object(mapping, start, page_size, warnings, what):
    if bytes(mapping[start:start + 8]) != OLD_SIGNATURE:
        raise FormatError(f"{what}: неверная сигнатура объекта")
    length = struct.unpack_from("<I", mapping, start + 8)[0]
    numbers = list(struct.unpack_from("<" + "I" * 1018, mapping, start + 24))
    alloc_count = old_alloc_page_count(length, page_size)
    if length == 0:
        return Stream(0, [], [], True)
    alloc_pages = numbers[:alloc_count]
    data_count = (length + page_size - 1) // page_size
    data_pages = []
    remaining = data_count
    for alloc in alloc_pages:
        offset = alloc * page_size
        if offset + 4 > len(mapping):
            warnings.append(f"{what}: страница размещения вне файла")
            break
        count = struct.unpack_from("<i", mapping, offset)[0]
        if count < 0:
            count = 0
        count = min(count, 1023, remaining)
        if offset + 4 + count * 4 > len(mapping):
            warnings.append(f"{what}: страница размещения обрезана")
            break
        if count:
            data_pages.extend(struct.unpack_from("<" + "I" * count, mapping, offset + 4))
        remaining -= count
        if remaining <= 0:
            break
    if len(data_pages) < data_count:
        warnings.append(f"{what}: число страниц размещения меньше длины потока")
    return Stream(length, data_pages[:data_count], alloc_pages, True)


def _page_numbers(mapping, page, page_size, count, warnings, what):
    offset = page * page_size
    if page <= 0 or offset + count * 4 > len(mapping):
        warnings.append(f"{what}: страница размещения вне файла")
        return []
    return list(struct.unpack_from("<" + "I" * count, mapping, offset))


def _stream_bytes(mapping, page_size, stream, warnings, what):
    if stream.length == 0:
        return b""
    parts = []
    remaining = stream.length
    for page in stream.data_pages:
        if remaining <= 0:
            break
        offset = page * page_size
        take = min(page_size, remaining)
        if offset < 0 or offset + take > len(mapping):
            warnings.append(f"{what}: страница данных вне файла")
            parts.append(b"\x00" * take)
        else:
            parts.append(mapping[offset:offset + take])
        remaining -= take
    if remaining:
        warnings.append(f"{what}: поток короче объявленной длины")
        parts.append(b"\x00" * remaining)
    return b"".join(parts)


def _blob_chain(blob, start, warnings, what):
    if start <= 0:
        return b""
    parts = []
    seen = set()
    block = start
    limit = max(len(blob) // BLOCK_SIZE, 1)
    while block and block not in seen and len(seen) <= limit:
        seen.add(block)
        offset = block * BLOCK_SIZE
        if offset + 6 > len(blob):
            warnings.append(f"{what}: блок вне потока")
            break
        nxt, length = struct.unpack_from("<Ih", blob, offset)
        if length < 0:
            length = 0
        if length > BLOCK_DATA:
            warnings.append(f"{what}: длина блока больше 250")
            length = BLOCK_DATA
        parts.append(blob[offset + 6:offset + 6 + length])
        block = nxt
    return b"".join(parts)


def _decode_bytes(raw):
    raw = raw.replace(b"\x00", b"")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.startswith(b"\xff\xfe"):
        raw = raw[2:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    return text.replace("\ufeff", "")


def _decode_utf16(raw):
    if raw.startswith(b"\xff\xfe"):
        raw = raw[2:]
    if len(raw) % 2:
        raw = raw[:-1]
    return raw.decode("utf-16-le").replace("\x00", "").replace("\ufeff", "")


def _text_bytes(raw):
    return raw.split(b"\x00", 1)[0].decode("latin1").strip()
