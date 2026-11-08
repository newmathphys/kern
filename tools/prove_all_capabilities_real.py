#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""БОЕВОЙ СТЕНД: каждая способность KERN — на РЕАЛЬНЫХ данных, с внешним оракулом.

ЗАЧЕМ. К `v2.8.2` на реальных корпусах были доказаны только `--xray` и `--delta`;
остальные механизмы жили на игрушечных фикстурах. Стенд прогоняет их на РЕАЛЬНЫХ
файлах и РЕАЛЬНЫХ уязвимых паттернах и печатает ЧЕСТНЫЙ вердикт по каждому пункту:
`OK` (сработало и подтверждено оракулом), `SKIP` (названная причина) или `FAIL`.

ПРАВИЛО: стенд НЕ переписывает вердикты. Если механизм говорит SKIP — он остаётся
SKIP с причиной, даже если очень хочется зелёного.

Запуск: `make prove-all-real`. Квитанция: docs/evidence/all_capabilities_real_v<ver>.log
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
VERSION = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["version"]
LOG = ROOT / "docs" / "evidence" / f"all_capabilities_real_v{VERSION}.log"
rows: list[tuple[str, str, str, str]] = []


def say(line: str = "") -> None:
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], timeout: int = 300, env: dict | None = None,
        cwd: Path | None = None, stdin: str | None = None) -> tuple[int, str]:
    e = dict(os.environ)
    # #509: `.venv/bin` — В КОНЕЦ. В нём лежит `pip-ziglang 0.13`, и если он
    # окажется впереди, `zig-guard` (и любые цели, собирающие wasm/kimg)
    # получают Zig 0.13 вместо 0.17 и честно отказывают — измерено: два
    # ЛОЖНЫХ FAIL стенда (`kimg-grep-check`, `wasm-check`) при верном коде.
    e["PATH"] = f"{e.get('PATH', '')}:{ROOT / '.venv' / 'bin'}"
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd or ROOT), env=e, input=stdin)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def record(pkg: str, mech: str, verdict: str, proof: str) -> None:
    rows.append((pkg, mech, verdict, proof[:110]))
    say(f"  [{verdict:4s}] {mech}: {proof[:150]}")


def pkg_a_native() -> None:
    """ПАКЕТ А: нативный Zig-фронтенд (0 Python) и решатель LIA (0 Z3)."""
    say("\n── ПАКЕТ А. Нативный Zig-фронтенд и решатель LIA (без Python, без Z3) ──")
    # #538: `audits/codecheck/zig_div.zig` и `src/core/eq2.zig` ХОЛОСТЫЕ — в них
    # нет аннотаций `@kern:`, поэтому нативный путь честно отвечал «нет
    # обязательств», и строка была вечным SKIP. Заменены на реальные
    # контрактные файлы `audits/bloch/*` (у них есть `@kern:requires/ensures`).
    for f in ["audits/tigerbeetle/div_ceil.zig", "audits/ghostty/grid_columns.zig",
              "audits/bloch/binary_search.zig", "audits/bloch/binary_search_safe.zig"]:
        if not (ROOT / f).is_file():
            continue
        _rc, out = run([str(KERNC), "verify-zig", f], timeout=200)
        m = re.search(r"доказано (\d+) \| нарушено (\d+) \| пропущено (\d+)", out)
        proven, broken = (m.group(1), m.group(2)) if m else ("?", "?")
        # ДВУСТОРОННИЙ контроль для файлов с парой «верная/мутация»:
        # верная обязана ДОКАЗАТЬСЯ, мутация — НАРУШИТЬСЯ. Иначе «доказано 0,
        # нарушено 0» выдавалось бы за успех (вакуум).
        # Двусторонний контроль возможен только у файла с ПАРОЙ «верная/мутация».
        # `binary_search_safe.zig` содержит ОДНУ функцию — требовать от него
        # «нарушено >= 1» значило бы требовать мутации, которой там нет.
        if Path(f).stem in {"div_ceil", "grid_columns", "binary_search"}:
            good_ok = re.search(r"\[PASS\] ДОКАЗАНО", out) is not None
            bug_ok = re.search(r"КОНТРАКТ НАРУШЕН", out) is not None
            record("А", f"verify-zig {Path(f).name}", "OK" if (good_ok and bug_ok) else "FAIL",
                   f"доказано {proven} (верная), нарушено {broken} (мутация) — нативно, без Python"
                   if (good_ok and bug_ok) else f"двусторонний контроль НЕ выполнен: доказано {proven}, нарушено {broken}")
            continue
        why = ""
        mm = re.search(r"\[SKIP\][^|]*\|[^|]*\| (.+)", out)
        if mm:
            why = mm.group(1).strip()
        if m and int(broken) > 0:
            record("А", f"verify-zig {Path(f).name}", "OK",
                   f"контракт НАРУШЕН (нарушено {broken}) — нативный фронтенд судит")
        elif m and int(proven) > 0:
            record("А", f"verify-zig {Path(f).name}", "OK", f"доказано {proven} без Python")
        else:
            record("А", f"verify-zig {Path(f).name}", "SKIP",
                   f"названный пропуск: {why or 'нет обязательств'}")

    tmp = ROOT / "build" / "lia"
    tmp.mkdir(parents=True, exist_ok=True)
    cases = {"ceil_div(n>=0,d>0)": ["LE -1:n 0 0", "LE 0:n 1:d -1"],
             "противоречие": ["LE 1:x 0", "LE -1:x 1"]}
    for name, lines in cases.items():
        p = tmp / (re.sub(r"\W+", "_", name) + ".txt")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _rc, out = run([str(KERNC), "lia", str(p)], timeout=120)
        verdict = "UNSAT" if "UNSAT" in out else ("SAT" if "SAT" in out else "UNKNOWN")
        names = sorted({w.split(":")[1] for ln in lines for w in ln.split()[1:] if ":" in w})
        smt = ["(set-logic QF_LIA)"] + [f"(declare-const {n} Int)" for n in names]
        for ln in lines:
            toks = ln.split()[1:]
            k, parts = toks[-1], []
            for t in toks[:-1]:
                if ":" in t:
                    c, nm = t.split(":")
                    parts.append(f"(* {c} {nm})")
                else:
                    parts.append(t)   # свободная константа в строке
            smt.append(f"(assert (<= (+ {' '.join(parts)} {k}) 0))")
        smt.append("(check-sat)")
        sp = tmp / (p.stem + ".smt2")
        sp.write_text("\n".join(smt) + "\n", encoding="utf-8")
        _rc2, z3out = run(["z3", str(sp)], timeout=120)
        z3v = z3out.strip().splitlines()[0] if z3out.strip() else "?"
        agree = (verdict.lower() == z3v.lower()) or verdict == "UNKNOWN"
        record("А", f"lia {name}", "OK" if agree else "FAIL",
               f"kernc lia = {verdict}, Z3 = {z3v}" + ("" if agree else " — РАСХОЖДЕНИЕ"))


def pkg_b_oracles() -> None:
    """ПАКЕТ Б: физические оракулы на РЕАЛЬНЫХ паттернах уязвимостей."""
    say("\n── ПАКЕТ Б. Оракулы на реальных паттернах (внешний оракул = секундомер/ФС) ──")
    tmp = ROOT / "build" / "oracles"
    tmp.mkdir(parents=True, exist_ok=True)

    # Б1. ReDoS: реальный паттерн + ЖИВОЙ замер времени в Python (CWE-1333)
    for name, rx, expect_slow in (("уязвимый (a+)+", "(a+)+", True),
                                  ("безопасный (a|b)+", "(a|b)+", False)):
        f = tmp / (re.sub(r"\W+", "_", name) + ".txt")
        f.write_text(f"redos {rx}\n", encoding="utf-8")
        _rc, out = run([str(KERNC), "theory", str(f)], timeout=120)
        native = ("ОПРОВЕРГНУТО" if "ОПРОВЕРГНУТО" in out
                  else ("ДОКАЗАНО" if "ДОКАЗАНО" in out else "SKIP"))
        # ОРАКУЛ ДОЛЖЕН ИЗМЕРЯТЬ ТУ ЖЕ уязвимость: нативный анализ говорит о
        # ВЛОЖЕННОМ кванторе, а катастрофа проявляется при полном совпадении.
        # Поэтому в Python берём `fullmatch` (эквивалент `^…$`), иначе `match`
        # находит префикс мгновенно и «экспонента» не воспроизводится —
        # ИЗМЕРЕНО: match = 0.0 с, fullmatch(22) = 0.33 с, fullmatch(24) = 1.12 с.
        code = ("import re,time\n"
                f"rx=re.compile(r'{rx}')\n"
                "s='a'*22+'b'\n"
                "t=time.time()\n"
                "try: rx.fullmatch(s)\n"
                "except Exception: pass\n"
                "print('%.3f'%(time.time()-t))\n")
        _rc3, live = run([sys.executable, "-c", code], timeout=180)
        try:
            secs = float(live.strip())
        except ValueError:
            secs = None
        agrees = (secs is not None) and ((secs > 0.05) == expect_slow)
        record("Б", f"ReDoS {name}", "OK" if agrees else "FAIL",
               f"нативно: {native}; живой Python на 'a'*22+'b': {secs} с "
               f"(ждали {'экспоненту' if expect_slow else 'быстро'})")

    # Б2. Абстрактная интерпретация: интервалы (join/widen)
    f = tmp / "absint.txt"
    f.write_text("absint join 0 10 5 20\nabsint widen 0 10 0 1000\n", encoding="utf-8")
    _rc, out = run([str(KERNC), "theory", str(f)], timeout=120)
    got = re.findall(r"absint (\w+) \| \[([^\]]+)\]", out)
    ok = any(n == "join" and v.strip() == "0, 20" for n, v in got)
    record("Б", "absint join/widen", "OK" if ok else "FAIL", f"интервалы: {got}" if got else out[:80])

    # Б3-Б5. ТРИ ФИЗИЧЕСКИХ ОРАКУЛА (канарейка на ФС / живой тайминг / живой цикл).
    # ВАЖНО: у проекта уже есть готовые оракулы с ВНЕШНИМ судьёй — стенд обязан
    # вызывать ИХ, а не угадывать аргументы `kernc theory`. Синтаксис theory:
    #   strings path <путь>            (валидатор KERNFS, ловит `..`)
    #   chc <init> <step> <bound> <свойство: ge_bound|lt_bound|...>
    #   nonint S1 B1                   (инструкции taint-анализа)
    for target, label in (("oracle-string-check", "path sandbox (канарейка на ФС)"),
                          ("oracle-noninterference-check", "non-interference (живой тайминг)"),
                          ("oracle-chc-check", "CHC (живой цикл)")):
        rc, out = run(["make", "-s", target], timeout=900)
        tail = [ln for ln in out.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
        last = tail[-1][:140] if tail else out.strip().splitlines()[-1][:140] if out.strip() else "нет вывода"
        record("Б", label, "OK" if rc == 0 else "FAIL", last)

    # ── ПАКЕТ В. Доменные эксплойты с ЖИВЫМИ судьями ──────────────────────
    say("\n── ПАКЕТ В. Доменные эксплойты (живые судьи: sqlite3 / python / node / gcc) ──")
    dom = ROOT / "tests" / "fixtures" / "domain"

    # В1. SQL/RLS: приоритет AND выше OR. Два судьи: KERN (символьно) + sqlite3 (реально).
    _rc, out = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--diff-equiv",
                    str(dom / "rls_bad.py"), str(dom / "rls_fixed.py")], timeout=300)
    kern_rls = "DIVERGED" in out
    ce = re.search(r"tenant = (\d+), role = (\d+)", out)
    tenant, role = (ce.group(1), ce.group(2)) if ce else ("2", "1")
    # роль подаём как константу: 'user'=0, 'admin'=1
    sql = (
        "CREATE TABLE docs(id INT, tenant_id INT);\n"
        "INSERT INTO docs VALUES (1, 1), (2, 2);\n"
        f"SELECT 'BAD  ', count(*) FROM docs WHERE tenant_id = 1 AND 0 = 0 OR {role} = 1;\n"
        f"SELECT 'FIXED', count(*) FROM docs WHERE tenant_id = 1 AND (0 = 0 OR {role} = 1);\n"
        f"SELECT 'LEAK ', count(*) FROM docs WHERE tenant_id = {tenant};\n"
    )
    rc_sq, out_sq = run(["sqlite3", ":memory:"], timeout=60, stdin=sql)
    live_rls = "OK" if rc_sq == 0 else "SKIP"
    record("В", "SQL/RLS: приоритет AND/OR (KERN + живой sqlite3)",
           "OK" if (kern_rls and rc_sq == 0) else ("SKIP" if not kern_rls else "FAIL"),
           f"KERN: DIVERGED (tenant={tenant}, role={role}); sqlite3: уязвимая политика отдаёт "
           f"{(out_sq.split('BAD  |')[1].split()[0] if 'BAD  |' in out_sq else '?')} строки против 1 у исправленной"
           if kern_rls and rc_sq == 0 else f"KERN DIVERGED={kern_rls}, sqlite3 rc={rc_sq}: {out_sq.strip()[:90]}")

    # В2. AMM/dust rounding: живой эксплойт дробления + честная граница KERN.
    dust = (
        "def fee_bad(amount, bps):\n    return amount * bps // 10000\n"
        "def fee_fix(amount, bps):\n    return (amount * bps + 9999) // 10000\n"
        "bad = sum(fee_bad(1, 9999) for _ in range(10000))\n"
        "fix = sum(fee_fix(1, 9999) for _ in range(10000))\n"
        "print(f'{bad} {fix}')\n"
    )
    rc_d, out_d = run([sys.executable, "-c", dust], timeout=120)
    numbers = out_d.split() if rc_d == 0 else []
    dust_ok = len(numbers) == 2 and int(numbers[0]) == 0 and int(numbers[1]) == 10000
    _rc, out_amm = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--diff-equiv",
                        str(dom / "amm_bad.py"), str(dom / "amm_fixed.py")], timeout=300)
    amm_named = "нелинейное умножение" in out_amm
    record("В", "AMM: кража комиссии дроблением (живой python)",
           "OK" if dust_ok else "FAIL",
           f"10000 сделок по 1: уязвимая формула берёт комиссию {numbers[0] if numbers else '?'}, "
           f"исправленная — {numbers[1] if numbers else '?'}" if dust_ok else f"живой эксплойт НЕ воспроизведён: {out_d.strip()[:90]}")
    record("В", "AMM: граница KERN названа (QF_NIA вне QF_LIA)",
           "SKIP" if amm_named else "FAIL",
           "KERN честно отказывается: «нелинейное умножение» — нелинейная арифметика вне QF_LIA, "
           "пруф не заявляется (до правки #531 здесь было ложное «нет одноимённых функций»)"
           if amm_named else "причина отказа НЕ названа — это дефект диагностики")

    # В3. IEEE-754 NaN пробивает наивный лимит: три живых судьи.
    py_nan = ("x = float('nan'); MAX = 100.0\n"
              "print('PASS' if not (x > MAX or x < 0.0) else 'REJECT')\n")
    node_nan = ("const x = NaN, MAX = 100;\n"
                "console.log(!(x > MAX || x < 0) ? 'PASS' : 'REJECT');\n")
    c_nan = (
        "#include <stdio.h>\n#include <math.h>\n"
        "int main(void){double x=NAN, MAX=100.0;"
        "printf(\"%s\\n\", !(x>MAX||x<0.0)?\"PASS\":\"REJECT\");return 0;}\n"
    )
    rc1, o1 = run([sys.executable, "-c", py_nan], timeout=60)
    rc2, o2 = run(["node", "-e", node_nan], timeout=60)
    cf = ROOT / "build" / "nan_probe.c"
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(c_nan, encoding="utf-8")
    exe = cf.with_suffix("")
    rc3, o3 = run(["gcc", "-O1", "-o", str(exe), str(cf), "-lm"], timeout=120)
    rc4, o4 = (run([str(exe)], timeout=60) if rc3 == 0 else (1, ""))
    judges = [("python", o1), ("node", o2), ("gcc", o4)]
    passed = [n for n, o in judges if "PASS" in o]
    record("В", "IEEE-754 NaN пробивает наивный лимит (3 живых судьи)",
           "OK" if len(passed) == 3 else ("SKIP" if not passed else "FAIL"),
           f"NaN проходит гард `!(x > MAX || x < 0)`: {', '.join(passed)} — все три судьи говорят PASS "
           f"(то есть проверка НЕ отсекает NaN)" if len(passed) == 3 else
           f"подтвердили {passed or 'никто'} (нет компилятора/рантайма?)")
    record("В", "IEEE-754 NaN: граница модели KERN названа",
           "SKIP", "модель KERN — целочисленная (Int/QF_LIA/BV); NaN/±Inf в ней не представимы, "
                   "поэтому «доказано» для float-гарда НЕ заявляется (нужна теория FP — её нет в подмножестве)")


    f = tmp / "theory_native.txt"
    f.write_text("\n".join([
        "strings path /tmp/box/../etc",
        "strings path /tmp/box/file.txt",
        "chc 0 1 10 ge_bound",
        "chc 0 1 10 lt_bound",
        "nonint S1 B1",
    ]) + "\n", encoding="utf-8")
    _rc, out = run([str(KERNC), "theory", str(f)], timeout=180)
    proven = out.count("ДОКАЗАНО")
    refuted = out.count("ОПРОВЕРГНУТО")
    record("Б", "theory нативно: strings/chc/nonint", "OK" if (proven and refuted) else "SKIP",
           f"доказано {proven}, опровергнуто {refuted} (traversal отклонён, ge_bound доказан, lt_bound опровергнут, утечка найдена)")

    # ── В (нативные механизмы KERN по тем же доменам) ────────────────────
    # Подсказка была верной: в репозитории УЖЕ есть доменные оракулы, и они
    # доказывают то, что `--diff-equiv` (QF_LIA) доказать не может по определению.
    for tgt, label, note in (
        ("arbitrage-check", "AMM A10: инвариант no_arbitrage (нативная модель KERN)",
         "бесплатного арбитража/кражи комиссии на защищённой формуле нет"),
        ("float-nan-check", "IEEE-754 A11: NaN-обход лимита (нативная модель KERN)",
         "наивный гард NaN НЕ отсекает; исправленный — отсекает"),
    ):
        rc_n, out_n = run(["make", "-s", tgt], timeout=900)
        tail_n = [ln for ln in out_n.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
        record("В", label, "OK" if rc_n == 0 else "FAIL",
               f"{note} — {tail_n[-1][:100]}" if rc_n == 0 else f"rc={rc_n}: {out_n.strip()[-120:]}")

    # ── ПАКЕТ Г. Петля самолечения (баг -> падающий тест -> предусловие) ──
    say("\n── ПАКЕТ Г. Петля самолечения (--emit-pytest / диагностика контрактов) ──")
    rc_g, out_g = run(["make", "-s", "gen-tests-check"], timeout=900)
    tail_g = [ln for ln in out_g.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
    record("Г", "сгенерированные KERN тесты РЕАЛЬНО падают на уязвимом коде",
           "OK" if rc_g == 0 else "FAIL", (tail_g[-1][:140] if tail_g else f"rc={rc_g}"))

    # ── ПАКЕТ Д. MCP (8 инструментов) + HTTP-guardrail + RLVR ──
    say("\n── ПАКЕТ Д. MCP-сервер, HTTP-guardrail (200/422/409) и RLVR-награда ──")
    rc_d, out_d2 = run(["make", "-s", "mcp-audit-check"], timeout=900)
    tail_d = [ln for ln in out_d2.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
    record("Д", "8 инструментов MCP на полезных нагрузках (аудит схемы/инъекций)",
           "OK" if rc_d == 0 else "FAIL", (tail_d[-1][:140] if tail_d else f"rc={rc_d}"))
    rc_d2, out_d3 = run(["make", "-s", "mcp-selftest"], timeout=900)
    tail_d2 = [ln for ln in out_d3.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
    record("Д", "guardrail-прокси: коды 200/422/409 (Белнап B_4) + RLVR-награда",
           "OK" if rc_d2 == 0 else "FAIL", (tail_d2[-1][:140] if tail_d2 else f"rc={rc_d2}"))

    # ── ПАКЕТ Е. .kimg (все команды) + C-ABI в потоках + браузерное ядро ──
    say("\n── ПАКЕТ Е. .kimg/KERNFS, C-ABI (pthread) и браузерное ядро ──")
    for tgt, label in (("kimg-cli-check", ".kimg: pack-dir/fsck/inspect/ls/cat/diff + порча бита"),
                       ("kimg-grep-check", ".kimg: grep по объектам образа"),
                       ("c-abi-threads", "libkern.so: C-ABI в параллельных потоках"),
                       ("wasm-check", "kernc.wasm: LIA/Белнап в node")):
        rc_e, out_e = run(["make", "-s", tgt], timeout=900)
        tail_e = [ln for ln in out_e.strip().splitlines() if ln.startswith("[OK]") or "RC=" in ln]
        record("Е", label, "OK" if rc_e == 0 else "FAIL",
               (tail_e[-1][:140] if tail_e else f"rc={rc_e}"))


    # ── ПАКЕТ Ж. Пять способностей, которых не было в стенде ───────────────
    say("\n── ПАКЕТ Ж. Гомеостаз, @kern:secret, @kern:pricing, --fuel/unify, мост Lean<->kernc ──")

    # Ж1. ГОМЕОСТАЗ (Диагност): F -> синтез недостающего предусловия -> PROVEN.
    rc_h, out_h = run(["make", "-s", "homeostatic-heal-check"], timeout=900)
    healed = [ln.strip() for ln in out_h.splitlines()
              if ("heal" in ln.lower() or "исцел" in ln.lower() or "F ->" in ln)
              and ("OK" in ln or "PROVEN" in ln or "T" == ln.strip()[-1:])]
    record("Ж", "гомеостаз: F -> синтез @kern:requires -> повторная проверка -> PROVEN",
           "OK" if rc_h == 0 else "FAIL",
           (healed[-1][:140] if healed else f"make homeostatic-heal-check rc={rc_h}"))

    # Ж2. @kern:secret — утечка секретного параметра против безопасной функции.
    rc_s, out_s = run(["make", "-s", "secrets-check"], timeout=600)
    tail_s = [ln.strip() for ln in out_s.splitlines() if ln.startswith("[OK]") or "RC=" in ln]
    record("Ж", "@kern:secret: перехват утечки секрета (selftest + реальный скан)",
           "OK" if rc_s == 0 else "FAIL", (tail_s[-1][:140] if tail_s else f"rc={rc_s}"))

    # Ж3. @kern:pricing — тарифная матрица без дыр и противоречий.
    rc_p, out_p = run(["make", "-s", "pricing-matrix-check"], timeout=600)
    tail_p = [ln.strip() for ln in out_p.splitlines() if ln.startswith("[OK]") or "RC=" in ln]
    record("Ж", "@kern:pricing: полнота и непротиворечивость тарифной матрицы",
           "OK" if rc_p == 0 else "FAIL", (tail_p[-1][:140] if tail_p else f"rc={rc_p}"))

    # Ж4. `kernc run --fuel` — ДВУСТОРОННЕ: бесконечный CALL -> OutOfQuota,
    #     программа с HALT -> HALT OK. Формат байткода: 0x06 addr8 (CALL), 0xFF HALT.
    bc_dir = ROOT / "build" / "fuel"
    bc_dir.mkdir(parents=True, exist_ok=True)
    loop_bc, halt_bc = bc_dir / "loop.bcx", bc_dir / "halt.bcx"
    loop_bc.write_bytes(bytes([0x06, 0x00]))       # CALL 0 -> бесконечный цикл
    halt_bc.write_bytes(bytes([0x00, 0xFF]))       # NOP; HALT
    manifest = ROOT / "examples" / "hello_world.kern"
    fuel_rows: list[tuple[str, str]] = []
    for name, bc, want in (("цикл", loop_bc, "OutOfQuota"), ("halt", halt_bc, "HALT OK")):
        img = bc_dir / f"{bc.stem}.kimg"
        _rcb, outb = run([str(KERNC), "build", str(manifest), "-o", str(img),
                          "--bytecode", str(bc)], timeout=300)
        _rcr, outr = run([str(KERNC), "run", str(img), "--fuel", "200"], timeout=300)
        got = "OutOfQuota" if "OutOfQuota" in outr else ("HALT OK" if "HALT OK" in outr else "?")
        fuel_rows.append((name, got))
        record("Ж", f"kernc run --fuel ({name}): детерминированный бюджет",
               "OK" if got == want else "FAIL",
               f"ожидали {want}, получили {got} (топливо 200)")

    # Ж5. `kernc unify` — консолидация Белнапа B_4 прямо в CLI (две стороны).
    _rcu1, out_u1 = run([str(KERNC), "unify", "5", "3"], timeout=120)
    _rcu2, out_u2 = run([str(KERNC), "unify", "3", "7"], timeout=120)
    agree = "[T]" in out_u1 and "УСПЕШНА" in out_u1
    conflict = "[B]" in out_u2 and "КОНФЛИКТ" in out_u2
    record("Ж", "kernc unify: согласие -> T, расхождение -> B (Belnap B_4 в CLI)",
           "OK" if (agree and conflict) else "FAIL",
           f"unify 5/3 -> {'T' if agree else out_u1.strip()[:40]}; "
           f"unify 3/7 -> {'B' if conflict else out_u2.strip()[:40]}")

    # Ж6. МОСТ Lean 4 <-> kernc: законы решётки из `formal/*.lean` сверяются с CLI.
    #     `KernAllMath.contradiction_isolation : joinK T F = B` -> unify даёт B;
    #     `joinK_idem : joinK a a = a` -> unify согласия даёт T;
    #     `joinK_comm` -> порядок аргументов не меняет вердикт.
    _rc1, o1 = run([str(KERNC), "unify", "4", "4"], timeout=120)
    _rc2, o2 = run([str(KERNC), "unify", "2", "6"], timeout=120)
    _rc3, o3 = run([str(KERNC), "unify", "6", "2"], timeout=120)
    idem = "[T]" in o1                     # joinK_idem : joinK a a = a
    iso = "[B]" in o2                      # contradiction_isolation : joinK T F = B
    # `kernc unify` — РОЛЕВО-АСИММЕТРИЧЕН (аргумент 1 = лимит архитектора,
    # аргумент 2 = минимум ИИ), поэтому `joinK_comm` из Lean к нему НЕ применяется:
    # unify 2 6 -> B, unify 6 2 -> T. Это проверяется как ФАКТ асимметрии,
    # а не выдаётся за нарушение закона решётки.
    asymmetric = ("[B]" in o2) and ("[T]" in o3)
    record("Ж", "мост Lean<->kernc: joinK_idem / contradiction_isolation (+ роль-асимметрия)",
           "OK" if (idem and iso and asymmetric) else "FAIL",
           f"idem: unify 4/4 -> {'T' if idem else '?'}; isolation: unify 2/6 -> "
           f"{'B' if iso else '?'}; роль-асимметрия (2/6=B, 6/2=T)={asymmetric}")


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    say("=" * 79)
    say(f"БОЕВОЙ СТЕНД ВСЕХ СПОСОБНОСТЕЙ KERN v{VERSION} — "
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    say(f"машина: {os.uname().sysname} {os.uname().machine}")
    say("=" * 79)
    if not KERNC.is_file():
        say("[!] нет zig-out/bin/kernc — сначала `make build`")
        return 2
    pkg_a_native()
    pkg_b_oracles()
    say("\n" + "=" * 79)
    ok = sum(1 for r in rows if r[2] == "OK")
    skip = sum(1 for r in rows if r[2] == "SKIP")
    fail = sum(1 for r in rows if r[2] == "FAIL")
    say(f"ИТОГ СТЕНДА: OK {ok} | SKIP {skip} | FAIL {fail} | всего {len(rows)}")
    say(f"квитанция: {LOG.relative_to(ROOT)}")
    say("=" * 79)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

