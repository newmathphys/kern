# KERN applied to KERN — self-verification, with verbatim output

> Every block below is copied from a real run. Raw logs:
> `docs/evidence/self_verification/` (`run.log`, `xray_src.log`, `xray_tools.log`).
> Re-run everything with `make self-verify`, `make diff-equiv`,
> `python3 tools/scan_to_kern.py . -o /tmp/bridge.kern`, `./zig-out/bin/kernx graph`,
> `python3 tools/kern_contracts.py --xray src tools`.

## 1. The kernel's own contract

`make self-verify` runs the contract checker over `examples/self_verify.zig` — a file
that states the project's own invariants as `@kern:` contracts:

```
[PASS] remaining:     ДОКАЗАНО
       [PROOF VERIFIED] steps: 54 | premises bound: 3/3 | mp: 15 | rewrite (linear): 18 | farkas: 1 | trusted: 0 | holes: 0
[PASS] farkasNegLeZero: ДОКАЗАНО
       [PROOF VERIFIED] steps: 27 | premises bound: 3/3 | mp: 10 | rewrite (linear): 10 | farkas: 1 | trusted: 0 | holes: 0
[PASS] clampToPool:   ДОКАЗАНО
       [PROOF VERIFIED] steps: 50 | premises bound: 2/2 | mp: 9 | rewrite (linear): 17 | farkas: 2 | trusted: 0 | holes: 0
ИТОГО: доказано 3 | нарушено 0 | НЕ РЕШЕНО 0 | ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0
```

`trusted: 0 | holes: 0` on all three: the proof DAG was re-checked by the native
checker, with no trusted steps and no holes. There is a non-vacuous can-fail case
(`self-verify`) that breaks the contract and requires the gate to go red.

## 2. Every claim in the repository, turned into a bridge file

```
$ python3 tools/scan_to_kern.py . -o /tmp/kern_bridge.kern
[OK] артефактов=557, утверждений=74, связей=276
```

The scanner walks the tree and extracts 74 claims (files present, tests present,
anchors intact, TODOs) into a `.kern` manifest — no hand-written inventory.

## 3. The Truth Gate over our own claims

```
$ ./zig-out/bin/kernc build /tmp/kern_bridge.kern -o /tmp/bridge.kimg
[OK] Образ собран: /tmp/bridge.kimg (631 объектов)

$ ./zig-out/bin/kernc verify /tmp/bridge.kimg
    контракт НЕ привязан -> e=0 (N): текст без машинного доказательства
    ... (repeated per claim)
[i] ИТОГ: доказано 1, контрпримеров 0, без контракта 73,
    РАСХОЖДЕНИЙ С ЗАЯВЛЕННЫМ СТАТУСОМ 0
[i] e=1 выставляется ТОЛЬКО по вердикту решателя. Заявления без
    привязанного контракта остаются e=0 — это и есть честный статус.
```

**This is the most important result in this document.** Of 74 claims the repository
makes about itself, **73 get `e=0`** — because they are *prose*, not machine
contracts. The gate refuses to accept its own README as evidence. Zero claims
contradict their declared status, and `e=1` is granted only by a solver verdict.

A tool that does not believe itself is the only kind that can be trusted to check
someone else's code.

## 4. Architecture graph of the kernel, by the kernel

```
$ ./zig-out/bin/kernx graph --root src
узлов 88 | рёбер 70 | внешних 0 | SCC-циклов 0
```

88 modules, 70 import edges, no external edges (the tree is closed at `src/`), and
**no strongly connected components** — i.e. no circular module dependencies. The
graph is also cross-checked against the showcase artefact by `make graph-check`.

## 5. Zero-annotation X-ray on our own Zig

```
$ python3 tools/kern_contracts.py --xray src
[REPO SUMMARY] файлов 89 | функций проверено 129 / 377 (skipped 248) | находок 0
```

**0 findings.** 248 functions were skipped with an explicit reason (outside the
supported subset); none of them were silently counted as clean.

## 6. Zero-annotation X-ray on our own Python tooling

```
$ python3 tools/kern_contracts.py --xray tools
[REPO SUMMARY] файлов 95 | функций проверено 676 / 918 (skipped 242) | находок 679
```

679 findings: **4 `[CRASH PATH]` accusations and 660 `[BOUNDS]` candidates**.
Accusations and candidates are different things and are classified separately.

### The 4 accusations, classified

| Function | Claim | Verdict |
| --- | --- | --- |
| `bucket_of` (`cache_avalanche_bench.py:67`) | `% buckets` with `buckets == 0` | **Real latent hazard.** The module guards it (`if N == 0: sys.exit(2)`), the *function* does not — so any other caller passing 0 crashes. This is the residual of defect #323, whose fix was placed at module level. Deliberately **not silenced**: the function-level truth is what the tool reports. |
| `div_ok` (`deal_contracts.py:62`) | `a // b` with `b == 0` | **Known false accusation**, class #322: the guard is `@deal.pre(lambda a, b: b != 0)` — a *decorator* precondition, which the analyser does not model (it models `if`/ternary guards, fixed in #327). The file is a fixture for the deal-contract check. |
| `div_bad` (`deal_contracts.py:68`) | same | Same class; this fixture is *meant* to be wrong. |

### Why there are 660 `[BOUNDS]` candidates

A `[BOUNDS]` entry means the analyser saw an index whose length is **symbolic** —
there is neither a literal nor a `len(...)` condition it can use. Those are
*candidates*, and the tool prints them as such; it never promotes them to defects.
They cluster on functions that walk caller-supplied collections (`main`, `render`,
`body_smt`, `collect`, …). Turning them into verdicts needs loop invariants
(CHC wired into the analyser), which is tracked as open work, not claimed here.

## 7. Refactoring equivalence on our own examples

```
$ make diff-equiv
[КОНТРПРИМЕР] amount = 1, res_old = 0, res_new = 2, balance = 1
ИТОГО: эквивалентных 0 | разошедшихся 1 | всего 1
[OK] расхождение обнаружено (rc=1) — доказательство не фиктивно

[EQUIVALENT] charge: рефакторинг математически эквивалентен на всём домене Z (пруф-чекер принял)
ИТОГО: эквивалентных 1 | разошедшихся 0 | всего 1
[OK] положительный контроль: EQUIVALENT, пруф-чекер принял (trusted)
```

Two directions in one gate: a deliberately broken refactoring **must** be caught
with a concrete input, and an identical one **must** be proven — otherwise the check
would be a tautology.

## 8. What self-application does NOT prove

- **It is not a proof that the code is correct.** The kernel's own Zig has no
  `@kern:` contracts, so §5 reports "0 findings" over the *subset it could parse*
  (129 of 377 functions) — the other 248 were skipped, with reasons.
- **It does not cover the tooling soundly.** §6 produced 679 candidates, of which 3
  accusations are known false (class #322) and 1 is a real latent hazard. Nothing
  there is a proof.
- **It does not prove the proofs.** `trusted: 0 | holes: 0` is about the *proof
  DAG*, not about Z3, which stays a trusted component (see `docs/THREAT_MODEL.md`).
- **`e=0` on our own README is the expected outcome, not a failure.** It says the
  claims are prose. Making them `e=1` would require machine contracts for each.
- **The evidence gate validates `RC=` only for top-level logs.** Of the 49 logs in
  subdirectories, 21 carry no `RC=` — most are raw model transcripts (data, not
  command runs), but the two classes are not distinguished yet. Recorded here
  rather than patched: forcing `RC=` onto a transcript would invent a value.

## 9. What it does establish

| Property | Evidence |
| --- | --- |
| The project's own invariants are proven by its own checker | §1, `trusted: 0 \| holes: 0` |
| Every claim in the tree is extracted mechanically | §2, 557 artefacts / 74 claims |
| The gate does **not** accept prose as evidence | §3, `e=0` on 73 of 74 |
| No circular dependencies in the kernel | §4, 0 SCC |
| The analyser is silent on our own Zig where it has no evidence | §5, 0 findings, 248 skips with reasons |
| Where it accuses, it is checkable — and where it is wrong, we say so | §6, 4 accusations classified |
| Equivalence checking can both catch and prove | §7, both directions |

## 10. Facts referenced by this document

<!-- fact:core_tests -->451 core tests · <!-- fact:next_tests -->53 next ·
<!-- fact:catalog -->480 catalog · <!-- fact:check_targets -->182 CHECK ·
<!-- fact:canfail_cases -->222 can-fail cases · <!-- fact:anchors -->183 anchors ·
<!-- fact:registry_targets -->238 targets · <!-- fact:meta_targets -->41 META ·
<!-- fact:lean_theorems -->147 Lean theorems ·
QuixBugs <!-- fact:quixbugs.smt -->6/40 formal SMT ·
<!-- fact:quixbugs.differential -->40/40 live differential.

> Numbers come from `docs/facts.json` and are maintained by `make sync`;
> `make docs-parity` requires this block in both language versions.

