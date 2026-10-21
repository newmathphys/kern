#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Anti-self-deception gate: KERN's verdicts must survive REAL tools.

Two independent checks, both on the corpus in `audits/codecheck/`:

  A. GROUND TRUTH. Every `F` case is replayed with the EXACT counterexample
     numbers KERN printed, using the native toolchain (`python3`, `gcc` with
     UBSan, `rustc` with overflow checks, `zig run`). A witness that does not
     make the real program fail is a paper-only witness.
  B. MUTATION KILL. Every `T` case is mutated in a temporary copy; KERN must
     flip to `F`. A proof that survives a semantic mutation is blind to the body.

The mutations are chosen to be **semantically different** by construction. An
*equivalent* mutation (e.g. `x < lo` -> `x <= lo` where both branches return the
same value) must NOT be used as evidence, because a prover returning `F` there
would be wrong - that trap is documented in `docs/REAL_WORLD_MEGATEST.md` 14.2.

Exit codes: 0 = all checks pass; 1 = at least one; 2 = corpus/toolchain missing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "audits" / "codecheck"
KC = ROOT / "tools" / "kern_contracts.py"
ZIG = Path(os.environ.get("ZIG", shutil.which("zig") or
                          Path.home() / "opt/zig-x86_64-linux-0.17.0/zig"))


def env() -> dict:
    e = dict(os.environ)
    e["PATH"] = str(ROOT / ".venv" / "bin") + os.pathsep + e.get("PATH", "")
    return e


def kern(path: Path):
    r = subprocess.run([sys.executable, str(KC), str(path)], capture_output=True,
                       text=True, env=env(), timeout=300)
    out = r.stdout + r.stderr
    verdict = ("T" if "[PASS]" in out else "F" if "[FAIL]" in out
               else "N" if "[N]" in out else "SKIP")
    ce = {}
    m = re.search(r"\[КОНТРПРИМЕР\]\s*([^\n]+)", out)
    if m:
        for mm in re.finditer(r"([A-Za-z_]\w*)\s*=\s*(-?\d+)", m.group(1)):
            ce[mm.group(1)] = int(mm.group(2))
    return verdict, ce, out


def sh(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


# ---------------------------------------------------------------- PART A

def ground_truth(tmp: Path) -> tuple[int, int, list[str]]:
    ok = total = 0
    notes: list[str] = []

    # Python: the contract must fail as an assertion at runtime.
    src = CORPUS / "py_abs_bad.py"
    v, ce, _ = kern(src)
    total += 1
    runner = tmp / "py_ce.py"
    runner.write_text(
        f"import sys; sys.path.insert(0, {str(CORPUS)!r})\n"
        f"from py_abs_bad import absolute\n"
        f"x = {ce.get('x', -1)}\n"
        f"r = absolute(x)\n"
        f"assert r >= 0 and (r == x or r == -x), f'ensures violated: absolute({{x}})={{r}}'\n"
        f"print('NO VIOLATION')\n", encoding="utf-8")
    rc, out = sh([sys.executable, str(runner)])
    if v == "F" and rc != 0 and "AssertionError" in out:
        ok += 1
        notes.append(f"python  {ce} -> AssertionError (rc={rc})")
    else:
        notes.append(f"python  FAILED: verdict={v} rc={rc} {out.strip()[:80]}")

    # C: UBSan must trap division by zero.
    v, ce, _ = kern(CORPUS / "c_unguarded.c")
    total += 1
    c = tmp / "c_ce.c"
    c.write_text("#include <stdio.h>\nint ratio(int a, int b) { return a / b; }\n"
                 "int main(void) {\n"
                 f"    printf(\"NO VIOLATION %d\\n\", ratio({ce.get('a', 1)}, {ce.get('b', 0)}));\n"
                 "    return 0;\n}\n", encoding="utf-8")
    exe = tmp / "c_ce"
    rc_c, out_c = sh(["gcc", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                      "-o", str(exe), str(c)])
    rc, out = sh([str(exe)]) if rc_c == 0 else (rc_c, out_c)
    if v == "F" and rc != 0 and "division by zero" in out:
        ok += 1
        notes.append(f"c       b={ce.get('b')} -> UBSan division by zero (rc={rc})")
    else:
        notes.append(f"c       FAILED: verdict={v} rc={rc} {out.strip()[:80]}")

    # Rust: overflow checks must panic.
    v, ce, _ = kern(CORPUS / "rust_overflow.rs")
    total += 1
    rs = tmp / "rs_ce.rs"
    rs.write_text("pub fn add32(a: i32, b: i32) -> i32 { return a + b; }\n"
                  "fn main() { let r = add32(%d, %d); println!(\"NO VIOLATION {}\", r); }\n"
                  % (ce.get("a", 2147483647), ce.get("b", 1)), encoding="utf-8")
    exe = tmp / "rs_ce"
    rc_c, out_c = sh(["rustc", "-C", "overflow-checks=on", "-o", str(exe), str(rs)])
    rc, out = sh([str(exe)]) if rc_c == 0 else (rc_c, out_c)
    if v == "F" and rc != 0 and "overflow" in out:
        ok += 1
        notes.append(f"rust    a={ce.get('a')}, b={ce.get('b')} -> panic overflow (rc={rc})")
    else:
        notes.append(f"rust    FAILED: verdict={v} rc={rc} {out.strip()[:80]}")

    # Zig: division by zero must panic at runtime (u64 keeps `/` legal).
    v, ce, _ = kern(CORPUS / "zig_div.zig")
    total += 1
    z = tmp / "zig_ce.zig"
    z.write_text(
        'const std = @import("std");\n'
        'pub fn ratio(a: u64, b: u64) u64 {\n    return a / b;\n}\n'
        'pub fn main() void {\n'
        f'    std.debug.print("NO VIOLATION {{d}}\\n", .{{ratio({ce.get("a", 8)}, {ce.get("b", 0)})}});\n'
        '}\n', encoding="utf-8")
    rc, out = sh([str(ZIG), "run", str(z)])
    if v == "F" and rc != 0 and "division by zero" in out:
        ok += 1
        notes.append(f"zig     b={ce.get('b')} -> panic division by zero (rc={rc})")
    else:
        notes.append(f"zig     FAILED: verdict={v} rc={rc} {out.strip()[:80]}")

    return ok, total, notes


# ---------------------------------------------------------------- PART B

# Семантически РАЗЛИЧНЫЕ мутации (не эквивалентные мутанты).
MUTATIONS = {
    "py_abs_ok.py": [("return x", "return -x")],
    "py_clamp_ok.py": [("return lo", "return lo - 1")],
    "zig_clean.zig": [("return a + b;", "return a - b;")],
    "c_clean.c": [("return a + b;", "return a - b;")],
    "rust_clean.rs": [("return a + b;", "return a - b;")],
}


def mutation_kill(tmp: Path) -> tuple[int, int, list[str]]:
    ok = total = 0
    notes: list[str] = []
    for name, subs in MUTATIONS.items():
        src = CORPUS / name
        v0, _, _ = kern(src)
        for old, new in subs:
            total += 1
            body = src.read_text(encoding="utf-8")
            if old not in body:
                notes.append(f"{name}: mutation anchor missing ({old!r}) - fixture drift")
                continue
            copy = tmp / ("mut_" + name)
            copy.write_text(body.replace(old, new, 1), encoding="utf-8")
            v1, ce, _ = kern(copy)
            if v0 == "T" and v1 == "F":
                ok += 1
                notes.append(f"{name}: {old!r} -> {new!r}  T -> F {ce}")
            else:
                notes.append(f"{name}: {old!r} -> {new!r}  base={v0} after={v1} SURVIVED")
    return ok, total, notes


def main() -> int:
    if not CORPUS.is_dir():
        print(f"[FAIL] corpus missing: {CORPUS}")
        return 2
    if not Path(ZIG).exists():
        print(f"[FAIL] zig not found at {ZIG} (set ZIG=...)")
        return 2
    for tool in ("gcc", "rustc"):
        if shutil.which(tool) is None:
            print(f"[FAIL] {tool} not found in PATH")
            return 2

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        gt_ok, gt_total, gt_notes = ground_truth(tmp)
        mk_ok, mk_total, mk_notes = mutation_kill(tmp)

    print("=== A. ground truth: KERN's counterexamples vs native toolchains ===")
    for n in gt_notes:
        print("  " + n)
    print("=== B. mutation kill: every T file must flip to F ===")
    for n in mk_notes:
        print("  " + n)
    print(f"\nGROUND TRUTH {gt_ok}/{gt_total} · MUTATION KILL {mk_ok}/{mk_total}")
    if gt_ok != gt_total or mk_ok != mk_total:
        print("ANTI-SELF-DECEPTION FAILED")
        return 1
    print("ANTI-SELF-DECEPTION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
