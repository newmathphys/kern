#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the KERN Source License (see LICENSE).
"""ВОРОНКА `--xray` КАК СПЕЦИФИКАЦИЯ, КОТОРУЮ ДОКАЗЫВАЕТ САМ KERN.

ЧТО ЭТО. Учёт воронки (`checked` / `trivial` / `skipped` / `total` и «пропуски
без записанной причины») вынесен в ЧИСТЫЕ функции с контрактами
`# @kern:requires` / `# @kern:ensures`. Их проверяет ТОТ ЖЕ движок, которым
проект проверяет чужой код (`tools/kern_contracts.py` + Z3), а гейт
`tools/funnel_contract_check.py` требует, чтобы (а) все функции были ДОКАЗАНЫ,
(б) ослабленные двойники были ОПРОВЕРГНУТЫ (иначе доказательство вакуумно) и
(в) инварианты сходились на ИЗМЕРЕННЫХ числах корпусов.

ПОЧЕМУ ЭТО НУЖНО (дефекты #405/#407.2; измерено на `d98953c`):
  * `--xray` печатал «пропусков БЕЗ записанной причины: -6»: `named` суммировал
    причины уровня ВЕТКИ, `skipped` считал ФУНКЦИИ, и разность двух РАЗНЫХ
    размерностей выдавалась за число пропусков. Спецификация `unexplained_skips`
    называет это нарушением ПРЕДПОСЫЛКИ (`named <= skipped`), и KERN опровергает
    нарушителя контрпримером `result = -1, named = 1, skipped = 0`
    ([RUNTIME CONFIRMED] — измерено, а не предположено);
  * воронка `checked + trivial + skipped == total` держалась на честном слове:
    ни одна её строка не была заперта, поэтому шаг 2 плана (#405) мог сломать
    инвариант МОЛЧА. Теперь его сторожат `funnel_total` и `unaccounted`.

ЧЕСТНАЯ ГРАНИЦА (измерено, а не предположено):
  * KERN доказывает здесь МОДЕЛЬ АРИФМЕТИКИ УЧЁТА, а не сам `--xray` целиком:
    он не доказывает, что корзины ЗАПОЛНЯЮТСЯ правильно (это шаг 2 плана).
    Заперт ровно тот инвариант счёта, который врал;
  * `ensures` скалярной функции НЕ может утверждать связь МЕЖДУ её входами:
    попытка записать `result + trivial + skipped == total` прямо в `ensures`
    даёт контрпример `total = 0, trivial = 1` — то есть ЛОЖНОЕ ОБВИНЕНИЕ
    корректной функции (измерено). Поэтому связь выражена функцией
    `unaccounted`, а её нулевое значение проверяет ГЕЙТ на реальных числах;
  * кортеж как результат движок не поддерживает (`SKIP — узел Tuple`), поэтому
    три корзины нельзя вернуть одной функцией.
"""


# @kern:requires total >= 0 and without_if >= 0 and total >= without_if
# @kern:ensures result == total - without_if and result >= 0
def branches_denominator(total: int, without_if: int) -> int:
    """Функций С ВЕТВЛЕНИЯМИ = всего - без `if`.

    Дефект: в плане такта 2.2 этот знаменатель стоял как 184 и 122, тогда как
    измерение даёт 182 и 121 — разница ровно в трёх функциях, чью причину
    пропуска атрибутировали неверно. Здесь формула заперта.
    """
    if without_if > total:
        raise ValueError(
            f"нарушена предпосылка total >= without_if (total={total}, "
            f"without_if={without_if}) — это дефект счётчика, а не корпуса")
    return total - without_if


# @kern:requires skipped >= 0 and named >= 0 and named <= skipped
# @kern:ensures result == skipped - named and result >= 0
def unexplained_skips(skipped: int, named: int) -> int:
    """Пропусков без записанной причины = пропуски - НАЗВАННЫЕ причины.

    ДЕФЕКТ #407.2 (измерен): `named` суммировал причины уровня ВЕТКИ, а `skipped`
    считает ФУНКЦИИ. Разность выходила ОТРИЦАТЕЛЬНОЙ (`9 - 15 = -6`) и
    печаталась как «число пропусков». Предпосылка `named <= skipped` — это и
    есть требование ОДНОЙ РАЗМЕРНОСТИ; нарушить её значит смешать единицы.
    """
    if named > skipped:
        raise ValueError(
            f"нарушена предпосылка named <= skipped (named={named}, "
            f"skipped={skipped}): единицы смешаны — причины уровня ВЕТКИ попали "
            f"в счёт уровня ФУНКЦИИ (#407.2, шаг 3 плана)")
    return skipped - named


# @kern:requires checked_branches >= 0 and checked_arith_only >= 0 and trivial >= 0 and skipped >= 0
# @kern:ensures result == checked_branches + checked_arith_only + trivial + skipped and result >= checked_branches
def funnel_total(checked_branches: int, checked_arith_only: int, trivial: int,
                 skipped: int) -> int:
    """ОПРЕДЕЛЕНИЕ `total`: четыре корзины обязаны покрывать его ровно один раз.

    Это пин дефекта #405. Функции БЕЗ `if` ПРОВЕРЯЮТСЯ на арифметику, поэтому
    их нельзя записывать в `skipped`; они либо `checked_arith_only`, либо
    `trivial`. Двойник, забывший `checked_arith_only`, опровергается гейтом.
    """
    return checked_branches + checked_arith_only + trivial + skipped


# @kern:requires total >= 0 and checked_branches >= 0 and checked_arith_only >= 0 and trivial >= 0 and skipped >= 0
# @kern:ensures result == total - checked_branches - checked_arith_only - trivial - skipped
def unaccounted(total: int, checked_branches: int, checked_arith_only: int,
                trivial: int, skipped: int) -> int:
    """ОСТАТОК: сколько функций не попало НИ В ОДНУ корзину.

    Гейт требует `unaccounted(...) == 0` на измеренных числах корпусов: если
    правка счётчиков потеряет функцию, инвариант перестанет сходиться и это
    будет видно ЧИСЛОМ, а не на глаз.
    """
    return total - checked_branches - checked_arith_only - trivial - skipped
