"""CWE-787 Out-of-bounds Write (Juliet-style `good` twin).

Исправление: индекс проверяется ДО записи, поэтому на пути записи обязательство
`0 <= i < 8` выполнено и находок быть НЕ должно.
"""

# @kern:len(data) = 8
def write_good(data, i, v):
    if 0 <= i < 8:
        data[i] = v
    return 0
