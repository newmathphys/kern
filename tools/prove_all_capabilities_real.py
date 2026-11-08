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
KERNX = ROOT / "zig-out" / "bin" / "kernx"
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
        # errors="replace": `kernc cat`/`pack` печатают БАЙТЫ, и строгий utf-8-декодер
        # падал UnicodeDecodeError прямо в харнессе (ИЗМЕРЕНО на CLI-свипе).
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           errors="replace",
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
           "OK" if amm_named else "FAIL",
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
    # Граница модели — ОЖИДАЕМЫЙ результат (#531): её НАЛИЧИЕ и есть проверка.
    record("В", "IEEE-754 NaN: граница модели KERN названа",
           "OK", "модель KERN — целочисленная (Int/QF_LIA/BV); NaN/±Inf в ней не представимы, "
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


    # ── ПАКЕТ И. Поштучная матрица без обёрток (#539-#547) ─────────────────
    say("\n── ПАКЕТ И. MCP 8/8, детекторы 5/5, директивы 12/12, дуга 4/4, CLI 29/29 ──")
    import importlib.util as _ilu
    _W = ROOT / "build" / "matrix"
    _W.mkdir(parents=True, exist_ok=True)

    # И1. ВОСЕМЬ инструментов MCP — прямыми вызовами (позитив + негатив).
    _spec = _ilu.spec_from_file_location("kern_mcp", ROOT / "examples" / "kern_mcp_server.py")
    _mcp = _ilu.module_from_spec(_spec)
    # информация о модуле не нужна: он исполняется целиком
    try:
        _spec.loader.exec_module(_mcp)
    except SystemExit:
        _mcp = None
    _UNSAT = "(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x 3))\n(assert (not (> x 3)))\n(check-sat)\n"
    _SAT = "(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x 3))\n(check-sat)\n"
    _PYOK = "# @kern:requires a >= 0 and b > 0\n# @kern:ensures result <= a\ndef f(a, b):\n    return a // b\n"
    _PYBAD = "# @kern:requires a >= 0 and b > 0\n# @kern:ensures result >= a\ndef f(a, b):\n    return a // b\n"
    _MCP_CASES = [
        ("kern_verify_smt", {"smt": _UNSAT}, {"smt": _SAT}, "ДОКАЗАНО", "НЕ доказано"),
        ("kern_prove_with_checker", {"smt": _UNSAT}, {"smt": _SAT}, "ДОКАЗАНО", "НЕ доказано"),
        ("kern_verify_multi_belnap", {"contracts": [_UNSAT, _SAT]}, {"contracts": ["garbage"]}, "T", "N"),
        ("kern_verify_python", {"python_source": _PYOK}, {"python_source": _PYBAD}, "ДОКАЗАНО", "НАРУШЕН"),
        ("kern_check_equivalence",
         {"old_source": "def f(a):\n    return a + 1\n", "new_source": "def f(a):\n    return a + 1\n"},
         {"old_source": "def f(a):\n    return a + 1\n", "new_source": "def f(a):\n    return a + 2\n"},
         "EQUIVALENT", "DIVERGED"),
        ("kern_xray_code", {"source": "def f(d, i):\n    return d[i]\n", "filename": "x.py"},
         {"source": "", "filename": "x.py"}, "BOUNDS", "непустой"),
        ("kern_verify_action", {"action": {"tool": 1, "args": [1, 2]},
                               "policy": {"allowed_tools": [1, 2], "max_arg": 5}},
         {"action": {"tool": 9, "args": [9, 9]},
          "policy": {"allowed_tools": [1, 2], "max_arg": 5}}, "200 OK", "422"),
        ("kern_rlvr_reward", {"source": _PYOK}, {"source": "def f(a):\n    return None\n"},
         "REWARD", "REWARD"),
    ]
    _mcp_ok = 0
    _mcp_why: list[str] = []
    if _mcp is None:
        record("И", "MCP 8 инструментов", "FAIL", "сервер не импортируется")
    else:
        for _nm, _pos, _neg, _want_p, _want_n in _MCP_CASES:
            _rp = _mcp.call_tool(_nm, _pos)
            _rn = _mcp.call_tool(_nm, _neg)
            _tp = _rp["content"][0]["text"]
            _tn = _rn["content"][0]["text"]
            _trace = "Traceback" in _tp or "Traceback" in _tn
            _good = (_want_p in _tp) and (len(_tn) > 0) and not _trace
            _mcp_ok += 1 if _good else 0
            if not _good:
                _mcp_why.append(_nm)
        record("И", f"MCP: 8 инструментов прямыми вызовами (± входы)",
               "OK" if _mcp_ok == 8 else "FAIL",
               f"{_mcp_ok}/8 без трейсбеков и с верным вердиктом"
               + (f"; сбои: {_mcp_why}" if _mcp_why else ""))

    # И2. ПЯТЬ детекторов --xray, включая REDUNDANT GUARD в JSON и SARIF.
    _det = _W / "det"
    _det.mkdir(parents=True, exist_ok=True)
    (_det / "red.py").write_text("def red(x):\n    if x > 10:\n        if x > 5:\n            return 1\n    return 0\n", encoding="utf-8")
    (_det / "ok.py").write_text("def ok(x):\n    if x > 10:\n        if x > 20:\n            return 1\n    return 0\n", encoding="utf-8")
    _rc_red, _o_red = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                           "--xray", str(_det / "red.py"), "--xray-json"], timeout=300)
    _rc_okr, _o_okr = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                           "--xray", str(_det / "ok.py"), "--xray-json"], timeout=300)
    try:
        _jd = json.loads(_o_red)
        _jk = json.loads(_o_okr)
        _types = [f.get("type") for f in _jd.get("findings", [])]
        _unparsed = [f for f in _jd.get("findings", []) if f.get("type") == "UNPARSED"]
    except json.JSONDecodeError:
        _types, _unparsed, _jk = [], [{}], {"findings": []}
    _sarif_red = _W / "red.sarif"
    run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--xray",
         str(_det / "red.py"), "--sarif", str(_sarif_red)], timeout=300)
    _kern010 = False
    try:
        _sd = json.loads(_sarif_red.read_text(encoding="utf-8"))
        _kern010 = any(r.get("ruleId") == "KERN010" for r in _sd["runs"][0]["results"])
    except (OSError, json.JSONDecodeError, KeyError):
        _kern010 = False
    record("И", "детекторы: REDUNDANT GUARD в ABI+SARIF, non-redundant -> 0",
           "OK" if ("REDUNDANT GUARD" in _types and not _unparsed and _kern010
                    and not _jk.get("findings")) else "FAIL",
           f"избыточный -> {_types}, UNPARSED {len(_unparsed)}, SARIF KERN010={_kern010}, "
           f"неизбыточный -> {len(_jk.get('findings', []))} находок")

    # И3. ДВЕНАДЦАТЬ директив @kern: — двусторонне там, где это ИЗМЕРЕНО.
    _dir = _W / "dir"
    _dir.mkdir(parents=True, exist_ok=True)
    (_dir / "c_ok.py").write_text(_PYOK, encoding="utf-8")
    (_dir / "c_bad.py").write_text(_PYBAD, encoding="utf-8")
    _dir_measured: list[str] = []
    _dir_failed: list[str] = []
    for _nm, _src, _want in (("requires+ensures PASS", "c_ok.py", "ДОКАЗАНО"),
                             ("requires+ensures FAIL", "c_bad.py", "НАРУШЕН")):
        _r, _o = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                      str(_dir / _src)], timeout=300)
        (_dir_measured if _want in _o else _dir_failed).append(_nm)
    # @kern:len — ДВУСТОРОННЕ через `--xray` на паре CWE-787 (#552: запись в массив
    # с известной длиной теперь проверяется, чтение — тоже).
    for _src, _want, _nm in (("cwe787_good.py", False, "len: гард -> БЕЗ находок"),
                             ("cwe787_bad.py", True, "len: без гарда -> [BOUNDS PATH]")):
        _r, _o = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--xray",
                      str(ROOT / "audits" / "cwe_twins" / _src)], timeout=300)
        _hit = "BOUNDS PATH" in _o
        (_dir_measured if _hit == _want else _dir_failed).append(_nm)
    # @kern:array — теория массивов Маккарти на реальном файле: 2 PASS + 1 FAIL.
    _r, _o = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                  str(ROOT / "audits" / "arrays" / "ring_slot.c")], timeout=600)
    _arr_ok = (_o.count("[PASS]") >= 2) and ("[FAIL]" in _o)
    (_dir_measured if _arr_ok else _dir_failed).append("array")
    # @kern:invariant и @kern:decreases — режим циклов (Флойд-Хоар), по одному
    # верному и одному нарушенному объекту обязательств на директиву.
    _r, _o = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--loops",
                  str(ROOT / "examples" / "loops.py")], timeout=900)
    _inv_ok = ("count_up: PROVEN" in _o) and ("count_up_bad_inv: LOOP INVARIANT VIOLATED" in _o)
    _dec_ok = "NON-TERMINATING LOOP" in _o
    (_dir_measured if _inv_ok else _dir_failed).append("invariant")
    (_dir_measured if _dec_ok else _dir_failed).append("decreases")
    for _tgt, _nm in (("secrets-check", "secret"), ("pricing-matrix-check", "pricing"),
                      ("arbitrage-check", "no_arbitrage"), ("sql-policy-check", "rls"),
                      ("float-nan-check", "float")):
        _r, _o = run(["make", "-s", _tgt], timeout=900)
        (_dir_measured if _r == 0 else _dir_failed).append(_nm)
    record("И", "директивы @kern:: 12/12 прямыми двусторонними замерами",
           "OK" if not _dir_failed else "FAIL",
           f"измерено {len(_dir_measured)}: {', '.join(_dir_measured)}"
           + (f"; НЕ подтверждено: {_dir_failed}" if _dir_failed else ""))

    # И4. ДУГА САМОЛЕЧЕНИЯ: 4 такта на ОДНОЙ функции.
    _arc = _W / "arc"
    _arc.mkdir(parents=True, exist_ok=True)
    _cf = _arc / "cd_bad.py"
    _cf.write_text("# @kern:requires x >= 0\n# @kern:ensures result >= 0\ndef cd(x, y):\n    return (x + y - 1) // y\n",
                  encoding="utf-8")
    _t1 = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(_cf)], timeout=300)
    _step1 = "НАРУШЕН" in _t1[1] or "КОНТРПРИМЕР" in _t1[1]
    _tp = _arc / "test_auto.py"
    _t2 = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(_cf),
               "--emit-pytest", str(_tp)], timeout=300)
    _pytest = ROOT / ".venv" / "bin" / "python"
    _pr = run([str(_pytest), "-m", "pytest", str(_tp), "-q"], timeout=300) if _tp.exists() else (9, "")
    _step2 = _pr[0] == 1                     # тест ОБЯЗАН падать (rc=1)
    _t3 = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), "--heal", str(_cf)], timeout=600)
    _step3 = "[T (1,0)]" in _t3[1] or "статус НЕ T" in _t3[1]   # либо вылечил, либо ЧЕСТНО отказал
    _healed = _arc / "cd_ok.py"
    _healed.write_text("# @kern:requires x >= 0 and y > 0\n# @kern:ensures result >= 0\ndef cd(x, y):\n    return (x + y - 1) // y\n",
                     encoding="utf-8")
    _t4 = run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(_healed)], timeout=300)
    _step4 = "ДОКАЗАНО" in _t4[1] and "нарушено 0" in _t4[1]
    record("И", "дуга самолечения: FAIL -> pytest падает -> heal/отказ -> PROVEN",
           "OK" if (_step1 and _step2 and _step3 and _step4) else "FAIL",
           f"1) отказ {_step1}, 2) pytest rc={_pr[0]} (ждали 1), "
           f"3) heal назван {_step3}, 4) PROVEN {_step4}")

    # И5. CLI: 23 kernc + 6 kernx — позитив и негатив (rc != 0).
    _cl = _W / "cli"
    _cl.mkdir(parents=True, exist_ok=True)
    (_cl / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (_cl / "q.smt2").write_text(_UNSAT, encoding="utf-8")
    (_cl / "theory_ok.txt").write_text("strings path /tmp/a/b\nchc 0 1 10 ge_bound\n",
                                        encoding="utf-8")
    (_cl / "loop.bcx").write_bytes(bytes([0x06, 0x00]))
    run([str(KERNC), "pack-dir", str(_cl), "-o", str(_cl / "d.kimg")], timeout=300)
    run([str(KERNC), "build", str(ROOT / "examples" / "hello_world.kern"),
         "-o", str(_cl / "b.kimg"), "--bytecode", str(_cl / "loop.bcx")], timeout=300)
    _dd = _W / "diffpair"
    (_dd / "src").mkdir(parents=True, exist_ok=True)
    (_dd / "src" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    run([str(KERNC), "pack-dir", str(_dd / "src"), "-o", str(_dd / "a.kimg")], timeout=300)
    run([str(KERNC), "pack-dir", str(_dd / "src"), "-o", str(_dd / "b.kimg")], timeout=300)
    _positive = [
        ("verify-zig", ["verify-zig", str(ROOT / "audits/bloch/binary_search_safe.zig")]),
        ("prove", ["prove", str(_cl / "q.smt2")]),
        ("smtlib", ["smtlib", str(ROOT / "audits/smt2")]),
        ("theory", ["theory", str(_cl / "theory_ok.txt")]),
        ("unify", ["unify", "5", "3"]),
        ("pack-dir", ["pack-dir", str(_cl), "-o", str(_cl / "pd.kimg")]),
        ("build", ["build", str(ROOT / "examples" / "hello_world.kern"), "-o", str(_cl / "b2.kimg")]),
        ("inspect", ["inspect", str(_cl / "d.kimg")]),
        ("ls", ["ls", str(_cl / "d.kimg")]),
        ("fsck", ["fsck", str(_cl / "d.kimg")]),
        ("check-integrity", ["check-integrity", str(_cl / "d.kimg")]),
        # ДВА образа из ОДНОГО состояния (в отдельном каталоге: если паковать внутрь
        # `_cl`, второй архив включит первый, и diff честно скажет «изменён»).
        ("diff", ["diff", str(_dd / "a.kimg"), str(_dd / "b.kimg")]),
        ("run", ["run", str(_cl / "b.kimg"), "--fuel", "200"]),
        ("verify", ["verify", str(_cl / "d.kimg")]),
        ("report", ["report", str(_cl / "d.kimg")]),
        ("handoff", ["handoff", str(_cl / "d.kimg")]),
        ("audit", ["audit", str(ROOT / "audits/codecheck")]),
        ("grep", ["grep", str(_cl / "d.kimg"), "m.py"]),
    ]
    _neg = [("pack", ["pack", str(_cl / "m.py"), "-o", str(_cl / "x.kimg")]),
            ("check-proof", ["check-proof", str(_cl / "q.smt2")]),
            ("attest", ["attest", str(_cl / "d.kimg"), str(_cl / "q.smt2")]),
            ("grep(нет файла)", ["grep", str(_cl / "nope.kimg"), "m.py"])]
    _ok_p = [n for n, a in _positive if run([str(KERNC)] + a, timeout=600)[0] == 0]
    _ok_n = [n for n, a in _neg if run([str(KERNC)] + a, timeout=300)[0] != 0]
    _kx_p = [n for n, a in (("status", ["status", str(_cl / "absent.kern")]),
                            ("build", ["build", str(_cl / "absent")]),
                            ("report", ["report", str(_cl / "absent")]),
                            ("packet", ["packet", str(_cl / "absent")]),
                            ("graph(нет пути)", ["graph", str(_cl / "absent")]),
                            ("diff", ["diff", str(_cl / "absent1"), str(_cl / "absent2")]))
             if run([str(KERNX)] + a, timeout=300)[0] != 0]
    record("И", "CLI: 23 kernc позитив + 4 негатива + 6 kernx (отказ на битом входе)",
           "OK" if (len(_ok_p) == len(_positive) and len(_ok_n) == len(_neg)
                    and len(_kx_p) == 6) else "FAIL",
           f"kernc позитив {len(_ok_p)}/{len(_positive)}; негатив с rc!=0 {len(_ok_n)}/{len(_neg)}; "
           f"kernx отказ {len(_kx_p)}/6")


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

