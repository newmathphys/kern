"""ШАГ 1, ТЕСТ 2 (НЕГАТИВ): баг ВНУТРИ `helper`.

Контракт `caller` обязан быть ОПРОВЕРГНУТ, причём контрпример обязан быть
ТОЧНЫМ (`n = 1, result = 3`) — это доказывает, что тело `helper` реально
подставлено, а не «угадано».
"""


def helper(x: int) -> int:
    return x * 2 + 1


# @kern:requires n > 0
# @kern:ensures result == n * 2
def caller(n: int) -> int:
    return helper(n)
