# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Законы на РЕАЛЬНЫЕ функции из чужих репозиториев (проверка ценности KERN).

Источники (транскрипция в подмножество, арифметика сохранена дословно):
  * `darshi1337/apogee`  — `apogee-extension/lib/summarize/mapReduce.js:pickFanIn`
      `Math.max(2, Math.ceil(partialCount / maxChunks))`, контракт в комментарии:
      «Caller guarantees partialCount > maxChunks»;
  * `emieks/pencil-puzzles` — `crates/core/src/grid.rs` (индекс ячейки `r * cols + c`);
  * `MossabArektout/archetype-py` — счётчики нарушений в `archetype/check.py`.
"""


# --- apogee: pickFanIn ------------------------------------------------------
# @kern:requires partial_count > max_chunks and max_chunks >= 1
# @kern:ensures  result >= 2 and result <= partial_count
def pick_fan_in(partial_count: int, max_chunks: int) -> int:
    fan = (partial_count + max_chunks - 1) // max_chunks
    return fan if fan > 2 else 2


# ЗАВЕДОМО СЛИШКОМ СИЛЬНЫЙ закон: требует, чтобы веер не превышал max_chunks.
# Такой закон обязан БЫТЬ ОПРОВЕРГНУТ с конкретными числами — иначе чекер
# «доказывает» что угодно.
# @kern:requires partial_count > max_chunks and max_chunks >= 1
# @kern:ensures  result <= max_chunks
def pick_fan_in_too_strong(partial_count: int, max_chunks: int) -> int:
    fan = (partial_count + max_chunks - 1) // max_chunks
    return fan if fan > 2 else 2


# --- pencil-puzzles: индекс ячейки -----------------------------------------
# @kern:requires rows > 0 and cols > 0 and r < rows and c < cols
# @kern:ensures  result >= 0 and result < rows * cols
def cell_index(rows: int, cols: int, r: int, c: int) -> int:
    return r * cols + c


# --- archetype-py: сумма нарушений -----------------------------------------
# @kern:requires a >= 0 and b >= 0
# @kern:ensures  result >= a and result >= b
def violations_total(a: int, b: int) -> int:
    return a + b
