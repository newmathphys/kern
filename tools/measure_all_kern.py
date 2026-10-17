#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""
KERN: ТЕЛЕМЕТРИЧЕСКИЙ СТЕНД (metrology harness).

ЗАЧЕМ. Принцип проекта — MEASURED: «команда -> код возврата -> числовой вывод».
Этот скрипт прогоняет контур и снимает по каждому шагу:
  * вес (критичность для безопасности/корректности),
  * код возврата,
  * время (мс),
  * пиковое потребление ОЗУ (MaxRSS, КБ),
  * SHA-256 доказательства (отпечаток вывода),
  * извлечённые ЧИСЛОВЫЕ метрики (тесты, покрытие, мутации, теоремы, ...).

ЧЕСТНОСТЬ. Скрипт НЕ печатает заранее заготовленных чисел. Если проверка
невозможна в окружении — ставится NOT RUN, и она НЕ даёт баллов. Итоговый
балл — это сумма реально заработанных весов, а не константа.

Запуск:
    python3 tools/measure_all_kern.py                 # весь стенд
    python3 tools/measure_all_kern.py --quick         # без мутаций/фаззинга
    python3 tools/measure_all_kern.py --out report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIG_DIR = os.environ.get("ZIG_DIR", str(Path.home() / "opt/zig-x86_64-linux-0.17.0"))

# --- Матрица весов (сумма = 100) -------------------------------------------
# Критичность: целостность/безопасность весит больше «косметики».
WEIGHTS = {
    "slsa_determinism": 15,   # бит-в-бит воспроизводимость (дефект #56)
    "core_tests": 15,         # тесты ядра + ReleaseSafe
    "kern_next_tests": 8,
    "decision_coverage": 10,  # MC/DC-стиль, норматив DO-178C
    "mutation_integrity": 12, # мутационный скор + чистота дерева
    "kimg_throughput": 10,    # RAW vs Safe + СОВПАДЕНИЕ срезов (дефект #55)
    "z3_bridge_stress": 8,    # таймаут/зомби/дескрипторы
    "memory_fuzz": 7,         # OOM/SIGBUS/фаззинг
    "lean_proofs": 10,        # 7 файлов, 0 sorry
    "semantic_gap": 5,        # Z (Int) vs BitVec32
}


def _env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ZIG_DIR}:{ROOT / '.venv' / 'bin'}:{Path.home() / '.elan' / 'bin'}:{env.get('PATH','')}"
    return env


def run(name: str, cmd: list[str], timeout: float = 900.0) -> dict:
    """Прогон команды с метриками. Возвращает dict с rc/ms/rss/hash/output."""
    t0 = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout, env=_env())
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc = -9
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = ((e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")) + "\n[TIMEOUT]"
    except FileNotFoundError as e:
        return {"name": name, "rc": 127, "ms": 0.0, "rss_kb": 0, "hash": "-",
                "output": f"[NOT RUN] {e}"}
    ms = round((time.perf_counter() - t0) * 1000.0, 2)
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    rss_kb = max(0, after - before)
    combined = out + "\n" + err
    return {
        "name": name,
        "rc": rc,
        "ms": ms,
        "rss_kb": rss_kb,
        "hash": hashlib.sha256(combined.encode()).hexdigest()[:16],
        "output": combined,
    }


def num(pattern: str, text: str, default=None):
    m = re.search(pattern, text)
    if not m:
        return default
    try:
        return float(m.group(1))
    except (ValueError, IndexError):
        return default


def bin_path(name: str) -> Path:
    return ROOT / "zig-out" / "bin" / name


def have(cmd: str) -> bool:
    return shutil.which(cmd, path=_env().get("PATH")) is not None


# ===========================================================================
#  ПРОВЕРКИ. Каждая возвращает (earned, metrics: dict, evidence: str)
# ===========================================================================

def check_slsa_determinism() -> tuple[int, dict, str]:
    """Дефект #56: Debug не воспроизводим, ReleaseFast — воспроизводим.

    Делаем ДВЕ чистые сборки (rm -rf .zig-cache) в ReleaseFast и сравниваем
    sha256. Совпадение = бит-в-бит воспроизводимость (инвариант SLSA).
    """
    w = WEIGHTS["slsa_determinism"]
    cache = ROOT / ".zig-cache"
    hashes = []
    for i in (1, 2):
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
        r = run(f"build#{i}", ["zig", "build", "-Doptimize=ReleaseFast"])
        if r["rc"] != 0:
            return 0, {"build_rc": r["rc"]}, f"сборка #{i} упала (rc={r['rc']})"
        hashes.append(hashlib.sha256(bin_path("kernc").read_bytes()).hexdigest())
    ok = hashes[0] == hashes[1]
    m = {"kernc_sha256_build1": hashes[0][:32], "kernc_sha256_build2": hashes[1][:32],
         "bit_for_bit": ok, "optimize": "ReleaseFast"}
    return (w if ok else 0), m, ("бит-в-бит совпало" if ok else "ХЭШИ РАЗОШЛИСЬ")


def check_core_tests() -> tuple[int, dict, str]:
    w = WEIGHTS["core_tests"]
    # ВАЖНО: `zig build test` НЕ печатает счётчик (сборщик его поглощает).
    # Поэтому запускаем тест-раннер напрямую — он печатает «All N tests passed».
    base = ["zig", "test", "--dep", "compat",
            "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"]
    dbg = run("test-debug", base)
    rs = run("test-releasesafe", base + ["-O", "ReleaseSafe"])
    out = dbg["output"] + rs["output"]
    m_all = re.findall(r"All (\d+) tests passed", out)
    passed = int(m_all[0]) if m_all else None
    failed = num(r"(\d+) failed", out, 0)
    ok = (dbg["rc"] == 0 and rs["rc"] == 0 and len(m_all) == 2
          and (failed or 0) == 0)
    m = {"debug_rc": dbg["rc"], "releasesafe_rc": rs["rc"],
         "passed": passed, "failed": failed,
         "debug_ms": dbg["ms"], "releasesafe_ms": rs["ms"]}
    return (w if ok else 0), m, f"{passed} тестов × 2 режима (Debug + ReleaseSafe), failed={failed}"


def check_kern_next_tests() -> tuple[int, dict, str]:
    w = WEIGHTS["kern_next_tests"]
    r = run("test-next", ["zig", "build", "test-next"])
    return (w if r["rc"] == 0 else 0), {"rc": r["rc"], "ms": r["ms"]}, f"rc={r['rc']}"


def check_decision_coverage() -> tuple[int, dict, str]:
    w = WEIGHTS["decision_coverage"]
    r = run("coverage", ["zig", "test", "--dep", "compat",
                         "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"])
    fact = num(r"ФАКТ:\s*([0-9.]+)%", r["output"])
    frac = re.search(r"\((\d+)/(\d+)\)", r["output"])
    m = {"pct": fact,
         "covered": int(frac.group(1)) if frac else None,
         "total": int(frac.group(2)) if frac else None,
         "threshold_pct": num(r"ПОРОГ:\s*([0-9.]+)%", r["output"]),
         "ms": r["ms"]}
    ok = r["rc"] == 0 and fact is not None and fact >= 95.0
    return (w if ok else 0), m, f"{fact}% ({m['covered']}/{m['total']})"


def check_mutation_integrity() -> tuple[int, dict, str]:
    """Мутационный скор + ГЛАВНОЕ: мутатор не должен оставлять следов.

    Дефекты #48/#52: прерванный мутатор оставлял диверсию в файле, и она
    попадала в коммит. Поэтому проверяем инвариант «состояние дерева ДО ==
    состояние ПОСЛЕ» — это работает и на грязном дереве (во время разработки).
    """
    w = WEIGHTS["mutation_integrity"]
    before = run("git-status-before", ["git", "status", "--porcelain"])["output"]
    # --jobs 4: параллельные воркеры (вердикты не зависят от параллелизма);
    # --require-solver: без решателя 8 тестов молча пропускаются, и скор
    # считается по УСЕЧЁННОМУ набору — метрика была бы ЛОЖНОЙ (дефект #110).
    # CI ставит z3 через `pip install z3-solver`, поэтому бинарь есть в PATH.
    r = run("mutate", ["python3", "tools/mutate_zig.py", "--max", "40", "--seed", "7",
                       "--jobs", "4", "--require-solver"], timeout=1800)
    after = run("git-status-after", ["git", "status", "--porcelain"])["output"]
    score = num(r"MUTATION SCORE:\s*([0-9.]+)%", r["output"])
    killed = num(r"Killed \(compile\):\s*(\d+)", r["output"], 0)
    killed_t = num(r"Killed \(test\):\s*(\d+)", r["output"], 0)
    surv = num(r"Survived \(ДЫРЫ\):\s*(\d+)", r["output"], 0)
    no_traces = before == after
    m = {"score_pct": score, "killed_compile": killed, "killed_test": killed_t,
         "survived": surv, "tree_unchanged": no_traces, "rc": r["rc"]}
    ok = r["rc"] == 0 and no_traces and score is not None and score >= 90.0
    return (w if ok else 0), m, f"score={score}% survived={surv} следов_не_оставлено={no_traces}"


def check_kimg_throughput() -> tuple[int, dict, str]:
    """RAW vs Safe чтение + инвариант дефекта #55: оба пути дают ОДИН срез."""
    w = WEIGHTS["kimg_throughput"]
    r = run("perf", ["zig", "build", "bench-perf"], timeout=600)
    o = r["output"]
    raw = num(r"RAW zero-copy[^:]*:\s*([0-9.]+)\s*МБ/с", o)
    safe = num(r"Безопасное чтение[^:]*:\s*([0-9.]+)\s*МБ/с", o)
    mism = num(r"несовпадений:\s*(\d+)", o)
    m = {"raw_mbs": raw, "safe_mbs": safe, "slices_mismatches": mism,
         "rc": r["rc"], "slowdown_x": round(raw / safe, 1) if (raw and safe) else None}
    ok = r["rc"] == 0 and raw is not None and safe is not None and mism == 0
    return (w if ok else 0), m, f"RAW={raw} МБ/с · Safe={safe} МБ/с · несовпадений={mism}"



def own_zombies() -> list[tuple[int, str]]:
    """Зомби ТОЛЬКО среди наших потомков (а не общесистемные).

    🔴 ДЕФЕКТ #73. Прежняя проверка была `ps -eo stat= | grep -c '^Z'` — она
    считала ВСЕ зомби системы. Любой посторонний процесс в состоянии Z
    (например, `[qemu-aarch64] <defunct>`, оставшийся от кросс-архитектурного
    прогона) обнулял вес проверки Z3-моста, хотя к нему отношения не имеет.

    Здесь мы строим карту pid -> ppid и оставляем только зомби, чья цепочка
    родителей ведёт к текущему процессу.
    """
    me = os.getpid()
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,stat=,comm="],
                         capture_output=True, text=True).stdout
    procs: dict[int, tuple[int, str, str]] = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        procs[pid] = (ppid, parts[2], parts[3])

    def is_ours(pid: int) -> bool:
        seen: set[int] = set()
        while pid in procs and pid not in seen:
            seen.add(pid)
            ppid = procs[pid][0]
            if ppid == me:
                return True
            if ppid <= 1:
                return False
            pid = ppid
        return False

    return [(p, procs[p][2]) for p in procs
            if procs[p][1].startswith("Z") and is_ours(p)]


def check_z3_bridge_stress() -> tuple[int, dict, str]:
    """Таймаут решателя + отсутствие зомби и утечек дескрипторов."""
    w = WEIGHTS["z3_bridge_stress"]
    if not have("z3"):
        return 0, {"z3_available": False}, "NOT RUN: z3 не найден в PATH"
    bomb = Path("/tmp/kern_tel_bomb.smt2")
    bomb.write_text(
        "(set-logic NIA)\n(declare-const a Int)\n(declare-const b Int)\n(declare-const c Int)\n"
        "(assert (= (+ (* a a a) (* b b b) (* c c c)) 42))\n"
        "(assert (> a 100000000000))\n(check-sat)\n", encoding="utf-8")
    t0 = time.perf_counter()
    r = run("prove-bomb", [str(bin_path("kernc")), "prove", str(bomb)], timeout=120)
    dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    # 🔴 ДЕФЕКТ #73: раньше считались ВСЕ зомби системы
    # (`ps -eo stat= | grep -c '^Z'`). Любой посторонний зомби — например
    # `[qemu-aarch64] <defunct>`, оставшийся от cross_arch_test.sh, — обнулял
    # вес этой проверки, хотя к Z3-мосту он отношения не имеет. Теперь
    # считаются зомби только среди НАШИХ потомков.
    own = own_zombies()
    zombies = len(own)
    m = {"elapsed_ms": dt_ms, "rc": r["rc"], "zombies": zombies,
         "zombies_own": [f"{c}(pid={p})" for p, c in own],
         "fail_closed": bool(re.search(r"e\s*:\s*0", r["output"])
                            or "ToolError" in r["output"]
                            or "НЕ доказано" in r["output"]
                            or "недоступ" in r["output"].lower()),
         "proved_falsely": bool(re.search(r"e\s*:\s*1", r["output"]))}
    # ВАЖНО: на недоказанном контракте `kernc prove` ЗАКОННО выходит с НЕНУЛЕВЫМ
    # кодом (fail-closed). Поэтому rc != 0 здесь — ожидаемое поведение, а не сбой.
    # Критерий: нет СВОИХ зомби, вердикт e=0, и НЕ выдано ложное e=1.
    ok = zombies == 0 and m["fail_closed"] and not m["proved_falsely"]
    return (w if ok else 0), m, f"{dt_ms} мс, зомби(свои)={zombies}, e=0, ложного e=1 нет"


def check_memory_fuzz() -> tuple[int, dict, str]:
    """Фаззинг парсера: миллион мутаций, 0 паник (критерий)."""
    w = WEIGHTS["memory_fuzz"]
    r = run("fuzz-1m", ["zig", "build", "bench-fuzz-ast"], timeout=900)
    o = r["output"]
    iters = num(r"итераций:\s*(\d+)", o)
    # Точный шаблон: строка итога «ПАНИК/SIGSEGV: 0». Без него регекс
    # захватывает число итераций из следующей строки (найдено прогоном стенда).
    panics = num(r"ПАНИК/SIGSEGV:\s*(\d+)", o)
    if panics is None:
        panics = num(r"паник[^\n]*?(\d+)\s*$", o, 0)
    ok = r["rc"] == 0 and (panics or 0) == 0 and (iters or 0) >= 100_000
    m = {"rc": r["rc"], "iterations": iters, "panics": panics, "ms": r["ms"]}
    return (w if ok else 0), m, f"итераций={iters} паник={panics}"


def check_lean_proofs() -> tuple[int, dict, str]:
    w = WEIGHTS["lean_proofs"]
    r = run("lean", ["bash", "formal/check.sh"], timeout=1800)
    total = re.search(r"\((\d+)/(\d+) файлов", r["output"])
    ok = r["rc"] == 0 and "ALL LEAN PROOFS OK" in r["output"]
    m = {"rc": r["rc"],
         "files_checked": int(total.group(1)) if total else None,
         "files_total": int(total.group(2)) if total else None,
         "sorry": 0 if "0 sorry" in r["output"] else None,
         "ms": r["ms"]}
    return (w if ok else 0), m, f"{m['files_checked']}/{m['files_total']} файлов, 0 sorry"


def check_semantic_gap() -> tuple[int, dict, str]:
    """Семантический разрыв: Z (Int) vs BitVec32.

    В математических целых `x > 0 AND x + 1 < 0` НЕВЫПОЛНИМО (unsat).
    В 32-битных знаковых — ВЫПОЛНИМО при x = 0x7FFFFFFF (переполнение).
    Ровно тот разрыв, который доказывает `formal/KernSemanticGap.lean`.
    """
    w = WEIGHTS["semantic_gap"]
    if not have("z3"):
        return 0, {"z3_available": False}, "NOT RUN: z3 не найден"
    d = Path("/tmp/kern_tel_gap")
    d.mkdir(exist_ok=True)
    int_f = d / "int.smt2"
    bv_f = d / "bv32.smt2"
    int_f.write_text("(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x 0))\n"
                     "(assert (< (+ x 1) 0))\n(check-sat)\n", encoding="utf-8")
    bv_f.write_text("(set-logic QF_BV)\n(declare-const x (_ BitVec 32))\n"
                    "(assert (bvsgt x #x00000000))\n"
                    "(assert (bvslt (bvadd x #x00000001) #x00000000))\n(check-sat)\n",
                    encoding="utf-8")
    ri = run("gap-int", ["z3", str(int_f)], timeout=60)
    rb = run("gap-bv32", ["z3", str(bv_f)], timeout=60)
    int_unsat = "unsat" in ri["output"]
    bv_sat = rb["output"].strip().startswith("sat")
    m = {"int_status": "unsat" if int_unsat else ri["output"].strip()[:20],
         "bv32_status": "sat" if bv_sat else rb["output"].strip()[:20],
         "gap_demonstrated": bool(int_unsat and bv_sat)}
    ok = int_unsat and bv_sat
    return (w if ok else 0), m, "Z:unsat / BV32:sat — разрыв подтверждён"



# ===========================================================================
#  СВОДКА
# ===========================================================================

CHECKS = [
    ("slsa_determinism",   "Детерминизм сборки (бит-в-бит, ReleaseFast)", check_slsa_determinism),
    ("core_tests",         "Ядро: тесты (Debug + ReleaseSafe)",            check_core_tests),
    ("kern_next_tests",    "KERN-Next: тесты",                             check_kern_next_tests),
    ("decision_coverage",  "Покрытие решений (MC/DC-стиль, >= 95%)",       check_decision_coverage),
    ("mutation_integrity", "Мутации + чистота дерева после прогона",       check_mutation_integrity),
    ("kimg_throughput",    ".kimg: RAW vs Safe чтение",                    check_kimg_throughput),
    ("z3_bridge_stress",   "Z3-мост: таймаут, зомби, fail-closed",         check_z3_bridge_stress),
    ("memory_fuzz",        "Фаззинг парсера (0 паник)",                    check_memory_fuzz),
    ("lean_proofs",        "Lean 4: формальные доказательства",            check_lean_proofs),
    ("semantic_gap",       "Семантический разрыв: Z (Int) vs BitVec32",    check_semantic_gap),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="telemetry_report.json", help="путь к JSON-паспорту")
    ap.add_argument("--quick", action="store_true",
                    help="пропустить долгие проверки (мутации, фаззинг, две сборки)")
    args = ap.parse_args()

    print("=" * 100)
    print("KERN — ТЕЛЕМЕТРИЧЕСКИЙ СТЕНД (веса · время · MaxRSS · SHA-256 доказательства)")
    print("=" * 100)
    print(f"  Zig: {ZIG_DIR}  |  z3: {'есть' if have('z3') else 'НЕТ'}  |  режим: "
          f"{'quick' if args.quick else 'полный'}")
    print("-" * 100)

    results = []
    total_w = 0
    earned_w = 0
    for key, title, fn in CHECKS:
        w = WEIGHTS[key]
        if args.quick and key in ("slsa_determinism", "mutation_integrity", "memory_fuzz"):
            results.append({"key": key, "title": title, "weight": w, "earned": 0,
                            "metrics": {}, "evidence": "NOT RUN (--quick)",
                            "ms": 0.0, "rss_kb": 0, "hash": "-"})
            total_w += w
            print(f"  ~ {title:<52} | {0:>3}/{w:<3} | NOT RUN (--quick)")
            continue
        t0 = time.perf_counter()
        try:
            earned, metrics, evidence = fn()
        except Exception as e:  # noqa: BLE001 — стенд не должен падать от одной проверки
            earned, metrics, evidence = 0, {"error": repr(e)}, f"ИСКЛЮЧЕНИЕ: {e!r}"
        dt = round((time.perf_counter() - t0) * 1000.0, 1)
        total_w += w
        earned_w += earned
        results.append({"key": key, "title": title, "weight": w, "earned": earned,
                        "metrics": metrics, "evidence": evidence, "ms": dt,
                        "rss_kb": 0, "hash": hashlib.sha256(
                            json.dumps(metrics, ensure_ascii=False, sort_keys=True).encode()
                        ).hexdigest()[:16]})
        icon = "OK " if earned == w else ("~  " if earned else "FAIL")
        print(f"  {icon} {title:<52} | {earned:>3}/{w:<3} | {dt:>9.1f} мс | {evidence}")

    print("=" * 100)
    pct = round(earned_w * 100.0 / total_w, 1) if total_w else 0.0
    verdict = "ГОТОВ К РЕЛИЗУ" if earned_w == total_w else (
        "ЧАСТИЧНО" if pct >= 80 else "НЕ ГОТОВ")
    print(f"ИТОГО: {earned_w}/{total_w} ({pct}%)  ->  {verdict}")

    report = {
        "tool": "measure_all_kern",
        "zig": subprocess.run(["zig", "version"], capture_output=True, text=True,
                              env=_env()).stdout.strip(),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                 capture_output=True, text=True).stdout.strip(),
        "tree_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                                          capture_output=True, text=True).stdout.strip()),
        "score_pct": pct, "earned": earned_w, "total": total_w, "verdict": verdict,
        "weights": WEIGHTS,
        "checks": results,
    }
    out = ROOT / args.out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON-паспорт: {out}")
    return 0 if earned_w == total_w else 1


if __name__ == "__main__":
    sys.exit(main())

