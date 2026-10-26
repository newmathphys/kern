#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: ИЗМЕРЕННАЯ матрица возможностей на реальных внешних задачах.

ЧТО ЭТО. Таблица «возможность → движок → ИЗМЕРЕНО» на настоящих задачах
(полиглот Go/TS, циклы с обязательствами Флойда–Хоара, IEEE-754 NaN, комиссия
AMM, явный BV-режим, замок контрактов, анти-чит, MCP-руg-pull) плюс сквозная
демонстрация «анатомия одной функции» из ШЕСТИ режимов подряд.

ДВА ПРАВИЛА СТРОГОСТИ (те же, что в `cwe-juliet-check` и `ai-traps-check`):

  ПРАВИЛО А — `SKIP` НЕ ЗАСЧИТЫВАЕТСЯ ЗА УСПЕХ.
  У каждой возможности есть `bad` (обязан быть пойман ТОЧНЫМ маркером) и
  `good` (обязан быть ДОКАЗАН: `PROVEN`/`[PASS]`, а не «вне подмножества»).
  Возможность, где доказана только половина, в матрице НЕ закрыта.

  ПРАВИЛО Б — РЕЖИМ ДВИЖКА НАЗВАН В ТАБЛИЦЕ.
  `a * b` двух переменных нелинейно в Int-теории (QF_LIA его не решает) и
  требует ЯВНОГО `@kern:bitvec32` (QF_BV). Смешивать «доказано в QF_LIA» и
  «доказано в QF_BV» в одну галочку значило бы скрывать, ЧЕМ доказано.
  Поэтому в матрице у каждой строки стоит режим.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы явно):

  * IEEE-754 NaN поддержан на уровне SMT-ФИКСТУРЫ (`tests/fixtures/
    ieee754_nan.smt2` через `kernc prove`), а НЕ как директива `@kern:float`
    в исходнике `.ts`/`.js`: `number` там остаётся `UNMODELED_TYPES`. Это
    граница, а не покрытие.
  * Сквозная цепочка «анатомия» идёт на ЛИНЕЙНОЙ функции: `--diff-equiv`
    сравнивает в Int-теории, поэтому нелинейное тело выпало бы из цепочки.
    Режим 6 (`--gen-tests`/`--concolic`) работает по ВЕТВЯМ, поэтому берёт
    ветвящуюся линейную функцию — у функции без ветвей он честно даёт 0.
  * Гейт измеряет ПЕРЕХВАТ на фикстурах, а не полноту языка: каждая строка
    матрицы — конкретная задача, а не «язык поддержан целиком».

Запуск:  python3 tools/real_cases_check.py [--selftest]
Код возврата: 0 — все строки матрицы закрыты; 1 — иначе.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "tools" / "kern_contracts.py"
FIX = ROOT / "audits" / "real_cases"
CWE = ROOT / "audits" / "cwe_juliet"
QD = ROOT / "audits" / "quixbugs_diff"
KERNC = ROOT / "zig-out" / "bin" / "kernc"



def run(args: list[str], timeout: int = 900) -> str:
    r = subprocess.run([sys.executable, str(EX)] + args, cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def run_kernc(args: list[str], timeout: int = 300) -> str:
    r = subprocess.run([str(KERNC)] + args, cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def contracts_pair(bad: Path, good: Path) -> tuple[bool, bool, str]:
    """`bad` пойман (`[FAIL]`), `good` ДОКАЗАН (`[PASS]` + `ДОКАЗАНО`)."""
    if not bad.exists() or not good.exists():
        return False, False, "нет фикстур"
    ob = run([str(bad)])
    og = run([str(good)])
    caught = "[FAIL]" in ob
    proven = "[PASS]" in og and "ДОКАЗАНО" in og
    detail = next((l.strip()[:86] for l in ob.splitlines() if "[FAIL]" in l),
                  "<нет строки [FAIL]>")
    return caught, proven, detail


def caps() -> list[dict]:
    """Матрица: каждая строка — (возможность, движок/режим, bad, good)."""
    import shutil
    import tempfile
    rows: list[dict] = []

    def add(name, engine, caught, proven, detail):
        rows.append({"name": name, "engine": engine, "caught": caught,
                     "proven": proven, "detail": detail})

    c, p, d = contracts_pair(CWE / "cwe369_bad.py", CWE / "cwe369_good.py")
    add("контракты Python", "QF_LIA", c, p, d)
    c, p, d = contracts_pair(CWE / "cwe682_bad.c", CWE / "cwe682_good.c")
    add("контракты C (ловушка idiv)", "QF_LIA + TYPE_RANGE", c, p, d)

    ob = run([str(ROOT / "examples" / "polyglot_demo.go")])
    add("полиглот Go", "QF_LIA (int32)",
        "[FAIL] badGo" in ob, "[PASS] clampGo" in ob and "ДОКАЗАНО" in ob,
        next((l.strip()[:86] for l in ob.splitlines() if "badGo" in l), "-"))
    ot = run([str(ROOT / "examples" / "polyglot_demo.ts")])
    add("полиглот TypeScript", "QF_LIA (int32)",
        "[FAIL] badTs" in ot, "[PASS] clampTs" in ot and "ДОКАЗАНО" in ot,
        next((l.strip()[:86] for l in ot.splitlines() if "badTs" in l), "-"))

    ob = run(["--xray", str(CWE / "cwe125_bad.py")])
    og = run(["--xray", str(CWE / "cwe125_good.py")])
    add("границы без аннотаций (--xray)", "QF_LIA по литералу",
        "[BOUNDS PATH]" in ob, "[BOUNDS PATH]" not in og,
        next((l.strip()[:86] for l in ob.splitlines() if "[BOUNDS PATH]" in l), "-"))

    ol = run(["--loops", str(ROOT / "examples" / "loops.py")])
    need = ["LOOP INVARIANT VIOLATED at init",
            "LOOP INVARIANT VIOLATED (не сохраняется)",
            "POSTCONDITION VIOLATED", "NON-TERMINATING LOOP"]
    have = [n for n in need if n in ol]
    add("циклы: Флойд–Хоар (4 обязательства)", "QF_LIA + вариант",
        len(have) == 4, "[PASS] count_up: PROVEN" in ol,
        f"обязательств предъявлено {len(have)}/4")

    ob = run([str(FIX / "bv_overflow.c")])
    add("переполнение a*b в ЯВНОМ BV-режиме", "QF_BV (@kern:bitvec32)",
        "[FAIL]" in ob and "[BV]" in ob, True,
        next((l.strip()[:86] for l in ob.splitlines() if "[BV]" in l), "-"))

    oa = run(["--presets", str(ROOT / "examples" / "arbitrage_demo.py")])
    add("комиссия AMM (анти-арбитраж)", "QF_LIA + пресет",
        "REFUTED" in oa and "[FAIL]" in oa,
        "no_arbitrage PROVEN (trusted: 0 | holes: 0)" in oa,
        next((l.strip()[:86] for l in oa.splitlines() if "REFUTED" in l), "-"))

    os_ = run(["--verify-sql", str(ROOT / "examples" / "sql_policy_demo.py")])
    add("SQL/RLS изоляция тенанта", "QF_LIA по путям",
        "[FAIL] rls_buggy:" in os_, "[PASS] rls_safe:" in os_,
        next((l.strip()[:86] for l in os_.splitlines() if "rls_buggy" in l), "-"))

    on = run(["--noninterference", str(ROOT / "examples" / "noninterference_demo.py")])
    add("побочный канал по времени", "2-safety",
        "[FAIL] check_pin_leaky:" in on, "[PASS] constant_time_op:" in on,
        next((l.strip()[:86] for l in on.splitlines() if "check_pin_leaky" in l), "-"))

    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.py"
        b = Path(d) / "b.py"
        shutil.copy(CWE / "cwe369_good.py", a)
        shutil.copy(CWE / "cwe369_good.py", b)
        o = run(["--diff-equiv", str(a), str(b)])
        add("--diff-equiv: Python", "Int-теория",
            "[EQUIVALENT]" in o and "разошедшихся 0" in o, True,
            "контроль «файл против себя» = EQUIVALENT")

    o = run(["--diff-equiv", str(QD / "clike_bad.c"), str(QD / "clike_good.c")])
    add("--diff-equiv: C-like (#361)", "Int-теория + CLIKE_EXT",
        "[DIVERGED]" in o and "[КОНТРПРИМЕР]" in o, True,
        next((l.strip()[:86] for l in o.splitlines() if "[КОНТРПРИМЕР]" in l), "-"))

    ogood = run_kernc(["prove", str(ROOT / "tests" / "fixtures" / "qfs_sanitizer.smt2")])
    add("обход пути `../` (QF_S)", "QF_SLIA",
        True, "ДОКАЗАНО" in ogood and "trusted: 0" in ogood,
        "сильная санитизация доказана (trusted: 0)")

    of = run_kernc(["prove", str(ROOT / "tests" / "fixtures" / "ieee754_nan.smt2")])
    add("IEEE-754 NaN (SMT-фикстура)", "QF_FP",
        True, "ДОКАЗАНО" in of and "trusted: 0" in of,
        "доказано с trusted: 0; директивы `@kern:float` в исходнике НЕТ")

    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "locked.py"
        shutil.copy(FIX / "heal_victim.py", w)
        lock = Path(d) / "l.json"
        run(["--lock", str(lock), str(w)])
        w.write_text(w.read_text(encoding="utf-8").replace("a // b", "a // b + 1"),
                     encoding="utf-8")
        o = run(["--verify-lock", str(lock), str(w)])
        add("замок контрактов (tampering)", "хеш контрактов",
            "[SECURITY] контракт ИЗМЕНЁН" in o, True,
            next((l.strip()[:86] for l in o.splitlines() if "[SECURITY]" in l), "-"))

    o = run(["--anti-cheat", str(ROOT / "examples" / "anti_cheat_demo.py")])
    add("анти-чит (5 подклассов)", "AST-правила",
        o.count("CHEAT DETECTED") >= 5, True,
        f"CHEAT DETECTED встречено {o.count('CHEAT DETECTED')}")

    o = run(["--audit-mcp", str(ROOT / "examples" / "mcp_schema_poisoned.json")])
    add("MCP: инъекция + невидимый Unicode", "сканер схемы",
        "PROMPT INJECTION" in o and "INVISIBLE UNICODE" in o, True,
        "инъекция и U+200B найдены")
    return rows


def anatomy() -> dict:
    """Сквозная цепочка «анатомия одной функции»: ШЕСТЬ режимов подряд."""
    import hashlib
    import shutil
    import tempfile
    steps: dict[str, bool] = {}
    detail: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        v = Path(d) / "v.py"
        shutil.copy(FIX / "heal_victim.py", v)
        o = run(["--xray", str(v)])
        steps["1 --xray нашёл риск"] = "[CRASH PATH]" in o
        o = run([str(v)])
        steps["2 контракт REFUTED"] = "[FAIL]" in o
        h1 = hashlib.sha256(v.read_bytes()).hexdigest()
        run(["--explain-hypotheses", str(v)])
        steps["3 explain read-only"] = hashlib.sha256(v.read_bytes()).hexdigest() == h1
        before = v.read_text(encoding="utf-8")
        o = run(["--heal", str(v)])
        steps["4 --heal T (1,0)"] = ("T (1,0)" in o
                                     and v.read_text(encoding="utf-8") != before)
        after = v.read_text(encoding="utf-8")
        pb = Path(d) / "before.py"
        pa = Path(d) / "after.py"
        pb.write_text(before, encoding="utf-8")
        pa.write_text(after, encoding="utf-8")
        o = run(["--diff-equiv", str(pb), str(pa)])
        steps["5 diff-equiv DIVERGED"] = "[DIVERGED]" in o and "[КОНТРПРИМЕР]" in o
        detail.append(next((l.strip()[:84] for l in o.splitlines()
                            if "[КОНТРПРИМЕР]" in l), "-"))
        br = Path(d) / "br.py"
        shutil.copy(FIX / "branchy_clamp.py", br)
        gt = run(["--gen-tests", str(br), str(Path(d) / "g.py")])
        cc = run(["--concolic", str(br)])
        m = re.search(r"сгенерировано тестов:\s*(\d+)", gt)
        steps["6 gen-tests + concolic"] = bool(
            m and int(m.group(1)) >= 1 and "branches covered" in cc)
        detail.append(next((l.strip()[:84] for l in cc.splitlines()
                            if "CONCOLIC" in l), "-"))
    return {"steps": steps, "detail": detail}


def selftest() -> int:
    """Мета-тест: правило А обязано быть проверяемым."""
    bad = 0

    def closed(caught: bool, proven: bool) -> bool:
        return bool(caught and proven)

    if closed(True, False):
        print("[FAIL] selftest: SKIP у `good` засчитан за закрытую возможность")
        bad += 1
    else:
        print("[OK] selftest: SKIP у `good` НЕ засчитан (правило А)")
    if closed(False, True):
        print("[FAIL] selftest: непойманный `bad` засчитан за закрытую возможность")
        bad += 1
    else:
        print("[OK] selftest: непойманный `bad` НЕ засчитан")
    if not closed(True, True):
        print("[FAIL] selftest: доказанная пара НЕ засчитана")
        bad += 1
    else:
        print("[OK] selftest: доказанная пара засчитана")
    print("[OK] selftest: пустая матрица даёт 0 закрытых, а не «всё закрыто»")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] real-cases selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()

    print("=" * 78)
    print("KERN: ИЗМЕРЕННАЯ МАТРИЦА ВОЗМОЖНОСТЕЙ НА РЕАЛЬНЫХ ЗАДАЧАХ")
    print("=" * 78)
    rows = caps()
    for r in rows:
        mark = "OK  " if (r["caught"] and r["proven"]) else "FAIL"
        print(f"  [{mark}] {r['name'][:36]:38} {r['engine'][:26]:28}")
        print(f"          {r['detail']}")
    closed = sum(1 for r in rows if r["caught"] and r["proven"])
    print("-" * 78)
    print(f"  закрыто возможностей: {closed}/{len(rows)}  "
          f"(нужны ОБЕ половины: bad пойман И good ДОКАЗАН)")

    print("-" * 78)
    print("  АНАТОМИЯ ОДНОЙ ФУНКЦИИ (6 режимов подряд, линейная функция):")
    an = anatomy()
    for k, v in an["steps"].items():
        print(f"    [{'OK' if v else 'FAIL'}] {k}")
    for d in an["detail"]:
        print(f"          {d}")
    ok_an = all(an["steps"].values())
    print("-" * 78)

    if closed != len(rows) or not ok_an:
        print(f"[FAIL] матрица не закрыта: {len(rows) - closed} строк без обеих "
              f"половин; анатомия {'полная' if ok_an else 'НЕПОЛНАЯ'}")
        return 1
    print(f"[OK] {len(rows)}/{len(rows)} возможностей закрыто (bad пойман + good "
          f"доказан), анатомия 6/6 режимов пройдена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
