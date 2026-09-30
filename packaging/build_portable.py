"""Сборка портативных архивов Linux и Windows. Windows PE не запускается."""

import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zipcompat import pack_directory
WORK = ROOT / "portable" / "work"
PORTABLE = ROOT / "portable"
EMBED_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
READ_ME = """cdsize 0.2.1
Размеры таблиц файловой базы 1С (файл 1Cv8.1CD). Только чтение, платформа 1С не нужна.
Имена вроде _Reference7 — имена хранения, не синонимы конфигуратора.

Linux
  ./cdsize
  ./cdsize examples/mini.1CD
  ./cdsize examples/mini.1CD --json

Без пути открывается окно в браузере на 127.0.0.1. Консоль для отчёта остаётся в терминале.

Windows
  Двойной щелчок по Запуск.vbs открывает окно и скрывает консоль.
  cdsize.bat без аргументов делает то же самое.
  cdsize.bat examples\\mini.1CD печатает отчёт.
  Отдельного pythonw нет: окно — это браузер.

«Свободно» в шапке — свободные страницы файла, а не удалённые строки.
"""


def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    PORTABLE.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True)
    linux_zip = PORTABLE / "cdsize-linux-x64.zip"
    windows_zip = PORTABLE / "cdsize-windows-x64.zip"
    for path in (linux_zip, windows_zip):
        if path.exists():
            path.unlink()
    build_linux(linux_zip)
    build_windows(windows_zip)
    shutil.rmtree(WORK)
    print(linux_zip)
    print(windows_zip)


def build_linux(archive_path):
    dist = WORK / "pyinstaller"
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller==6.16.0"])
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "cdsize",
        "--distpath", str(dist),
        "--workpath", str(WORK / "pyi-build"),
        "--specpath", str(WORK / "pyi-spec"),
        "--paths", str(ROOT),
        "--add-data", str(ROOT / "cdsize" / "ui.html") + ":cdsize",
        "--collect-submodules", "cdsize",
        str(ROOT / "packaging" / "launcher.py"),
    ], cwd=ROOT)
    stage = WORK / "linux-root"
    stage.mkdir()
    binary = stage / "cdsize"
    shutil.copy2(dist / "cdsize", binary)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    _examples(stage)
    (stage / "ПРОЧТИ.txt").write_text(READ_ME, encoding="utf-8")
    smoke = subprocess.run(
        [str(binary), "examples/mini.1CD", "--limit", "1"],
        cwd=stage,
        check=True,
        capture_output=True,
        text=True,
    )
    if "_AccumRg3" not in smoke.stdout:
        raise SystemExit("дымовая проверка Linux не нашла _AccumRg3")
    pack_directory(archive_path, stage, create_system=3, executables={"cdsize"})
    unpacked = WORK / "linux-unpacked"
    unpacked.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        _check_archive(archive, create_system=3, required={"cdsize", "ПРОЧТИ.txt", "examples/", "examples/mini.1CD"})
        archive.extractall(unpacked)
    extracted = unpacked / "cdsize"
    extracted.chmod(extracted.stat().st_mode | stat.S_IEXEC)
    again = subprocess.run(
        [str(extracted), "examples/mini.1CD", "--limit", "1"],
        cwd=unpacked,
        check=True,
        capture_output=True,
        text=True,
    )
    if "_AccumRg3" not in again.stdout:
        raise SystemExit("распакованный Linux-файл не напечатал _AccumRg3")


def build_windows(archive_path):
    embed_zip = WORK / "python-embed.zip"
    urllib.request.urlretrieve(EMBED_URL, embed_zip)
    stage = WORK / "windows-root"
    python_dir = stage / "python"
    python_dir.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip) as archive:
        archive.extractall(python_dir)
    pth = python_dir / "python312._pth"
    pth.write_bytes(b"python312.zip\r\n.\r\n..\\app\r\nimport site\r\n")
    app = stage / "app" / "cdsize"
    app.parent.mkdir()
    shutil.copytree(ROOT / "cdsize", app, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _examples(stage)
    (stage / "ПРОЧТИ.txt").write_bytes(b"\xef\xbb\xbf" + READ_ME.encode("utf-8"))
    (stage / "Запуск.vbs").write_bytes(_vbs().encode("utf-8"))
    (stage / "cdsize.bat").write_bytes(b"\xef\xbb\xbf" + _bat().encode("utf-8"))
    version = (app / "__init__.py").read_text(encoding="utf-8")
    if '__version__ = "0.2.1"' not in version:
        raise SystemExit("в Windows-копии __version__ не 0.2.1")
    if (python_dir / "python.exe").read_bytes()[:2] != b"MZ":
        raise SystemExit("python.exe не начинается с MZ")
    pth_text = pth.read_text(encoding="utf-8")
    for line in ("python312.zip", ".", r"..\app", "import site"):
        if line not in pth_text.splitlines():
            raise SystemExit(f"в python312._pth нет строки {line}")
    vbs = (stage / "Запуск.vbs").read_text(encoding="utf-8")
    if "WScript.Shell" not in vbs or ", 0, False" not in vbs:
        raise SystemExit("Запуск.vbs не скрывает консоль")
    pack_directory(archive_path, stage, create_system=0)
    with zipfile.ZipFile(archive_path) as archive:
        _check_archive(
            archive,
            create_system=0,
            required={
                "Запуск.vbs",
                "cdsize.bat",
                "ПРОЧТИ.txt",
                "app/",
                "examples/",
                "python/",
                "app/cdsize/__init__.py",
                "examples/mini.1CD",
                "python/python.exe",
                "python/python312._pth",
            },
        )


def _examples(stage):
    target = stage / "examples"
    target.mkdir()
    shutil.copy2(ROOT / "examples" / "mini.1CD", target / "mini.1CD")


def _vbs():
    return (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        "root = fso.GetParentFolderName(WScript.ScriptFullName)\r\n"
        "shell.CurrentDirectory = root\r\n"
        'shell.Run """" & root & "\\python\\python.exe"" -m cdsize --app", 0, False\r\n'
    )


def _bat():
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        'set "ROOT=%~dp0"\r\n'
        'if "%~1"=="" (\r\n'
        '  wscript //nologo "%ROOT%Запуск.vbs"\r\n'
        "  exit /b 0\r\n"
        ")\r\n"
        '"%ROOT%python\\python.exe" -m cdsize %*\r\n'
    )


def _check_archive(archive, *, create_system, required):
    names = set(archive.namelist())
    missing = required - names
    if missing:
        raise SystemExit(f"в архиве нет {sorted(missing)}")
    if any(name.startswith("cdsize-linux") or name.startswith("cdsize-windows") for name in names):
        raise SystemExit("архив обёрнут во внешнюю папку")
    for info in archive.infolist():
        if info.create_system != create_system:
            raise SystemExit(f"{info.filename}: create_system {info.create_system}")
        if info.filename.endswith("/"):
            if info.external_attr & 0xFF != 0x10:
                raise SystemExit(f"{info.filename}: нет DOS-атрибута каталога")
            if (info.external_attr >> 16) != 0o40755:
                raise SystemExit(f"{info.filename}: режим каталога {oct(info.external_attr >> 16)}")
        else:
            if info.external_attr & 0xFF != 0x20:
                raise SystemExit(f"{info.filename}: нет DOS-атрибута файла")
            if info.external_attr == 0x81A40000:
                raise SystemExit(f"{info.filename}: голый external_attr ZipFile.write")


if __name__ == "__main__":
    main()
