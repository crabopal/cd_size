"""Поля таблицы, ширина строки и назначение по имени хранения."""

from cdsize.brace import BraceError, parse_brace

MIN_ROW_SIZE = 5

SERVICE_NAMES = {
    "CONFIG": "конфигурация",
    "CONFIGSAVE": "сохранённая конфигурация",
    "CONFIGCAS": "расширения",
    "PARAMS": "параметры",
    "V8USERS": "пользователи",
    "IBVERSION": "версия ИБ",
    "DBSCHEMA": "схема базы",
    "FILES": "файлы",
    "DBCHANGES": "изменения",
}

# Более длинные префиксы раньше коротких: _AccumRgT раньше _AccumRg, _AccRg раньше _Acc.
PREFIXES = (
    ("_ACCUMRGAGGOPT", "настройки агрегатов"),
    ("_ACCUMRGAGG", "агрегаты"),
    ("_ACCUMRGOPT", "настройки регистра накопления"),
    ("_ACCUMRGST", "настройки регистра накопления"),
    ("_ACCUMRGT", "итоги"),
    ("_ACCUMRG", "регистр накопления"),
    ("_INFORGCHNGR", "изменения регистра сведений"),
    ("_INFORGOPT", "настройки регистра сведений"),
    ("_INFORG", "регистр сведений"),
    ("_ACCRGAT", "итоги регистра бухгалтерии"),
    ("_ACCRGCT", "итоги регистра бухгалтерии"),
    ("_ACCRGED", "итоги регистра бухгалтерии"),
    ("_ACCRGOPT", "настройки регистра бухгалтерии"),
    ("_ACCRG", "регистр бухгалтерии"),
    ("_REFERENCECHNGR", "изменения справочника"),
    ("_REFERENCE", "справочник"),
    ("_DOCUMENTJOURNAL", "журнал документов"),
    ("_DOCUMENTCHNGR", "изменения документа"),
    ("_DOCUMENT", "документ"),
    ("_ENUM", "перечисление"),
    ("_CONSTCHNGR", "изменения константы"),
    ("_CONST", "константа"),
    ("_NODECHNGR", "изменения плана обмена"),
    ("_NODE", "план обмена"),
    ("_CHRCCHNGR", "изменения плана видов характеристик"),
    ("_CHRC", "план видов характеристик"),
    ("_CALCKIND", "план видов расчёта"),
    ("_CKIND", "план видов расчёта"),
    ("_CALCCHNGR", "изменения плана видов расчёта"),
    ("_ACCCHNGR", "изменения плана счетов"),
    ("_ACC", "план счетов"),
    ("_SEQ", "последовательность"),
    ("_TASK", "задача"),
    ("_BPROUTEPOINT", "точка маршрута"),
    ("_BPROUTE", "бизнес-процесс"),
    ("_SCHEDULE", "график"),
    ("_YEAROFFSET", "смещение дат"),
)


class Field:
    def __init__(self, name, type_name, null_exists, length, precision=0, case_sensitive=""):
        self.name = name
        self.type_name = type_name
        self.null_exists = bool(null_exists)
        self.length = length
        self.precision = precision
        self.case_sensitive = case_sensitive

    def __repr__(self):
        return f"Field({self.name!r}, {self.type_name!r}, null={self.null_exists}, len={self.length})"


class TableDescription:
    def __init__(self, name, fields, recordlock, files):
        self.name = name
        self.fields = fields
        self.recordlock = recordlock
        self.data_page, self.blob_page, self.index_page = files

    def __repr__(self):
        return f"TableDescription({self.name!r}, fields={len(self.fields)})"


def kind_of(name):
    """Назначение по префиксу имени хранения, не по синониму конфигуратора."""
    if not name:
        return ""
    upper = name.upper()
    if upper in SERVICE_NAMES:
        return SERVICE_NAMES[upper]
    if "_VT" in upper:
        return "табличная часть"
    for prefix, label in PREFIXES:
        if upper.startswith(prefix):
            return label
    return ""


def field_width(type_name, length, null_exists):
    """Ширина поля в байтах. None — тип неизвестен, число записей не считать."""
    kind = (type_name or "").upper()
    extra = 1 if null_exists else 0
    if kind == "B":
        return extra + int(length)
    if kind == "L":
        return extra + 1
    if kind == "N":
        return extra + (int(length) + 2) // 2
    if kind == "NC":
        return extra + int(length) * 2
    if kind == "NVC":
        return extra + int(length) * 2 + 2
    if kind == "RV":
        return extra + 16
    if kind == "NT":
        return extra + 8
    if kind == "I":
        return extra + 8
    if kind == "DT":
        return extra + 7
    return None


def row_size_candidates(fields, recordlock):
    """Кандидаты длины строки. При Recordlock без RV первый — со скрытыми 8 байтами."""
    total = 1
    has_rv = False
    for field in fields:
        width = field_width(field.type_name, field.length, field.null_exists)
        if width is None:
            return []
        total += width
        if field.type_name.upper() == "RV":
            has_rv = True
    if recordlock and not has_rv:
        return [_at_least_5(total + 8), _at_least_5(total)]
    return [_at_least_5(total)]


def choose_row_size(candidates, data_length):
    """Первый кандидат, нацело делящий длину данных. Основной идёт раньше запасного."""
    if not candidates:
        return None
    if not data_length:
        return candidates[0]
    for size in candidates:
        if size and data_length % size == 0:
            return size
    return None


def parse_table(text):
    data = parse_brace(text)
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        raise BraceError("описание таблицы без имени")
    name = data[0]
    fields = []
    recordlock = False
    files = [0, 0, 0]
    for item in data[1:]:
        if not isinstance(item, list) or not item:
            continue
        key = item[0]
        if not isinstance(key, str):
            continue
        if key == "Fields":
            for raw in item[1:]:
                field = _parse_field(raw)
                if field is not None:
                    fields.append(field)
        elif key == "Recordlock":
            recordlock = _is_one(item[1]) if len(item) > 1 else False
        elif key == "Files":
            for index in range(3):
                if index + 1 < len(item):
                    files[index] = _as_int(item[index + 1])
    return TableDescription(name, fields, recordlock, tuple(files))


def _parse_field(raw):
    if not isinstance(raw, list) or len(raw) < 4:
        return None
    name = raw[0] if isinstance(raw[0], str) else str(raw[0])
    type_name = raw[1] if isinstance(raw[1], str) else str(raw[1])
    null_exists = _is_one(raw[2])
    length = _as_int(raw[3])
    precision = _as_int(raw[4]) if len(raw) > 4 else 0
    case_sensitive = raw[5] if len(raw) > 5 and isinstance(raw[5], str) else ""
    return Field(name, type_name, null_exists, length, precision, case_sensitive)


def _is_one(value):
    if isinstance(value, str):
        return value.strip() == "1"
    return value == 1 or value is True


def _as_int(value):
    if value is None or value is True or value is False:
        return int(value or 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _at_least_5(size):
    return size if size >= MIN_ROW_SIZE else MIN_ROW_SIZE
