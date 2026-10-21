def clamp_int(x: int, lo: int, hi: int) -> int:
    if lo > hi:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
