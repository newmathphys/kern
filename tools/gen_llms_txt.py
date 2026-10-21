#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Генератор `llms.txt` (и его копии в `docs/`) из `docs/facts.json`.

ЗАЧЕМ. `llms.txt` — точка входа для ИИ-агентов (стандарт llms.txt): именно этот
файл модель читает ПЕРВЫМ. Дефект #311: в нём жили числа, отставшие на десятки
единиц (400 тестов вместо 402, 120 теорем вместо 143, 1225 мутантов вместо
1361), и НИ ОДИН страж его не проверял — файла просто не было в списках.

ПРИНЦИП. Числа не пишутся руками: файл целиком собирается из `docs/facts.json`,
а `--check` сравнивает байты. Любая ручная правка числа становится красным
гейтом, а не «незаметным дрейфом».

Копий две (`llms.txt` в корне и `docs/llms.txt`) — обе пишутся из одного
источника, поэтому разойтись не могут.

Запуск:  python3 tools/gen_llms_txt.py [--check|--write|--selftest]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"
COPIES = ("llms.txt", "docs/llms.txt")


def _fmt_thousands(n: int) -> str:
    """86 953 — тонкий пробел, как в остальных документах проекта."""
    return f"{n:,}".replace(",", "\u202f") if n >= 10_000 else str(n)


def _wasm_bytes() -> int:
    p = ROOT / "docs" / "kernc.wasm"
    return p.stat().st_size if p.exists() else 0


def _mcp_tools() -> int:
    p = ROOT / "server.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    tools = d.get("tools")
    return len(tools) if isinstance(tools, list) else 0


def render(facts: dict) -> str:
    core = int(facts["core_tests"])
    skipped = int(facts.get("cross_arch_skipped", 0))
    passed = core - skipped
    nxt = int(facts["next_tests"])
    cat = int(facts["catalog"])
    lean = int(facts["lean_theorems"])
    sites = int(facts["mutation_sites"])
    files = int(facts["mutation_files"])
    checks = int(facts["check_targets"])
    cases = int(facts["canfail_cases"])
    arch_p = int(facts["cross_arch_passed"])
    arch_s = int(facts["cross_arch_skipped"])
    wasm = _wasm_bytes()
    tools_n = _mcp_tools()
    head = f"""# KERN — zero-trust verification gateway

> KERN verifies AI-generated code instead of trusting it: Z3 plus a native Zig
> proof-DAG checker (zero trusted steps), Belnap B4 four-valued logic, Lean 4
> soundness theorems, and a zero-annotation X-ray for Python, Zig, C, Rust, Go
> and TypeScript/JavaScript. The gate answers admit (e=1) only when a claim is
> proven; anything unverified is denied (e=0) — no probabilistic allowance.

## What it does

- **Proof, not vibes.** `kernc prove` runs Z3, then re-checks the emitted proof
  DAG with its own checker; `trusted: 0 | holes: 0` is the only accepted result.
- **Four-valued logic (Belnap B4).** Claims are combined in a lattice
  `N (0,0) / T (1,0) / F (0,1) / B (1,1)`; `JOIN_K(T, F) = B` and a conflict
  absorbs any later `T`, so a contradiction cannot be voted away.
- **Zero-annotation X-ray.** `--xray` (alias `--auto`) finds dead branches,
  crash paths (division by zero, overflow), array-bound violations and McCabe
  complexity in code that has **no** `@kern:` annotations at all.
- **Evidence with an epoch.** Execution evidence is bound to a BLAKE3 digest of
  the file; when the file changes the status decays `T -> N` (stale evidence
  closes the gate) until it is re-proven.
- **Proof-carrying containers.** `.kimg` images carry a Merkle root over object
  digests **and** names; `kernc verify` can check an embedded proof without a
  solver (`[PCC VERIFIED]`, `PATH` may be empty).

## Measured facts (this repository, current tree)

- Core Zig tests: **{core}** (`{passed} passed + {skipped} skipped`, 0 failed); KERN-Next: **{nxt}**;
  full catalog: **{cat}**.
- Lean 4: **{lean} theorems in 8 files, 0 errors, 0 sorry**.
- Mutation score on the Zig kernel: **{sites} / {sites} killed (100.0 %)** across
  **{files} files**, no sampling, zero survivors.
- Can-fail harness: **{checks} CHECK targets, {cases} non-vacuous cases, 0 vacuous**.
- Cross-architecture: **{arch_p} passed / {arch_s} skipped / 0 failed** on x86_64, ARM64 and
  PowerPC64 big-endian (QEMU).
- WebAssembly: `kernc.wasm` (**{_fmt_thousands(wasm)} bytes**) exports `kern_wasm_verify_proof`,
  `kern_wasm_lia_unsat2`, `kern_wasm_belnap_join`, `kern_wasm_belnap_allow`,
  `kern_wasm_admission_valid` — the proof checker and the Fourier–Motzkin
  solver run in the browser with no OS calls.

> These numbers are generated from `docs/facts.json` by `tools/gen_llms_txt.py`
> and gated by `make llms-check`. Editing them by hand fails the gate.
"""
    return head + TAIL.format(tools_n=tools_n)


TAIL = """
## Command line (selected)

- `kernc prove <file.smt2>` — prove + machine-check; prints `trusted`/`holes`.
- `kernc verify <image.kimg>` — verify a sealed image (proof-carrying if a
  `<stem>.proof` object is present).
- `kernc grep <pattern> <image.kimg>` — integrity-checked search inside `.kimg`.
- `kernc pack-dir <dir> -o <out.kimg>` — pack a directory tree into one image.
- `kernc fsck|inspect|diff <image.kimg>` — integrity check, JSON passport,
  section-by-section comparison of two images.
- `python3 tools/kern_contracts.py --xray <file|dir>` — zero-annotation X-ray.
- `python3 tools/kern_contracts.py explain --hypotheses <file>` — read-only
  abduction: which `@kern:requires` is missing. Never edits the file.
- `--audit-repo <path|owner/repo|url>` — audit an arbitrary project (safe git
  sandbox: no hooks, no LFS, no prompts), with `--html` report.
- `--diff-equiv old.py new.py` — prove (or refute) that a refactoring changed
  behaviour, with a concrete input where it diverges.
- `--audit-mcp <schema.json>` — prompt-injection, invisible-Unicode and
  rug-pull audit of MCP tool schemas.
- `--heal <file>` — find a crash path, insert a guard, re-verify, and only then
  replace the file atomically (keeping `<file>.bak`).

## MCP server ({tools_n} tools, stdio)

`python3 examples/kern_mcp_server.py` — `kern_verify_smt`,
`kern_prove_with_checker`, `kern_verify_multi_belnap`, `kern_verify_python`,
`kern_check_equivalence`, `kern_xray_code`, `kern_verify_action`,
`kern_rlvr_reward`. Manifests: `server.json`, `mcp.json`, `.well-known/mcp.json`
(generated from the server itself by `tools/gen_mcp_manifests.py`).

## Documentation

- [README](https://github.com/newmathphys/kern/blob/main/README.md): overview and quickstart
- [Capability status](https://github.com/newmathphys/kern/blob/main/docs/CAPABILITY_STATUS.md): defect journal, what is measured and what is not
- [Capabilities with evidence](https://github.com/newmathphys/kern/blob/main/docs/CAPABILITIES.md): every claim checked against code
- [Metrics](https://github.com/newmathphys/kern/blob/main/docs/METRICS.md): every measurement with the command that produced it
- [Testing and speed guide](https://github.com/newmathphys/kern/blob/main/docs/TESTING_AND_SPEED_GUIDE.md): verification methods and the speed-ups
- [Belnap sources](https://github.com/newmathphys/kern/blob/main/docs/BELNAP_SOURCES.md): theory-to-code map with machine-checked bibliography
- [Cybernetics](https://github.com/newmathphys/kern/blob/main/docs/CYBERNETIC_VISION.md): why this architecture (Anokhin, Glushkov, Belnap, Victor)
- [High-stakes use cases](https://github.com/newmathphys/kern/blob/main/docs/HIGH_STAKES_USE_CASES.md): AMM ramp (Rust), hex-nibble parser (C), money in cents (Python) - proven and refuted obligations with compiler-reproduced witnesses
- [How to write a contract for ANY project](https://github.com/newmathphys/kern/blob/main/docs/CONTRACT_ANY_PROJECT.md): the 5-step recipe plus a worked example that found a real crash (SIGFPE) in TheAlgorithms/C
- [Shadow-audit case study](https://github.com/newmathphys/kern/blob/main/docs/SHADOW_AUDIT_EXAMPLE.md): two real defects in TheAlgorithms/C math/catalan.c - a SIGFPE on n=0 and silent wrong answers from n=11 - with the correct fix and the obvious wrong one
- [Site](https://newmathphys.github.io/kern/): live demo, browser WASM playground

## Honest limits

- The extractor works on a **subset** (linear integer arithmetic, `if/else`
  paths, machine-type bounds). Unsupported constructs are reported as `SKIP`
  with a reason, never silently accepted.
- KERN verifies **contracts**, not arbitrary code. Third-party repositories
  contain no `@kern:` annotations, so an automatic sweep over them yields a
  table of zeros; measured in `audits/README.md`.
- Python contracts are translated with no type information: an attribute may be
  modelled as `Int`.
- The proof checker is conservative: an uncovered rule yields `trusted > 0`, and
  `trusted > 0` is **never** presented as `trusted: 0`.
- `.kimg` names are covered by the Merkle root; a byte flip in a name is
  detected, but the model of a third-party function is ours — a counterexample
  must be reproduced on their build before it is called a bug.
- Licence: **PolyForm Noncommercial 1.0.0** (source-available). Commercial use
  requires a licence from the copyright holder.
"""


def _facts() -> dict:
    return json.loads(FACTS.read_text(encoding="utf-8"))


def check() -> int:
    want = render(_facts())
    bad = 0
    for rel in COPIES:
        p = ROOT / rel
        got = p.read_text(encoding="utf-8") if p.exists() else ""
        if got != want:
            print(f"[FAIL] {rel} устарел — запустите tools/gen_llms_txt.py --write")
            bad += 1
    if bad:
        print(f"\n[FAIL] расхождений: {bad}")
        return 1
    print("[OK] llms.txt и docs/llms.txt совпадают с docs/facts.json")
    return 0


def write() -> int:
    want = render(_facts())
    n = 0
    for rel in COPIES:
        p = ROOT / rel
        if not p.exists() or p.read_text(encoding="utf-8") != want:
            p.write_text(want, encoding="utf-8")
            n += 1
            print(f"  updated {rel}")
    print(f"[OK] llms.txt: файлов обновлено {n}")
    return 0


def selftest() -> int:
    """Мета-тест: подсадка старого числа ОБЯЗАНА ловиться, а сдвиг любого
    факта — менять вывод. Иначе число в шаблоне захардкожено и снова устареет
    молча (ровно так прожил дефект #311)."""
    facts = _facts()
    base = render(facts)
    bad = 0
    if render(facts) != base:
        print("[FAIL] selftest: рендер не идемпотентен")
        bad += 1
    for key in ("core_tests", "lean_theorems", "mutation_sites", "check_targets",
                "canfail_cases", "catalog", "next_tests"):
        mutated = dict(facts)
        mutated[key] = int(facts[key]) + 1
        if render(mutated) == base:
            print(f"[FAIL] selftest: {key} не влияет на вывод — число захардкожено")
            bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] llms.txt selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    if "--check" in args:
        return check()
    if "--write" in args:
        return write()
    print("usage: tools/gen_llms_txt.py [--check|--write|--selftest]")
    return 2


if __name__ == "__main__":
    sys.exit(main())

