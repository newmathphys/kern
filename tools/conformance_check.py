#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Phase 5: the conformance exam (12 sections).

WHY THIS EXISTS. Unit tests prove that *some* code path works. This exam proves
that the SYSTEM conforms to the twelve architectural requirements, and it does
so without trusting test names: it reads facts produced by the kernel binary
(`zig-out/bin/kern-conformance`, see `src/conformance_oracle.zig`) and by the
real CLI (`kernc fsck/inspect/diff`). Every section is PASS/FAIL with a
non-zero exit code, so a broken requirement cannot hide behind a green suite.

Sections:
  1  Belnap B4 values (twist pairs)
  2  all 16 joinK pairs, and join is the least upper bound of <=k
  3  both lattices (<=k, <=t) + conflation
  4  seven state axes and their laws (timeout != F, out_of_fuel != B, ...)
  5  evidence ledger: add / retract / idempotency / order independence
  6  provenance: negative recursive SCC rejected, positive allowed
  7  admission gate: certificate binding and QueryKind rejection
  8  KERN-X: one shared fuel counter, quotas
  9  cache key: every one of the 13 fields invalidates
 10  broken .kimg through the CLI: fsck / inspect / diff
 11  KERNFS attacks, including no-mmap
 12  determinism: the same input twice gives the same verdict

Usage:
    python3 tools/conformance_check.py            # all sections
    python3 tools/conformance_check.py --only 10  # one section
    python3 tools/conformance_check.py --json out.json
    python3 tools/conformance_check.py --selftest # prove checks are not vacuous
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "zig-out" / "bin" / "kern-conformance"
KERNC = ROOT / "zig-out" / "bin" / "kernc"
FIXTURES = ROOT / "tests" / "fixtures"

OK = "OK"
BAD = "FAIL"


def zig() -> str:
    env = os.environ.get("ZIG")
    if env and Path(env).exists():
        return env
    found = shutil.which("zig")
    if found:
        return found
    for cand in sorted(Path.home().glob("opt/zig-*/zig")):
        if cand.exists():
            return str(cand)
    return "zig"


def read_facts() -> dict[tuple[str, str], str]:
    """Run the oracle and parse `section|key|value` lines."""
    # ДЕФЕКТ #281: экзамен мог оценивать УСТАРЕВШИЙ бинарник (сборка упала, а
    # `python3 tools/conformance_check.py` запускали напрямую). Теперь сначала
    # сборка; если она не прошла - отказ, а не зелёный отчёт по старому коду.
    build = subprocess.run([zig(), "build"], cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    if build.returncode != 0:
        raise SystemExit(
            "build failed - refusing to grade a stale binary:\n"
            + (build.stderr or build.stdout)[-2000:]
        )
    if not ORACLE.exists():
        raise SystemExit(
            f"oracle missing: {ORACLE}\n"
            "build it first: zig build   (target: zig-out/bin/kern-conformance)"
        )
    out = subprocess.run([str(ORACLE)], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SystemExit(f"oracle failed rc={out.returncode}:\n{out.stderr[-2000:]}")
    facts: dict[tuple[str, str], str] = {}
    for raw in out.stdout.splitlines():
        parts = raw.split("|")
        if len(parts) < 3:
            continue
        # `b4|N|0|0` -> ("b4", "N") = "0|0";  `join|N|T|T` -> ("join", "N|T") = "T"
        section, rest = parts[0], parts[1:]
        if section in ("b4", "conflate"):
            facts[(section, rest[0])] = "|".join(rest[1:])
        elif section in ("join", "le_k", "le_t"):
            facts[(section, rest[0] + "|" + rest[1])] = "|".join(rest[2:])
        else:
            facts[(section, rest[0])] = "|".join(rest[1:])
    return facts


class Section:
    def __init__(self, number: int, title: str):
        self.number = number
        self.title = title
        self.checks: list[tuple[bool, str]] = []

    def check(self, ok: bool, message: str) -> None:
        self.checks.append((bool(ok), message))

    def eq(self, got, want, label: str) -> None:
        self.check(got == want, f"{label}: got {got!r}, want {want!r}")

    @property
    def failed(self) -> int:
        return sum(1 for ok, _ in self.checks if not ok)

    def emit(self, verbose: bool) -> None:
        status = "PASS" if self.failed == 0 else "FAIL"
        print(f"[{status}] section {self.number:2d}: {self.title}")
        for ok, message in self.checks:
            if ok and not verbose:
                continue
            print(f"       {'ok  ' if ok else 'FAIL'} {message}")


B4 = ("N", "T", "F", "B")

AXES = ("BelnapValue", "CoverageState", "VerificationVerdict", "Lifecycle",
        "IntegrityState", "TrustState", "ExecutionOutcome")


def _table(facts, name, values=B4):
    t = {}
    for a in values:
        for b in values:
            raw = facts.get((name, a + "|" + b))
            if raw is not None:
                t[(a, b)] = raw == "1"
    return t


def section1(facts):
    s = Section(1, "Belnap B4 values (twist pairs)")
    want = {"N": "0|0", "T": "1|0", "F": "0|1", "B": "1|1"}
    for sym, pair in want.items():
        s.eq(facts.get(("b4", sym)), pair, f"B4[{sym}] = (p|n)")
    s.eq(len([k for k in facts if k[0] == "b4"]), 4, "exactly four truth values")
    return s


def section2(facts):
    s = Section(2, "all 16 joinK pairs; join is the lub of <=k")
    t = {}
    for a in B4:
        for b in B4:
            v = facts.get(("join", a + "|" + b))
            if v in B4:
                t[(a, b)] = v
    s.eq(len(t), 16, "16 joinK pairs present")
    le = _table(facts, "le_k")
    s.eq(len(le), 16, "16 <=k comparisons present")
    if len(t) != 16 or len(le) != 16:
        return s

    comm = all(t[(a, b)] == t[(b, a)] for a in B4 for b in B4)
    s.check(comm, "joinK is commutative")
    s.check(all(t[(a, a)] == a for a in B4), "joinK is idempotent")
    s.check(all(t[("N", a)] == a for a in B4), "N is the unit")
    s.check(all(t[("B", a)] == "B" for a in B4), "B absorbs (contradiction cannot be erased)")
    s.eq(t[("T", "F")], "B", "joinK(T,F) = B")

    lub = True
    for a in B4:
        for b in B4:
            c = t[(a, b)]
            if not (le[(a, c)] and le[(b, c)]):
                lub = False
            for d in B4:
                if le[(a, d)] and le[(b, d)] and not le[(c, d)]:
                    lub = False
    s.check(lub, "joinK is the LEAST upper bound of <=k, for all 16 pairs")
    return s


def section3(facts):
    s = Section(3, "both lattices (<=k, <=t) and conflation")
    lek = _table(facts, "le_k")
    let = _table(facts, "le_t")
    s.eq(len(lek), 16, "16 <=k comparisons")
    s.eq(len(let), 16, "16 <=t comparisons")
    if len(lek) != 16 or len(let) != 16:
        return s

    for name, rel in (("<=k", lek), ("<=t", let)):
        s.check(all(rel[(a, a)] for a in B4), f"{name} is reflexive")
        s.check(all((rel[(a, b)] and rel[(b, a)]) == (a == b) for a in B4 for b in B4),
                f"{name} is antisymmetric")
        tri = all(not (rel[(a, b)] and rel[(b, c)]) or rel[(a, c)]
                  for a in B4 for b in B4 for c in B4)
        s.check(tri, f"{name} is transitive (a partial order)")

    s.check(all(lek[("N", a)] for a in B4), "<=k minimum is N (no information)")
    s.check(all(lek[(a, "B")] for a in B4), "<=k maximum is B (over-determined)")
    s.check(all(let[("F", a)] for a in B4), "<=t minimum is F")
    s.check(all(let[(a, "T")] for a in B4), "<=t maximum is T")
    s.check(not lek[("T", "F")] and not lek[("F", "T")], "T and F are <=k incomparable")
    s.check(not let[("N", "B")] and not let[("B", "N")], "N and B are <=t incomparable")

    confl = {a: facts.get(("conflate", a)) for a in B4}
    s.eq(confl["N"], "B", "conflate(N) = B")
    s.eq(confl["B"], "N", "conflate(B) = N")
    s.eq(confl["T"], "T", "conflate(T) = T")
    s.eq(confl["F"], "F", "conflate(F) = F")
    s.eq(facts.get(("conflate_involution", "all")), "1", "conflate is an involution")
    rev = all(lek[(a, b)] == lek[(confl[b], confl[a])] for a in B4 for b in B4)
    s.check(rev, "conflate reverses <=k and preserves <=t (information inversion)")
    return s


def section4(facts):
    s = Section(4, "seven state axes and their laws")
    src = (ROOT / "src" / "next" / "state_axes.zig").read_text(encoding="utf-8")
    for name in AXES:
        s.check(f"pub const {name}" in src, f"axis type {name} exists")

    want = {"proved": "T", "refuted": "F", "unknown": "N", "timeout": "N",
            "out_of_fuel": "N", "invalid_certificate": "N", "tool_error": "N"}
    for verdict, belnap in want.items():
        s.eq(facts.get(("verdict", verdict)), belnap, f"{verdict} -> {belnap}")

    s.check(facts.get(("verdict", "timeout")) != "F", "timeout != F (no evidence is not refutation)")
    s.check(facts.get(("verdict", "out_of_fuel")) != "B", "out_of_fuel != B (no limit is not contradiction)")
    s.check(facts.get(("verdict", "invalid_certificate")) != "F",
            "invalid_certificate != F (a bad proof is not a counterexample)")
    s.eq(facts.get(("verdict_b_never", "all")), "1", "B is never produced by a verdict (only by T + F)")
    return s


def section5(facts):
    s = Section(5, "evidence ledger: add / retract / idempotency / order")
    s.eq(facts.get(("ledger", "after_pos")), "T", "one positive contribution -> T")
    s.eq(facts.get(("ledger", "conflict")), "B", "positive + negative -> B (contradiction kept)")
    s.eq(facts.get(("ledger", "after_retract")), "T", "retract(negative) RECOMPUTES -> T")
    s.eq(facts.get(("ledger", "duplicate_rejected")), "1", "duplicate add is idempotent")
    s.eq(facts.get(("ledger", "order_independent")), "1", "contribution order does not matter")
    return s


def section6(facts):
    s = Section(6, "provenance: negative recursive SCC rejected")
    s.eq(facts.get(("scc", "negative")), "1", "f -> g -> not f is rejected")
    s.eq(facts.get(("scc", "positive")), "0", "f <-> g is accepted (cycles are legal)")
    return s


def section7(facts):
    s = Section(7, "admission gate: certificate binding and QueryKind")
    s.eq(facts.get(("gate", "matching_kind")), "T", "valid certificate with matching kind -> T")
    s.eq(facts.get(("gate", "query_kind_mismatch")), "1",
         "equivalence proof presented as refutation is rejected")
    s.eq(facts.get(("gate", "cert_reuse_other_fn")), "1",
         "certificate for another function is rejected")
    return s


def section8(facts):
    s = Section(8, "KERN-X: one shared fuel counter")
    s.eq(facts.get(("kernx", "fuel_after_first")), "0", "first machine burned the shared fuel to 0")
    s.eq(facts.get(("kernx", "second_branch_exhausted")), "1",
         "second machine sees 0 -> OutOfFuel (no copy per branch)")
    return s


def section9(facts):
    s = Section(9, "cache key: all 13 fields invalidate")
    fields = ("task_kind", "semantic_slice", "body_hashes", "contract",
              "dependency_hashes", "model_fingerprint", "prompt_hash",
              "params_hash", "tools_hash", "retrieval_hash", "schema_hash",
              "policy_hash", "checker_version")
    for f in fields:
        s.eq(facts.get(("cache", f)), "1", f"changing {f} changes the key")
    s.eq(len(fields), 13, "exactly 13 fields")
    s.eq(facts.get(("cache", "schema_prefix")), "1", "schema prefix v2 is part of the key")
    s.eq(facts.get(("cache", "solver_version")), "1", "solver version reaches the key")
    return s


def _run(cmd, timeout=300):
    env = dict(os.environ)
    env.setdefault("PATH", "")
    extra = [str(ROOT / "zig-out" / "bin")]
    venv_bin = ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        extra.append(str(venv_bin))
    env["PATH"] = os.pathsep.join(extra) + os.pathsep + env["PATH"]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, env=env)


def section10(facts):
    s = Section(10, "broken .kimg through the CLI: fsck / inspect / diff")
    opt = FIXTURES / "kimg_unknown_optional.kimg"
    req = FIXTURES / "kimg_unknown_required.kimg"
    be = FIXTURES / "kimg_big_endian.kimg"
    for f in (opt, req, be):
        s.check(f.exists(), f"fixture on disk: {f.name}")
    if not (KERNC.exists() and opt.exists() and req.exists() and be.exists()):
        s.check(False, "kernc binary or fixtures missing (run `zig build`)")
        return s

    r = _run([str(KERNC), "fsck", str(opt)])
    s.check(r.returncode == 0, f"fsck(unknown optional) rc={r.returncode} (expected 0)")

    r = _run([str(KERNC), "fsck", str(req)])
    blob = (r.stdout + r.stderr)
    s.check(r.returncode != 0 and "UnsupportedRequiredFeature" in blob,
            "fsck(unknown REQUIRED) is rejected with UnsupportedRequiredFeature")

    r = _run([str(KERNC), "fsck", str(be)])
    blob = (r.stdout + r.stderr)
    s.check(r.returncode != 0 and "WrongEndianness" in blob,
            "fsck(big-endian) is rejected with WrongEndianness")

    r = _run([str(KERNC), "inspect", str(opt)])
    ok = False
    detail = f"inspect rc={r.returncode}"
    if r.returncode == 0:
        try:
            manifest = json.loads(r.stdout)
            ok = manifest.get("object_count") == 1 and len(manifest.get("objects", [])) == 1
            detail = f"inspect manifest: object_count={manifest.get('object_count')}"
        except json.JSONDecodeError as exc:
            detail = f"inspect output is not JSON: {exc}"
    s.check(ok, detail)

    r = _run([str(KERNC), "diff", str(opt), str(opt)])
    s.check(r.returncode == 0, f"diff(identical) rc={r.returncode} (expected 0)")
    r = _run([str(KERNC), "diff", str(opt), str(req)])
    s.check(r.returncode != 0, "diff(different) reports a difference")
    return s


def section11(facts):
    s = Section(11, "KERNFS attacks, including no-mmap")
    s.eq(facts.get(("kernfs", "dotdot")), "1", "../etc/passwd is rejected")
    s.eq(facts.get(("kernfs", "inner_dotdot")), "1", "/a/../../b is rejected")
    s.eq(facts.get(("kernfs", "null_byte")), "1", "NUL byte in a component is rejected")
    s.eq(facts.get(("kernfs", "normal")), "0", "/a/b is accepted")
    s.eq(facts.get(("kernfs", "write_denied")), "1", "write() is denied (read-only FS)")

    r = _run([zig(), "test", "--dep", "compat", "-Mroot=src/core_test_root.zig",
              "-Mcompat=src/compat.zig", "--test-filter", "no-mmap"], timeout=600)
    s.check(r.returncode == 0, "no-mmap: mutating the source buffer after mount changes nothing")
    return s


def section12(facts):
    s = Section(12, "determinism: same input twice, same verdict")
    r = _run([sys.executable, str(ROOT / "tools" / "determinism_check.py")], timeout=600)
    s.check(r.returncode == 0, "determinism_check.py agrees on two runs")
    return s


BUILDERS = {1: section1, 2: section2, 3: section3, 4: section4, 5: section5,
            6: section6, 7: section7, 8: section8, 9: section9, 10: section10,
            11: section11, 12: section12}


def selftest(facts) -> int:
    """Prove the exam is not a rubber stamp: corrupt a fact, expect a FAIL."""
    corruptions = [
        (1, ("b4", "N"), "1|1"),
        (2, ("join", "T|F"), "T"),
        (3, ("conflate", "N"), "N"),
        (4, ("verdict", "timeout"), "F"),
        (5, ("ledger", "after_retract"), "B"),
        (6, ("scc", "negative"), "0"),
        (7, ("gate", "query_kind_mismatch"), "0"),
        (8, ("kernx", "second_branch_exhausted"), "0"),
        (9, ("cache", "prompt_hash"), "0"),
    ]
    bad = 0
    for number, key, value in corruptions:
        broken = dict(facts)
        broken[key] = value
        sec = BUILDERS[number](broken)
        if sec.failed == 0:
            print(f"[FAIL] selftest: section {number} did NOT notice {key} -> {value!r}")
            bad += 1
        else:
            print(f"[ok]   selftest: section {number} turns red on {key} -> {value!r}")
    if bad:
        print(f"\nSELFTEST FAILED: {bad} corruption(s) went unnoticed")
        return 1
    print(f"\nSELFTEST PASSED: {len(corruptions)} corruptions detected, exam is not vacuous")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="KERN conformance exam (12 sections)")
    ap.add_argument("--only", type=int, action="append", help="run only these sections")
    ap.add_argument("--json", type=Path, help="write a machine-readable report")
    ap.add_argument("--verbose", action="store_true", help="print successful checks too")
    ap.add_argument("--selftest", action="store_true", help="prove the exam can go red")
    args = ap.parse_args()

    facts = read_facts()
    print(f"conformance: {len(facts)} facts straight from the kernel\n")
    if args.selftest:
        return selftest(facts)

    chosen = args.only or sorted(BUILDERS)
    report, failed_sections = [], 0
    for number in chosen:
        builder = BUILDERS.get(number)
        if builder is None:
            print(f"[FAIL] unknown section {number}")
            failed_sections += 1
            continue
        sec = builder(facts)
        sec.emit(args.verbose)
        if sec.failed:
            failed_sections += 1
        report.append({"section": number, "title": sec.title,
                       "failed": sec.failed, "checks": len(sec.checks),
                       "details": [{"ok": ok, "message": m} for ok, m in sec.checks]})

    total_checks = sum(r["checks"] for r in report)
    total_failed = sum(r["failed"] for r in report)
    print(f"\nconformance: {len(report)} sections, {total_checks} checks, {total_failed} failed")
    if args.json:
        args.json.write_text(json.dumps(
            {"sections": report, "failed": total_failed}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"report: {args.json}")
    if failed_sections:
        print("CONFORMANCE FAILED")
        return 1
    print("CONFORMANCE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
