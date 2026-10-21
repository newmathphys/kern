# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [2.6.1] — 2026-10-21

Real-world hardening: four languages verified, live models measured, and three
defects found by the field tests themselves.

### Added
- `kernc pack-dir <dir> -o out.kimg`: pack a directory tree (a cloned repository)
  into one image; verified on a real clone with `fsck` (20/20 objects), `inspect`
  and `diff` (one changed file detected).
- `kernc prove --query-kind refutation|equivalence`: the premise-binding rule now
  belongs to contract proofs only, so `--diff-equiv` returns a **trusted**
  EQUIVALENT for real refactorings (verified on a live model rewrite of
  `boltons::clamp_int`).
- The code-checking corpus covers **Python, Zig, C and Rust** with machine-type
  bounds: `TP=5, TN=5, FP=0, FN=0, UNKNOWN=4`, including an `i32` overflow
  witness `a = 2147483647, b = 1 -> 2147483648`.
- Idiomatic Rust (tail expression) is now verified instead of skipped.

### Fixed
- #299 `kernc build <directory>` printed a raw Zig stack trace; now a clean
  message and exit code 2 (same for a missing argument).
- #300 `trace_explorer.py` builds parameter domains from standard Python
  annotations when the QuixBugs-style docstring is absent.
- #302 `pack-dir` silently packed 5 of 20 files (relative paths); the skipped
  counter exposed it on the first run.
- #304 `kernc prove` read the file path from a fixed argument position, so a new
  flag was read as a file.
- #306 Rust bodies written as tail expressions were skipped, so live model
  answers were never verified.

### Measured (live models, not opinions)
- 3 free models x 4 languages: round 1 blind **4 proved / 7 refuted / 1 honest N**;
  after KERN’s counterexample **4 of 7 refuted tasks repaired**. The three
  un-repaired ones are the same Zig overflow task, while the Rust twin was fixed.
- Both models tested rewrite `@kern:requires` (never `@kern:ensures`) when the
  contract is unsatisfiable; `contracts-lock-check` catches it.
## [2.6.0] — 2026-10-21

Trust that can be checked from outside, and an exam that can fail.

### Added
- **External attestation**: `docs/keys/kern-owner.pub` ships in the repository,
  so anyone can verify `kern.intoto.jsonl` with `make verify-attestation`
  (no `$HOME` key, no owner machine). `kid` is recorded in the attestation.
- **Secrets scanner** (`make secrets-check`): 9 provider patterns, redacted
  output, self-test with 7 plantings; runs over git-tracked files.
- **Determinism gate**: the same SMT input twice must give the same verdict,
  counterexample, `trusted` and `holes`.
- **Conformance exam** (`make conformance-check`): 12 sections, 95 checks,
  reading facts emitted by the kernel itself; `--selftest` corrupts nine facts
  and requires every section to turn red.
- **Code-checking corpus** (`make codecheck`) with an honest confusion matrix:
  `TP=2, TN=2, FP=0, FN=0, UNKNOWN=8` - `TN` only means "proved clean".
- **Contract classes** `hard` / `advisory`: `T_advisory` never mixes into `T`,
  and the class is part of the lock fingerprint.
- **Read-only abductive report**: `explain --hypotheses` proposes `requires`
  only, re-verifies each candidate, rejects vacuous ones out loud, and never
  writes to the source.
- **Evidence ledger** `add`/`retract` with recomputation, three provenance
  graphs, and rejection of negative recursive SCCs.
- **`kernx graph`** as the single source of the `G_src` graph (byte parity with
  the showcase).
- **KIMG**: unknown-optional vs unknown-required policy, `WrongEndianness`,
  `kernc fsck / inspect / diff`, three golden fixtures.
- **13-field cache key** and **KERN-X shared budget** with quotas.

### Changed
- `kernc` and the C ABI are `v2.6.0`; `kern_kimg_object_count` returns
  `int64_t` and lengths use `size_t` (LLP64-safe).
- QuixBugs: **40/40** tasks diverge (29 value, 10 crash, 1 hang); the seven
  former `EXPLORED` cases were harness bugs, not clean code.
- `artifact-check*` reclassified `CHECK -> BUILD`: they verify a release
  artefact against a hash announced in README, which only exists at release.

### Fixed
- `timeout`, `out_of_fuel` and `invalid_certificate` no longer collapse into
  `F`; a missing solver is `N`, not an accusation (#277).
- `andT`/`orT` were wrong on the pairs (N,B) and (B,N) (#279).
- Harness: rollback now restores file modes (#283); a skipped case under
  `--only` is an error, not a silent pass (#275).
- Two can-fail cases no longer cling to numbers that `make sync` rewrites
  (#282) and cannot silently pass (#281).

### Known limitations
- Bounded intuitionistic mode (`--intuitionistic --worlds N`) is in the
  backlog: the full text of Kamide & Niki 2026 (IGPL, `10.1093/jigpal/jzag024`)
  describes a Gentzen calculus `sQBDi` and is not available locally
  (`read = {false}`); writing Kripke semantics from an abstract is forbidden.
- Windows is not supported (three POSIX blockers in `docs/PLATFORMS.md`).
- The attestation is signed by the owner key, not by a hosted builder
  (Sigstore/Rekor remain in the backlog).
## [2.5.2] — 2026-10-20

Honest showcase and a release pipeline that cannot lie: proof-flow map with
CEGIS arrow, Ego-Lens over the real `@import` graph, `[+][~][-][=]` filter
matrix, zoom on both diagrams, `--diff-equiv` no longer declares identical
files divergent, unknown KIMG flags are honoured, orphan fact-anchors are
caught, Release Drafter no longer hijacks the release tag, and the site
stopped claiming that README, build and asset hashes are equal (#243–#250).

Full release notes: [`docs/RELEASE_NOTES_v2.5.2.md`](docs/RELEASE_NOTES_v2.5.2.md).

## [2.5.1] — 2026-10-20

Honest QuixBugs boundary (6/40 SMT + 33/40 differential), `make sync` with
`docs/facts.json` and anchors, EN/RU parity guard, no AI boilerplate,
canfail 144/0/0/0, scorecard 128/144, attestation with `attests_commit`.

Full release notes: [`docs/RELEASE_NOTES_v2.5.1.md`](docs/RELEASE_NOTES_v2.5.1.md).

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
- **WASM kernel** `kernc.wasm` (86,953 bytes; 5 `kern_wasm_*` functions including `kern_wasm_verify_proof`; 7 export entries with `memory`/`__stack_pointer`).
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
- **#174** 52 duplicate top-level definitions in `kern_contracts.py` — **resolved
  (52 → 0, −2003 lines)**; `dup_defs_guard` ratchet now at 0. A second
  `if __name__ == "__main__"` (early `main()` before later defs) and the lost
  C-like routing in `cmd_xray` were found and fixed. Field-audit fixes
  **#178–#184** (comment/string stripping, `assert` guards, Rust signatures,
  scorecard profiles, balanced-paren `assert`, type ranges + let-inlining,
  three-valued `_smt_sat`) ship in the same release.
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
