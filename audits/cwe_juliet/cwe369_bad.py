"""CWE-369 Divide By Zero (NIST Juliet-style `bad` twin).

Настоящий дефект: предусловия `b != 0` НЕТ, поэтому вызов с `b = 0`
приводит к делению на ноль.
"""

# @kern:ensures result == a // b
def div_bad(a: int, b: int) -> int:
    return a // b
