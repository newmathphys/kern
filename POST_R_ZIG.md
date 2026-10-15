<!--
Текст внешней публикации (r/Zig). Все числа сверены с прогонами; ссылки проверены.

Разбор того, что было исправлено относительно первого черновика, — в конце файла.
-->

# Текст для r/Zig (готов к вставке)


# Вариант для r/Zig (готов к вставке)

---

Hey `r/Zig`, I've been building **KERN** — a verification gateway that sits between
automated code generators/agents and a repository. Instead of trusting a boolean
`1 passed` exit code from a potentially vacuous test, KERN requires contracts to be
discharged by an external Z3 SMT solver and accumulates verdicts in Belnap's
four-valued logic (B4: `N`, `T`, `F`, `B`).

We just finished migrating the codebase from Zig 0.13 to **Zig 0.17.0** — the
mechanical migration commit alone touched 44 files (291 insertions), and 58 of the
69 Zig files under `src/` needed changes across the whole effort.

Repo (AGPL-3.0): https://github.com/newmathphys/kern

### Highlights of the Zig implementation

* **Zero-copy `.kimg` container and `KERNFS`:** 128-byte little-endian header,
  96-byte object descriptors, Merkle tree over the descriptor table. Digest
  dispatch between `BLAKE3` (`0x0001`, default) and `SHA-256` (`0x0002`), selected
  by the image header so older images keep verifying unchanged.
* **Measured throughput** (Intel i7-7700, Kaby Lake — no SHA-NI, AVX2 only):

  | Workload | Throughput |
  |:--|:--|
  | Raw zero-copy slice addressing | **~90 GB/s** |
  | Verified read, end-to-end, 200-byte objects | **~390 MB/s** |
  | Isolated `std.crypto.hash.Blake3`, 64 KiB blocks | **2,601 MB/s** |

  The block-size dependency is worth calling out: BLAKE3's Merkle tree parallelises
  across AVX2 lanes once chunks reach roughly 1024 B and saturates the 8 lanes
  between 8 and 64 KiB. A 200-byte object exercises a single leaf, so state
  initialisation and finalisation dominate — hence 1.21x over SHA-256 there versus
  **8.92x** (2,601 vs 292 MB/s) on 64 KiB blocks. Both numbers are measured, not
  projected from one another.
* **C-ABI (`libkern.so`):** 8 exported functions (`include/kern.h`), consumed by a
  zero-dependency Python HTTP guardrail proxy that maps the lattice onto RFC 9110:
  `200 OK` on `T`, `422 Unprocessable Entity` on `F`/`N`, and `409 Conflict` when
  `JOIN_K(T, F) = B`.
* **Cross-arch and UB testing:** 204/204 core tests and 37/37 `kernx`
  (SQLite-backed DSL) tests pass in `Debug` and `ReleaseSafe` on `x86_64`, and on
  `aarch64-linux-musl` (strict alignment) and `powerpc64-linux-musl`
  (**big-endian**) under QEMU.

### Lessons from Zig 0.17 and mutation testing

1. **Removing an `ECHILD` race in the Z3 timeout killer.** In Zig 0.13,
   `Child.kill()` sends the signal *and reaps the child itself* (it calls `wait()`
   internally). Our timeout thread ran concurrently with the main thread's
   `child.wait()`, so the second `waitpid` returned `ECHILD` — which `std` treats
   as `unreachable`, producing a SIGABRT. It stayed hidden until we swept the
   official SMT-LIB suite (2,432 files). The fix is to send the signal directly
   with `std.posix.kill(pid, SIG.TERM)` and let the main thread be the only
   reaper. We found the same pattern in three more call sites.

2. **Catching a latent size bug via mutation testing.** Our Zig-native mutator
   (`tools/mutate_zig.py`, 92.5% kill rate) caught defect #55: the verified read
   path and the raw path selected `compressed_size` versus `uncompressed_size` in
   *opposite* order, so they could return different slices when the two differed.
   It was invisible in practice because the writer always sets both equal.

3. **Proving that tests can actually fail (`tools/canfail.py`).** While auditing
   our own suite we found 25 instances of "silently broken checks" — for example a
   pipeline `./formal/check.sh | tail -3` without `pipefail` (masking the exit
   code), or `kernc cat` printing through `std.debug.print` to *stderr* while
   returning `0` on a missing path. Now every check is verified by injecting a
   fault and asserting a non-zero exit code: 64 checks proven non-vacuous.

Happy to answer questions about the Zig 0.17 migration, the Z3 child-process pool,
or the Belnap lattice implementation.

---

# Вариант без ссылки на релиз (если тег не восстанавливать)

Замените строку `Repo (AGPL-3.0): ...` на:

```
Repo (AGPL-3.0): https://github.com/newmathphys/kern
```

и удалите любое упоминание тега `v2.1.0` — остальной текст не меняется.

---

# Что было исправлено относительно исходного черновика

| Было | Стало | Почему |
|:--|:--|:--|
| `https://github.com` (голый) | `https://github.com/newmathphys/kern` | ссылка вела в никуда |
| `https://github.com/releases/tag/v2.1.0` | ссылка убрана (тег удалён) | этот URL даёт 404 — путь без владельца и репозитория |
| `End-to-end verified read (/safe/, ...)` | `Verified read, end-to-end, ...` | **пути `/safe/` в KERNFS не существует** — есть только `/raw/` и `/claims/`; проверка хеша происходит внутри `/raw/` через `objectPayload()` |
| `~30 files, ~300 call sites` | `44 files (291 insertions)`, 58 из 69 | проверено `git show --stat`; занижение |
| `In 0.17, our killer thread passes pid by value...` | `Removing an ECHILD race... Zig 0.13's Child.kill() reaps internally` | это **наш** фикс, а не свойство Zig 0.17; формулировка «нам повезло с апгрейдом» слабее реальной истории с найденным багом |
| 8.92x без контекста | 8.92x **на блоках 64 КиБ**, 1.21x на 200 Б | иначе цифра читается как завышение |
