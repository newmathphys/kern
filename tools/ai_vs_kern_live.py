#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ЖИВОЙ СТЕНД «ИИ против KERN»: свободные модели opencode пишут код по
спецификации, KERN его СУДИТ (а не наоборот).

ЗАЧЕМ. Все прежние корпуса — чужой код, написанный людьми. Здесь экзамен
берётся у генераторов: если модель реализует спецификацию, KERN обязан
ПОДТВЕРДИТЬ (`ДОКАЗАНО`); если модель халтурит (`x // y` вместо ceil) — KERN
обязан ПРЕДЪЯВИТЬ контрпример.

ЧЕСТНАЯ ГРАНИЦА. Модель недетерминирована: результат — ЗАМЕР на конкретных
генерациях (модель/промпт/время сохраняются), а не «модель X всегда ошибается».
Пропуск (SKIP/ошибка разбора) НЕ засчитывается ни как успех, ни как провал
KERN — он печатается отдельной корзиной.

Запуск:
    python3 tools/ai_vs_kern_live.py --models opencode/glm-5.3-flash-free \\
        [--tasks ceil_div,clamp,abs_int] [--timeout 180] [--json out.json]

Коды: 0 — прогон состоялся; 1 — АНТИ-ВАКУУМ не прошёл (KERN не доказал эталон
или не опроверг заведомо сломанный код — тогда мерять модели бессмысленно);
2 — нет opencode/сети — НАЗВАННЫЙ отказ, не «зелёный».
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPENCODE = Path.home() / ".opencode" / "bin" / "opencode"

# Каждая задача: спецификация словами + контракт + ЗАВЕДОМО ВЕРНАЯ реализация.
# Эталон нужен для анти-вакуума: если KERN не доказывает эталон, судить модели
# бессмысленно (это дефект инструмента, а не модели).
TASKS: dict[str, dict] = {
    "ceil_div": {
        "spec": "ceil_div(x, y) = ceil(x/y) для целых x,y (округление ВВЕРХ), y > 0",
        "req": "x >= 0 and y > 0",
        "ens": "result == (x + y - 1) // y",
        "good": "def ceil_div(x, y):\n    return (x + y - 1) // y\n",
    },
    "clamp": {
        "spec": "clamp(x, lo, hi) = x, если lo <= x <= hi; lo, если x < lo; hi, если x > hi; lo <= hi",
        "req": "lo <= hi",
        "ens": "result >= lo and result <= hi",
        "good": "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
    },
    "abs_int": {
        "spec": "abs_int(x) = |x| для целого x",
        "req": "x >= -1000000 and x <= 1000000",
        "ens": "result >= 0 and result >= x",
        "good": "def abs_int(x):\n    if x < 0:\n        return -x\n    return x\n",
    },
}


def _run(cmd: list[str], timeout: int, cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd or ROOT), errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def _extract_code(text: str) -> str:
    """Последний ```python-блок; иначе — строки кода/контрактов."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    keep = [ln for ln in text.splitlines()
            if ln.strip().startswith(("def ", "# @kern:")) or ln.startswith(("    ", "\t"))
            or ln.strip() == ""]
    return "\n".join(keep).strip() + "\n"


def kern_verdict(path: Path) -> tuple[str, str]:
    """Вердикт KERN: proven | refuted | skip | error + полный вывод."""
    _rc, out = _run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(path)],
                    timeout=300)
    if "ДОКАЗАНО" in out and "нарушено 0" in out:
        return "proven", out
    if "КОНТРАКТ НАРУШЕН" in out or re.search(r"нарушено [1-9]", out):
        return "refuted", out
    if "вне подмножества" in out or "SKIP" in out:
        return "skip", out
    return "error", out



def sanity_reference(tmp: Path) -> list[str]:
    """АНТИ-ВАКУУМ: эталоны обязаны ДОКАЗЫВАТЬСЯ, а сломанный код — опровергаться."""
    problems: list[str] = []
    for name, t in TASKS.items():
        good = tmp / f"ref_good_{name}.py"
        good.write_text(f"# @kern:requires {t['req']}\n# @kern:ensures {t['ens']}\n" + t["good"],
                        encoding="utf-8")
        v, _ = kern_verdict(good)
        if v != "proven":
            problems.append(f"эталон `{name}`: KERN дал {v}, а обязан ДОКАЗАТЬ")
    bad = tmp / "ref_bad_ceil.py"
    bad.write_text("# @kern:requires x >= 0 and y > 0\n"
                   "# @kern:ensures result == (x + y - 1) // y\n"
                   "def ceil_div(x, y):\n    return x // y\n", encoding="utf-8")
    v, _ = kern_verdict(bad)
    if v != "refuted":
        problems.append(f"сломанный ceil_div: KERN дал {v}, а обязан ОПРОВЕРГНУТЬ")
    return problems


def one_case(model: str, task: str, timeout: int, tmp: Path) -> dict:
    t = TASKS[task]
    prompt = (
        f"Напиши ТОЛЬКО код Python, без пояснений, по спецификации: {t['spec']}\n"
        f"Функция ОБЯЗАНА иметь комментарии-контракт ровно в таком виде:\n"
        f"# @kern:requires {t['req']}\n# @kern:ensures {t['ens']}\n"
        f"Верни только блок кода."
    )
    t0 = time.time()
    rc, out = _run([str(OPENCODE), "run", "-m", model, prompt],
                   timeout=timeout, cwd=Path("/tmp"))
    if rc != 0:
        return {"model": model, "task": task, "status": "model_error",
                "why": out.strip()[:300], "seconds": round(time.time() - t0, 1)}
    code = _extract_code(out)
    f = tmp / f"{task}.py"
    f.write_text(code, encoding="utf-8")
    verdict, kout = kern_verdict(f)
    m = re.search(r"\[КОНТРПРИМЕР\]\s*([^\]\n]+)", kout)
    return {"model": model, "task": task, "status": verdict,
            "counterexample": (m.group(1).strip()[:80] if m else ""),
            "code": code[:400], "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="opencode/glm-5.3-flash-free")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    if not OPENCODE.is_file():
        print(f"[!] нет opencode ({OPENCODE}) — живой прогон невозможен: НАЗВАННЫЙ отказ")
        return 2
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip() in TASKS]

    with tempfile.TemporaryDirectory(prefix="ai_vs_kern_") as td:
        tmp = Path(td)
        print("── АНТИ-ВАКУУМ: эталоны (KERN обязан доказать верное и опровергнуть сломанное)")
        problems = sanity_reference(tmp)
        if problems:
            for p in problems:
                print(f"  [FAIL] {p}")
            return 1
        print(f"  [OK] эталоны: {len(TASKS)} доказаны, сломанный ceil_div опровергнут")

        rows: list[dict] = []
        for model in models:
            for task in tasks:
                r = one_case(model, task, a.timeout, tmp)
                rows.append(r)
                ce = f" | [КОНТРПРИМЕР] {r['counterexample']}" if r.get("counterexample") else ""
                print(f"  [{r['status']:11s}] {model:36s} {task:10s} {r['seconds']:5.1f} с{ce}")

        if a.json:
            Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
        print("\n── ИТОГ")
        proven = sum(1 for r in rows if r["status"] == "proven")
        refuted = sum(1 for r in rows if r["status"] == "refuted")
        skip = sum(1 for r in rows if r["status"] == "skip")
        err = sum(1 for r in rows if r["status"] in ("error", "model_error"))
        print(f"  генераций: {len(rows)} | ДОКАЗАНО {proven} | ОПРОВЕРГНУТО {refuted} "
              f"| пропуск {skip} | ошибок {err}")
        print("  (пропуск/ошибка НЕ считаются ни успехом KERN, ни провалом)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

