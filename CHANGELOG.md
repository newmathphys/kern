# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [2.5.0] — 2026-10-19

Полные заметки о релизе: [`docs/RELEASE_NOTES_v2.5.0.md`](docs/RELEASE_NOTES_v2.5.0.md).
Каждое число ниже получено командой из репозитория; исторические измерения
(например, 77.5 % мутаций БЕЗ решателя в `PATH`) сохранены как история, а не как
текущее состояние.

### Added
- **Встроенный решатель Фурье — Моцкина** (`src/verifier/builtin_lia.zig`): 100 систем
  против Z3 — 0 расхождений; 60/60 метаморфных проверок; `--full-file` 18/18.
- **Проверка SAT-моделей внутри ядра** (`verifyModelAgainstSmt`): модель Z3
  подставляется в `(assert …)` и вычисляется независимо; ложная модель →
  `SPURIOUS MODEL` и контрпример НЕ предъявляется.
- **`musl abs.c`: `SKIP → PROVEN`** (51 шаг, `trusted: 0 | holes: 0`) — доказаны
  `intro-def`, `lemma`, `def-axiom`, `rewrite`, `monotonicity`.
- **Новые теории с `trusted: 0`**: IEEE-754 (NaN-ловушка), QF_S (обход санитайзера),
  циклы (`invariant`/`decreases`), границы массивов, инварианты состояний, RLS.
- **`--xray` без единой аннотации** + 7 языков (`.py .zig .c .rs .ts .js .go`);
  6 полевых адаптеров (`self.x`, let-inlining, константы модуля, `min/max/abs`,
  рекурсивный обход, инвариант длины).
- **`--audit-repo <path|owner/repo|url>`**: безопасная песочница git
  (`core.hooksPath=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_LFS_SKIP_SMUDGE=1`,
  timeout 30 с), уборка `/dev/shm` по SIGTERM/atexit, фильтр мусора и симлинков.
- **Proof-Carrying `.kimg`** (`[PCC VERIFIED]` без решателя) · **Evidence Decay** ·
  **Merkle-цепочка** журнала · **Bit-Rot Guard** (30/30 инъекций).
- **WASM-ядро** `kernc.wasm` (86 953 Б, 5 экспортов, включая `kern_wasm_verify_proof`).
- **8 MCP-инструментов** + `server.json` / `mcp.json` / `.well-known/mcp.json`
  (генерируются из `tools/list`) + MCP Tool Annotations.
- **`llms.txt`**, `--sarif` (SARIF 2.1.0), `action.yml` с режимом `xray`,
  `tools/trust_scorecard.py` и карточка `#scorecard` на сайте.

### Fixed (выборочно; полный журнал — `docs/CAPABILITY_STATUS.md` §6c–§6d)
- **#155** пруф-чекер принимал подделку DAG (битая ссылка `@xN` → `.bad`).
- **#166** ложный `unknown` в WASM (переменная с нулевым коэффициентом).
- **#171** `bench-semantic`: единый источник корня (`sealImageRoot`).
- **#173** предохранитель свидетельств ложно обвинял харнесс (write-once базис,
  продукты вне базиса, грязный старт → `rc=3`).
- **#174** 51 дублирующееся определение в `kern_contracts.py` — долг **заморожен**
  ratchet-стражем `tools/dup_defs_guard.py`; перестройка вынесена за релиз.

### Notes
- Лицензия: **PolyForm Noncommercial 1.0.0** (source-available); коммерческое
  использование — по лицензии правообладателя.
- `align(32)` в `blake3_simd8`: измеримого ускорения нет (2.42 против 2.41 GB/s) —
  правка безвредна, но НЕ заявляется как оптимизация.


## [2.4.0] — 2026-10-17

### Added
- **Polyglot contract checking**: `@kern:requires` / `@kern:ensures` are read from
  `.py`, `.zig`, `.c` and `.rs`; machine types (`i32`/`u32`/`i64`/`usize`) are enforced,
  so i32 overflow / unsigned underflow and division by zero are caught.
- **Vacuous-requires detector**: a contradictory precondition (`false ⟹ anything`) is
  reported as `[VACUOUS] precondition is unsatisfiable (empty domain) -> B4: N, e = 0`
  instead of a false PASS.
- **Contract lock** (`--lock` / `--verify-lock`): BLAKE3 fingerprints of every contract in
  `docs/contracts.lock.json`; removing or weakening an `@kern:ensures` line is `rc = 2`.
- **Refactoring equivalence without contracts** (`--diff-equiv old.py new.py`): checks
  `∃x: f_old(x) ≠ f_new(x)` over all of ℤ and prints the exact diverging input;
  exposed as the fifth MCP tool `kern_check_equivalence`.
- **Counterexample → pytest** (`--emit-pytest`) and **SARIF 2.1.0** / GitHub annotations
  (`--sarif`, `--github-annotations`) so a refuted contract lands on the exact PR line.
- **Git pre-commit hook** (`--install-hook`, `--git-diff`): an AI agent cannot commit
  broken code or a weakened contract.
- **`make self-verify`**: KERN verifies its own arithmetic functions.
- **`docs/FarkasSoundness.lean`**: soundness of the proof checker formalised in Lean 4
  (`int_not_le_iff`, `farkas_2_sound`, `farkas_3_sound`, `three_valued_check_sound`,
  `vacuous_requires_unsound`, `skip_preserves_belnap_join`) — 8 files, **42 theorems, 0 sorry**.
- **Ed25519-signed SLSA attestation** (`kern.intoto.jsonl` + `kern.intoto.sig`), verified
  by `python3 tools/slsa_provenance.py --check`.
- **`action.yml`**: the reusable GitHub Action now verifies the downloaded binary against
  `SHA256SUMS` (`sha256sum -c`) before running it.
- **English mirrors** of the key documents: `docs/CAPABILITIES.en.md`,
  `docs/ATTESTATION_PASSPORT.en.md`, `docs/CAPABILITY_STATUS.en.md`, `docs/METRICS.en.md`.

### Changed
- **Mutation score 95.0 % (38/40 killed; 2 survivors proven equivalent)** over
  **14 files / 420 sites** (previously 6 files / 63 sites). The mutator now requires a
  solver in `PATH` (`--require-solver`), because the earlier 77.5 % figure was taken with
  8 solver-dependent tests silently skipped (defect #110).
- **Mutator speed**: `KERN_MUTATE_FAST` reduces stress-loop iterations *without disabling
  any test* (11.4 s → 5.8 s per mutant), plus `--jobs N` (2.15×).
- Can-fail harness: **78/78 CHECK targets** have a proven-can-fail case
  (93 non-vacuous cases, 0 vacuous, 0 case errors) and a `--check-anchors` pre-flight.
- Constant-time digest comparison (`std.crypto.timing_safe.eql`) in 5 places (FIPS 140-3).

### Fixed
- **CI #68/#69 went red** because can-fail cases patched a hard-coded hash in `README.md`
  (root cause found via the GitHub API; anchors are now derived from the files).
- Defects **#104–#116**, including: `witness_model` was always `null` (#104), the memory
  leak opened by that fix (#105), sampling bias in the mutation run (#107), a hanging pipe
  regression test (#108), a pipe deadlock in `child.wait()` (#109), environment variables
  that silently did nothing in tests (#112), the mutation score measured without a solver
  (#110), can-fail polluting committed evidence (#114), a vacuous `slsa` case (#115) and
  harness rollback silently discarding edits made during a run (#116).
- Documentation honesty: fabricated cross-architecture numbers (`279/279` where the log
  says `240 passed / 4 skipped / 0 failed`), stale core counts (198 → 279), a stale KERN-Next
  count (37 → 38 executed tests) and several dated snapshots now marked as such.

## [2.2.0] — 2026-10-16

### Added
- MCP server (stdio) with four verification tools, `make mcp-selftest`.
- `docs/contracts.lock.json`-based specification sealing; `--diff-equiv` groundwork.
- GitHub Action with a SARIF output path.

### Fixed
- Release artefact chain (README ↔ build ↔ asset) enforced by `make artifact-check`.

[2.4.0]: https://github.com/newmathphys/kern/compare/v2.2.0...v2.4.0
[2.2.0]: https://github.com/newmathphys/kern/releases/tag/v2.2.0
