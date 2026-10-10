#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Авто-дискавери тестов + физический прогон + генерация свидетельств KERN.

Без ручного списка targets: находит тесты сам, связывает с утверждениями,
запускает в изоляции и вшивает блоки execution/evidence/link в .kern.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kern_exec_runner import KernExecutionRunner  # noqa: E402

EXCLUDE = {".git", ".venv", ".venvs", "__pycache__", "node_modules", "library",
           "sites", "images", "_trash", ".models", ".pdfium", "logs", "reports"}


def discover(root: Path, py: str = "python3"):
    targets = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in EXCLUDE and not d.startswith("."))
        rel_dir = os.path.relpath(dp, root)
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            rel = fn if rel_dir == "." else os.path.normpath(os.path.join(rel_dir, fn))
            if fn.startswith("test_") or fn.endswith("_test.py"):
                targets.append((f"tests present: {rel}", [py, rel], rel))
    mk = root / "Makefile"
    if mk.exists() and re.search(r"^test:", mk.read_text(encoding="utf-8", errors="ignore"), re.M):
        targets.append(("tests present: Makefile", ["make", "test"], None))
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--kern", default="bk.kern")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--python", default="python3")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    runner = KernExecutionRunner(str(root))

    targets = discover(root, args.python)
    if args.limit:
        targets = targets[:args.limit]
    print(f"[KERN RUNNER] авто-дискавери: найдено мишеней {len(targets)}", flush=True)

    results = []
    for claim_id, cmd, tf in targets:
        print(f"  ► {' '.join(cmd)} ... ", end="", flush=True)
        r = runner.run_target(claim_id, cmd, test_file=tf, timeout_sec=args.timeout)
        ok = (r.exit_code == 0) and r.non_vacuous
        print(f"[{'PASSED' if ok else 'FAILED'} exit={r.exit_code} vacuous={not r.non_vacuous} "
              f"masked={r.secrets_masked}] {r.duration_ms}ms", flush=True)
        results.append(r)

    evidence = runner.generate_kern_evidence(results)
    kern_path = root / args.kern
    with open(kern_path, "a", encoding="utf-8") as f:
        f.write(evidence)
    print(f"\n✅ [KERN] свидетельства вшиты в {kern_path}", flush=True)


if __name__ == "__main__":
    main()
