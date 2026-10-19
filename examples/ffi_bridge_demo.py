# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 29: межъязыковой мост FFI (`@kern:calls_i32` / `@kern:calls_u32`).
# Значение из языка с произвольной точностью (Python) или 53-битным float (JS/TS)
# уходит в C-ABI (`libkern.so` / Zig / Rust), где тип ИМЕЕТ конечную разрядность.
# Ожидания приёмки (`make ffi-bridge-check`):
#   REFUTED: to_c_u32_unsafe (без клеммы -> усечение),
#   PROVEN : to_c_u32_safe, to_c_i32_safe (клемма внутри границ типа).


# @kern:calls_u32
def to_c_u32_unsafe(x):
    return x * 1000000


# @kern:calls_u32
def to_c_u32_safe(x):
    if x < 0:
        return 0
    if x > 4294:
        return 4294
    return x * 1000000


# @kern:calls_i32
def to_c_i32_safe(x):
    if x < -2147:
        return -2147483648
    if x > 2147:
        return 2147483647
    return x * 1000000
