# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Минимальный пример: как ЗАКОН превращается в доказательство или в число.

Функция взята из реального проекта (`darshi1337/apogee`, MIT):
`apogee-extension/lib/summarize/mapReduce.js: pickFanIn` —
`Math.max(2, Math.ceil(partialCount / maxChunks))`, в комментарии контракт
«Caller guarantees partialCount > maxChunks».

ЗАКОН — это два комментария над функцией:
    # @kern:requires  <что верно на входе>
    # @kern:ensures   <что обязано быть на выходе>
Дальше KERN сам решает: доказать или найти число, на котором закон ломается.
"""


# ПРАВИЛЬНЫЙ закон: веер не меньше 2 и не больше числа кусков.
# @kern:requires partial_count > max_chunks and max_chunks >= 1
# @kern:ensures  result >= 2 and result <= partial_count
def pick_fan_in(partial_count: int, max_chunks: int) -> int:
    fan = (partial_count + max_chunks - 1) // max_chunks   # ceil(p / m)
    return fan if fan > 2 else 2


# ЛОЖНЫЙ закон: будто веер никогда не превышает число кусков.
# Такой закон ОБЯЗАН быть опровергнут конкретным входом — иначе доверия нет.
# @kern:requires partial_count > max_chunks and max_chunks >= 1
# @kern:ensures  result <= max_chunks
def pick_fan_in_wrong_law(partial_count: int, max_chunks: int) -> int:
    fan = (partial_count + max_chunks - 1) // max_chunks
    return fan if fan > 2 else 2
