"""Свидетели переполнения размера кучи: чистая арифметика C11 (LP64).

Модуль намеренно без внешних зависимостей и без Z3: свидетели детерминированы,
а корректность проверяется численно по правилам стандарта — произведение
считается в 32 битах и усекается в `int`.

Запуск автотеста: python3 tools/_witness.py
"""
from __future__ import annotations

import math

M32 = 1 << 32
I32_MAX = (1 << 31) - 1


def as_int32(v: int) -> int:
    v %= M32
    return v - M32 if v >= (1 << 31) else v


def witness(kind: str = "product", k: int = 1, n_tainted: int = 2, cap=None) -> str:
    """Строка-свидетель или "" если переполнения в такой форме не существует.

    kind        — "product" (a * b * k) или "signed";
    k           — произведение константных множителей выражения;
    n_tainted   — сколько множителей контролируемы извне;
    cap         — потолок источника (побайтовая сборка даёт максимум 65535).
    """
    if k < 1:
        return ""
    limit = min(cap, I32_MAX) if cap else I32_MAX

    # Один контролируемый множитель: malloc(a * k)
    if n_tainted <= 1:
        if k < 2:
            return ""                      # a * 1 схлопнуться не может
        for m in (1, 2, 3):
            a0 = (m * M32 + k - 1) // k
            for a in (a0 - 1, a0, a0 + 1):
                if not 1 <= a <= limit:
                    continue
                total = a * k
                if total < M32:
                    continue
                wrapped = as_int32(total)
                if 0 <= wrapped < 4096:
                    return (f"a={a}: ({a} * {k}) wraps in int32 to {wrapped} bytes "
                            f"(needs {total})")
        return ""

    if kind == "signed" and cap is None:
        a, b = -65536, 65536                 # обход одной верхней границы
        if as_int32(a * b * k) == 0:
            return (f"a={a}, b={b}: negative value bypasses an upper-only bound "
                    f"and wraps mod 2^32 to 0 bytes")

    # Два и более контролируемых множителя. Пересечение кратного m * 2^32
    # происходит при a ~ sqrt(m * 2^32 / k), поэтому семена берём оттуда,
    # плюс потолок источника и классические 2^16.
    seeds = {limit, 65535, 65536}
    if cap:                                  # источник с потолком: смотрим у края
        seeds |= set(range(max(1, limit - 400), limit + 1))
    for m in (1, 2, 3):
        root = math.isqrt(m * M32 // max(k, 1))
        for delta in range(-3, 4):
            seeds.add(root + delta)
    for a in sorted(s for s in seeds if 1 <= s <= limit):
        denom = a * k
        for m in (1, 2, 3):
            b0 = (m * M32 + denom - 1) // denom
            for b in (b0 - 1, b0, b0 + 1):
                if not 1 <= b <= limit:
                    continue
                total = a * b * k
                if total < M32:
                    continue
                wrapped = as_int32(total)
                if 0 <= wrapped < 4096:
                    return (f"a={a}, b={b}: ({a} * {b} * {k}) wraps in int32 to "
                            f"{wrapped} bytes (needs {total})")

    if kind == "signed" and cap is None:
        a, b = -65536, 65536
        total = a * b * k
        if as_int32(total) == 0:
            return (f"a={a}, b={b}: negative value bypasses an upper-only bound "
                    f"and wraps mod 2^32 to 0 bytes")
    return ""


def selftest() -> int:
    bad = 0

    def ok(cond, label):
        nonlocal bad
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            bad += 1

    # 1. два множителя, полный диапазон: 2^16 * 2^16 == 2^32 == 0
    w = witness("product", 1, 2, None)
    ok("a=" in w and "0 bytes" in w, "два множителя: 2^16 * 2^16 даёт 0 байт")

    # 2. u16 + k=3: точного нуля по модулю нет (gcd(3, 2^32) == 1),
    #    но малое усечение есть
    w = witness("product", 3, 2, 65535)
    ok(bool(w) and "to " in w, "u16 + k=3: малое усечение найдено")
    if w:
        import re as _re
        got = int(_re.search(r"to (\d+) bytes", w).group(1))
        ok(0 <= got < 4096, f"u16 + k=3: усечение {got} < 4096 (не 0 — gcd(3, 2^32)=1)")
        a, b = map(int, _re.findall(r"[ab]=(\d+)", w)[:2])
        ok(a <= 65535 and b <= 65535, "u16 + k=3: оба множителя влезают в uint16")
        ok((a * b * 3) % M32 == got, "u16 + k=3: арифметика свидетеля сходится")

    # 3. u16 + k=4: кратность 4 делит 2^32, поэтому достижим ровно 0
    w = witness("product", 4, 2, 65535)
    ok(bool(w) and "to 0 bytes" in w, "u16 + k=4: ровно 0 байт")
    if w:
        a, b = map(int, __import__("re").findall(r"[ab]=(\d+)", w)[:2])
        ok(a <= 65535 and b <= 65535 and (a * b * 4) % M32 == 0,
           "u16 + k=4: множители в uint16 и произведение кратно 2^32")

    # 4. один контролируемый множитель при k=4: a = 2^30
    w = witness("product", 4, 1, None)
    ok("a=1073741824" in w and "to 0 bytes" in w, "один taint + k=4: a = 2^30")

    # 5. один множитель при k=1 не переполняется в принципе
    ok(witness("product", 1, 1, None) == "", "один taint + k=1: свидетеля нет")

    # 6. один множитель при k=3 (нечётный): малое усечение обязано найтись
    w = witness("product", 3, 1, 65535)
    ok(w == "", "один taint + u16 + k=3: 65535*3 << 2^32, свидетеля нет")

    # 7. знаковый обход только верхней границы
    w = witness("signed", 1, 2, None)
    ok("negative" in w and "0 bytes" in w, "signed: обход верхней границы даёт 0 байт")

    # 8. ваши пары из разбора — проверяем арифметикой, не на слово
    print(f"    сверка: 65502*21857*3 % 2^32 = {(65502 * 21857 * 3) % M32}")
    print(f"    сверка: 65527*43700*3 % 2^32 = {(65527 * 43700 * 3) % M32}")
    ok((32768 * 32768 * 4) % M32 == 0, "пара 32768 x 32768 x 4 усекается в 0 байт")

    # 9. большой k без cap: свидетель тоже существует
    ok(bool(witness("product", 12, 2, None)), "k=12 без потолка: свидетель есть")

    print(f"\n[WITNESS-SELFTEST] провалов: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
