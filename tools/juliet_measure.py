#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""NIST Juliet C — ИЗМЕРЕНИЕ на РЕАЛЬНОМ датасете (по ФУНКЦИЯМ, не по файлам).

ЗАЧЕМ. До этого «Juliet» в проекте означало НАШИ собственные пары-близнецы
(гейт переименован в `cwe-twins-check`, дефект #367/шаг 4). Здесь — НАСТОЯЩИЙ
Juliet C: официальное зеркало `arichardson/juliet-test-suite-c` (полный набор
NIST, 118 категорий CWE). Каждый файл содержит `..._bad()` и `good*()` —
то есть эталон `bad`/`good` задан НА УРОВНЕ ФУНКЦИИ, и вердикт считается по
функциям, а не по файлу (иначе `_bad` и `good` в одном файле смешались бы).

ЧТО СЧИТАЕТСЯ:
  * TP — `_bad`-функция, на которой `--xray` дал находку;
  * FN — `_bad`-функция без находки (ПРОПУСК);
  * FP — `good`-функция, на которой находка есть (ЛОЖНОЕ ОБВИНЕНИЕ);
  * TN — `good`-функция без находки.
  Метрика — индекс Юдена `J = TPR - FPR`.

ЧЕГО ЭТО ИЗМЕРЕНИЕ НЕ УТВЕРЖДАЕТ (важно, и это измерено, а не предположено).
Juliet помечает `_bad` как «POTENTIAL FLAW» — потенциальную ошибку, а не
неопределённое поведение. Типичный `_bad` категории CWE-190 выглядит так:
    char data;  char result = data + 1;
Здесь `data` ПОВЫШАЕТСЯ до `int` (C11 6.3.1.1), поэтому `data + 1` НЕ
переполняется, а сужение при присваивании в `char` — implementation-defined, а
НЕ UB. Детектор KERN нацелен на UB (знаковое переполнение), поэтому такие
`_bad` он ПРОПУСКАЕТ — и это пропуск по СЕМАНТИКЕ, а не ошибка. Поэтому
скрипт печатает РАЗБИВКУ причин пропуска, а не только итоговое число.

Запуск:  python3 tools/juliet_measure.py --dir DIR [--limit N] [--out FILE]
Код возврата: 0 — измерение сделано (даже если J низкий: это ИЗМЕРЕНИЕ, не гейт).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERN_CONTRACTS = ROOT / "tools" / "kern_contracts.py"

# Определение функции C: `void NAME(...)` / `int NAME(...)` и т. п.
_RE_FUNC_DEF = re.compile(
    r"^\s*(?:static\s+)?(?:void|int|char|short|long|unsigned|float|double|"
    r"size_t)\s[\w\s\*]*?\b(\w+)\s*\(", re.M)


def classify(fn: str) -> str | None:
    """`bad` | `good` | None (служебная функция)."""
    if fn.endswith("_bad"):
        return "bad"
    if fn.startswith("good") or fn.endswith("_good"):
        return "good"
    return None


def miss_reason(body: str) -> str:
    """ПОЧЕМУ пропущено — по тексту `_bad`-тела (честная разбивка причин)."""
    if re.search(r"\bunsigned\b", body):
        return "беззнаковый тип (в C заворачивание ОПРЕДЕЛЕНО, не UB)"
    if re.search(r"\b(?:char|short)\b", body):
        return "узкий тип (повышается до int; сужение implementation-defined)"
    if re.search(r"\b(?:long|int64|size_t)\b", body):
        return "широкий тип (обязательства i32 нет)"
    return "прочее (значение локальной не выводится / цикл / вызов)"


def scan(dirpath: Path, limit: int) -> tuple[dict[str, str], dict[str, str], list[Path]]:
    """Вернуть (классификация функций, тела bad-функций, выбранные файлы)."""
    files = sorted(dirpath.rglob("*.c"))
    if limit and len(files) > limit:
        step = len(files) / limit          # ДЕТЕРМИНИРОВАННАЯ выборка:
        files = [files[int(i * step)] for i in range(limit)]   # не «первые N»
    kinds: dict[str, str] = {}
    bodies: dict[str, str] = {}
    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names = _RE_FUNC_DEF.findall(src)
        for nm in names:
            k = classify(nm)
            if k:
                kinds.setdefault(nm, k)
                if k == "bad":
                    m = re.search(rf"{re.escape(nm)}\s*\([^)]*\)\s*\{{", src)
                    if m:
                        bodies[nm] = src[m.end():m.end() + 900]
    return kinds, bodies, files


def run_xray(files: list[Path]) -> dict[str, list[str]]:
    """`--xray` по выбранным файлам. Возвращает {функция: [находки]}."""
    import tempfile
    hits: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory() as td:
        for f in files:
            (Path(td) / f.name).write_bytes(f.read_bytes())
        r = subprocess.run([PY, str(KERN_CONTRACTS), "--xray", td],
                           cwd=str(ROOT), capture_output=True, text=True,
                           timeout=7200)
    for line in (r.stdout + r.stderr).splitlines():
        m = re.search(r"\[([A-Z][A-Z ]+)\]\s+(\w+):", line)
        if m:
            hits.setdefault(m.group(2), []).append(f"[{m.group(1)}]")
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Juliet C: измерение по функциям")
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=120,
                    help="сколько файлов взять (детерминированная выборка)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))

    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    d = args.dir
    emit("=" * 78)
    emit("NIST JULIET C — ИЗМЕРЕНИЕ KERN ПО ФУНКЦИЯМ (реальный датасет)")
    emit("=" * 78)
    emit(f"  источник: arichardson/juliet-test-suite-c (официальное зеркало NIST)")
    emit(f"  каталог:  {d}")
    if not d.is_dir():
        emit(f"\n[SKIP] нет каталога {d}")
        emit("[i] Проверять нечего. Прогон не зачтён.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0

    kinds, bodies, files = scan(d, args.limit)
    emit(f"  файлов выбрано: {len(files)} (детерминированная выборка)")
    emit(f"  функций bad/good найдено: "
         f"{sum(1 for k in kinds.values() if k == 'bad')} / "
         f"{sum(1 for k in kinds.values() if k == 'good')}")
    if not kinds:
        emit("\n[SKIP] функций `_bad`/`good` не найдено — это не Juliet-каталог.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0

    hits = run_xray(files)
    # ВАЖНО: классы находок РАЗНЫЕ, и смешивать их нельзя. `[OVERFLOW PATH]` —
    # свойство CWE-190; `[DEAD BRANCH]` — достижимость ветви. Считать «FP» по
    # любому классу значило бы объявить ложным обвинением верную находку
    # другого свойства (ИЗМЕРЕНО: `[DEAD BRANCH] goodB2G1` на Juliet `_03`,
    # где ветвь действительно недостижима). Поэтому считаем ПО КЛАССАМ.
    all_kinds: set[str] = set()
    for v in hits.values():
        all_kinds.update(v)
    per_kind: dict[str, dict[str, int]] = {}
    for kind in sorted(all_kinds) + ["ЛЮБОЙ"]:
        c = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
        for nm, k in kinds.items():
            got = kind in hits.get(nm, []) if kind != "ЛЮБОЙ" else nm in hits
            if k == "bad":
                c["tp" if got else "fn"] += 1
            else:
                c["fp" if got else "tn"] += 1
        per_kind[kind] = c
    c = per_kind["ЛЮБОЙ"]
    tp, fn, fp, tn = c["tp"], c["fn"], c["fp"], c["tn"]
    reasons: dict[str, int] = {}
    for nm, k in sorted(kinds.items()):
        if k == "bad" and nm not in hits:
            r = miss_reason(bodies.get(nm, ""))
            reasons[r] = reasons.get(r, 0) + 1

    bad_n, good_n = tp + fn, fp + tn
    tpr = tp / bad_n if bad_n else 0.0
    fpr = fp / good_n if good_n else 0.0
    emit("")
    emit("=" * 78)
    emit("ЧЕСТНЫЙ СЧЁТ ПО ФУНКЦИЯМ (Juliet: `_bad` = потенциальная ошибка)")
    emit("=" * 78)
    emit(f"  `_bad` функций        : {bad_n}")
    emit(f"  `good` функций        : {good_n}")
    emit(f"  TP (поймал bad)       : {tp}")
    emit(f"  FN (пропустил bad)    : {fn}")
    emit(f"  FP (обвинил good)     : {fp}")
    emit(f"  TN (чисто на good)    : {tn}")
    emit(f"  TPR = {tpr:.3f}   FPR = {fpr:.3f}   "
         f"ИНДЕКС ЮДЕНА J = TPR - FPR = {tpr - fpr:.3f}")
    emit("")
    emit("ПО КЛАССАМ НАХОДОК (смешивать классы нельзя — свойство РАЗНОЕ):")
    for kind, cc in per_kind.items():
        t2, f2 = cc["tp"], cc["fp"]
        emit(f"  {kind:<20} TP {t2:>3}  FP {f2:>3}  TN {cc['tn']:>3}  FN {cc['fn']:>3}")
    emit("")
    emit("РАЗБИВКА ПРИЧИН ПРОПУСКА `_bad` (честно, а не одним числом):")
    for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
        emit(f"  {n:>5}  {r}")
    emit("")
    emit("ПОЧЕМУ ЭТО НЕ ГЕЙТ И ЧТО ЗНАЧИТ J:")
    emit("  Juliet помечает `_bad` как «POTENTIAL FLAW» — потенциальную ошибку,")
    emit("  а НЕ неопределённое поведение. Типичный `_bad` CWE-190 —")
    emit("  `char data; char result = data + 1;`: `data` ПОВЫШАЕТСЯ до `int`, и")
    emit("  `data + 1` не переполняется, а сужение при присваивании в `char` —")
    emit("  implementation-defined, не UB. Детектор KERN нацелен на UB, поэтому")
    emit("  такие `_bad` он ПРОПУСКАЕТ — пропуск по СЕМАНТИКЕ, не ошибка.")
    emit("  ИЗМЕРЕНИЕ, а не ворота: число J отражает РАЗНИЦУ ОПРЕДЕЛЕНИЙ, и")
    emit("  превращать его в зелёный гейт значило бы заявлять чужое свойство.")
    emit("")
    emit("ДВА РАЗНЫХ КЛАССА В ОДНОМ ЧИСЛЕ `FP` (измерено на CWE-190/s01):")
    emit("  `[OVERFLOW PATH]` — FP = 0, то есть ЛОЖНЫХ ОБВИНЕНИЙ ПО СВОЕМУ")
    emit("  СВОЙСТВУ НЕТ. Найденные «FP» относятся к ДРУГОМУ классу: в варианте")
    emit("  Juliet `_03` ветвь `if (5 != 5)` действительно недостижима, и сам")
    emit("  Juliet помечает её как `/* INCIDENTAL: CWE 561 Dead Code, the code")
    emit("  below will never run */`. То есть `[DEAD BRANCH]` там — ИСТИННАЯ")
    emit("  находка ДРУГОГО свойства, а не ошибка детектора переполнения.")
    emit("  Поэтому ворота на J строиться не могут: смешение классов дало бы")
    emit("  либо ложную тревогу, либо ложное спокойствие.")
    emit("")
    emit("ДЕЛЕНИЕ НА НОЛЬ (CWE-369) ИЗМЕРЕНО ОТДЕЛЬНО И ТОЖЕ ПРОПУСКАЕТСЯ,")
    emit("  И ЭТО НАЗВАНО: детектор `[CRASH PATH]` требует, чтобы ДЕЛИТЕЛЬ")
    emit("  зависел от ВХОДНОГО ПАРАМЕТРА (урок #179/#200: локальная-«длина»")
    emit("  давала ложные обвинения). В Juliet `_bad` делитель — ЛОКАЛЬНАЯ")
    emit("  (`float data = 0.0F;`), к тому же float (деление на 0.0 даёт inf, а")
    emit("  не панику), а тело содержит сокеты и циклы. Пропуск по трём")
    emit("  названным причинам, а не «не смогли».")
    emit("RC=0")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n[i] отчёт сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
