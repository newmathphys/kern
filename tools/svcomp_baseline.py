#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""SV-COMP: ЧЕСТНОЕ ИЗМЕРЕНИЕ (это НЕ гейт — см. почему ниже).

ЗАЧЕМ. Заявка «прогнали SV-COMP» без замера — это иллюстрация, а не факт.
Скрипт берёт ОФИЦИАЛЬНЫЕ задачи категории `signedintegeroverflow-regression`
из `sosy-lab/sv-benchmarks` (репозиторий мирового чемпионата по верификации),
читает эталонный вердикт из `.yml` и сверяет с ним то, что РЕАЛЬНО отвечает
KERN. Числа не округляются.

ПОЧЕМУ ЭТО НЕ ГЕЙТ (измеренный вывод, а не осторожность).
Свойство SV-COMP `no-overflow.prp` требует, чтобы КАЖДАЯ арифметическая
операция оставалась в границах типа. KERN проверяет ИТОГОВОЕ значение
возврата. Различие проявляется ровно там, где оно и в этом датасете:
`(2147483647 + 1) - 23` переполняется ВНУТРИ (`2147483648`), но итог
`2147483625` снова попадает в диапазон — и обязанность типа удовлетворена.
Сделать из этого зелёный гейт значило бы заявить покрытие свойства, которого
нет. Поэтому скрипт ИЗМЕРЯЕТ и печатает матрицу, а решение о гейте
принимается отдельно по числам.

ТРИ КОЛОНКИ МАТРИЦЫ:

  1. `--xray` — ОФИЦИАЛЬНЫЙ файл БЕЗ изменений. Работает без аннотаций, но
     имеет детекторы только для деления на ноль, границ массивов, размера
     аллокации и ветвлений. Переполнения обычного выражения среди них нет.
  2. контрактный путь на ПРОИЗВОДНОМ файле (официальный + одна тривиальная
     аннотация). Помечается ЯВНО: файл изменён, значит это уже не задача
     чемпионата в чистом виде, а замер «что скажет движок, если свойство
     выразить». Без аннотаций контрактный путь не делает НИЧЕГО.
  3. `expected_verdict` из `.yml` — эталон.

Запуск:  python3 tools/svcomp_baseline.py [--dir DIR] [--out FILE]
Код возврата: всегда 0 — это измерение, а не ворота.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERN_CONTRACTS = ROOT / "tools" / "kern_contracts.py"
DEFAULT_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kern" / "svcomp"
_RAW = ("https://raw.githubusercontent.com/sosy-lab/sv-benchmarks/master/"
        "c/signedintegeroverflow-regression/")
TASKS = ["AdditionIntMax", "AdditionIntMin", "ConversionToSignedInt", "Division-1",
         "IntegerPromotion-1", "Multiplication-1", "Multiplication-2", "NoConversion",
         "NoNegativeIntegerConstant", "PostfixDecrement", "PostfixIncrement",
         "PrefixDecrement", "PrefixIncrement", "UnaryMinus",
         "UsualArithmeticConversions"]



def ensure_tasks(directory: Path) -> tuple[bool, str]:
    """Скачать официальные задачи в КЭШ, если их нет."""
    import urllib.request
    directory.mkdir(parents=True, exist_ok=True)
    missing = [t for t in TASKS if not (directory / f"{t}.c").exists()]
    for t in missing:
        for ext in ("c", "yml"):
            try:
                with urllib.request.urlopen(f"{_RAW}{t}.{ext}", timeout=60) as r:
                    (directory / f"{t}.{ext}").write_bytes(r.read())
            except Exception as e:                          # noqa: BLE001
                return False, f"не удалось скачать {t}.{ext} ({type(e).__name__})"
    return True, ""


def expected_verdict(directory: Path, task: str) -> str:
    """`false` = БАГ ЕСТЬ (unsafe), `true` = БЕЗОПАСНО (safe)."""
    txt = (directory / f"{task}.yml").read_text(encoding="utf-8", errors="replace")
    vals = re.findall(r"expected_verdict:\s*(true|false)", txt)
    if not vals:
        return "?"
    # У части задач два свойства с ОДИНАКОВЫМ вердиктом; берём множество.
    return vals[0] if len(set(vals)) == 1 else f"КОНФЛИКТ{sorted(set(vals))}"


def run_xray(directory: Path) -> dict[str, str]:
    """`--xray` по ОФИЦИАЛЬНЫМ файлам. Возвращает {файл: строка находки}.

    `--xray` берёт КАТАЛОГ, поэтому подаём каталог целиком и разбираем вывод.
    """
    r = subprocess.run([PY, str(KERN_CONTRACTS), "--xray", str(directory)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    found: dict[str, str] = {}
    for line in out.splitlines():
        m = re.search(r"/([A-Za-z0-9_.\-]+\.c):\s*\[([A-Z ]+)\]\s*(.*)", line)
        if m:
            found.setdefault(m.group(1), f"[{m.group(2).strip()}] {m.group(3).strip()}")
    return found


def run_contract(directory: Path, task: str, strip_calls: bool = False
                 ) -> tuple[str, str]:
    """Контрактный путь на ПРОИЗВОДНОМ файле. Возвращает (вердикт, деталь).

    Аннотация тривиальна (`requires 1 == 1`), чтобы НЕ менять семантику: цель —
    активировать обязанность типа, а не переписать задачу. Файл помечается как
    производный, и в матрице это указано явно.

    `strip_calls=True` дополнительно убирает строки с вызовами (`printf`).
    ЗАЧЕМ: измерено, что вызов библиотечной функции выводит ТЕЛО за подмножество,
    и тогда вердикта нет вообще. Снятие вызова открывает ВТОРОЙ слой: что
    скажет движок, когда тело ему по силам.
    """
    src = (directory / f"{task}.c").read_text(encoding="utf-8", errors="replace")
    # Аннотация обязана стоять ВПЛОТНУЮ перед определением функции: парсер ищет
    # её в блоке комментариев непосредственно над заголовком. Поэтому вставляем
    # ПЕРЕД первой строкой-определением, а не в начало файла (в начале стоят
    # `// Author:`, `#include` и `int x` внутри тела).
    lines = src.splitlines(keepends=True)
    at = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(?:static\s+)?(?:int|void|long|unsigned|char|float|double|"
                    r"size_t|u?int\d+_t)\s+\w+\s*\(", ln):
            at = i
            break
    if at is None:
        return "SKIP", "не найдено определение функции"
    body_lines = lines[at:]
    if strip_calls:
        body_lines = [ln for ln in body_lines
                      if not re.search(r"\bprintf\s*\(", ln)]
    derived = ("".join(lines[:at])
               + "// @kern:requires 1 == 1\n// @kern:ensures result == result\n"
               + "".join(body_lines))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"{task}.c"
        p.write_text(derived, encoding="utf-8")
        r = subprocess.run([PY, str(KERN_CONTRACTS), str(p)],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    if "ПЕРЕПОЛНЕНИЕ типа" in out:
        return "REFUTED", "ПЕРЕПОЛНЕНИЕ типа (обязанность типа сработала)"
    if "нет функций с аннотациями" in out:
        return "SKIP", "нет функций с аннотациями"
    if "вне подмножества" in out and "нарушено 0" in out and "доказано 0" in out:
        m0 = re.search(r"вне подмножества (\d+)", out)
        return "SKIP", f"вне подмножества {m0.group(1) if m0 else '?'}"
    m = re.search(r"ИТОГО: доказано (\d+) \|.*?нарушено (\d+) .*?вне подмножества (\d+)",
                  out)
    if not m:
        return "SKIP", "нет сводки"
    proved, violated, outside = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if violated:
        return "REFUTED", f"нарушено {violated}"
    if proved:
        return "PROVEN", f"доказано {proved}"
    if outside:
        return "SKIP", f"вне подмножества {outside}"
    return "SKIP", "нет вердикта"



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SV-COMP: честное измерение (не гейт)")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))

    directory = args.dir
    ok, why = ensure_tasks(directory)
    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("=" * 78)
    emit("SV-COMP: ЧЕСТНОЕ ИЗМЕРЕНИЕ KERN (категория signedintegeroverflow-regression)")
    emit("=" * 78)
    emit("  источник: sosy-lab/sv-benchmarks (репозиторий чемпионата TACAS)")
    emit("  свойство: ../properties/no-overflow.prp")
    emit("  ЛИЦЕНЗИЯ И ПРОИСХОЖДЕНИЕ: файлы не изменяются для колонки `--xray`;")
    emit("  для контрактной колонки строится ПРОИЗВОДНЫЙ файл (см. ниже).")
    if not ok:
        emit(f"\n[SKIP] {why}")
        emit("[i] Проверять нечего. Прогон не зачтён.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0

    xray = run_xray(directory)
    emit("")
    emit("  №  задача                         эталон  --xray(офиц.)  контракт(произв.)  "
         "контракт −printf")
    emit("  " + "-" * 88)
    counts = {"xray_hit_bad": 0, "xray_miss_bad": 0, "xray_false_bad": 0,
              "c_refuted_bad": 0, "c_proven_good": 0, "c_proven_bad": 0,
              "c_skip": 0, "c2_refuted_bad": 0, "c2_proven_bad": 0,
              "c2_proven_good": 0, "c2_skip": 0}
    for i, t in enumerate(TASKS, 1):
        exp = expected_verdict(directory, t)
        xr = xray.get(f"{t}.c", "—")
        cv, cd = run_contract(directory, t)
        cv2, cd2 = run_contract(directory, t, strip_calls=True)
        xr_short = "НАХОДКА" if xr != "—" else "нет находки"
        if exp == "false":
            counts["xray_hit_bad" if xr != "—" else "xray_miss_bad"] += 1
            if cv == "REFUTED":
                counts["c_refuted_bad"] += 1
            elif cv == "PROVEN":
                counts["c_proven_bad"] += 1
            else:
                counts["c_skip"] += 1
            if cv2 == "REFUTED":
                counts["c2_refuted_bad"] += 1
            elif cv2 == "PROVEN":
                counts["c2_proven_bad"] += 1
            else:
                counts["c2_skip"] += 1
        elif exp == "true":
            if xr != "—":
                counts["xray_false_bad"] += 1
            if cv == "PROVEN":
                counts["c_proven_good"] += 1
            elif cv == "SKIP":
                counts["c_skip"] += 1
            if cv2 == "PROVEN":
                counts["c2_proven_good"] += 1
            elif cv2 == "SKIP":
                counts["c2_skip"] += 1
        emit(f"  {i:>2}  {t:<30} {exp:<7} {xr_short:<14} {cv:<18} {cv2} ({cd2})")

    emit("")
    emit("=" * 78)
    emit("ЧЕСТНЫЙ СЧЁТ (эталон: false = БАГ ЕСТЬ, true = БЕЗОПАСНО)")
    emit("=" * 78)
    unsafe = sum(1 for t in TASKS if expected_verdict(directory, t) == "false")
    safe = len(TASKS) - unsafe
    tp = counts["xray_hit_bad"]
    fn = counts["xray_miss_bad"]
    fp = counts["xray_false_bad"]
    tn = safe - fp
    tpr = tp / unsafe if unsafe else 0.0
    fpr = fp / safe if safe else 0.0
    emit(f"  задач всего          : {len(TASKS)}  (unsafe {unsafe}, safe {safe})")
    emit(f"  --xray поймал unsafe : {tp} из {unsafe}   (TP)")
    emit(f"  --xray пропустил     : {fn} из {unsafe}   (FN)")
    emit(f"  --xray ложных тревог : {fp} из {safe}   (FP)")
    emit(f"  --xray чисто на safe : {tn} из {safe}   (TN)")
    emit(f"  TPR = {tpr:.2f}   FPR = {fpr:.2f}   "
         f"ИНДЕКС ЮДЕНА J = TPR - FPR = {tpr - fpr:.2f}")
    emit("")
    emit("СЛОЙ 2 — контракт на производном файле БЕЗ вызова `printf`:")
    emit(f"  REFUTED unsafe (поймал)     : {counts['c2_refuted_bad']} из {unsafe}")
    emit(f"  ЛОЖНО PROVEN unsafe (пропустил): {counts['c2_proven_bad']} из {unsafe}")
    emit(f"  PROVEN safe                 : {counts['c2_proven_good']} из {safe}")
    emit(f"  SKIP                        : {counts['c2_skip']}")
    emit("")
    emit("ДИАГНОЗ (измеренный, не предположение):")
    emit("  Свойство `no-overflow.prp` требует, чтобы КАЖДАЯ арифметическая")
    emit("  операция оставалась в границах типа. KERN проверяет ИТОГОВОЕ значение")
    emit("  возврата. Различие видно ровно на `(2147483647 + 1) - 23`: переполнение")
    emit("  происходит ВНУТРИ (`2147483648`), но итог `2147483625` снова попадает в")
    emit("  диапазон — и обязанность типа удовлетворена. Поэтому класс задач, где")
    emit("  переполнение «схлопывается» обратно, KERN не ловит.")
    emit("")
    emit("  ВАЖНО: это НЕ ложь о заявленном контракте. `ensures result == 0`")
    emit("  действительно выполняется. KERN заявляет МЕНЬШЕ свойства SV-COMP, а не")
    emit("  больше — то есть это пропуск, а не подмена вердикта.")
    emit("")
    emit("  БЕЗ аннотаций контрактный путь не делает НИЧЕГО (`нет функций с")
    emit("  аннотациями`), а `--xray` для C не имеет детектора переполнения")
    emit("  обычного выражения (только размер аллокации). Значит колонка")
    emit("  «контракт(произв.)» относится к ПРОИЗВОДНОМУ файлу и задачей")
    emit("  чемпионата в чистом виде НЕ является.")
    emit("")
    emit("ПОЧЕМУ БЕЗ ГЕЙТА: зелёный гейт на этих 15 задачах означал бы заявление")
    emit("  покрытия свойства `no-overflow`, которого у KERN нет. Честное покрытие")
    emit("  требует применения `.prp` к КАЖДОЙ операции — отдельная работа в")
    emit("  трансляторе. Поэтому здесь только ИЗМЕРЕНИЕ.")
    emit("")
    emit("ПОСЛЕ ДЕФЕКТА #367 (детектор переполнения обычного выражения в `--xray`):")
    emit("  колонка `--xray` больше НЕ пуста — именно её числа и смотрите выше.")
    emit("  Остальные колонки оставлены как ИСТОРИЯ измерения: контрактный путь")
    emit("  по-прежнему проверяет только итог возврата, и это его свойство, а не")
    emit("  регрессия. Гейт детектора — `make xray-overflow-check`.")
    # Финальная строка RC=<n>: её требует устав (P6, «свидетельство отслеживается
    # и не содержит провала»). Лог без неё считается неполным или снятым вручную.
    emit("RC=0")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n[i] отчёт сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
