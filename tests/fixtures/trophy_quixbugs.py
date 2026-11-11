# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""10 классических пар QuixBugs (buggy, correct) — компактная фикстура Банка.

Это НЕ копия чужого репозитория: функции переписаны по мотивам классических
дефектов QuixBugs (одна строка изменена). 4 КБ, живёт в репозитории —
не зависит от ~/.cache и /tmp.

Каждая пара: (имя, buggy, correct, домен аргументов).
"""
from __future__ import annotations

PAIRS = [
    ("bitcount",
     lambda n: bin(n & (n - 1)).count("1"),
     lambda n: bin(n).count("1"),
     lambda: [(n,) for n in (0, 1, 2, 3, 7)]),
    ("gcd",
     lambda a, b: a if b == 0 else b if a == 0 else None,
     lambda a, b: _gcd(a, b),
     lambda: [(6, 4), (0, 5), (12, 8), (7, 3)]),
    ("to_base",
     lambda n, b: _to_base_bad(n, b),
     lambda n, b: _to_base_ok(n, b),
     lambda: [(0, 2), (1, 2), (10, 2), (255, 16)]),
    ("wrap",
     lambda v, lo, hi: v if lo <= v <= hi else lo,
     lambda v, lo, hi: hi if v > hi else lo if v < lo else v,
     lambda: [(5, 1, 3), (0, 1, 3), (4, 1, 3), (1, 1, 3)]),
    ("find_first_in_sorted",
     lambda arr, x: _ffs(arr, x, True),
     lambda arr, x: _ffs(arr, x, False),
     lambda: [([1, 2, 2, 3], 2), ([1], 1), ([], 5), ([2, 2], 2)]),
    ("get_factors",
     lambda n: [i for i in range(1, n) if n % i == 0],
     lambda n: [i for i in range(1, n + 1) if n % i == 0],
     lambda: [(1,), (2,), (12,), (7,)]),
    ("next_palindrome",
     lambda n: _next_pal_bad(n),
     lambda n: _next_pal_ok(n),
     lambda: [(11,), (99,), (123,), (1001,)]),
    ("rpn_eval",
     lambda toks: _rpn(toks, True),
     lambda toks: _rpn(toks, False),
     lambda: [(["1", "2", "+"],), (["3", "4", "-", "2", "*"],),
              (["5"],), (["2", "3", "^"],)]),
    ("is_valid_parenthesization",
     lambda s: s.count("(") == s.count(")"),
     lambda s: _balanced(s),
     lambda: [("(())",), (")(",), ("(()",), ("",)]),
    ("bucketsort",
     lambda arr: _bucket(arr, True),
     lambda arr: _bucket(arr, False),
     lambda: [([4, 1, 3],), ([0, 0, 0],), ([5, 4, 3, 2, 1],), ([2, 2, 1],)]),
]


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def _to_base_ok(n: int, b: int) -> str:
    digits = "0123456789abcdef"
    if n == 0:
        return "0"
    out = ""
    while n:
        out = digits[n % b] + out
        n //= b
    return out


def _to_base_bad(n: int, b: int) -> str:
    digits = "0123456789abcdef"
    out = ""
    while n:
        out = digits[n % b] + out
        n //= b
    return out          # БАГ: пустая строка для n, а не "0" (и неверно для n=0)


def _ffs(arr, x, bad):
    lo, hi, res = 0, len(arr), -1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            if arr[mid] == x:
                res = mid
            if bad:
                lo = mid + 1        # БАГ: идём вправо -> последнее вхождение
            else:
                hi = mid
    return res


def _is_pal(n: int) -> bool:
    s = str(n)
    return s == s[::-1]


def _next_pal_bad(n: int) -> int:
    # БАГ: если n уже палиндром, возвращает его же (а нужен СЛЕДУЮЩИЙ)
    while not _is_pal(n):
        n += 1
    return n


def _next_pal_ok(n: int) -> int:
    n += 1
    while not _is_pal(n):
        n += 1
    return n


def _rpn(toks, bad):
    st = []
    for t in toks:
        if t in "+-*^":
            b, a = st.pop(), st.pop()
            if t == "+":
                st.append(a + b)
            elif t == "-":
                st.append(a - b)
            elif t == "^":
                st.append(a + b if bad else a ** b)   # БАГ при bad: ^ как +
            else:
                st.append(a * b)
        else:
            st.append(int(t))
    return st[-1] if st else 0


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        d += 1 if ch == "(" else -1 if ch == ")" else 0
        if d < 0:
            return False
    return d == 0


def _bucket(arr, bad):
    if not arr:
        return []
    out = [0] * (max(arr) + 1)
    for v in arr:
        out[v] += 1
    res = []
    for i, c in enumerate(out):
        res.extend([i] * c)
    if bad:
        res.append(0)          # БАГ: лишний нуль в конце
    return res
