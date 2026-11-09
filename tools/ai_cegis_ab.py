#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""A/B + CEGIS: чем KERN отличается от обычных тестов на коде, который пишет ЖИВОЙ ИИ.

ЗАЧЕМ. Прошлый стенд (`ai_vs_kern_live.py`) показывал `proven` на простых задачах —
скептик справедливо отвечает: «pytest тоже сказал бы passed». Здесь берутся задачи с
КРАЕВОЙ ЛОВУШКОЙ (переполнение 32-битного int), где наивная формула, которую модель
пишет с первой попытки, ПРОХОДИТ обычные тесты и ЛОМАЕТСЯ на границе диапазона.

ТРИ ЗАМЕРА НА ОДНОМ И ТОМ ЖЕ КОДЕ МОДЕЛИ:
  A. ОБЫЧНЫЕ ТЕСТЫ (`gcc` + счастливые входы) — внешний оракул, как pytest;
  Б. KERN (контракт + Z3 + пруф-чекер) — ищет контрпример по всему домену;
  В. CEGIS-РАУНД 2: контрпример KERN отправляется ТОЙ ЖЕ модели с просьбой исправить;
     исправленный код снова проверяется KERN.

ЧЕСТНЫЕ ГРАНИЦЫ:
  * Модель недетерминирована: результат — замер конкретных генераций, а не «модель X
    всегда ошибается». `model_error` (таймаут/лимит) идёт отдельной корзиной и НЕ
    засчитывается ни как успех, ни как провал.
  * «Обычные тесты» здесь — компиляция `gcc` и запуск с несколькими нормальными
    входами; это ЧЕСТНАЯ имитация pytest, а не сам pytest.
  * Если KERN НЕ опроверг код модели, это не значит «код верен»: печатается вердикт
    (`proven`/`skip`/`unknown`) как есть.

Запуск:
    python3 tools/ai_cegis_ab.py --models m1,m2 [--json out.json]
Коды: 0 — прогон состоялся; 1 — анти-вакуум не прошёл (KERN не поймал заведомо
сломанный эталон — тогда мерить модели бессмысленно); 2 — нет opencode/gcc.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPENCODE = Path.home() / ".opencode" / "bin" / "opencode"
GCC = "gcc"

# ── Задачи с КРАЕВОЙ ЛОВУШКОЙ ────────────────────────────────────────────────
# `naive` — то, что модели пишут в Раунде 1 (проходит счастливые тесты!).
# `fixed` — то, что должно получиться после контрпримера (доказано KERN).
TASKS: dict[str, dict] = {
    "midpoint_i32": {
        "sig": "int midpoint(int lo, int hi)",
        "spec": "вернуть середину отрезка [lo, hi] (целые 32-битные, lo <= hi)",
        "contract": "// @kern:bitvec32\n// @kern:requires lo >= 0 and hi >= 0 and lo <= hi\n"
                    "// @kern:ensures result >= lo and result <= hi",
        "happy": [((2, 6), 4), ((0, 10), 5), ((3, 9), 6)],
        "naive": "int midpoint(int lo, int hi) {\n    return (lo + hi) / 2;\n}\n",
        "fixed": "int midpoint(int lo, int hi) {\n    return lo + (hi - lo) / 2;\n}\n",
    },
    "bounds_ok": {
        "sig": "int bounds_ok(int offset, int len, int cap)",
        "spec": "вернуть 1, если диапазон [offset, offset+len) целиком внутри [0, cap), иначе 0",
        "contract": "// @kern:bitvec32\n// @kern:requires offset >= 0 and len >= 0 and cap >= 0\n"
                    "// @kern:ensures result == 0 or offset <= cap - len",
        "happy": [((10, 5, 20), 1), ((0, 5, 5), 1), ((15, 10, 20), 0)],
        "naive": "int bounds_ok(int offset, int len, int cap) {\n"
                 "    if (offset + len <= cap) {\n        return 1;\n    }\n    return 0;\n}\n",
        "fixed": "int bounds_ok(int offset, int len, int cap) {\n"
                 "    if (len > cap || offset > cap - len) {\n        return 0;\n    }\n"
                 "    return 1;\n}\n",
    },
    "capacity_ok": {
        "sig": "int capacity_ok(int used, int add, int cap)",
        "spec": "вернуть 1, если used+add не превысит cap, иначе 0 (аргументы неотрицательны)",
        "contract": "// @kern:bitvec32\n// @kern:requires used >= 0 and add >= 0 and cap >= 0\n"
                    "// @kern:ensures result == 0 or used <= cap - add",
        "happy": [((10, 5, 20), 1), ((0, 5, 5), 1), ((18, 5, 20), 0)],
        "naive": "int capacity_ok(int used, int add, int cap) {\n"
                 "    if (used + add <= cap) {\n        return 1;\n    }\n    return 0;\n}\n",
        "fixed": "int capacity_ok(int used, int add, int cap) {\n"
                 "    if (add > cap || used > cap - add) {\n        return 0;\n    }\n"
                 "    return 1;\n}\n",
    },
}


def _run(cmd: list[str], timeout: int, cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd or ROOT), errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError as e:
        return 127, f"нет программы: {e.filename}"


def _code_block(text: str) -> str:
    """Код из ```c-блока; иначе — строки от `#include`/`@kern:`/сигнатуры."""
    blocks = re.findall(r"```(?:c|cpp)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    keep, on = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(("#include", "// @kern:", "int ")) or (on and (ln.startswith(("    ", "\t", "}")) or s in ("}", ""))):
            on = True
            keep.append(ln)
        elif on and s == "":
            continue
    return "\n".join(keep).strip() + "\n"


def happy_path(code: str, task: str, tmp: Path) -> tuple[bool, str]:
    """ИМИТАЦИЯ pytest: `gcc` + несколько СЧАСТЛИВЫХ входов (без краевых)."""
    t = TASKS[task]
    fn = t["sig"].split("(")[0].split()[-1]
    lines = ["#include <stdio.h>", code, "int main(void) {"]
    for args, want in t["happy"]:
        call = f"{fn}(" + ", ".join(str(x) for x in args) + ")"
        lines.append(f"    if ({call} != {want}) {{ printf(\"{call} = %d, ждали {want}\\n\", {call}); return 1; }}")
    lines.append('    printf("все счастливые входы сошлись\\n");')
    lines.append("    return 0;\n}")
    src = tmp / f"{task}_happy.c"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    exe = tmp / f"{task}_happy"
    rc, out = _run([GCC, "-O0", "-o", str(exe), str(src)], timeout=120)
    if rc != 0:
        return False, f"не скомпилировалось: {out.strip().splitlines()[-1][:120] if out.strip() else ''}"
    rc, out = _run([str(exe)], timeout=60)
    return rc == 0, out.strip().splitlines()[-1][:120] if out.strip() else ""


def kern_verdict(path: Path) -> tuple[str, str]:
    _rc, out = _run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(path)],
                    timeout=300)
    if "ДОКАЗАНО" in out and "нарушено 0" in out:
        return "proven", out
    if "КОНТРАКТ НАРУШЕН" in out or re.search(r"нарушено [1-9]", out):
        return "refuted", out
    if "вне подмножества" in out or "SKIP" in out:
        return "skip", out
    return "unknown", out


def _ce(out: str) -> str:
    m = re.search(r"\[КОНТРПРИМЕР\]\s*([^\]\n]+)", out)
    return m.group(1).strip()[:100] if m else ""


def write_task_file(task: str, body: str, tmp: Path, tag: str) -> Path:
    f = tmp / f"{task}_{tag}.c"
    f.write_text(TASKS[task]["contract"] + "\n" + body, encoding="utf-8")
    return f


def ask(model: str, prompt: str, timeout: int) -> tuple[int, str]:
    return _run([str(OPENCODE), "run", "-m", model, prompt], timeout=timeout, cwd=Path("/tmp"))


def prompt_round1(task: str) -> str:
    t = TASKS[task]
    return (f"Напиши ТОЛЬКО код на C, без пояснений. Сигнатура: {t['sig']}\n"
            f"Задача: {t['spec']}\n"
            f"Перед функцией ОБЯЗАТЕЛЬНО помести ровно эти строки контракта:\n{t['contract']}\n"
            f"Верни только блок ```c ... ```.")


def prompt_round2(task: str, code: str, ce: str) -> str:
    return (f"Твой код прошёл обычные тесты, но формальный верификатор KERN нашёл "
            f"контрпример: {ce}\nВот код:\n```c\n{code}```\n"
            f"Исправь функцию так, чтобы она была верна для ВСЕХ допустимых входов "
            f"(контракт сохрани). Верни только блок ```c ... ```.")


def anti_vacuum(tmp: Path) -> list[str]:
    """АНТИ-ВАКУУМ: наивный эталон обязан БЫТЬ ПОЙМАН, исправленный — ДОКАЗАН.

    Без этого «модель ошиблась» могло бы значить «KERN не работает»: сначала
    доказываем, что на заведомо известном баге гейт срабатывает.
    """
    bad: list[str] = []
    for task, t in TASKS.items():
        green, _ = happy_path(t["naive"], task, tmp)
        if not green:
            bad.append(f"{task}: наивный эталон НЕ проходит обычные тесты "
                       f"(тогда ловушка не «слепая», задача выбрана неверно)")
        path = write_task_file(task, t["naive"], tmp, "ref_naive")
        v, _ = kern_verdict(path)
        if v != "refuted":
            bad.append(f"{task}: KERN дал {v} на НАИВНОМ эталоне, а обязан ОПРОВЕРГНУТЬ")
        path = write_task_file(task, t["fixed"], tmp, "ref_fixed")
        v, _ = kern_verdict(path)
        if v != "proven":
            bad.append(f"{task}: KERN дал {v} на ИСПРАВЛЕННОМ эталоне, а обязан ДОКАЗАТЬ")
    return bad


def one(model: str, task: str, timeout: int, tmp: Path) -> dict:
    t0 = time.time()
    rc, out = ask(model, prompt_round1(task), timeout)
    if rc != 0:
        return {"model": model, "task": task, "status": "model_error",
                "why": out.strip()[:200], "seconds": round(time.time() - t0, 1)}
    code = _code_block(out)
    green, hp_msg = happy_path(code, task, tmp)
    path = write_task_file(task, code, tmp, "ai_r1")
    v1, out1 = kern_verdict(path)
    ce = _ce(out1)
    rec = {"model": model, "task": task, "pytest_green": green, "pytest_msg": hp_msg,
           "kern_round1": v1, "counterexample": ce, "status": "ok",
           "round2": None, "seconds": round(time.time() - t0, 1)}
    # CEGIS: контрпример уходит ТОЙ ЖЕ модели
    if v1 == "refuted":
        rc2, out2 = ask(model, prompt_round2(task, code, ce), timeout)
        if rc2 != 0:
            rec["round2"] = {"kern": "model_error", "why": out2.strip()[:200]}
        else:
            code2 = _code_block(out2)
            p2 = write_task_file(task, code2, p2_tag := "ai_r2", tmp)
            v2, _ = kern_verdict(p2)
            green2, _ = happy_path(code2, task, tmp)
            rec["round2"] = {"kern": v2, "pytest_green": green2}
    rec["seconds"] = round(time.time() - t0, 1)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="opencode/glm-5.3-flash-free")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    if not OPENCODE.is_file():
        print(f"[!] нет opencode ({OPENCODE}) — прогон невозможен: НАЗВАННЫЙ отказ")
        return 2
    if not shutil.which(GCC):
        print(f"[!] нет {GCC} — «обычные тесты» провести нечем: НАЗВАННЫЙ отказ")
        return 2
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip() in TASKS]

    with tempfile.TemporaryDirectory(prefix="ai_cegis_") as td:
        tmp = Path(td)
        print("── АНТИ-ВАКУУМ: наивный эталон обязан быть ПОЙМАН, исправленный — ДОКАЗАН")
        bad = anti_vacuum(tmp)
        if bad:
            for b in bad:
                print(f"  [FAIL] {b}")
            return 1
        print(f"  [OK] {len(TASKS)} задач: наивная формула проходит обычные тесты и ловится KERN; "
              f"исправленная — доказывается")

        rows: list[dict] = []
        for model in models:
            for task in tasks:
                r = one(model, task, a.timeout, tmp)
                rows.append(r)
                if r["status"] != "ok":
                    print(f"  [model_error] {model:36s} {task:12s} {r.get('why','')[:50]}")
                    continue
                r2 = r["round2"]
                r2s = f" | CEGIS: {r2['kern']}" if r2 else ""
                print(f"  [{'GREEN' if r['pytest_green'] else 'red  '}] {model:34s} {task:12s} "
                      f"обычные тесты | KERN r1: {r['kern_round1']:8s}{r2s}")
                if r["counterexample"]:
                    print(f"        контрпример KERN: {r['counterexample']}")

        if a.json:
            Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                    encoding="utf-8")

        ok = [r for r in rows if r["status"] == "ok"]
        blind = [r for r in ok if r["pytest_green"] and r["kern_round1"] == "refuted"]
        healed = [r for r in blind if (r["round2"] or {}).get("kern") == "proven"]
        print("\n── ИТОГ")
        print(f"  генераций: {len(rows)} | состоялось: {len(ok)} "
              f"| ошибок модели: {len(rows) - len(ok)}")
        print(f"  A. обычные тесты ЗЕЛЁНЫЕ на багованном коде ИИ: {len(blind)}")
        print(f"  Б. KERN перехватил (refuted) там, где тесты зелёные: "
              f"{sum(1 for r in blind if r['kern_round1'] == 'refuted')}")
        print(f"  В. CEGIS-раунд 2 довёл до PROVEN: {len(healed)} из {len(blind)}")
        print("  (ошибки модели НЕ считаются ни успехом KERN, ни провалом)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
