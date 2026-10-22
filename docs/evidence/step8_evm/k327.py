# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def ternary_guarded(a: int, b: int) -> int:
    return 0 if b == 0 else a // b

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def if_guarded(a: int, b: int) -> int:
    if b == 0:
        return 0
    return a // b
