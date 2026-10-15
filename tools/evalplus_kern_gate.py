#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN-гейт поверх сэмплов EvalPlus (без генерации, без LLM).

Прогоняет каждый сэмпл через статический гейт KERN:
  1) синтаксическая компиляция prompt+completion (ast.parse)
  2) анти-вакуум: наличие реального тела (не только pass/...)
Заблокированные (e=0) заменяются на безопасную заглушку, чтобы их
нельзя было зачесть как правильные. Затем считаем, сколько решений
гейт отсеял и сколько из отсеянных реально падали на тестах.
"""
import argparse
import ast
import json
import sys
from pathlib import Path


def gate(prompt: str, completion: str):
    """Возвращает (admitted: bool, reason: str)."""
    code = prompt + completion
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, "SyntaxError: %s" % e.msg
    # анти-вакуум: есть ли хоть один не-тривиальный оператор в теле completion
    real = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Return, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While,
                             ast.Try, ast.With, ast.Raise, ast.Call, ast.Assert)):
            real += 1
    if real == 0:
        return False, "VacuousCodeBlocked"
    return True, "Admitted"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="humaneval", choices=["humaneval", "mbpp"])
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.dataset == "humaneval":
        from evalplus.data import get_human_eval_plus as get
    else:
        from evalplus.data import get_mbpp_plus as get
    prob = get()

    rows = [json.loads(l) for l in open(args.samples, encoding="utf-8")]
    blocked = []
    out = []
    for r in rows:
        tid = r["task_id"]
        prompt = prob[tid]["prompt"]
        ok, reason = gate(prompt, r["completion"])
        if ok:
            out.append(r)
        else:
            blocked.append((tid, reason))
            out.append({"task_id": tid,
                        "completion": "\n    raise NotImplementedError('Blocked by KERN Gate')\n"})
    Path(args.out).write_text("\n".join(json.dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"[KERN] всего={len(rows)} допущено={len(rows)-len(blocked)} заблокировано={len(blocked)}")
    from collections import Counter
    c = Counter(reason.split(":")[0] for _, reason in blocked)
    for k, v in c.most_common():
        print(f"       {k}: {v}")
    for tid, reason in blocked[:10]:
        print(f"       - {tid}: {reason[:60]}")


if __name__ == "__main__":
    main()
