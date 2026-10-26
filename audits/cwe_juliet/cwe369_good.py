"""CWE-369 `good` twin: правильный гард `b != 0` делает деление безопасным."""

# @kern:requires b != 0
# @kern:ensures result == a // b
def div_good(a: int, b: int) -> int:
    return a // b
