"""CWE-125/CWE-193 `good` twin: правильные гарды по границам (тот же код
плюс защита), поэтому обвинения быть НЕ ДОЛЖНО."""

# @kern:len(data) = 8
def read_good(data, i):
    if i < 0:
        return 0
    if i >= 8:
        return 0
    return data[i]
