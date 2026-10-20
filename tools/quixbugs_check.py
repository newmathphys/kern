#!/usr/bin/env python3
"""QuixBugs baseline: 40 пар buggy/correct через `--diff-equiv`.

Ничего в репозитории не меняет. Классификация исходов:
  DIVERGED   — расхождение ДОКАЗАНО (есть контрпример Z3);
  EQUIVALENT — поведение совпадает на всём Z;
  UNKNOWN    — тело содержит `_havoc_k` (абстракция вызова): расхождение
               НЕДОКАЗУЕМО. Дефект #206: без этой ветки havoc давал ложный
               `[DIVERGED]` (два разных havoc всегда «различны»);
  SKIP       — функция вне подмножества (причина печатается).

Использование:
    git clone --depth 1 https://github.com/jkoppel/QuixBugs /tmp/QuixBugs-master
    python3 tools/quixbugs_check.py [/tmp/QuixBugs-master] [--json out.json]

Заменяет прежний скрипт v1.3, который проверял только `ast.parse` и ничего
не верифицировал.
"""
import ast
import collections
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "zig-out/bin/kernc"

_spec = importlib.util.spec_from_file_location("kc", ROOT / "tools/kern_contracts.py")
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)


def bodies(path: Path):
    """Как `parse_bodies`, но с ПРИЧИНОЙ отказа для каждой функции."""
    ok, bad = {}, {}
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {}, {"<parse>": f"SyntaxError: {e}"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        stmts = [
            st for st in node.body
            if not isinstance(st, ast.Pass)
            and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))
        ]
        try:
            body = kc.body_smt(stmts, {})
        except kc.NoReturn:
            bad[node.name] = "путь без return"
            continue
        except kc.Unsupported as e:
            bad[node.name] = str(e) or "Unsupported"
            continue
        except Exception as e:                      # noqa: BLE001
            bad[node.name] = f"{type(e).__name__}: {e}"
            continue
        params = [a.arg for a in node.args.args if a.arg != "self"]
        ok[node.name] = (params, body)
    return ok, bad


def run(qb: Path, json_out: Path | None) -> int:
    tasks = sorted(p.stem for p in (qb / "python_programs").glob("*.py")
                   if not p.stem.endswith("_test") and p.stem != "node")
    rows, reasons = [], collections.Counter()
    for name in tasks:
        b_file = qb / "python_programs" / f"{name}.py"
        c_file = qb / "correct_python_programs" / f"{name}.py"
        if not c_file.exists():
            rows.append((name, "NO-CORRECT", "", ""))
            continue
        a, a_bad = bodies(b_file)
        b, b_bad = bodies(c_file)
        common = [n for n in a if n in b]
        if not common:
            for _n, why in {**a_bad, **b_bad}.items():
                reasons[why] += 1
            first = next(iter({**a_bad, **b_bad}.values()), "нет функций в подмножестве")
            rows.append((name, "SKIP", "", first))
            continue
        diverged = same = unknown = 0
        seen = []
        for fn in sorted(common):
            pa, ba = a[fn]
            pb, bb = b[fn]
            if pa != pb:
                seen.append(f"{fn}:SKIP-params")
                continue
            if "_havoc_" in ba or "_havoc_" in bb:      # дефект #206
                unknown += 1
                seen.append(f"{fn}:UNKNOWN(havoc)")
                continue
            _rc, out = kc.run_kernc(str(KC), kc.diff_equiv_smt(pa, ba, bb))
            if "ДОКАЗАНО" in out:
                same += 1
                seen.append(f"{fn}:EQ")
            else:
                diverged += 1
                seen.append(f"{fn}:DIV")
        verdict = ("DIVERGED" if diverged else
                   ("UNKNOWN" if unknown and not same else
                    ("EQUIVALENT" if same else "SKIP")))
        rows.append((name, verdict, f"{diverged}/{same}/{unknown}", " ".join(seen)))

    w = max(len(r[0]) for r in rows) + 2
    print(f"{'task':<{w}} {'verdict':<11} {'div/eq/unk':<10} detali")
    for r in rows:
        print(f"{r[0]:<{w}} {r[1]:<11} {r[2]:<10} {r[3]}")
    cnt = collections.Counter(r[1] for r in rows)
    print("\n=== SUMMARY ===")
    for k, v in cnt.most_common():
        print(f"  {k:<11} {v}")
    print("\n=== SKIP REASONS (by function) ===")
    for why, n in reasons.most_common(20):
        print(f"  {n:3d}  {why}")
    if json_out:
        json_out.write_text(json.dumps({"rows": rows, "counts": cnt,
                                        "reasons": reasons}, ensure_ascii=False,
                                       indent=1), encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    qb = Path("/tmp/QuixBugs-master")
    json_out = None
    i = 1
    while i < len(argv):
        if argv[i] == "--json" and i + 1 < len(argv):
            json_out = Path(argv[i + 1])
            i += 2
            continue
        qb = Path(argv[i])
        i += 1
    if not (qb / "python_programs").is_dir():
        print(f"[!] нет {qb}/python_programs — склонируйте:\n"
              f"    git clone --depth 1 https://github.com/jkoppel/QuixBugs {qb}")
        return 2
    if not KC.exists():
        print(f"[!] не найден kernc: {KC} (соберите: zig build)")
        return 2
    return run(qb, json_out)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
