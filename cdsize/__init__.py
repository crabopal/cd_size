"""Чтение размеров таблиц файловой базы 1С (1Cv8.1CD)."""

from cdsize.reader import Database, FormatError, open_database

__version__ = "0.2.1"

__all__ = ["Database", "FormatError", "open_database", "__version__"]
