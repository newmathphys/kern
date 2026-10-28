#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для CHC/Horn (шаг D плана).

ЗАЧЕМ. До этого шага семейство `chc` проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ: `chc.zig`
строит Horn-запрос, Z3 отвечает `sat`/`unsat`, и этот ответ объявляется верным.
Вакуум: никто не сверял вердикт с РЕАЛЬНЫМ исполнением цикла.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ. Для каждого цикла `x := init; while (x < bound) x += step;`
и именованного свойства:
  1. НАТИВНЫЙ вердикт — `kernc theory` с формой `chc <init> <step> <bound> <свойство>`:
     `sat` = индуктивный инвариант СУЩЕСТВУЕТ (свойство держится на всех прогонах),
     `unsat` = инварианта НЕТ (свойство нарушается);
  2. РЕАЛЬНЫЙ прогон цикла в Python → фактическое значение на выходе;
  3. СОГЛАСОВАНИЕ. Цикл ДЕТЕРМИНИРОВАН (init/step/bound фиксированы), поэтому один
     реальный прогон — это ВСЯ его траектория, а вердикт Horn универсален. Значит
     расхождение в любую сторону — ошибка:
       * `sat` + свойство НАРУШЕНО  → ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО (худший класс);
       * `unsat` + свойство ВЫПОЛНЕНО → ложная тревога.

ИНВАРИАНТЫ:
  * ложных доказательств 0; ложных тревог 0;
  * НЕВАКУУМНОСТЬ: есть и подтверждённые `sat`, и подтверждённые `unsat` —
    иначе сравнение тривиально (все совпадут на одном классе);
  * НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор обязан ловить ОБА класса ошибок;
  * ДЕТЕРМИНИЗМ: два прогона дают один вердикт.

ЧЕГО ЭТО НЕ ДОКАЗЫВАЕТ:
  * проверяется ОДИН вид цикла (`x += step`, константы) и 4 именованных свойства,
    а не произвольные Horn-системы;
  * проверяется согласование вердикта с исполнением, а не качество самого
    инварианта: то, что `sat` подтверждён на этой траектории, не доказывает,
    что синтезированный инвариант сильнее необходимого.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SPEC_DIR = ROOT / "tests" / "fixtures" / "oracles"

# (init, step, bound, свойство)
FIXTURES = [
    (0, 1, 10, "ge_bound"),
    (0, 1, 10, "lt_bound"),
    (0, 2, 10, "parity_even"),
    (1, 2, 10, "parity_even"),
    (5, 1, 10, "le_init"),
    (100, 1, 50, "ge_bound"),
    (0, 1, 10, "le_init"),
]


def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return env


def native_verdict(init: int, step: int, bound: int, prop: str, idx: int) -> tuple[str, str]:
    """'sat' (инвариант есть) | 'unsat' (инварианта нет) | 'skip' | 'error'."""
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec = SPEC_DIR / f"chc_loop_{idx}.txt"
    spec.write_text(f"# физический оракул CHC\nchc {init} {step} {bound} {prop}\n", encoding="utf-8")
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT, env=child_env(),
                           capture_output=True, text=True, errors="replace", timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "error", f"kernc theory не запустился: {e}"
    out = p.stdout + p.stderr
    if "инвариант СУЩЕСТВУЕТ" in out:
        return "sat", ""
    if "инварианта НЕТ" in out:
        return "unsat", ""
    if "[SKIP]" in out:
        return "skip", out.strip().splitlines()[-1][:160] if out.strip() else ""
    return "error", f"вердикт не разобран: {out.strip()[:160]}"


def real_exit(init: int, step: int, bound: int) -> int:
    """РЕАЛЬНЫЙ прогон цикла: фактическое значение на выходе."""
    x = init
    while x < bound:
        x += step
    return x


def prop_holds(prop: str, x: int, init: int, bound: int) -> bool:
    if prop == "ge_bound":
        return x >= bound
    if prop == "lt_bound":
        return x < bound
    if prop == "parity_even":
        return x % 2 == 0
    if prop == "le_init":
        return x <= init
    raise ValueError(f"неизвестное свойство: {prop}")


def classify(native: str, holds: bool) -> str:
    """Классификатор. ВЫНЕСЕН отдельно — негативный контроль проверяет его сам."""
    if native == "sat":
        return "CONFIRMED_HOLDS" if holds else "FALSE_PROOF"
    if native == "unsat":
        return "FALSE_ALARM" if holds else "CONFIRMED_VIOLATED"
    return "BOUNDARY"


def run() -> int:
    print("=" * 72)
    print("=== KERN: ФИЗИЧЕСКИЙ ОРАКУЛ CHC/Horn (вердикт ядра против РЕАЛЬНОГО цикла) ===")
    print("=" * 72)

    counts = {"CONFIRMED_HOLDS": 0, "CONFIRMED_VIOLATED": 0,
              "FALSE_PROOF": 0, "FALSE_ALARM": 0, "BOUNDARY": 0}
    bad: list[str] = []

    for i, (init, step, bound, prop) in enumerate(FIXTURES):
        nv, why = native_verdict(init, step, bound, prop, i)
        x = real_exit(init, step, bound)
        holds = prop_holds(prop, x, init, bound)
        cls = classify(nv, holds)
        counts[cls] += 1
        mark = "OK " if cls in ("CONFIRMED_HOLDS", "CONFIRMED_VIOLATED") else "!! "
        print(f"  {mark}{cls:18s} ({init:>4},{step:>3},{bound:>4}) {prop:12s} "
              f"| реальный выход x={x:<8} свойство={'выполнено' if holds else 'НАРУШЕНО':9s} ядро={nv}")
        if cls in ("FALSE_PROOF", "FALSE_ALARM"):
            bad.append(f"({init},{step},{bound},{prop}): {cls} ({why})")

    # НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор обязан ловить ОБА класса ошибок.
    neg = []
    if classify("sat", False) != "FALSE_PROOF":
        neg.append("НЕ ловит ложное доказательство")
    if classify("unsat", True) != "FALSE_ALARM":
        neg.append("НЕ ловит ложную тревогу")
    if classify("sat", True) != "CONFIRMED_HOLDS":
        neg.append("не подтверждает выполнение свойства")
    if classify("skip", True) != "BOUNDARY":
        neg.append("SKIP смешан с вердиктом")
    print(f"  {'OK ' if not neg else '!! '}НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор "
          f"{'ловит оба класса ошибок' if not neg else '; '.join(neg)}")

    # ДЕТЕРМИНИЗМ: два прогона — один вердикт.
    det = True
    for i, (init, step, bound, prop) in enumerate(FIXTURES[:3]):
        a, _ = native_verdict(init, step, bound, prop, i)
        b, _ = native_verdict(init, step, bound, prop, i)
        if a != b:
            det = False
            bad.append(f"({init},{step},{bound},{prop}): вердикт недетерминирован ({a} vs {b})")
    print(f"  {'OK ' if det else '!! '}ДЕТЕРМИНИЗМ: два прогона дают один вердикт")

    print("-" * 72)
    print(f"  подтверждено `sat`  (свойство держится) : {counts['CONFIRMED_HOLDS']}")
    print(f"  подтверждено `unsat` (свойство нарушено): {counts['CONFIRMED_VIOLATED']}")
    print(f"  ЛОЖНЫХ ДОКАЗАТЕЛЬСТВ                    : {counts['FALSE_PROOF']}  (обязано быть 0)")
    print(f"  ЛОЖНЫХ ТРЕВОГ                           : {counts['FALSE_ALARM']}  (обязано быть 0)")
    print("-" * 72)

    ok = True
    if counts["FALSE_PROOF"]:
        print(f"[FAIL] ложных доказательств: {counts['FALSE_PROOF']}")
        ok = False
    if counts["FALSE_ALARM"]:
        print(f"[FAIL] ложных тревог: {counts['FALSE_ALARM']}")
        ok = False
    if counts["CONFIRMED_HOLDS"] < 2 or counts["CONFIRMED_VIOLATED"] < 2:
        print(f"[FAIL] невакуумность: sat={counts['CONFIRMED_HOLDS']}, "
              f"unsat={counts['CONFIRMED_VIOLATED']} (нужно >= 2 каждого)")
        ok = False
    if neg:
        print("[FAIL] негативный контроль не прошёл")
        ok = False
    if not det:
        print("[FAIL] вердикт недетерминирован")
        ok = False
    for r in bad:
        print(f"[FAIL] {r}")
        ok = False
    if ok:
        print(f"[OK] физический оракул CHC: {counts['CONFIRMED_HOLDS']} вердиктов `sat` и "
              f"{counts['CONFIRMED_VIOLATED']} `unsat` согласованы с РЕАЛЬНЫМ исполнением "
              f"цикла; 0 ложных доказательств, 0 ложных тревог")
    print(f"RC={0 if ok else 1}")
    return 0 if ok else 1


def selftest() -> int:
    """Проверка классификатора, реального цикла и предикатов (без kernc)."""
    checks = [
        ("sat + свойство нарушено = ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО", classify("sat", False) == "FALSE_PROOF"),
        ("unsat + свойство выполнено = ЛОЖНАЯ ТРЕВОГА", classify("unsat", True) == "FALSE_ALARM"),
        ("sat + выполнено = подтверждено", classify("sat", True) == "CONFIRMED_HOLDS"),
        ("unsat + нарушено = подтверждено", classify("unsat", False) == "CONFIRMED_VIOLATED"),
        ("SKIP не считается вердиктом", classify("skip", False) == "BOUNDARY"),
        ("реальный цикл (0,1,10) → 10", real_exit(0, 1, 10) == 10),
        ("реальный цикл (0,2,10) → 10 (чётный)", real_exit(0, 2, 10) == 10),
        ("реальный цикл (1,2,10) → 11 (нечётный)", real_exit(1, 2, 10) == 11),
        ("цикл без итераций (100,1,50) → 100", real_exit(100, 1, 50) == 100),
        ("ge_bound: 10 >= 10", prop_holds("ge_bound", 10, 0, 10)),
        ("lt_bound: 10 < 10 ложно", not prop_holds("lt_bound", 10, 0, 10)),
        ("parity_even: 11 нечётно", not prop_holds("parity_even", 11, 1, 10)),
        ("le_init: 10 <= 5 ложно", not prop_holds("le_init", 10, 5, 10)),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'[OK]' if ok else '[FAIL]'} {n}")
    if bad:
        print(f"[FAIL] selftest: {len(bad)} проверок не прошло")
        return 1
    print(f"[OK] selftest: {len(checks)}/{len(checks)} проверок")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not KERNC.exists():
        print(f"[FAIL] нет бинарника {KERNC} — сначала `make build`")
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
