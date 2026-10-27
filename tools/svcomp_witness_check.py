#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: SV-COMP — 4 ОФИЦИАЛЬНЫЕ категории + ВАЛИДАЦИЯ СВИДЕТЕЛЯ.

ЗАЧЕМ. `svcomp_baseline.py` (#367/#368) измерил ОДНУ категорию
(`signedintegeroverflow-regression`) и печатал матрицу. В SV-COMP вердикт НЕ
засчитывается без ПОДТВЕРЖДЁННОГО свидетеля (Witness): доказательство того, что
нарушение ДОСТИЖИМО, обязан подтвердить ВНЕШНИЙ валидатор. У KERN такого не
было вообще — вердикт `UNSAFE` предъявлялся без свидетеля.

ЧТО ДЕЛАЕТ ГЕЙТ (Executable Harness Witness). Для каждой официальной задачи
собирается ИСПОЛНЯЕМЫЙ стенд:

  1. ОРИГИНАЛЬНЫЙ `.c` файл копируется БЕЗ ИЗМЕНЕНИЙ (это требование SV-COMP:
     свидетель проверяется на задаче чемпионата, а не на производном файле);
  2. рядом кладутся НАШИ заглушки: `assert.h` с `__VERIFIER_assert` /
     `reach_error` / `assume_abort_if_not` и `harness.c` с определениями
     `__VERIFIER_nondet_*` (слабые символы — определение задачи побеждает);
  3. сборка: `gcc -O0 -g -fsanitize=undefined,address -fno-sanitize-recover=all`;
  4. запуск со СВИДЕТЕЛЕМ: значения недетерминированных входов подаются через
     `KERN_ND` (список через запятую; последнее значение повторяется).

СИГНАЛ ЗАВИСИТ ОТ СВОЙСТВА, И ЭТО ПРИНЦИПИАЛЬНО. Смешивать сигналы нельзя:
задача может быть `SAFE` по `unreach-call` и при этом иметь ошибку памяти,
которую поймает ASan. Поэтому:

  * свойство `overflow` (`no-overflow.prp`)  -> сигнал: диагностика UBSan
    («runtime error: signed integer overflow»);
  * свойство `unreach-call`                  -> сигнал: `REACH_ERROR`
    (наша заглушка `reach_error`).

ЧТО ИМЕННО ТРЕБУЕТСЯ:

  * `ЛОЖНЫХ ТРЕВОГ == 0` — на `SAFE`-задачах НИ ОДИН свидетель из
    пространства поиска не имеет права вызвать сигнал свойства;
  * `ЛОЖНЫХ ДОПУСКОВ == 0` — вердикт `UNSAFE` без ПОДТВЕРЖДЁННОГО компилятором
    и запуском свидетеля не засчитывается;
  * невакуумность — в каждой категории должен быть хотя бы один разобранный
    случай, иначе «0 нарушений» ничего не значит (класс #345).

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы, а не умолчаны):

  * ПРОСТРАНСТВО СВИДЕТЕЛЕЙ ОГРАНИЧЕНО и названо: константа из
    `{-1,0,1,2,3,5,10,100}` либо пара значений из того же множества. Свидетель
    SV-COMP — это АВТОМАТ по последовательности вызовов; здесь его нет. Поэтому
    «свидетель не найден» означает «не найден в этом пространстве», а не
    «нарушение недостижимо».
  * Подтверждается ТОЛЬКО найденный свидетель (внешним компилятором и
    запуском). `SAFE` НЕ доказывается: проверяется лишь отсутствие сигнала на
    перебранных свидетелях.
  * KERN-вердикты по этим категориям здесь только ИЗМЕРЯЮТСЯ (`--xray`), чтобы
    не выдать обёртку за доказательство.

Запуск:  python3 tools/svcomp_witness_check.py [--selftest] [--dir DIR] [--out FILE]
Код возврата: 0 — инварианты выполнены; 1 — нарушение; 2 — нет выборки и нет
              сети (честный SKIP, НЕ «зелёный»).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERN_CONTRACTS = ROOT / "tools" / "kern_contracts.py"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kern" / "svcomp-witness"
_RAW = "https://raw.githubusercontent.com/sosy-lab/sv-benchmarks/master/c/"

# ЗАКРЕПЛЁННАЯ ВЫБОРКА: 4 официальные категории. Имена фиксированы, чтобы прогон
# был воспроизводим; полный состав категорий измерен разведкой (см. METRICS §155).
SAMPLE: dict[str, list[str]] = {
    "signedintegeroverflow-regression": [
        "AdditionIntMax", "AdditionIntMin", "ConversionToSignedInt", "Division-1",
        "IntegerPromotion-1", "Multiplication-1", "Multiplication-2", "NoConversion",
        "NoNegativeIntegerConstant", "PostfixDecrement", "PostfixIncrement",
        "PrefixDecrement", "PrefixIncrement", "UnaryMinus",
        "UsualArithmeticConversions",
    ],
    "bitvector-regression": [
        "implicitfloatconversion", "implicitunsignedconversion-1",
        "implicitunsignedconversion-2", "integerpromotion-2", "integerpromotion-3",
        "recHanoi03-1", "signextension-1", "signextension-2", "signextension2-1",
        "signextension2-2",
    ],
    "loop-lit": ["gcnr2008", "afnp2014", "bhmr2007", "cggmp2005_variant",
                 "css2003", "ddlm2013"],
    "array-examples": ["relax-1", "relax-2", "sanfoundry_02_ground",
                       "standard_init1_ground-1", "standard_allDiff2_ground",
                       "sorting_bubblesort_2_ground"],
}

# ПРОСТРАНСТВО СВИДЕТЕЛЕЙ (названо явно): константа либо пара значений.
WITNESS_VALUES = (-1, 0, 1, 2, 3, 5, 10, 100)
# Лимит на ОДИН запуск и БЮДЖЕТ на задачу. Нужны потому, что свидетель может
# увести программу в длинный цикл: без бюджета гейт не был бы ограничен по
# времени, а «не найден» нельзя выдавать за результат перебора, которого не было.
RUN_TIMEOUT_S = 8
TASK_BUDGET_S = 60

STUBS_H = """\
#ifndef KERN_SVCOMP_STUBS_H
#define KERN_SVCOMP_STUBS_H
/* СИСТЕМНЫЙ `assert.h` ПОДКЛЮЧАЕТСЯ ПЕРВЫМ: часть официальных задач САМА
   определяет `reach_error` через `assert(0)` (например `array-examples/relax-1`).
   Без `#include_next` наш `assert.h` перекрывал системный, и такие задачи НЕ
   СОБИРАЛИСЬ — ИЗМЕРЕНО: 6 задач `array-examples` дали «сборка не удалась». */
#include_next <assert.h>
#include <stdio.h>
#include <stdlib.h>
#define LARGE_INT 1000000
extern void abort(void);
int __VERIFIER_nondet_int(void);
unsigned int __VERIFIER_nondet_uint(void);
unsigned __VERIFIER_nondet_unsigned_int(void);
long __VERIFIER_nondet_long(void);
unsigned long __VERIFIER_nondet_ulong(void);
char __VERIFIER_nondet_char(void);
unsigned char __VERIFIER_nondet_uchar(void);
short __VERIFIER_nondet_short(void);
float __VERIFIER_nondet_float(void);
double __VERIFIER_nondet_double(void);
_Bool __VERIFIER_nondet_bool(void);
void __VERIFIER_error(void);
void __VERIFIER_assert(int cond);
void reach_error(void);
void assume_abort_if_not(int cond);
#endif
"""

STUBS_C = """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

/* СВИДЕТЕЛЬ подаётся через KERN_ND: значения через запятую; последнее
   повторяется. Индекс вызова растёт, поэтому пара значений задаёт
   ПОСЛЕДОВАТЕЛЬНОСТЬ, а не одну константу. */
static long kern_nd(void)
{
    const char *e = getenv("KERN_ND");
    static long vals[512];
    static int n = -1, i = 0;
    if (n < 0) {
        n = 0;
        if (e && *e) {
            char buf[4096], *save = NULL;
            strncpy(buf, e, sizeof(buf) - 1);
            buf[sizeof(buf) - 1] = 0;
            for (char *tok = strtok_r(buf, ",", &save); tok && n < 512;
                 tok = strtok_r(NULL, ",", &save))
                vals[n++] = strtol(tok, NULL, 10);
        }
        if (n == 0) { vals[0] = 0; n = 1; }
    }
    long v = vals[i < n ? i : n - 1];
    i++;
    return v;
}

__attribute__((weak)) int __VERIFIER_nondet_int(void) { return (int)kern_nd(); }
__attribute__((weak)) unsigned int __VERIFIER_nondet_uint(void) { return (unsigned int)kern_nd(); }
__attribute__((weak)) unsigned __VERIFIER_nondet_unsigned_int(void) { return (unsigned)kern_nd(); }
__attribute__((weak)) long __VERIFIER_nondet_long(void) { return kern_nd(); }
__attribute__((weak)) unsigned long __VERIFIER_nondet_ulong(void) { return (unsigned long)kern_nd(); }
__attribute__((weak)) char __VERIFIER_nondet_char(void) { return (char)kern_nd(); }
__attribute__((weak)) unsigned char __VERIFIER_nondet_uchar(void) { return (unsigned char)kern_nd(); }
__attribute__((weak)) short __VERIFIER_nondet_short(void) { return (short)kern_nd(); }
__attribute__((weak)) float __VERIFIER_nondet_float(void) { return (float)kern_nd(); }
__attribute__((weak)) double __VERIFIER_nondet_double(void) { return (double)kern_nd(); }
__attribute__((weak)) _Bool __VERIFIER_nondet_bool(void) { return kern_nd() != 0; }

__attribute__((weak)) void reach_error(void)
{
    fprintf(stderr, "REACH_ERROR\\n");
    fflush(stderr);
    abort();
}
__attribute__((weak)) void __VERIFIER_error(void) { reach_error(); }
__attribute__((weak)) void __VERIFIER_assert(int cond)
{
    if (!cond) reach_error();
}
__attribute__((weak)) void assume_abort_if_not(int cond)
{
    if (!cond) abort();
}
"""


def _fetch(url: str) -> bytes | None:
    """Скачать файл. `urllib` первым, `curl` — как запасной путь."""
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return r.read()
    except Exception:                                       # noqa: BLE001
        pass
    r = subprocess.run(["curl", "-s", "-f", url], capture_output=True, timeout=120)
    return r.stdout if r.returncode == 0 and r.stdout else None


def ensure_sample() -> tuple[Path | None, str]:
    """Каталог с выборкой. Скачивает в КЭШ, если его нет."""
    for cat, tasks in SAMPLE.items():
        (CACHE / cat).mkdir(parents=True, exist_ok=True)
        for t in tasks:
            for ext in ("c", "yml"):
                dst = CACHE / cat / f"{t}.{ext}"
                if dst.exists():
                    continue
                b = _fetch(f"{_RAW}{cat}/{t}.{ext}")
                if b is None:
                    return None, (f"не удалось скачать {cat}/{t}.{ext} и кэш "
                                  f"неполон (нет сети?)")
                dst.write_bytes(b)
    return CACHE, ""


def property_of(yml: Path) -> tuple[str, str]:
    """Вернуть `(вердикт, свойство)`. Вердикт `?` — несколько РАЗНЫХ вердиктов."""
    txt = yml.read_text(encoding="utf-8", errors="replace")
    props = re.findall(r"property_file:\s*(\S+)\s*\n\s*expected_verdict:\s*(true|false)", txt)
    if not props:
        return "?", "?"
    verdicts = {v for _, v in props}
    prop = "overflow" if any("overflow" in p for p, _ in props) else "unreach"
    if len(verdicts) != 1:
        return "?", prop
    return ("unsafe" if verdicts == {"false"} else "safe"), prop



def build_harness(work: Path, src: Path) -> tuple[bool, str, str]:
    """Собрать исполняемый стенд: оригинальный `.c` + НАШИ заглушки.

    Файл задачи копируется БЕЗ ИЗМЕНЕНИЙ — это требование SV-COMP.
    Возвращает `(ok, ошибка, предупреждения_компилятора)`. Предупреждения нужны
    как ОТДЕЛЬНЫЙ внешний валидатор: ИЗМЕРЕНО, что КОНСТАНТНО-СВЁРНУТОЕ
    переполнение (`int x = 2147483647 + 1;`) на рантайме НЕ наблюдаемо — UBSan
    проверять нечего, компилятор уже посчитал выражение. При этом сам
    компилятор о нарушении СООБЩАЕТ (`-Woverflow`), и это внешнее свидетельство.
    """
    (work / "assert.h").write_text(STUBS_H, encoding="utf-8")
    (work / "harness.c").write_text(STUBS_C, encoding="utf-8")
    target = work / src.name
    target.write_bytes(src.read_bytes())
    prog = work / "prog"
    cmd = ["gcc", "-O0", "-g", "-Wall", "-Wextra", "-Woverflow",
           "-fsanitize=undefined,address", "-fno-sanitize-recover=all",
           "-I", str(work), "-o", str(prog),
           str(work / "harness.c"), str(target)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not prog.exists():
        return False, (r.stderr.strip().splitlines() or ["?"])[0][:150], ""
    return True, "", r.stderr


def run_witness(work: Path, nd: str) -> tuple[str, str]:
    """Запуск со свидетелем `nd`. Возвращает `(вывод, деталь)`.

    СИГНАЛ считается ОТДЕЛЬНО и только по СВОЕМУ свойству (см. docstring):
    иначе `SAFE`-задача по `unreach-call` краснела бы из-за не связанной с ней
    ошибки памяти.
    """
    env = dict(os.environ)
    env["KERN_ND"] = nd
    env["ASAN_OPTIONS"] = "detect_leaks=0"
    try:
        r = subprocess.run([str(work / "prog")], cwd=str(work), env=env,
                           capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return "", "таймаут"
    out = (r.stdout or "") + (r.stderr or "")
    return out, f"rc={r.returncode}"


def property_signal(out: str, prop: str) -> tuple[bool, str]:
    """Есть ли сигнал СВОЕГО свойства в выводе запуска."""
    if prop == "overflow":
        if "runtime error:" in out:
            line = next((l for l in out.splitlines() if "runtime error:" in l), "")
            return True, line.strip()[:110]
        return False, ""
    if "REACH_ERROR" in out:
        return True, "REACH_ERROR (нарушение достижимо)"
    # Часть официальных задач определяет `reach_error` через `assert(0)` САМА
    # (например `array-examples/relax-1`), и тогда сигналом служит текст отказа
    # glibc-шного `assert`. ВАЖНО: `abort()` от `assume_abort_if_not` сигналом
    # НЕ считается — это отсечение НЕВЫПОЛНИМОЙ ветки, а не нарушение.
    if "Assertion" in out and "failed" in out:
        line = next((l for l in out.splitlines() if "Assertion" in l), "")
        return True, f"assert задачи: {line.strip()[:80]}"
    return False, ""


def compile_signal(warnings: str, prop: str, src: Path) -> tuple[bool, str]:
    """Сигнал КОМПИЛЯТОРА по своему свойству (второй внешний валидатор).

    ИЗМЕРЕНО: КОНСТАНТНО-СВЁРНУТЫЕ переполнения (`int x = 2147483647 + 1;`)
    на рантайме НЕ наблюдаемы — UBSan проверять нечего. Но компилятор о них
    сообщает, и это ровно то внешнее свидетельство, которого требует SV-COMP.
    Считаем ТОЛЬКО предупреждения, относящиеся к ФАЙЛУ ЗАДАЧИ (не к заглушкам).
    """
    if prop != "overflow":
        return False, ""
    name = src.name
    for line in warnings.splitlines():
        if name in line and "overflow" in line.lower() and "warning" in line:
            return True, f"компилятор: {line.strip()[:100]}"
    return False, ""


def witnesses():
    """Пространство свидетелей: константы, затем пары (названо в docstring)."""
    for v in WITNESS_VALUES:
        yield str(v)
    for a in WITNESS_VALUES:
        for b in WITNESS_VALUES:
            if a != b:
                yield f"{a},{b}"


def check_task(cat: str, task: str) -> dict:
    """Один случай: сборка + перебор свидетелей. Возвращает ИЗМЕРЕНИЯ."""
    src = CACHE / cat / f"{task}.c"
    yml = CACHE / cat / f"{task}.yml"
    expected, prop = property_of(yml)
    res: dict = {"expected": expected, "property": prop, "witness": None,
                 "signal": False, "tried": 0, "skip": None, "source": None}
    if expected == "?":
        res["skip"] = "несколько РАЗНЫХ вердиктов в .yml (свойства несовместимы)"
        return res
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ok, err, warnings = build_harness(work, src)
        if not ok:
            res["skip"] = f"сборка не удалась: {err}"
            return res
        # ВНЕШНИЙ ВАЛИДАТОР №1 — КОМПИЛЯТОР (константно-свёрнутые нарушения).
        hit, why = compile_signal(warnings, prop, src)
        if hit:
            res["signal"] = True
            res["witness"] = "(константа)"
            res["detail"] = why
            res["source"] = "компилятор"
            return res
        # ВНЕШНИЙ ВАЛИДАТОР №2 — ЗАПУСК со свидетелем.
        t0 = time.time()
        for nd in witnesses():
            if time.time() - t0 > TASK_BUDGET_S:
                res["budget_exhausted"] = True
                break
            res["tried"] += 1
            out, detail = run_witness(work, nd)
            hit, why = property_signal(out, prop)
            if hit:
                res["signal"] = True
                res["witness"] = nd
                res["detail"] = why
                res["rc"] = detail
                res["source"] = "запуск"
                return res
    return res


def run_kern_xray(directory: Path) -> dict:
    """KERN-вердикты по категории (`--xray`). ТОЛЬКО ИЗМЕРЕНИЕ."""
    r = subprocess.run([PY, str(KERN_CONTRACTS), "--xray", str(directory)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    found: dict = {}
    for line in out.splitlines():
        m = re.search(r"/([A-Za-z0-9_.\-]+)\.c:\s*\[([A-Z ]+)\]\s*(.*)", line)
        if m:
            found.setdefault(m.group(1), f"[{m.group(2).strip()}] {m.group(3).strip()}")
    return found



def collect(directory: Path) -> dict:
    """Прогон по 4 категориям. Только ИЗМЕРЕНИЯ."""
    rep: dict = {"categories": {}}
    for cat, tasks in SAMPLE.items():
        cdir = directory / cat
        if not cdir.is_dir():
            rep["categories"][cat] = {"error": f"нет каталога {cdir}"}
            continue
        cases: dict = {}
        for t in tasks:
            if not (cdir / f"{t}.c").exists():
                cases[t] = {"skip": "файла нет в кэше"}
                continue
            cases[t] = check_task(cat, t)
            r = cases[t]
            mark = "SKIP" if r.get("skip") else (
                f"СИГНАЛ witness={r['witness']}" if r.get("signal") else
                f"нет сигнала (перебрано {r['tried']})")
            print(f"    [{cat}] {t:<44} {mark}", flush=True)
        rep["categories"][cat] = {"cases": cases,
                                  "kern": run_kern_xray(cdir)}
    return rep


def verdict(rep: dict) -> list[str]:
    """Список нарушений. Пустой = гейт зелёный.

    КРАСНИТ:
      * ЛОЖНАЯ ТРЕВОГА: сигнал свойства на `SAFE`-задаче;
      * ВАКУУМ: в категории не разобрано НИ ОДНОГО случая (класс #345);
      * СБОЙ СБОРКИ: стенд обязан собираться (иначе «нет сигнала» — не замер);
      * НЕДОБОР ПОДТВЕРЖДЕНИЙ: в категории, где ЕСТЬ `UNSAFE`-задачи, ни один
        свидетель не подтверждён — тогда гейт не проверил ровно то, ради чего
        стоит (класс #345).

    НЕ КРАСНИТ (заявлено явно): `UNSAFE`, для которого НИ ОДИН доступный
    внешний валидатор не наблюдал нарушение. ИЗМЕРЕНО на официальной задаче
    `signedintegeroverflow-regression/UnaryMinus`: ни `gcc -O0..-O3` с
    `-fsanitize=undefined` и явным `-fsanitize=signed-integer-overflow`, ни
    компиляторная диагностика нарушения не показывают. Это ГРАНИЦА МЕТОДА, и
    она печатается отдельной строкой. Ложным допуском это НЕ объявляется —
    ложный допуск был бы ЗАЯВЛЕНИЕМ о подтверждении, которого нет.
    """
    if rep.get("error"):
        return [rep["error"]]
    bad: list[str] = []
    for cat, c in rep["categories"].items():
        if c.get("error"):
            bad.append(f"{cat}: {c['error']}")
            continue
        cases = c["cases"]
        resolved = confirmed = build_fail = 0
        for t, r in cases.items():
            if r.get("skip"):
                if r["skip"].startswith("сборка не удалась"):
                    build_fail += 1
                continue
            resolved += 1
            if r["expected"] == "safe":
                if r["signal"]:
                    bad.append(f"{cat}/{t}: ЛОЖНАЯ ТРЕВОГА — свидетель "
                               f"`{r['witness']}` вызвал сигнал на SAFE-задаче "
                               f"({r.get('detail', '')})")
            elif r["signal"]:
                confirmed += 1
        if resolved == 0:
            bad.append(f"{cat}: ВАКУУМ — ни одного разобранного случая "
                       f"(класс #345)")
        if build_fail:
            bad.append(f"{cat}: стенд не собрался для {build_fail} задач")
        unsafe_total = sum(1 for r in cases.values()
                           if r.get("expected") == "unsafe")
        if unsafe_total and confirmed == 0:
            bad.append(f"{cat}: НЕДОБОР — из {unsafe_total} UNSAFE-задач НИ ОДНА "
                       f"не подтверждена внешним валидатором (класс #345)")
    return bad


def _mk(cat: str, cases: dict) -> dict:
    return {"categories": {cat: {"cases": cases, "kern": {}}}}


def print_report(rep: dict) -> None:
    print("=" * 78)
    print("KERN: SV-COMP — 4 ОФИЦИАЛЬНЫЕ КАТЕГОРИИ + ВАЛИДАЦИЯ СВИДЕТЕЛЯ")
    print("=" * 78)
    for cat, c in rep["categories"].items():
        print(f"\n### {cat}")
        if c.get("error"):
            print(f"  [FAIL] {c['error']}")
            continue
        cases = c["cases"]
        unsafe = sum(1 for r in cases.values() if r.get("expected") == "unsafe")
        safe = sum(1 for r in cases.values() if r.get("expected") == "safe")
        skip = sum(1 for r in cases.values() if r.get("skip"))
        conf = sum(1 for r in cases.values() if r.get("signal")
                   and r.get("expected") == "unsafe")
        unobs = sum(1 for r in cases.values() if r.get("expected") == "unsafe"
                    and not r.get("signal") and not r.get("skip"))
        print(f"  задач {len(cases)}: UNSAFE {unsafe}, SAFE {safe}, SKIP {skip} | "
              f"ПОДТВЕРЖДЕНО {conf}, НЕ НАБЛЮДАЕМО {unobs}")
        for t, r in cases.items():
            line = f"  · {t:<44}"
            if r.get("skip"):
                line += f" SKIP: {r['skip'][:44]}"
            else:
                line += f" {r['expected']:<6} [{r['property']}]"
                if r.get("signal"):
                    line += (f" ПОДТВЕРЖДЕНО[{r.get('source')}] "
                             f"witness=`{r['witness']}` {r.get('detail', '')[:34]}")
                elif r["expected"] == "unsafe":
                    line += f" НЕ НАБЛЮДАЕМО (перебрано {r['tried']})"
                else:
                    line += f" чисто (перебрано {r['tried']})"
            print(line)
        kern = c.get("kern") or {}
        print(f"  KERN --xray: находок {len(kern)} "
              f"(ИЗМЕРЕНИЕ, не доказательство)")



def selftest() -> int:
    """Мета-тест: гейт обязан ловить КАЖДЫЙ класс поломки.

    Ветки: (1) ЛОЖНАЯ ТРЕВОГА на `SAFE`; (2) ВАКУУМ категории; (3) несобранный
    стенд; (4) НЕДОБОР (все `UNSAFE` без подтверждения); (5) здоровый прогон;
    (6) НЕ НАБЛЮДАЕМО на `UNSAFE` при наличии подтверждений НЕ краснит —
    это заявленная ГРАНИЦА МЕТОДА, а не ложный допуск.
    """
    bad = 0
    ok_cases = {
        "u.c": {"expected": "unsafe", "property": "unreach", "witness": "1",
                "signal": True, "tried": 3, "skip": None, "detail": "REACH_ERROR",
                "source": "запуск"},
        "s.c": {"expected": "safe", "property": "unreach", "witness": None,
                "signal": False, "tried": 64, "skip": None},
    }

    def expect_red(label: str, rep: dict):
        nonlocal bad
        if verdict(rep):
            print(f"[OK] selftest: {label} ловится")
        else:
            print(f"[FAIL] selftest: {label} НЕ поймано")
            bad += 1

    def expect_green(label: str, rep: dict):
        nonlocal bad
        if not verdict(rep):
            print(f"[OK] selftest: {label} проходит")
        else:
            print(f"[FAIL] selftest: {label} ошибочно краснит")
            bad += 1

    expect_green("здоровый прогон (UNSAFE подтверждён, SAFE чист)",
                 _mk("C", ok_cases))
    expect_red("ЛОЖНАЯ ТРЕВОГА на SAFE-задаче",
               _mk("C", {"s.c": dict(ok_cases["s.c"], signal=True, witness="1",
                                     detail="REACH_ERROR"),
                         "u.c": ok_cases["u.c"]}))
    expect_red("НЕДОБОР (все UNSAFE без подтверждения)",
               _mk("C", {"u.c": dict(ok_cases["u.c"], signal=False, witness=None),
                         "s.c": ok_cases["s.c"]}))
    expect_red("ВАКУУМ категории (все SKIP)",
               _mk("C", {"u.c": {"skip": "нет файла"}, "s.c": {"skip": "нет файла"}}))
    expect_red("стенд не собрался",
               _mk("C", {"u.c": {"skip": "сборка не удалась: error"},
                         "s.c": {"skip": "сборка не удалась: error"}}))
    expect_green("НЕ НАБЛЮДАЕМО при наличии подтверждений НЕ краснит (граница)",
                 _mk("C", {"u1.c": ok_cases["u.c"],
                           "u2.c": {"expected": "unsafe", "property": "overflow",
                                    "witness": None, "signal": False,
                                    "tried": 64, "skip": None},
                           "s.c": ok_cases["s.c"]}))
    expect_green("SKIP по несовместимым свойствам не краснит",
                 _mk("C", {"u.c": ok_cases["u.c"],
                           "x.c": {"skip": "несколько РАЗНЫХ вердиктов в .yml"},
                           "s.c": ok_cases["s.c"]}))
    print(f"[{'OK' if bad == 0 else 'FAIL'}] svcomp-witness selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SV-COMP: валидация свидетеля")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", type=Path, default=None,
                    help="свой каталог с подпапками категорий (для can-fail)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.selftest:
        return selftest()

    if args.dir is not None:
        directory = args.dir
        why = "" if args.dir.is_dir() else "нет каталога"
    else:
        directory, why = ensure_sample()
    if directory is None or why:
        print(f"\n[SKIP] {why}")
        print("[i] Это НЕ «зелёный гейт»: проверять нечего. Прогон не зачтён.")
        return 2

    rep = collect(directory)
    print_report(rep)
    bad = verdict(rep)
    print("\n" + "-" * 78)
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        return 1
    total = sum(len(c.get("cases", {})) for c in rep["categories"].values())
    confirmed = sum(1 for c in rep["categories"].values()
                    for r in c.get("cases", {}).values()
                    if r.get("signal") and r.get("expected") == "unsafe")
    safe_clean = sum(1 for c in rep["categories"].values()
                     for r in c.get("cases", {}).values()
                     if r.get("expected") == "safe" and not r.get("signal")
                     and not r.get("skip"))
    unobserved = sum(1 for c in rep["categories"].values()
                     for r in c.get("cases", {}).values()
                     if r.get("expected") == "unsafe" and not r.get("signal")
                     and not r.get("skip"))
    print(f"[OK] 4 категории: {total} задач, {confirmed} UNSAFE ПОДТВЕРЖДЕНО "
          f"ВНЕШНИМ валидатором (компилятор или запуск под gcc-санитайзерами), "
          f"{safe_clean} SAFE чисты на перебранных свидетелях, "
          f"ЛОЖНЫХ ТРЕВОГ 0, НЕДОБОРА 0.")
    print(f"[i] ГРАНИЦА МЕТОДА (названа, не спрятана): НЕ НАБЛЮДАЕМО {unobserved} "
          f"UNSAFE-задач — их нарушение не увидел НИ компилятор, НИ запуск. "
          f"Например `UnaryMinus`: измерено, что ни `gcc -O0..-O3` с "
          f"`-fsanitize=undefined` и явным `-fsanitize=signed-integer-overflow`, "
          f"ни `-Woverflow` нарушения не показывают. Это НЕ объявляется ложным "
          f"допуском (подтверждения не заявлялось) и НЕ считается доказанным.")
    print("[i] ГРАНИЦА ПОИСКА: пространство свидетелей ОГРАНИЧЕНО (константа или "
          "пара из 8 значений). «Свидетель не найден» — не доказательство "
          "недостижимости, и гейт этого не заявляет.")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        import json
        args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"[i] отчёт сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

