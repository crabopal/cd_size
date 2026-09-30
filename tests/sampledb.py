"""Синтетическая файловая база 1CD для проверок. Не копия чужих разборщиков."""

import struct
from pathlib import Path

from cdsize.schema import Field, row_size_candidates

BLOCK = 256


def render_description(name, fields, recordlock, files, pad=0):
    parts = [
        _quote(name),
        "0",
        '{"Fields",' + ",".join(_field(field) for field in fields) + "}",
    ]
    if pad:
        parts.append('{"Indexes","' + ("x" * pad) + '"}')
    else:
        parts.append('{"Indexes"}')
    parts.append('{"Recordlock",' + _quote("1" if recordlock else "0") + "}")
    parts.append('{"Files",%d,%d,%d}' % tuple(files))
    return "{" + ",".join(parts) + "}"


def build_rows(fields, recordlock, flags):
    objects = [
        Field(field[0], field[1], bool(field[2]), field[3], field[4] if len(field) > 4 else 0)
        for field in fields
    ]
    size = row_size_candidates(objects, recordlock)[0]
    data = bytearray(size * len(flags))
    for index, flag in enumerate(flags):
        data[index * size] = flag
    return bytes(data)


def write_database(path, tables, *, version=(8, 3, 8, 0), page_size=None, locale="ru_RU",
                   free_pages=0, fat=None):
    version = tuple(version)
    if len(version) < 4:
        version = version + (0,) * (4 - len(version))
    new = version >= (8, 3, 8)
    if page_size is None:
        page_size = 8192 if new else 4096
    if not new:
        page_size = 4096
    image = _Image(page_size)
    image.add_page()
    image.add_page()
    image.add_page()
    placed = []
    for spec in tables:
        placed.append(_place_table(image, spec, new=new, fat=fat))
    if new:
        _write_new_root(image, placed, locale)
    else:
        _write_old_root(image, placed, locale, version)
    free_numbers = [image.add_page() for _ in range(free_pages)]
    if new:
        _write_free_new(image, 1, free_numbers)
    else:
        _write_free_old(image, 1, free_numbers)
    _write_file_header(image, version, len(image.pages), page_size, new)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for page in image.pages:
            handle.write(page)
    return path


def build_mini(path):
    """Пример 8.3.8: страница 8192, 22 страницы, свободно 2.

    Потоки BLOB и индекса справочника ссылаются на уже занятые страницы
    заголовка файла (свободные страницы и корень). Длины при этом свои,
    содержимое этих потоков программа не читает — только размер.
    Так сумма «на диске» и размер файла сходятся с описанием примера.
    """
    reference_fields = [
        ("_IDRREF", "B", 0, 16, 0, "CS"),
        ("_VERSION", "RV", 0, 0, 0, "CS"),
        ("_DESCRIPTION", "NVC", 0, 10, 0, "CI"),
        ("_FLD8", "I", 1, 0, 0, "CS"),
    ]
    accum_fields = [
        ("_PERIOD", "DT", 0, 0, 0, "CS"),
        ("_RECORDER", "B", 0, 16, 0, "CS"),
    ]
    small = [("_VERSION", "B", 0, 7, 0, "CS")]
    tables = [
        {"name": "IBVERSION", "fields": small, "flags": [1, 0], "blob": b"\x00" * 64},
        {
            "name": "_Reference7",
            "fields": reference_fields,
            "flags": [1, 0, 0, 1],
            "blob": b"\x00" * 512,
            "blob_alias": [1],
            "index": b"\x00" * 100,
            "index_alias": [2],
        },
        {"name": "_Reference7_VT3", "fields": small, "flags": [1, 0]},
        {
            "name": "_AccumRg3",
            "fields": accum_fields,
            "recordlock": True,
            "flags": [1] + [0] * 20,
            "blob": b"\x00" * 64,
            "index": b"\x00" * 4096,
        },
    ]
    return write_database(
        path,
        tables,
        version=(8, 3, 8, 0),
        page_size=8192,
        locale="ru_RU",
        free_pages=2,
    )


class _Image:
    def __init__(self, page_size):
        self.page_size = page_size
        self.pages = []

    def add_page(self, data=b""):
        buf = bytearray(self.page_size)
        raw = bytes(data)
        buf[:min(len(raw), self.page_size)] = raw[:self.page_size]
        self.pages.append(buf)
        return len(self.pages) - 1

    def put(self, index, data):
        buf = bytearray(self.page_size)
        raw = bytes(data)
        buf[:min(len(raw), self.page_size)] = raw[:self.page_size]
        self.pages[index] = buf


def _place_table(image, spec, *, new, fat):
    data = _payload(spec, "data", "flags")
    blob = spec["blob"] if "blob" in spec else None
    index = spec["index"] if "index" in spec else None
    stream_fat = spec.get("fat", fat)
    files = (
        _store_stream(image, data, new=new, fat=spec.get("data_fat", stream_fat), alias=spec.get("data_alias")),
        _store_stream(image, blob, new=new, fat=spec.get("blob_fat", stream_fat), alias=spec.get("blob_alias")),
        _store_stream(image, index, new=new, fat=spec.get("index_fat", stream_fat), alias=spec.get("index_alias")),
    )
    if spec.get("description_bytes") is not None:
        raw = spec["description_bytes"]
    else:
        text = spec.get("description")
        if text is None:
            text = render_description(
                spec["name"],
                spec.get("fields") or [],
                spec.get("recordlock", False),
                files,
                pad=spec.get("pad", 0),
            )
        raw = text.encode(spec.get("encoding", "utf-8"))
        if spec.get("bom"):
            raw = b"\xef\xbb\xbf" + raw
        if spec.get("nul"):
            raw = raw[:1] + b"\x00" + raw[1:]
    return {"raw": raw, "files": files}


def _payload(spec, data_key, flags_key):
    if data_key in spec:
        return spec[data_key]
    if spec.get(flags_key) is not None:
        return build_rows(spec.get("fields") or [], spec.get("recordlock", False), spec[flags_key])
    return None


def _store_stream(image, data, *, new, fat, alias):
    if data is None:
        return 0
    if new:
        return _add_new_object(image, data, fat=fat, alias=alias)
    return _add_old_object(image, data)


def _add_new_object(image, data, *, fat, alias, header_page=None, signature=b"\x1c\xfd"):
    length = len(data)
    if alias is not None:
        data_pages = list(alias)
    else:
        data_pages = []
        for offset in range(0, length, image.page_size):
            data_pages.append(image.add_page(data[offset:offset + image.page_size]))
    slots = (image.page_size - 24) // 4
    use_fat = 1 if (fat is None and len(data_pages) > slots) or fat == 1 else 0
    if fat not in (None, 0, 1):
        use_fat = fat
    if use_fat == 0:
        listed = data_pages
    else:
        per = image.page_size // 4
        listed = []
        source = data_pages or [0]
        if not data_pages:
            source = []
        for offset in range(0, len(source), per):
            chunk = source[offset:offset + per]
            buf = bytearray(image.page_size)
            for index, number in enumerate(chunk):
                struct.pack_into("<I", buf, index * 4, number)
            listed.append(image.add_page(buf))
    header = bytearray(image.page_size)
    header[0:2] = signature
    struct.pack_into("<H", header, 2, use_fat if use_fat in (0, 1) else 1)
    struct.pack_into("<III", header, 4, 1, 1, 1)
    struct.pack_into("<Q", header, 16, length)
    for index, number in enumerate(listed):
        struct.pack_into("<I", header, 24 + index * 4, number)
    if header_page is None:
        return image.add_page(header)
    image.put(header_page, header)
    return header_page


def _add_old_object(image, data, header_page=None, version=1, length_field=None):
    length = len(data) if length_field is None else length_field
    data_pages = []
    if length_field is None:
        for offset in range(0, len(data), image.page_size):
            data_pages.append(image.add_page(data[offset:offset + image.page_size]))
    alloc_count = 0 if length == 0 else (length - 1) // (1023 * image.page_size) + 1
    alloc_pages = []
    rest = list(data_pages)
    for _ in range(alloc_count):
        chunk = rest[:1023]
        rest = rest[1023:]
        buf = bytearray(image.page_size)
        struct.pack_into("<i", buf, 0, len(chunk))
        for index, number in enumerate(chunk):
            struct.pack_into("<I", buf, 4 + index * 4, number)
        alloc_pages.append(image.add_page(buf))
    header = bytearray(image.page_size)
    header[0:8] = b"1CDBOBV8"
    struct.pack_into("<I", header, 8, length)
    struct.pack_into("<I", header, 20, version)
    for index, number in enumerate(alloc_pages):
        struct.pack_into("<I", header, 24 + index * 4, number)
    if header_page is None:
        return image.add_page(header)
    image.put(header_page, header)
    return header_page


def _write_new_root(image, placed, locale):
    blob = _Blob()
    indexes = [blob.add(item["raw"]) for item in placed]
    locale_raw = locale.encode("ascii")[:32].ljust(32, b"\x00")
    directory = locale_raw + struct.pack("<I", len(indexes))
    for index in indexes:
        directory += struct.pack("<I", index)
    blob.put_chain(1, directory)
    _add_new_object(image, blob.bytes(), fat=0, alias=None, header_page=2)


def _write_old_root(image, placed, locale, version):
    locale_len = 8 if version < (8, 1) else 32
    def_pages = []
    for item in placed:
        raw = item["raw"]
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        raw = raw.replace(b"\x00", b"")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1251")
        def_pages.append(_add_old_object(image, text.encode("utf-16-le")))
    body = bytearray(locale_len)
    encoded = locale.encode("ascii")
    body[:len(encoded)] = encoded
    body += struct.pack("<I", len(def_pages))
    for page in def_pages:
        body += struct.pack("<I", page)
    _add_old_object(image, bytes(body), header_page=2, version=1)


def _write_free_new(image, page, numbers):
    header = bytearray(image.page_size)
    header[0:2] = b"\x1c\xff"
    struct.pack_into("<H", header, 2, 0)
    struct.pack_into("<I", header, 4, len(numbers))
    for index, number in enumerate(numbers):
        struct.pack_into("<I", header, 24 + index * 4, number)
    image.put(page, header)


def _write_free_old(image, page, numbers):
    header = bytearray(image.page_size)
    header[0:8] = b"1CDBOBV8"
    struct.pack_into("<I", header, 8, len(numbers))
    struct.pack_into("<I", header, 20, 0)
    image.put(page, header)


def _write_file_header(image, version, page_count, page_size, new):
    header = bytearray(page_size)
    header[0:8] = b"1CDBMSV8"
    header[8:12] = bytes(version[:4])
    struct.pack_into("<I", header, 12, page_count)
    struct.pack_into("<I", header, 16, 1)
    if new:
        struct.pack_into("<I", header, 20, page_size)
    image.put(0, header)


class _Blob:
    def __init__(self):
        self.blocks = [bytearray(BLOCK), bytearray(BLOCK)]

    def add(self, payload):
        return self._append(payload)

    def put_chain(self, start, payload):
        chunks = _chunks(payload)
        ids = [start]
        for _ in chunks[1:]:
            ids.append(len(self.blocks))
            self.blocks.append(bytearray(BLOCK))
        for index, chunk in enumerate(chunks):
            nxt = ids[index + 1] if index + 1 < len(ids) else 0
            self.blocks[ids[index]] = _block(chunk, nxt)

    def bytes(self):
        return b"".join(self.blocks)

    def _append(self, payload):
        chunks = _chunks(payload)
        first = len(self.blocks)
        ids = []
        for _ in chunks:
            ids.append(len(self.blocks))
            self.blocks.append(bytearray(BLOCK))
        for index, chunk in enumerate(chunks):
            nxt = ids[index + 1] if index + 1 < len(ids) else 0
            self.blocks[ids[index]] = _block(chunk, nxt)
        return first


def _chunks(payload):
    payload = bytes(payload)
    if not payload:
        return [b""]
    return [payload[offset:offset + 250] for offset in range(0, len(payload), 250)]


def _block(chunk, nxt):
    block = bytearray(BLOCK)
    struct.pack_into("<I", block, 0, nxt)
    struct.pack_into("<h", block, 4, len(chunk))
    block[6:6 + len(chunk)] = chunk
    return block


def _field(field):
    name, type_name, null_exists, length = field[:4]
    precision = field[4] if len(field) > 4 else 0
    case = field[5] if len(field) > 5 else "CS"
    return "{" + ",".join([
        _quote(name),
        _quote(type_name),
        str(int(bool(null_exists))),
        str(int(length)),
        str(int(precision)),
        _quote(case),
    ]) + "}"


def _quote(text):
    return '"' + str(text).replace('"', '""') + '"'


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "examples" / "mini.1CD"
    build_mini(target)
    print(target, target.stat().st_size)
