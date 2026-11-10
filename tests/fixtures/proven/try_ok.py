# try с тривиальным обработчиком (звукое подмножество)
# @kern:requires 0 <= i and i <= n
# @kern:invariant 0 <= i and i <= n
# @kern:decreases n - i
def try_ok(n: int, i: int) -> int:
    s = 0
    while i < n:
        try:
            s += 1
        except ValueError:
            pass
        i += 1
    return s
