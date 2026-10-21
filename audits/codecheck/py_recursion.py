# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""CORPUS boundary: recursion is outside the supported subset.
Expected verdict: N (UNKNOWN/SKIP), never F."""


# @kern:requires n >= 0 and n <= 20
# @kern:ensures result >= 0
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
