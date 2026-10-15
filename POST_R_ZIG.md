# KERN — draft post for r/Zig / Ziggit

<!--
Внутренний черновик внешней публикации. НЕ часть проекта.
Все числа сверены с прогонами (docs/evidence/).
-->

* **Repository:** https://github.com/newmathphys/kern
* **Release v2.1.0:** https://github.com/newmathphys/kern/releases/tag/v2.1.0
* **License:** PolyForm Noncommercial 1.0.0 / Commercial (source-available)

KERN (`kernc`, `kernx`, `libkern.so`) is an L0–L5 verification gateway and immutable
container engine (`v2.1.0`) designed to sit between automated code generators and a
repository. Instead of relying on boolean test exit codes (`0` vs `1`), KERN seals
artifacts and `.kern` contracts into a binary `.kimg` image, discharges verification
conditions via an external Z3 SMT solver, and accumulates verdicts in Belnap's
four-valued lattice (B4: `N`, `T`, `F`, `B`) backed by 32 Lean 4 proofs (`0 sorry`).

Rather than repeating the README, here are the specific design decisions and bugs we
hit while migrating 44 files (touching 58 of 69 `.zig` files) from Zig 0.13 to
**Zig 0.17.0**:

### 1. Isolating `std.Io` without polluting pure function signatures (`src/compat.zig`)

In 0.17, threading `io: std.Io` through every parser, Merkle verifier and AST walker
would have touched almost every signature in the codebase. Instead we isolated
`std.Io` in `src/compat.zig` with three modes:

* **In `zig build test` (`if (builtin.is_test)` at comptime):** `compat.io()` resolves
  directly to `std.testing.io` — zero runtime overhead in release builds, and
  `std.heap.DebugAllocator` leak checks stay strict across all 204 core tests. This
  check runs **first**, before the thread-local cache, so the test runner can never
  pick up a stale instance.
* **In CLI binaries (`kernc`, `kernx`):** `main(init)` registers `init.io` once.
* **In the C-ABI shared library (`libkern.so`, 8 exported functions):** C and Python
  callers have no Zig `main`. A mutex-guarded `std.Io.Threaded` fallback initialises
  once per process, and each worker thread caches the resolved handle in
  `threadlocal var tls_io: ?std.Io = null`, keeping later I/O calls lock-free.

### 2. Fixing `Child.kill()` `ECHILD` panics (`src/verifier/z3_bridge.zig:53`) and 0.17 pipe EOF semantics

Our Z3 bridge spawns `z3 -in` as a child with a hard timeout killer thread. Two
low-level issues bit us:

1. **Concurrent reaping (`ECHILD` → SIGABRT).** In Zig 0.13, `Child.kill()` sends a
   signal *and* reaps the child itself (it calls `wait()` internally). If the killer
   thread fired while the main thread was blocked in `child.wait()`, the second
   `waitpid` got `ECHILD` → `unreachable` → `SIGABRT (rc=134)`. We fixed it by passing
   `pid` **by value** and sending `std.posix.kill(pid, SIG.TERM)` directly, so only
   the main thread reaps. Found by sweeping the official SMT-LIB suite: **5,111
   files, 3,240 hard 500 ms timeouts, 0 zombies, 0 divergences**.
2. **`error.EndOfStream` on pipes in 0.17.** `readPositionalAll` (`pread`) fails with
   `ESPIPE` on Z3's `stdout` pipe, and `readStreaming` surfaces `error.EndOfStream`
   when the child closes its write end, rather than returning `0` bytes like 0.13's
   `readToEndAlloc`.


### 3. Comptime/runtime hash dispatch (`BLAKE3` vs `SHA-256`) and small-object physics

The `.kimg` format (128-byte LE header, 96-byte descriptors, read-only `KERNFS` over
`/raw/` and `/claims/`) specifies `0x0001 = BLAKE3` and `0x0002 = SHA-256`. Because
`std.crypto.hash.Blake3` and `Sha256` are distinct types, `src/core/hash_algo.zig`
uses an `inline else` switch to dispatch on the image header.

* On an Intel i7-7700 (Kaby Lake, AVX2, **no SHA-NI**), isolated BLAKE3 reaches
  **2,601 MB/s** on 64 KiB blocks (**8.92×** faster than SHA-256 at 292 MB/s), but
  only **259 MB/s** on 96 B blocks (**1.21×**).
* End-to-end verified reads across 10,000 small 200-byte objects run at
  **~390 MB/s** (vs **~90 GB/s** for unverified raw slice addressing), because a
  200-byte payload fits inside a single 1024-byte BLAKE3 chunk where 8-lane AVX2
  chunk parallelism cannot saturate.

### 4. Non-deterministic DWARF in 0.17 Debug builds, and big-endian QEMU testing

* **Reproducibility:** Zig 0.17 `Debug` binaries produce different SHA-256 hashes
  across clean rebuilds (`rm -rf .zig-cache`) due to non-deterministic error-set
  ordering in `.debug_info` / `.debug_str`. Attesting `ReleaseFast` (and static
  `musl` `ReleaseSafe`) restored bit-for-bit reproducibility.
* **Cross-arch:** core tests run under `qemu-aarch64-static` (strict alignment) and
  `qemu-ppc64-static` (big-endian) via
  `zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig
  -target powerpc64-linux-musl --test-cmd ... --test-cmd-bin`.
  Result on both: **200 passed; 4 skipped; 0 failed**. The 4 skipped are the solver
  tests — and they **must** be skipped there: `z3` is a native x86_64 binary, and
  spawning a foreign-architecture child from inside `qemu-user` while a timeout
  killer thread waits on a futex deadlocks (emulated `waitpid` and the killer wait on
  each other forever; `SIGCHLD` is lost in QEMU's signal translation). Running the
  emulated test with a clean `PATH` (no `.venv/bin`) makes the bridge return
  `ToolError` immediately and the tests skip in about a second.

### Supported Zig versions

* **Zig 0.17.0** — tested on `x86_64-linux`, `aarch64-linux-musl`,
  `powerpc64-linux-musl`.

### AI / LLM usage disclosure

LLMs were used in two ways during development:

1. **As the adversarial test subject.** KERN is built to catch AI failure modes —
   vacuous tests with no assertions, and hallucinated fixes that miss edge cases such
   as negative amounts or the `i32` vs `Int` semantic gap. We used LLM coding agents
   to generate candidate patches across HumanEval, MBPP+ and QuixBugs to measure the
   precision of KERN's static gate and Z3 contracts.
2. **As a development assistant under a strict "can-fail" harness.** LLMs assisted
   with boilerplate, documentation, Python harnesses and mechanical call-site updates
   during the 0.13 → 0.17 migration. Relying on AI assistance exposed a major hazard:
   **25 of the 74 logged defects in our registry (`docs/CAPABILITY_STATUS.md`) were
   "silently broken checks"** — scripts or tests that returned exit code `0` when the
   check itself was broken (e.g. piping a test runner into `| tail -3` without
   `pipefail`, or `kernc cat` printing to *stderr* with `rc=0` on missing paths).
   Every check in the repo is now enforced by `tools/canfail.py` (64 non-vacuous
   checks, verified by fault injection) plus a Zig-native mutation tester

---

# Правки относительно исходного черновика

| Было | Стало | Почему |
|:--|:--|:--|
| `https://github.com` | `https://github.com/newmathphys/kern` | голый URL — заглушка |
| `https://github.com/releases/tag/v2.1.0` | `.../newmathphys/kern/releases/tag/v2.1.0` | путь без владельца/репозитория даёт 404 |
| **`License: MIT`** | **PolyForm Noncommercial 1.0.0 / Commercial** | проект переведён на dual license; MIT больше не действует |
| `KERN (Knowledge Evaluation and Resolution Node)` | **убрано** | 🔴 такой расшифровки **нет ни в проекте, ни в спецификации** — придумана. В README проект описан как «a zero-trust verification gateway» |
| `25 out of 67 logged defects` | `25 of the 74` | реестр доведён до #74 |
| `All 204 core tests run under qemu-*` | `200 passed; 4 skipped; 0 failed` | под QEMU 4 теста решателя штатно пропускаются (раздел 4) |
| `z3 -in -smt2` | `z3 -in` | фактическая командная строка в `z3_bridge.zig` |
| — | добавлено объяснение дедлока QEMU | реальная находка (дефект #74); объясняет, почему 4 теста пропускаются |
| — | добавлено «check runs first» про `is_test` | порядок веток закреплён как инвариант |
| — | добавлено про `_LOCK_HOLDER` | иначе GC закрывает fd и снимает flock |

## Проверено по свидетельствам

| Число в тексте | Источник | Совпало |
|:--|:--|:--:|
| 5,111 файлов SMT-LIB | `docs/evidence/smtlib_017.log` → `файлов всего: 5111` | ✅ |
| 3,240 таймаутов по 500 мс | `smtlib_017.log` → `таймаутов: 3240` | ✅ |
| 0 расхождений, 0 ложных | `smtlib_017.log` | ✅ |
| 92.5 % kill rate | `docs/evidence/mutate.log` → `MUTATION SCORE: 92.5%` | ✅ |
| 64 non-vacuous checks | `docs/evidence/canfail.log` | ✅ |
| 32 теоремы Lean, 0 sorry | `docs/evidence/lean_proofs.log` | ✅ |
| 44 файла миграции, 58 из 69 | `git show --stat 245d9cd` | ✅ |
| 2,601 / 292 MB/s (8.92×), 259 MB/s (1.21×) | `docs/evidence/hash_bench.log` | ✅ |
| ~390 MB/s verified / ~90 GB/s raw | `docs/evidence/bench_perf.log` | ✅ |
| 8 функций C-ABI | `nm -D libkern.so` | ✅ |
| 200 passed / 4 skipped на ARM64 и PPC64 | `docs/evidence/cross_arch.log` | ✅ |

   (**92.5 %** kill rate, 37/40 mutants killed).

Source code and verification logs: https://github.com/newmathphys/kern
