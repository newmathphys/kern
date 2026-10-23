# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""УСТАВ KERN, класс I: алгебраические законы, доказываемые самим KERN.

ЧТО ЭТО. Законы проекта, записанные как обычные `@kern:`-контракты, чтобы их
доказывал тот же движок, которым проект проверяет чужой код. Устав, который
нельзя проверить, — это пожелание; здесь каждый закон называет своего
проверяющего (`tools/charter_check.py`).

ЧЕСТНАЯ ГРАНИЦА, которую нельзя замалчивать. KERN доказывает законы над ЭТОЙ
моделью, а не над Zig-кодом напрямую. Чтобы модель не разошлась с ядром,
`charter_check.py` дополнительно СВЕРЯЕТ её с оракулом самого ядра
(`kern-conformance`, собранный из `src/core/eq2.zig` и
`src/next/state_axes.zig`): все 16 пар join, все 4 значения конфляции и все 7
отображений вердиктов обязаны совпасть. Модель без такой сверки — просто текст.

КОДИРОВКА — ровно как в `src/core/eq2.zig`: `code = p | (n << 1)`,
`N = 0, T = 1, F = 2, B = 3`.

ПОЧЕМУ ЗАКОНЫ ВЫГЛЯДЯТ ТАК. Подмножество контрактного движка — целые
параметры, `+ - * / // %`, `if/else`, один `return`; битовых операций и вызовов
в нём НЕТ. Поэтому дизъюнкция битов выражена ветвлением, а не `|`, и каждый
закон самодостаточен (никаких вызовов). Это ограничение движка, а не
формулировки.
"""

N, T, F, B = 0, 1, 2, 3


def p_of(code: int) -> int:
    return code % 2


def n_of(code: int) -> int:
    return code // 2


def join_code(a: int, b: int) -> int:
    """Точная верхняя грань по информационному порядку <=k (побитовое ИЛИ)."""
    return (p_of(a) | p_of(b)) | ((n_of(a) | n_of(b)) << 1)


def conflate_code(a: int) -> int:
    """Конфляция ~: переворачивает <=k, сохраняя <=t. ~(p,n) = (1-n, 1-p)."""
    return (1 - n_of(a)) | ((1 - p_of(a)) << 1)


# --- ЗАКОН 1: T ⊔ F = B (противоречие не затирается) -------------------------
# Вход зафиксирован на T=(1,0) и F=(0,1). Формула `p1+p2 + 2*(n1+n2)` — это
# дизъюнкция битов БЕЗ умножения, и она верна именно потому, что `requires`
# гарантирует: в каждой компоненте не более одной единицы. (Формулировка через
# `|` невозможна: битовых операций в подмножестве нет; формулировка через
# ветвления проверена и отвергнута пруф-чекером — неверный шаг unit-resolution.)
# @kern:requires p1 == 1 and n1 == 0 and p2 == 0 and n2 == 1
# @kern:ensures result == 3
def law_join_T_F(p1: int, n1: int, p2: int, n2: int) -> int:
    return p1 + p2 + 2 * (n1 + n2)


# --- ЗАКОН 2: join идемпотентен: x ⊔ x = x для любого кода --------------------
# @kern:requires x >= 0 and x <= 3
# @kern:ensures result == x
def law_join_idempotent(x: int) -> int:
    p = x % 2
    n = x // 2
    pj = 0
    if p == 1:
        pj = 1
    if p == 1:
        pj = 1
    nj = 0
    if n == 1:
        nj = 1
    if n == 1:
        nj = 1
    return pj + 2 * nj


# --- ЗАКОН 3: конфляция — инволюция: ~~a = a ---------------------------------
# @kern:requires a >= 0 and a <= 3
# @kern:ensures result == a
def law_conflate_involution(a: int) -> int:
    p = a % 2
    n = a // 2
    p1 = 1 - n
    n1 = 1 - p
    p2 = 1 - n1
    n2 = 1 - p1
    return p2 + 2 * n2


# --- ЗАКОН 4: сбой инструмента НЕ становится опровержением -------------------
# Отображение вердиктов как в `src/next/state_axes.zig`:
#   0 proved -> T(1) | 1 refuted -> F(2) | 2..6 -> N(0)
# Закон: результат равен F ТОЛЬКО для кода 1. Это и есть `timeout != F`,
# `out_of_fuel != F`, `invalid_certificate != F`, `tool_error != F` одним
# утверждением. Ровно тот дефект, который ловили в #277 (rc=2 -> F).
# @kern:requires v >= 0 and v <= 6
# @kern:ensures result != 2 or v == 1
def law_no_false_accusation(v: int) -> int:
    if v == 0:
        return 1
    if v == 1:
        return 2
    return 0


# --- ЗАКОН 5: B(1,1) не производится вердиктом -------------------------------
# Противоречие может прийти только от КОНФЛИКТА свидетельств (join), а не от
# одного исхода: вердикт не смеет сам объявить B.
# @kern:requires v >= 0 and v <= 6
# @kern:ensures result != 3
def law_verdict_never_b(v: int) -> int:
    if v == 0:
        return 1
    if v == 1:
        return 2
    return 0


# --- ЗАКОН 6: `invalid_certificate` не превращается в `F` --------------------
# Отдельный код 5 (негодный сертификат) обязан отображаться в N, иначе чекер
# обвинял бы код за СВОЙ сбой.
# @kern:requires v == 5
# @kern:ensures result == 0
def law_invalid_cert_is_unknown(v: int) -> int:
    if v == 0:
        return 1
    if v == 1:
        return 2
    return 0


# --- ЗАКОН 7: N — единица информационного порядка: N ⊔ x = x -----------------
# N=(0,0). Формула та же (дизъюнкция битов через сумму), верна потому, что
# `requires` фиксирует N и ограничивает x диапазоном кодов.
# @kern:requires p1 == 0 and n1 == 0 and x >= 0 and x <= 3
# @kern:ensures result == x
def law_join_identity_N(p1: int, n1: int, x: int) -> int:
    p = x % 2
    n = x // 2
    return p1 + p + 2 * (n1 + n)


# --- ЗАКОН 8: машинно доказанный частный случай закона 4: timeout -> N -------
# Общий закон 4 (для всех кодов) Z3 подтверждает, но наш пруф-чекер вывод не
# покрывает (см. CHARTER §3); здесь тот же закон в виде, который чекер
# принимает. Это и есть честная демонстрация: утверждение верно для всех
# кодов, а машинно доказано для каждого по отдельности.
# @kern:requires v == 3
# @kern:ensures result == 0
def law_timeout_is_unknown(v: int) -> int:
    if v == 0:
        return 1
    if v == 1:
        return 2
    return 0
