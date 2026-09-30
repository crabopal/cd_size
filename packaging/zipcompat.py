"""Архивы, которые проводник Windows показывает непустыми."""

import zipfile
from pathlib import Path

_DOS_DIR = 0x10
_DOS_FILE = 0x20
_DIR_MODE = 0o40755


def pack_directory(archive_path, source_dir, *, create_system, executables=()):
    """Кладёт дерево в корень архива.

    create_system=0 — Windows, create_system=3 — Unix (unzip сохраняет бит выполнения).
    У каталога отдельная запись с именем на «/», DOS-атрибут 0x10 и режим 0o40755.
    У файла DOS-атрибут 0x20 и Unix-режим в старших 16 битах external_attr.
    """
    source_dir = Path(source_dir)
    executable_names = {name.replace("\\", "/") for name in executables}
    directories = set()
    files = []
    for path in source_dir.rglob("*"):
        relative = path.relative_to(source_dir).as_posix()
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            files.append((path, relative))
            parent = Path(relative).parent.as_posix()
            while parent not in ("", "."):
                directories.add(parent)
                parent = Path(parent).parent.as_posix()
    archive_path = Path(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for directory in sorted(directories):
            _write(archive, directory + "/", b"", create_system=create_system, mode=_DIR_MODE, dos=_DOS_DIR)
        for path, relative in sorted(files, key=lambda item: item[1]):
            mode = 0o100755 if relative in executable_names else 0o100644
            _write(archive, relative, path.read_bytes(), create_system=create_system, mode=mode, dos=_DOS_FILE)


def _write(archive, name, data, *, create_system, mode, dos):
    info = zipfile.ZipInfo(name)
    info.create_system = create_system
    info.external_attr = (mode << 16) | dos
    info.compress_type = zipfile.ZIP_DEFLATED
    info.date_time = (2026, 9, 30, 12, 0, 0)
    if name.endswith("/"):
        info.external_attr = (_DIR_MODE << 16) | _DOS_DIR
    archive.writestr(info, data)
