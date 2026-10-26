#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: инлайнинг вызовов функций ИЗ ТОГО ЖЕ ФАЙЛА (ШАГ 1).

ЗАЧЕМ. В реальном коде почти каждая функция вызывает соседнюю (`lcm` зовёт
`gcd`). До этого шага любой такой вызов уходил в `_havoc` — свежий символ:
тело вызываемого НЕ анализировалось, а его обязанности безопасности (деление на
ноль, переполнение, аппаратные ловушки) НЕ собирались. ИЗМЕРЕНО: на 43 реальных
провалах MBPP+ **43/43 содержат вызов функции**.

ГЕЙТ ПРОВЕРЯЕТ ПЯТЬ СВОЙСТВ, и три из них — про ЗВУЧИМОСТЬ, а не про пользу:

  1. ПОЗИТИВ (`positive.py`): `caller` зовёт `helper` -> контракт ДОКАЗАН.
     Без инлайнинга здесь `НЕ РЕШЕНО`/`ЛОЖНАЯ ТРЕВОГА` (вызов = `_havoc`).
  2. НЕГАТИВ (`negative.py`): баг ВНУТРИ `helper` -> контракт ОПРОВЕРГНУТ и
     контрпример ТОЧНЫЙ (`n = 1, result = 3`). Это доказывает, что тело `helper`
     РЕАЛЬНО подставлено, а не «угадано».
  3. КОЛЛИЗИЯ ИМЁН (`collide.py`) — ПРАВИЛО 1, главный тест. `extra` внутри
     `helper` — СВОБОДНАЯ переменная; если инлайнинг наследует окружение
     вызывающего, она свяжется с локальной `extra = 5` из `caller`, и контракт
     ЛОЖНО докажется. Гейт ТРЕБУЕТ, чтобы `[PASS]` здесь НЕ было.
  4-5. РЕКУРСИЯ (`recursive.py`, `mutual.py`) — ПРАВИЛО 2. Стек вызовов обязан
     остановить развёртку. Гейт требует: НЕ падать (никакого `Traceback`) и НЕ
     объявлять нарушение.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы явно):

  * Инлайнинг работает в КОНТРАКТНОМ пути (`parse_file` + `body_smt`). Режим
    `--xray` для Python идёт ДРУГИМ путём — он транслирует только УСЛОВИЯ
    ветвлений и `body_smt` не вызывает. Поэтому на внешних репозиториях (где нет
    `@kern:`-аннотаций) воронка `--xray` этим шагом НЕ меняется — ИЗМЕРЕНО:
    `TheAlgorithms/Python/maths` 424/470 ДО и 424/470 ПОСЛЕ.
  * C-like путь (`_clike_stmts`) НЕ тронут: инлайнинг там не реализован, и
    воронка C этим шагом не меняется (`TheAlgorithms/C/math` 26/66 ДО и ПОСЛЕ).
  * Свободная переменная вызываемого объявляется как НЕОГРАНИЧЕННЫЙ символ
    (контракт опровергается). Это не `_havoc`-овер-аппроксимация: в Python такая
    переменная — настоящий NameError.

Запуск:  python3 tools/inline_check.py [--selftest]
Код возврата: 0 — все пять свойств держатся; 1 — иначе.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "tools" / "kern_contracts.py"
FIX = ROOT / "audits" / "inline"


def run(name: str) -> str:
    r = subprocess.run([sys.executable, str(EX), str(FIX / name)],
                       cwd=str(ROOT), capture_output=True, text=True,
                       timeout=600)
    return r.stdout + r.stderr


def checks() -> list[dict]:
    """Пять свойств Шага 1. Каждое — с ИЗМЕРЕННЫМ признаком."""
    out = []

    o = run("positive.py")
    out.append({"name": "1 позитив: helper+caller", "ok": "[PASS] caller" in o
                and "ДОКАЗАНО" in o, "detail":
                next((l.strip()[:80] for l in o.splitlines() if "[PASS]" in l),
                     next((l.strip()[:80] for l in o.splitlines()
                           if "[FAIL]" in l), "<нет вердикта>"))})

    o = run("negative.py")
    # Требуем И нарушение, И ТОЧНЫЙ контрпример: это доказывает, что тело
    # `helper` реально подставлено.
    out.append({"name": "2 негатив: баг внутри helper",
                "ok": "[FAIL] caller" in o and "[КОНТРПРИМЕР]" in o
                and "n = 1" in o, "detail":
                next((l.strip()[:80] for l in o.splitlines()
                      if "[КОНТРПРИМЕР]" in l), "<контрпримера нет>")})

    o = run("collide.py")
    # ПРАВИЛО 1: ложного PROVEN быть не должно НИ ПРИ КАКИХ обстоятельствах.
    out.append({"name": "3 КОЛЛИЗИЯ ИМЁН: ложное PROVEN запрещено",
                "ok": "[PASS] caller" not in o, "detail":
                next((l.strip()[:80] for l in o.splitlines()
                      if "[КОНТРПРИМЕР]" in l),
                     next((l.strip()[:80] for l in o.splitlines()
                           if "[FAIL]" in l or "НЕ РЕШЕНО" in l),
                          "<нет вердикта>"))})

    for nm, what in (("recursive.py", "4 прямая рекурсия"),
                     ("mutual.py", "5 взаимная рекурсия")):
        o = run(nm)
        no_crash = "Traceback" not in o
        no_violation = "нарушено 1" not in o
        out.append({"name": f"{what}: без краша и без ложного нарушения",
                    "ok": no_crash and no_violation, "detail":
                    ("краш!" if not no_crash else
                     ("ложное нарушение" if not no_violation
                      else "честный откат к _havoc (ЛОЖНАЯ ТРЕВОГА)"))})
    return out


def selftest() -> int:
    """Мета-тест: признаки обязаны быть ПРОВЕРЯЕМЫМИ.

    Ветки: (1) ложное `[PASS]` на коллизии обязано красить; (2) `Traceback`
    обязан красить; (3) ложное нарушение на рекурсии обязано красить;
    (4) корректный набор проходит.
    """
    bad = 0

    def ok_collide(o: str) -> bool:
        return "[PASS] caller" not in o

    def ok_rec(o: str) -> bool:
        return "Traceback" not in o and "нарушено 1" not in o

    if ok_collide("[PASS] caller: ДОКАЗАНО"):
        print("[FAIL] selftest: ложное PROVEN на коллизии НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: ложное PROVEN на коллизии ловится (правило 1)")
    if ok_rec("Traceback (most recent call last)"):
        print("[FAIL] selftest: Traceback НЕ пойман")
        bad += 1
    else:
        print("[OK] selftest: Traceback ловится (правило 2)")
    if ok_rec("ИТОГО: нарушено 1"):
        print("[FAIL] selftest: ложное нарушение на рекурсии НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: ложное нарушение ловится")
    if not (ok_collide("[FAIL] caller: КОНТРАКТ НАРУШЕН")
            and ok_rec("ИТОГО: нарушено 0")):
        print("[FAIL] selftest: корректный набор НЕ проходит")
        bad += 1
    else:
        print("[OK] selftest: корректный набор проходит")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] inline selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("=" * 76)
    print("KERN: ИНЛАЙНИНГ ВЫЗОВОВ ИЗ ТОГО ЖЕ ФАЙЛА (ШАГ 1) — 5 свойств")
    print("=" * 76)
    rows = checks()
    for r in rows:
        print(f"  [{'OK' if r['ok'] else 'FAIL'}] {r['name'][:52]:54}")
        print(f"        {r['detail']}")
    bad = [r for r in rows if not r["ok"]]
    print("-" * 76)
    if bad:
        print(f"[FAIL] свойств не держится: {len(bad)} из {len(rows)}")
        return 1
    print(f"[OK] все {len(rows)} свойств держатся: инлайнинг работает, "
          f"гигиена имён защищает от ложного PROVEN, рекурсия не роняет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
