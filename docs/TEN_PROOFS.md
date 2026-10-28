# Ten proofs: every command verified against commit `0577b49`

> **Status: MEASURED.** Every command below was executed from the repository root
> and its verdict copied verbatim. Where a number drifts between runs (timings),
> the **stable** claim is the threshold, not the seconds — and that is stated.
> Where the repository only has a **snapshot** of foreign code, the snapshot path
> is given instead of a non-existent upstream path.
>
> Companions: `docs/CAPABILITY_MATRIX.md` (all capabilities with gates),
> `docs/CORPORA.md` (corpus inventory), `docs/EXAMPLE_WHY_KERN.md` (the `lcm` story).

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->181 · cases <!-- fact:canfail_cases -->221 · anchors <!-- fact:anchors -->182 · registry <!-- fact:registry_targets -->237 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## 1. Hardware `i32` overflow (Rust)

```bash
python3 tools/kern_contracts.py audits/codecheck/rust_overflow.rs
```
```
[FAIL] add32: ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647])
       [КОНТРПРИМЕР] result = 2147483648, b = 1, a = 2147483647
       [RUNTIME CONFIRMED] вычисленное значение 2147483648 вне диапазона [...]
```
Note the sign: the counterexample is `result = 2147483648` — the value **outside**
the range, not the wrapped `-2147483648`.
**Oracle:** `rustc -C overflow-checks=on` → `panic: attempt to add with overflow` (rc=101).

## 2. Unguarded division by zero (C)

```bash
python3 tools/kern_contracts.py --auto audits/codecheck/c_unguarded.c
```
```
[CRASH PATH] ratio: возможно деление на ноль: b == 0
[XRAY SUMMARY] checked 0 / 1 functions, skipped 1 with explicit reasons, findings 1, SMT calls 1
```
**Oracle:** `gcc -fsanitize=undefined` at `b = 0` → `runtime error: division by zero`.

## 3. `SIGFPE` on an edge value (`TheAlgorithms/C`, PR #1595)

```bash
python3 tools/kern_contracts.py docs/evidence/any_project/catalan_contract.c
```
```
[FAIL] catalan_divisor: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] n = 0, result = 0
```
The upstream file itself is **not** in this repository (it is foreign code): the
snapshot is `docs/evidence/any_project/catalan_contract.c`, the fix is
`docs/pr/catalan_fix.patch`.
**Oracle:** `gcc -O0` on the unmodified upstream file with input `0` →
`Floating point exception (core dumped)` (SIGFPE, rc=136).

## 4. Signed multiplication overflow (`TheAlgorithms/C`, PR #1596)

The reproducing command — the shadow contract now lives **in the repository**, so
the verdict can be re-run by anyone:

```bash
python3 tools/kern_contracts.py docs/evidence/example_why_kern/lcm_numerator.c
```
```
[BV] lcm_numerator (стр. 15): теория битовых векторов (_ BitVec 32, знаковый)
[FAIL] lcm_numerator: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] a = #x643b3fbb, b = #5a724dfe, result = #x643a7a8a
```
The guard `lcm_numerator_guarded.c` (same body, honest bounds) is **PROVEN** — so
the refutation above is not vacuous. Gate: `make foreign-verdicts-check`.
The original run is kept as a snapshot in `docs/evidence/example_why_kern/lcm.log`:
```
[FAIL] lcm_numerator: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] a = #x643b3fbb, b = #5a724dfe, result = #x643a7a8a
--- gcc (наземная правда) ---
lcm_probe.c:24:16: runtime error: signed integer overflow: 1681908667 * 1517634558
                   cannot be represented in type 'int'
```
The KERN counterexample is in **hex** (`#x…`), not `a = 50000, b = 50000`. The
`50000 * 50000` pair is the **PR description's** illustration of the same defect,
confirmed by `gcc`, not the solver's counterexample.

## 5. `u64` underflow on subtraction (`TheAlgorithms/Rust`, PR #1075)

The reproducing command — the shadow contract (the verbatim expression `n - i`
from the upstream loop) is in the repository:

```bash
python3 tools/kern_contracts.py docs/evidence/thealgorithms_rust/binom_step.rs
```
```
[FAIL] binom_step: ПЕРЕПОЛНЕНИЕ типа `u64` (диапазон [0, 18446744073709551615])
       [КОНТРПРИМЕР] result = -1, k = 2, i = 1, n = 0
```
The guarded twin `binom_step_guarded.rs` (`requires i <= n`) is **PROVEN**, so the
refutation is not vacuous. Gate: `make foreign-verdicts-check`.
The upstream file itself is **not** vendored — it is kept verbatim as a snapshot:
```bash
cat docs/evidence/thealgorithms_rust/binomial_coefficient.rs   # upstream, verbatim
cat docs/evidence/thealgorithms_rust/binomial_coefficient_fixed.rs
```
**Oracle:** `cargo test` → `attempt to subtract with overflow` (rc=101);
Codecov recorded **100.00 % patch coverage** on the added guard
(`if k > n { return BigInt::from(0); }`).

## 6. Blind spots of the EvalPlus `MBPP+` benchmark

The dataset solution for `Mbpp/265`, **verbatim** from
`evalplus_results/samples_mbpp.jsonl`:
```python
def list_split(lst, n):
    result = [[] for _ in range(n)]
    for i, val in enumerate(lst):
        result[i % n].append(val)
    return result
```
(`n = 0` → `range(0)` gives an empty outer list, then `i % 0` → `ZeroDivisionError`.)

```bash
make mbpp-xray-check
```
The gate asserts `false_crash_accusations == 0` **verified by live Python** and
`confirmed_blindspots == 3` (`Mbpp/265`, `Mbpp/292`, `Mbpp/422`). Its selftest has
four branches: healthy run, false accusation, undercount, and **vacuum**.
**Oracle:** live `python3`: `list_split([1, 2], 0)` → `ZeroDivisionError`.

## 7. Specification tampering by an AI agent is blocked (the lock)

On a **clean tree** the command reports the lock is intact:
```bash
make contracts-lock-check
```
```
[OK] замок контрактов цел: ни один запечатанный контракт не изменён
  [OK] покрытие замка: 20 файлов с аннотациями
```
The alarm appears only when a contract is actually weakened — that is the
`canfail` case `contract-lock` (`[SECURITY] … rc=2`). Live models DeepSeek and GLM
did exactly this on an unsatisfiable contract (they narrowed `requires`, leaving
`ensures` untouched) — recorded in `docs/evidence/live_eval/`.

## 8. Comparing two revisions without contracts (`--diff-equiv`)

```bash
python3 tools/kern_contracts.py --diff-equiv \
    docs/evidence/real_history/idx_before.py docs/evidence/real_history/idx_after.py
```
```
[DIVERGED] idx_ok: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ
       [КОНТРПРИМЕР] k = -1, n = 0, res_old = 1, res_new = 0
```
Files are snapshots of `boltons` commit `5eb6cc0` (the real fix), kept under
`docs/evidence/real_history/`.
**Oracle:** live Python: the old code returned `1` for an invalid index, the new one returns `0`.

## 9. Catastrophic backtracking (ReDoS) with a physical timer

```bash
make oracle-redos-check
```
```
  OK CONFIRMED_VULN   (.+)+      сентинел='\n'   физика=1.4237с     ядро=vulnerable
  OK CONFIRMED_SAFE   abc        сентинел=''     физика=0.0001с     ядро=safe
  OK FAIL_CLOSED      (\d+)+     ядро=skip (вердикта НЕТ — верно)
  подтверждено УЯЗВИМЫХ: 6 · безопасных: 3 · ЛОЖНЫХ ОБВИНЕНИЙ: 0 · ПРОПУСКОВ: 0
```
**The stable claim is 6/3/0/0 and the threshold (0.2 s), not the seconds.** The
measured time varies between runs (`1.4237 с` here, `1.44 с` in the earlier
snapshot in `docs/METRICS.md` §159) because it is wall-clock time on a shared machine.
**Oracle:** the real Python `re` engine hangs on the pathological input.

## 10. Secret leak through execution time (non-interference)

```bash
make oracle-noninterference-check
```
```
[ИЗМЕРЕНО] отношение времён (позиция отличия 1 против 4096, min-of-N):
  constantTimeEqual : CT_RATIO=1.0035  (порог < 3.0)
  earlyExitEqual    : EE_RATIO=86.8099 (порог >= 10.0)
  [CONFIRMED_SAFE] constant-time: модель говорит утечки нет, реальность не зависит
  [CONFIRMED_LEAK] early-exit: модель говорит утечка, реальность зависит от позиции
```
**Again the stable claim is the pair of thresholds** (`CT < 3.0`, `EE ≥ 10.0`) and the
classification; the ratios drift between runs (`1.0003`/`68.80` in the §163 snapshot
versus `1.0035`/`86.81` here). This oracle is explicitly labelled a **statistical**
oracle: the OS scheduler contributes noise, so a single number is not a proof.
**Oracle:** the real processor timer on a 4096-byte secret.

## All of it in one command

```bash
make showcase-live
```
```
[OK  ] Переполнение i32 -> точные числа аварии              (0.8 с)
[OK  ] Деление на ноль -> точные числа аварии              (1.1 с)
[OK  ] Рефакторинг: эквивалентен ИЛИ расхождение с числом  (1.3 с)
[OK  ] Граница --xray по расширениям названа, а не молчалива (0.9 с)
[OK  ] Диагност: чего не хватает функции                   (1.7 с)
[OK  ] Замок: агент не подменил спецификацию               (0.9 с)
[OK  ] Нативный Zig-фронтенд (0 Python): контракты из .zig (0.2 с)
ИТОГ: выполнено 7 строк | провалов 0
```
Two honest notes. First, the total time is **not** printed and is **not 3.4 s**: the
rows above sum to ≈6.9 s on this machine. Second, the showcase **requires Zig 0.17
in `PATH`** — otherwise the `zig-guard` target refuses with a named
`[ОТКАЗ] … rc=2` (defect #392) instead of blaming `build.zig`.

## What none of this proves

- KERN is not a scanner: it does not search other people's repositories for bugs on its own.
- `[BOUNDS] … length NOT known` is a **candidate**, not an accusation.
- SKIP / "outside the subset" is never counted as a proof of correctness.
- The ReDoS and non-interference oracles are physical **measurements** with
  thresholds; they are not deterministic proofs.
