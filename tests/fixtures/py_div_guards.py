# KERN fixture for defect #327 — division guards in Python.
#
# Before the fix the divisor obligation was built WITHOUT path conditions, so a
# division guarded by a ternary or an `if` was still accused:
#
#     def f(a, b):
#         return 0 if b == 0 else a // b     # guard is explicit
#     [FAIL] f: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b)  counterexample b = 0
#
# Now the active guard is stored WITH the divisor and the obligation becomes
# `(and <guards> (= divisor 0))`, so Z3 answers UNSAT for a real guard.
#
# The fixture also pins the SOUNDNESS side: a guard that does NOT imply
# `b != 0` (`if a > 0`) must keep the accusation alive. A guard that silences
# every division would be a false negative — worse than the original bug.

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def unguarded(a: int, b: int) -> int:
    return a // b  # must be REFUTED (b = 0)

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def ternary_guard(a: int, b: int) -> int:
    return 0 if b == 0 else a // b  # must be PROVEN (guard in the ternary)

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def if_guard(a: int, b: int) -> int:
    if b == 0:
        return 0
    return a // b  # must be PROVEN (guard is a statement)

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def wrong_guard(a: int, b: int) -> int:
    if a > 0:
        return a // b  # must be REFUTED: `a > 0` says nothing about `b`
    return 0

# @kern:requires a >= 0 and b >= 0
# @kern:ensures result >= 0
def sufficient_guard(a: int, b: int) -> int:
    if b > 0:
        return a // b  # must be PROVEN: `b > 0` implies `b != 0`
    return 0
