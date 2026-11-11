# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ПОЛИГОН: вложенный цикл МЕНЯЕТ переменную контракта (счётчик простых)
# (форма sieve_of_eratosthenes, где внутренний for ставит sieve[i]=False,
#  а внешний считает оставшиеся простые)
# @kern:requires start >= 2 and end >= start
# @kern:invariant count >= 0 and start >= 2
# @kern:decreases end - start
def count_primes(sieve: list, start: int, end: int) -> int:
    count = 0
    while start <= end:
        for i in range(start * start, end + 1, start):
            if sieve[i]:
                sieve[i] = False
                count = count - 1
        count += 1
        start += 1
    return count
