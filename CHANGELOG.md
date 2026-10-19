# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [2.5.0] — 2026-10-19

Full release notes: [`docs/RELEASE_NOTES_v2.5.0.md`](docs/RELEASE_NOTES_v2.5.0.md).
Every number below is produced by a command in this repository; historical measurements
(e.g. the 77.5% mutation score obtained *without* a solver in `PATH`) are kept as history,
not as the current state.

### Added
- **Native Fourier–Motzkin LIA solver** (`src/verifier/builtin_lia.zig`): 100 systems
  checked against Z3 — 0 disagreements; 60/60 metamorphic checks; `--full-file` 18/18.
- **SAT-model validation inside the kernel** (`verifyModelAgainstSmt`): the Z3 model is
  substituted back into every `(assert …)` and evaluated independently; a false model is
  reported as `SPURIOUS MODEL` and **no counterexample is shown**.
- **`musl abs.c`: `SKIP → PROVEN`** (51 steps, `trusted: 0 | holes: 0`) — `intro-def`,
  `lemma`, `def-axiom`, `rewrite` and `monotonicity` are now checked, not trusted.
- **New theories at `trusted: 0`**: IEEE-754 (the NaN trap), QF_S (sanitiser bypass),
  loops (`invariant`/`decreases`), array bounds, state invariants and RLS policies.
- **`--xray` with zero annotations** across 7 languages (`.py .zig .c .rs .ts .js .go`);
  six field adapters (`self.x`, let-inlining, module constants, `min/max/abs`,
  recursive directory walk, length invariant).
- **`--audit-repo <path|owner/repo|url>`**: sandboxed git
  (`core.hooksPath=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_LFS_SKIP_SMUDGE=1`,
  30 s timeout), `/dev/shm` cleanup on SIGTERM/atexit, junk/symlink filters.
- **Proof-Carrying `.kimg`** (`[PCC VERIFIED]` with no solver) · **Evidence Decay** ·
  **Merkle audit chain** · **Bit-Rot Guard** (30/30 injections caught).
- **WASM kernel** `kernc.wasm` (86,953 bytes, 5 exports including `kern_wasm_verify_proof`).
- **8 MCP tools** plus `server.json` / `mcp.json` / `.well-known/mcp.json`
  (generated from `tools/list`) and MCP tool annotations.
- **`llms.txt`**, `--sarif` (SARIF 2.1.0), `action.yml` with an `xray` mode,
  `tools/trust_scorecard.py` and the `#scorecard` section on the site.

### Fixed (selected; the full journal is `docs/CAPABILITY_STATUS.md` §6c–§6d)
- **#155** the proof checker accepted a tampered DAG (a broken `@xN` reference now yields `.bad`).
- **#166** false `unknown` in WASM (the solver picked a variable with a zero coefficient).
- **#171** `bench-semantic`: single source of truth for the Merkle root (`sealImageRoot`).
- **#173** the evidence guard wrongly accused the harness (write-once baseline, artefacts
  outside the baseline, dirty start → `rc=3`).
- **#174** 51 duplicate top-level definitions in `kern_contracts.py` — the debt is **frozen**
  by the ratchet guard `tools/dup_defs_guard.py`; the refactor is scheduled after the release.
- **#179** mobile layout overflowed by 12 px (the `owner/repo` input had a fixed `size`
  attribute); the scorecard input is now fluid, and `scrollWidth == clientWidth` on both
  360 px and 1425 px viewports.

### Notes
- License: **PolyForm Noncommercial 1.0.0** (source-available); commercial use requires a
  license from the copyright holder.
- `align(32)` in `blake3_simd8`: no measurable speed-up (2.42 vs 2.41 GB/s) — the change is
  harmless but is **not** claimed as an optimisation.


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
