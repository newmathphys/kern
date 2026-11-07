#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕЙТ ТОЧНОСТИ `--xray` (#475): ДВУСТОРОННИЙ И ГЕРМЕТИЧНЫЙ.

ЗАЧЕМ. Охота на чужом коде дала **56 %** точности на `TheAlgorithms/Rust`
(18 находок, 8 ложных). Ложное обвинение — худший класс исхода, поэтому
точность должна измеряться МАШИНОЙ, а не триажем вручную. Корпус QuixBugs
лежит вне репозитория, поэтому основа гейта — ГЕРМЕТИЧНЫЙ микрокорпус:

  * `tests/fixtures/precision_clean/`  (py + rs + c) — код с ПОЛНЫМИ гардами:
    `находок 0`. Любая находка = регресс ложного обвинения (#471a/b/c, #472,
    #473, #454, #179, #468 — по одному представителю на класс);
  * `tests/fixtures/precision_buggy/`  — тот же класс ошибок БЕЗ гардов:
    ровно `EXPECTED_BUGGY` находок и КАЖДОЕ имя из `REQUIRED_FOUND` на месте
    (пропуск = потеря сигнала, FN).

ПЛЮС необязательная часть на внешнем корпусе (`QuixBugs/correct_python_programs`,
50 корректных программ): если он есть — находок обязано быть 0; если его нет —
печатается НАЗВАННЫЙ пропуск, а не зелёный результат (принцип `translator-diff`).

Почему это не «вакуумная» проверка: обе стороны обязательны. Заглушив
анализатор, получим 0 в clean И 0 в buggy — вторая половина покраснеет.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
CLEAN = ROOT / "tests" / "fixtures" / "precision_clean"
BUGGY = ROOT / "tests" / "fixtures" / "precision_buggy"
KNOWN_FP = ROOT / "tests" / "fixtures" / "precision_known_fp"
# #500: КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ к фикстуре `precision_clean/field_guard_write.c`:
# поле НЕ переписывается -> мёртвая ветвь НАСТОЯЩАЯ и обязана ловиться.
DEAD_FIELD = ROOT / "tests" / "fixtures" / "precision_dead_field"
# #502: УЧЁТ НАХОДОК. Две РАЗНЫЕ проверки с ОДНИМ условием в одной функции — это
# ОДНО обвинение (у `[DEAD BRANCH]` нет номера строки), а не два.
DEDUPE = ROOT / "tests" / "fixtures" / "precision_dedupe"
EXT = Path.home() / ".cache" / "kern" / "repos" / "QuixBugs" / "correct_python_programs"

# Ожидаемое число находок на «багованном» корпусе (5 функций, каждая обязана найтись).
EXPECTED_BUGGY = 5
REQUIRED_FOUND = ("div_unguarded", "idx_unguarded_literal", "mod_unguarded",
                  "div_unguarded_rs", "mod_unguarded_rs")
# Известные ложные обвинения (ретаргет #476): РОВНО столько и НИКАКИХ других.
# #495 (найдено ТРОФЕЙНОЙ ОХОТОЙ на cmark-gfm): гард `if (closing <= opening) { return; }`
# в `switch`-ветви НЕ сужает путь, если `link_end` переприсваивался в цикле -> ЛОЖНЫЙ
# OVERFLOW PATH на `closing--`. Минимальные формы БЕЗ переприсваивания НЕ воспроизводят.
EXPECTED_KNOWN_FP = 0      # #495 закрыт: класс пуст
KNOWN_FP_NAMES: tuple = ()   # пусто: FP не разрешены
# База ложных обвинений на внешнем корпусе (ИЗМЕРЕНО: 21 из 50 корректных
# программ). ЦЕЛЬ — 0. Гейт краснеет, если число ВЫРОСЛО: так регрессы видны,
# а существующий долг честно назван числом, а не спрятан.
EXT_FP_BASELINE = 4

RE_SUMMARY = re.compile(r"находок\s+(\d+)")
RE_FINDING = re.compile(r"\[(CRASH PATH|BOUNDS PATH|OVERFLOW PATH|DEAD BRANCH)\]\s+(\w+)")
# ДЕФЕКТ #476f: одна находка печатается ДВАЖДЫ (в контексте функции и в
# итоговом списке по файлам), поэтому счётчик сводки завышен. Для метрики
# ТОЧНОСТИ считаем УНИКАЛЬНЫЕ пары (файл, функция, тип): обвинённая функция —
# одна, сколько бы раз её ни напечатали.
RE_UNIQUE = re.compile(r"^\s+(/\S+?):\s+\[(CRASH PATH|BOUNDS PATH|OVERFLOW PATH|DEAD BRANCH)\]\s+(\w+)", re.M)


def xray(path: Path) -> tuple[int, str]:
    p = subprocess.run([PY, str(EXTRACTOR), "--xray", str(path)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def findings_of(out: str) -> tuple[int, set[str]]:
    m = RE_SUMMARY.search(out)
    n = int(m.group(1)) if m else -1
    return n, {fn for _lab, fn in RE_FINDING.findall(out)}


def unique_findings(out: str) -> set:
    """УНИКАЛЬНЫЕ обвинения: (файл, функция, тип). #476f: печать дублируется."""
    return {(f, fn, lab) for f, lab, fn in RE_UNIQUE.findall(out)}


def _no_analysis_reason(rc: int, out: str) -> str:
    """Почему вердикт о КОДЕ выносить нельзя (дефект #499, измерено на чистом клоне).

    Без решателя `--xray` возвращает 2, и гейт печатал «потеря сигнала (FN): не
    найдены [...]» — диагноз о ПРОВЕРЯЕМОМ КОДЕ вместо диагноза об инструменте.
    Класс #370/#497: сообщение говорит не то, что произошло.
    """
    low = (out or "").lower()
    if "z3 недоступен" in low or "z3 is not" in low or "solver_unavailable" in low:
        return "нет решателя Z3 — SMT-детекторы НЕ ЗАПУСКАЛИСЬ"
    if "не найден kernc" in low or "kernc_missing" in low:
        return "не найден бинарь kernc (соберите: zig build)"
    return f"rc={rc}; см. вывод инструмента выше"


def main() -> int:
    bad: list[str] = []

    # --- ЧАСТЬ 1а: ТОЧНОСТЬ. Защищённый код обязан молчать.
    rc_c, out_c = xray(CLEAN)
    n_c, f_c = findings_of(out_c)
    print(f"[i] clean: находок {n_c} (ожидали 0), rc={rc_c}")
    if n_c != 0:
        bad.append(f"ЛОЖНЫЕ ОБВИНЕНИЯ на защищённом коде: {n_c} — {sorted(f_c)}")
    if rc_c >= 2:
        # #499: анализа НЕ БЫЛО -> и «FN», и «пропуск» были бы ложным диагнозом о коде.
        print(f"[FAIL] #499: точность НЕ измерена — `--xray` rc={rc_c}: "
              f"{_no_analysis_reason(rc_c, out_c)}")
        return 1
    if rc_c != 0:
        bad.append(f"`--xray` упал на clean-корпусе (rc={rc_c})")

    # --- ЧАСТЬ 1а-бис: ДВУСТОРОННИЙ КОНТРОЛЬ #500 (поле структуры). ЛОВУШКА
    # (`precision_clean/field_guard_write.c`: поле переписано между гардом и
    # проверкой) уже покрыта частью 1а — ожидание 0. Здесь ОБРАТНАЯ сторона:
    # поле НЕ переписано, значит третья проверка `kind == 1` НАСТОЯЩАЯ мёртвая
    # ветвь. Если правка #500 убьёт и её — recall упал, гейт обязан покраснеть.
    rc_d, out_d = xray(DEAD_FIELD)
    n_d, f_d = findings_of(out_d)
    print(f"[i] dead_field (поле без перезаписи): находок {n_d} (ожидали 1), rc={rc_d}")
    if rc_d >= 2:
        print(f"[FAIL] #499: dead_field НЕ измерен — rc={rc_d}: "
              f"{_no_analysis_reason(rc_d, out_d)}")
        return 1
    if n_d != 1 or "dead_after_kind" not in f_d:
        bad.append(f"#500 ОБРАТНЫЙ КОНТРОЛЬ: ожидали РОВНО 1 находку `dead_after_kind`, "
                   f"получили {n_d} {sorted(f_d)} — правка «поля» съела настоящую ветвь")

    # --- ЧАСТЬ 1а-тер: УЧЁТ (#502). В фикстуре две РАЗНЫЕ проверки с ОДНИМ И ТЕМ ЖЕ
    # условием: обвинение ОДНО. До правки печаталось две находки (измерено:
    # «находок 2»), после — одна. Счётчик, завышающий число обвинений, врёт так же,
    # как и потеря находки (класс #476f).
    rc_u, out_u = xray(DEDUPE)
    n_u, _f_u = findings_of(out_u)
    print(f"[i] dedupe (две одинаковые мёртвые проверки): находок {n_u} (ожидали 1), rc={rc_u}")
    if rc_u >= 2:
        print(f"[FAIL] #499: dedupe НЕ измерен — rc={rc_u}: "
              f"{_no_analysis_reason(rc_u, out_u)}")
        return 1
    if n_u != 1:
        bad.append(f"#502 УЧЁТ: одна и та же находка посчитана {n_u} раз(а) — ожидалась 1")

    # --- ЧАСТЬ 1б: РЕТАРГЕТ известных ложных обвинений (#476).
    # Ровно столько и только эти имена: когда дефект починят, здесь станет 0 и
    # гейт ПОТРЕБУЕТ перенести функцию в `precision_clean` (ретаргет в обе стороны).
    rc_k, out_k = xray(KNOWN_FP)
    n_k, f_k = findings_of(out_k)
    print(f"[i] known_fp: находок {n_k} (ожидали {EXPECTED_KNOWN_FP}: {KNOWN_FP_NAMES})")
    if n_k != EXPECTED_KNOWN_FP:
        bad.append(f"ретаргет #476: находок {n_k}, ожидали {EXPECTED_KNOWN_FP} — "
                   f"если 0, дефект исправлен: перенесите функцию в precision_clean")
    extra = sorted(f_k - set(KNOWN_FP_NAMES))
    if extra:
        bad.append(f"в known_fp появились НОВЫЕ имена (не из списка): {extra}")

    # --- ЧАСТЬ 1в: ПОЛНОТА. Багованный код обязан ловиться, и КАЖДАЯ функция.
    rc_b, out_b = xray(BUGGY)
    n_b, f_b = findings_of(out_b)
    print(f"[i] buggy: находок {n_b} (ожидали {EXPECTED_BUGGY}), rc={rc_b}")
    if rc_b >= 2:
        print(f"[FAIL] #499: полнота НЕ измерена — `--xray` rc={rc_b}: "
              f"{_no_analysis_reason(rc_b, out_b)}")
        return 1
    if n_b != EXPECTED_BUGGY:
        bad.append(f"полнота: находок {n_b}, ожидали {EXPECTED_BUGGY}")
    missing = [f for f in REQUIRED_FOUND if f not in f_b]
    if missing:
        bad.append(f"потеря сигнала (FN): не найдены {missing}")

    # --- ЧАСТЬ 2: внешний корпус (необязательный, НАЗВАННЫЙ пропуск).
    if EXT.is_dir():
        rc_e, out_e = xray(EXT)
        n_e, f_e = findings_of(out_e)
        # #476f: сводка считает и контекст, и итоговый список -> сырой счётчик
        # завышен вдвое. Метрика ТОЧНОСТИ — уникальные обвинения.
        u_e = unique_findings(out_e)
        n_uniq = len(u_e) if u_e else len(f_e)
        print(f"[i] QuixBugs/correct_python_programs: {n_uniq} уникальных обвинений "
              f"(сырой счётчик {n_e}, база {EXT_FP_BASELINE}, цель 0)")
        if n_uniq > EXT_FP_BASELINE:
            bad.append(f"РЕГРЕСС на 50 КОРРЕКТНЫХ программах: {n_uniq} > базы "
                       f"{EXT_FP_BASELINE} — {sorted(f_e)[:8]}")
        elif n_uniq < EXT_FP_BASELINE:
            print(f"[i] ЛУЧШЕ БАЗЫ на {EXT_FP_BASELINE - n_uniq}: снизьте "
                  f"EXT_FP_BASELINE до {n_uniq} (ретаргет вниз)")
        if rc_e >= 2:
            print(f"[FAIL] #499: внешний корпус НЕ измерен — rc={rc_e}: "
                  f"{_no_analysis_reason(rc_e, out_e)}")
            return 1
        if rc_e != 0:
            bad.append(f"`--xray` упал на внешнем корпусе (rc={rc_e})")
    else:
        print(f"[SKIP] внешний корпус отсутствует: {EXT} — часть 2 НЕ выполнена "
              f"(это названный пропуск, а не «зелено»)")

    # --- ЧАСТЬ 3: LIMITS НЕ ОТСТАЁТ ОТ ГЕЙТА (#492).
    # ЗАЧЕМ. `docs/LIMITS` — единственная страница, где числа точности названы
    # пользователю. После #476 там оставались `known_fp = 1` и `21 FP`, то есть
    # документ ОТСТАВАЛ от кода. Теперь числа сверяются машинно: страница
    # обязана называть текущий EXPECTED_KNOWN_FP и текущую внешнюю базу.
    for doc in (ROOT / "docs" / "LIMITS.md", ROOT / "docs" / "LIMITS.ru.md"):
        if not doc.is_file():
            bad.append(f"{doc.name}: страница границ отсутствует")
            continue
        txt = doc.read_text(encoding="utf-8")
        if f"EXPECTED_KNOWN_FP` is now **{EXPECTED_KNOWN_FP}**" not in txt                 and f"`EXPECTED_KNOWN_FP` теперь **{EXPECTED_KNOWN_FP}**" not in txt:
            bad.append(f"{doc.name}: не называет EXPECTED_KNOWN_FP = {EXPECTED_KNOWN_FP} "
                       f"(документ отстал от гейта)")
        if str(EXT_FP_BASELINE) not in txt:
            bad.append(f"{doc.name}: не называет внешнюю базу {EXT_FP_BASELINE}")
        else:
            print(f"[OK] {doc.name}: числа точности синхронны с гейтом "
                  f"(known_fp {EXPECTED_KNOWN_FP}, внешняя база {EXT_FP_BASELINE})")

    for b in bad:
        print(f"[!] {b}")
    if bad:
        print(f"[FAIL] #475: провалов {len(bad)}")
        return 1
    print("[OK] #475: защищённый код молчит (0), 5/5 ошибок найдены, "
          f"ретаргет #476 = {EXPECTED_KNOWN_FP}, внешний корпус на базе "
          f"{EXT_FP_BASELINE} (цель 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
