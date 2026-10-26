"""ШАГ 1, ТЕСТ 1 (ПОЗИТИВ): `caller` зовёт `helper` из того же файла.

До инлайнинга вызов уходил в `_havoc` (свежий символ) -> контракт не доказывался.
После: тело `helper` подставляется, и контракт ДОКАЗЫВАЕТСЯ.
"""


def helper(x: int) -> int:
    return x * 2


# @kern:requires n > 0
# @kern:ensures result == n * 2
def caller(n: int) -> int:
    return helper(n)
