def bits_len_ok(val: int, len_: int) -> int:
    if val >= 2 ** len_:
        return 0
    return 1
