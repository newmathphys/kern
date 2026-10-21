# Источник: boltons/mathutils.py::clamp (github.com/mahmoud/boltons), целочисленная адаптация.
# @kern:requires lo <= hi
# @kern:ensures result >= lo and result <= hi
def clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))
