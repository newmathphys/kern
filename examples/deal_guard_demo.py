# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 4 / ДЕФЕКТ #351: ПРЕДУСЛОВИЕ-ДЕКОРАТОР — такой же ГАРД, как `if`.
#
# Проверка ДВУСТОРОННЯЯ (урок #178): под предусловием обвинять НЕЛЬЗЯ, а без
# него — ОБЯЗАНО. Иначе детектор либо слеп, либо генерирует ложные тревоги.
import deal


@deal.pre(lambda a, b: b != 0)
def div_guarded(a: int, b: int) -> int:
    return a // b          # b != 0 гарантировано ДЕКОРАТОРОМ -> находки быть НЕ должно


@deal.pre(lambda a, b: b != 0)
def div_guarded_nested(a: int, b: int) -> int:
    if a < 0:
        return 0
    return a // b          # тот же декоратор + ветвление -> тоже НЕ обвинять


def div_unguarded(a: int, b: int) -> int:
    return a // b          # БЕЗ гарда -> деление на ноль ВОЗМОЖНО (контроль)
