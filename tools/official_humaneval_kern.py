#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Официальный бенчмарк KERN на HumanEval / HumanEval+ (EvalPlus).

ЧЕСТНАЯ версия (исправлено):
  * сэмплы берутся от РЕАЛЬНОЙ LLM (не canonical_solution!);
  * гейт KERN — статические проверки (синтаксис + анти-вакуум);
  * запускается ОФИЦИАЛЬНЫЙ evalplus.evaluate на raw и на kern-сэмплах;
  * результат считается харнессом EvalPlus, а не печатается вручную.

ВАЖНО: статический гейт НЕ может поднять pass@1 — он может только отсеять
невалидный код. Реальная фильтрация требует ИСПОЛНЕНИЯ (см. Execution Runner).
"""
import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path


def kern_static_gate(completion: str) -> tuple[bool, str]:
    """Статический гейт: синтаксис + анти-вакуум (есть ли реальное тело)."""
    code = completion
    try:
        tree = ast.parse("def _wrap():\n" + "\n".join("    " + l for l in code.splitlines()))
    except SyntaxError:
        # пробуем как есть (иногда completion содержит отступы функции)
        try:
            ast.parse(code)
        except SyntaxError:
            return False, "SyntaxError"
        return True, "Admitted"
    # анти-вакуум: тело не должно быть только pass/.../return None
    body = tree.body[0].body if tree.body and isinstance(tree.body[0], ast.FunctionDef) else tree.body
    for st in body:
        if isinstance(st, ast.Pass):
            continue
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            continue  # docstring
        if isinstance(st, ast.Return) and (st.value is None or (isinstance(st.value, ast.Constant) and st.value.value is None)):
            continue
        return True, "Admitted"
    return False, "VacuousCodeBlocked"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="/tmp/samples_humaneval.jsonl",
                    help="JSONL с РЕАЛЬНЫМИ сэмплами LLM (task_id, completion)")
    ap.add_argument("--out-dir", default="evalplus_results")
    ap.add_argument("--run-evalplus", action="store_true", default=True)
    args = ap.parse_args()

    src = Path(args.samples)
    if not src.exists():
        print(f"[!] нет файла сэмплов {src}. Сначала: python3 tools/humaneval_ollama.py")
        sys.exit(1)

    out = Path(args.out_dir); out.mkdir(exist_ok=True)
    raw_p = out / "samples_raw.jsonl"
    kern_p = out / "samples_kern.jsonl"

    raw, kern = [], []
    admitted = blocked = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        comp = s.get("completion", "")
        raw.append({"task_id": s["task_id"], "completion": comp})
        ok, reason = kern_static_gate(comp)
        if ok:
            admitted += 1
            kern.append({"task_id": s["task_id"], "completion": comp})
        else:
            blocked += 1
            kern.append({"task_id": s["task_id"],
                         "completion": "\n    raise NotImplementedError('Blocked by KERN Gate')\n"})

    raw_p.write_text("\n".join(json.dumps(x) for x in raw) + "\n", encoding="utf-8")
    kern_p.write_text("\n".join(json.dumps(x) for x in kern) + "\n", encoding="utf-8")
    print(f"[i] всего сэмплов: {len(raw)}; KERN допустил: {admitted}; заблокировал: {blocked}")
    print(f"[i] записано: {raw_p}, {kern_p}")

    if args.run_evalplus:
        for label, path in (("RAW (без гейта)", raw_p), ("KERN (с гейтом)", kern_p)):
            print("\n" + "=" * 70)
            print(f"🏆 ОФИЦИАЛЬНЫЙ EVALPLUS — {label}")
            print("=" * 70, flush=True)
            subprocess.run([sys.executable, "-m", "evalplus.evaluate",
                            "--dataset", "humaneval", "--samples", str(path),
                            "--parallel", "4"], check=False)


if __name__ == "__main__":
    main()
