"""Разбор скобочной сериализации 1С (не JSON)."""


class BraceError(Exception):
    """Текст описания не является скобочной сериализацией."""


def parse_brace(text):
    parser = _Parser(text)
    value = parser.parse_value()
    parser.skip()
    if not parser.eof():
        raise BraceError("после значения есть лишние данные")
    return value


class _Parser:
    def __init__(self, text):
        self.text = text
        self.i = 0
        self.n = len(text)

    def eof(self):
        return self.i >= self.n

    def skip(self):
        text = self.text
        i = self.i
        n = self.n
        while i < n and text[i] in " \t\r\n":
            i += 1
        self.i = i

    def parse_value(self):
        self.skip()
        if self.eof():
            raise BraceError("неожиданный конец")
        char = self.text[self.i]
        if char == "{":
            return self.parse_list()
        if char == '"':
            return self.parse_string()
        if char in ",}":
            return None
        return self.parse_atom()

    def parse_list(self):
        self.i += 1
        items = []
        while True:
            self.skip()
            if self.eof():
                raise BraceError("список не закрыт")
            if self.text[self.i] == "}":
                self.i += 1
                return items
            if self.text[self.i] == ",":
                items.append(None)
                self.i += 1
                continue
            items.append(self.parse_value())
            self.skip()
            if self.eof():
                raise BraceError("список не закрыт")
            if self.text[self.i] == ",":
                self.i += 1
                continue
            if self.text[self.i] == "}":
                self.i += 1
                return items
            raise BraceError("ожидалась запятая или конец списка")

    def parse_string(self):
        self.i += 1
        text = self.text
        n = self.n
        out = []
        while self.i < n:
            char = text[self.i]
            if char == '"':
                if self.i + 1 < n and text[self.i + 1] == '"':
                    out.append('"')
                    self.i += 2
                    continue
                self.i += 1
                return "".join(out)
            out.append(char)
            self.i += 1
        raise BraceError("строка не закрыта")

    def parse_atom(self):
        text = self.text
        n = self.n
        start = self.i
        while self.i < n and text[self.i] not in " \t\r\n{},":
            self.i += 1
        token = text[start:self.i]
        if not token:
            raise BraceError("пустое значение")
        if _is_int(token):
            return int(token)
        return token


def _is_int(token):
    if token[0] == "-":
        return len(token) > 1 and token[1:].isdigit()
    return token.isdigit()
