# All 10 KERN capabilities: live examples and verbatim output

> This document is **generated** by `tools/run_all_10_capabilities_demo.py`:
> every section is a command that was really executed, with its real output.
> Nothing is written by hand, so the document cannot drift from the code.

Run: `make demo-all`

> Facts (synced by `make sync`): core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->180 · cases <!-- fact:canfail_cases -->218 · anchors <!-- fact:anchors -->179 · registry <!-- fact:registry_targets -->236 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

## 1-2. Overflow and division by zero: KERN verdict + real compilers

**Why.** KERN checks a function over the whole type domain, not on three samples. Then the counterexamples are replayed by REAL toolchains: python3, gcc -fsanitize=undefined, rustc -C overflow-checks=on, zig run.

**Command.**
```bash
make anti-self-deception-check
```

**Real output:**
```text
=== A. ground truth: KERN's counterexamples vs native toolchains ===
  python  {'x': -1, 'result': -1} -> AssertionError (rc=1)
  c       b=0 -> UBSan division by zero (rc=1)
  rust    a=2147483647, b=1 -> panic overflow (rc=101)
  zig     b=0 -> panic division by zero (rc=-6)
=== B. mutation kill: every T file must flip to F ===
  py_abs_ok.py: 'return x' -> 'return -x'  T -> F {'x': 1, 'result': -1}
  py_clamp_ok.py: 'return lo' -> 'return lo - 1'  T -> F {'lo': 0, 'hi': 0, 'result': -1, 'x': -2}
  zig_clean.zig: 'return a + b;' -> 'return a - b;'  T -> F {'b': -1, 'result': 1, 'a': 0}
  c_clean.c: 'return a + b;' -> 'return a - b;'  T -> F {'b': -1, 'result': 1, 'a': 0}
  rust_clean.rs: 'return a + b;' -> 'return a - b;'  T -> F {'b': -1, 'result': 1, 'a': 0}

GROUND TRUTH 4/4 · MUTATION KILL 5/5
ANTI-SELF-DECEPTION PASSED
```

## 3. Diagnosis: which input rule is missing

**Why.** When a function is refuted, KERN searches for the missing precondition, re-verifies every hypothesis with a second Z3 run and NEVER edits the file.

**Command.**
```bash
python3 tools/kern_contracts.py explain --hypotheses audits/codecheck/py_abs_bad.py
```

**Real output:**
```text
==========================================================================
KERN: объяснение — гипотезы для `requires` (Ф6.3)
==========================================================================
  функция: absolute (стр. 8)
  requires: x >= -1000 and x <= 1000
  ensures:  result >= 0 and (result == x or result == -x)
  контрпример: x = -1000, result = -1000

  ГИПОТЕЗА, не доказательство. Файл не изменён.

  [1] requires += `x >= 0`   (самодостаточна)
      отсекает: x = -1000, result = -1000
      НЕ отсекает: — (доказывает и без исходного requires)
  [2] requires += `x > 0`   (самодостаточна)
      отсекает: x = -1000, result = -1000
      НЕ отсекает: — (доказывает и без исходного requires)

  HYPOTHESIS, not a proof. File not modified.
```

## 4. Contract lock: catches a live model rewriting the spec

**Why.** Every @kern:requires/ensures is sealed with a hash. In a live experiment DeepSeek and GLM, given an UNSATISFIABLE contract, narrowed requires (leaving ensures alone) - the lock blocks exactly that. Below: the check on the current tree.

**Command.**
```bash
make contracts-lock-check
```

**Real output:**
```text
make[1]: вход в каталог «/home/mrbritneyxxx/Рабочий стол/kern»
[OK] замок контрактов цел: ни один запечатанный контракт не изменён
  [SECURITY] НЕ запечатаны файлы с контрактами: ['tools/gen_llms_txt.py', 'tools/run_all_10_capabilities_demo.py']
  → пересоберите замок: make contracts-lock
make[1]: выход из каталога «/home/mrbritneyxxx/Рабочий стол/kern»
make[1]: *** [Makefile:450: contracts-lock-check] Ошибка 2
```

## 5. Refactoring equivalence: what a model broke and what it did not

**Why.** Two versions of a function are compared without contracts. EQUIVALENT is reported ONLY when the in-house proof checker accepted the derivation (QueryKind.equivalence).

**Command.**
```bash
python3 tools/kern_contracts.py --diff-equiv clamp_orig.py clamp_opencode_deepseek-v4.1-flash-free.py
```

**Real output:**
```text
[DIVERGED] clamp_int: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ
         [КОНТРПРИМЕР] x = 0, res_new = -1, hi = -1, res_old = 0, lo = 0
--------------------------------------------------------------------------
ИТОГО: эквивалентных 0 | эквивалентных без пруф-чекера 0 | разошедшихся 1 | недоказуемых 0 | ошибок инструмента 0 | всего 1
```

## 6. Bug hunter with no contracts at all

**Why.** It reads argument types (including standard Python annotations) and builds up to 250 hostile inputs per function: empty lists, strings, boundaries. On QuixBugs it catches 40/40 bugs by live execution.

**Command.**
```bash
python3 tools/trace_explorer.py /tmp/kern-demo-blind  # функции boltons по алфавиту
```

**Real output:**
```text
[s2] ceil                   EXPLORED   31  lines=2/23    нет расхождения на 31 входах
  [s2] clamp                  EXPLORED   27  lines=2/30    нет расхождения на 27 входах
  [s2] floor                  EXPLORED   31  lines=2/25    нет расхождения на 31 входах
ceil    EXPLORED     31  нет расхождения на 31 входах
clamp   EXPLORED     27  нет расхождения на 27 входах
floor   EXPLORED     31  нет расхождения на 31 входах

=== STAGE-2 SUMMARY ===
  EXPLORED   3
[OK] DIVERGED (живой вызов, 0 ложных по построению): 0/3
```

## 7. [VACUOUS] conditions and hard / [advisory] classes

**Why.** `x > 10 and x < 5` is unsatisfiable: a plain test would say 'green', KERN honestly marks the vacuum. An [advisory] violation yields T_advisory, which is NEVER added to the proven counter T.

**Command.**
```bash
python3 tools/kern_contracts.py <vacuous.py>  |  examples/contracts_advisory_demo.py
```

**Real output:**
```text
--- вакуумное предусловие ---
==========================================================================
KERN: контракты из комментариев (@kern:requires / @kern:ensures)
==========================================================================
  [VACUOUS] bad: предусловие ПРОТИВОРЕЧИВО (пустой домен) -> B4: N, e = 0
         requires: x > 10 and x < 5
--------------------------------------------------------------------------
ИТОГО: доказано 0 | T_advisory 0 | нарушено 0 (из них безопасность: 0) | НЕ РЕШЕНО 0 | ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 1 | вне подмножества 0 | всего 1

--- классы контрактов ---
==========================================================================
KERN: контракты из комментариев (@kern:requires / @kern:ensures)
==========================================================================
  [PASS] add_hard: ДОКАЗАНО
         [PROOF VERIFIED] steps: 3 | premises bound: 2/2 | mp: 0 | rewrite (linear): 0 | farkas: 0 | trusted: 0 | holes: 0
  [T_advisory] add_advisory_violated: advisory-обязательство нарушено (не блокирует, но и НЕ доказано)
         [КОНТРПРИМЕР] result = 0, y = 0, x = 1
--------------------------------------------------------------------------
ИТОГО: доказано 1 | T_advisory 1 | нарушено 0 (из них безопасность: 0) | НЕ РЕШЕНО 0 | ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 2
```

## 8. Belnap B4 logic, 7 axes, evidence ledger (T + F = B)

**Why.** timeout and nonlinearity are N, not 'a bug' (hence FP = 0). A conflict of T and F gives B. The conformance exam checks 12 sections including add/retract and rejection of negative SCCs.

**Command.**
```bash
make conformance-check
```

**Real output:**
```text
conformance: 97 facts straight from the kernel

[PASS] section  1: Belnap B4 values (twist pairs)
[PASS] section  2: all 16 joinK pairs; join is the lub of <=k
[PASS] section  3: both lattices (<=k, <=t) and conflation
[PASS] section  4: seven state axes and their laws
[PASS] section  5: evidence ledger: add / retract / idempotency / order
[PASS] section  6: provenance: negative recursive SCC rejected
[PASS] section  7: admission gate: certificate binding and QueryKind
[PASS] section  8: KERN-X: one shared fuel counter
[PASS] section  9: cache key: all 13 fields invalidate
[PASS] section 10: broken .kimg through the CLI: fsck / inspect / diff
[PASS] section 11: KERNFS attacks, including no-mmap
[PASS] section 12: determinism: same input twice, same verdict

conformance: 12 sections, 95 checks, 0 failed
CONFORMANCE PASSED
```

## 9. Architecture graph and forbidden negative cycles

**Why.** An exact import graph is built (KERN itself and an external project); SCC analysis rejects negative recursive cycles (NegativeRecursiveCycle).

**Command.**
```bash
kernx graph  |  kernx graph --root <внешний проект>
```

**Real output:**
```text
KERN: модулей 88, рёбер 70
zig-clap: модулей 12, рёбер 1
```

## 10. .kimg container, KERNFS, KERN-X and external signature check

**Why.** Any directory (including a cloned foreign repository) is packed into .kimg with a Merkle tree; fsck verifies integrity, inspect prints the manifest, diff finds the changed file. The project signature is checked with a public key.

**Command.**
```bash
kernc pack-dir / fsck / inspect / diff  ·  make verify-attestation
```

**Real output:**
```text
$ kernc pack-dir ... -o v1.kimg
[OK] pack-dir: 20 файлов, 127046 байт -> /tmp/kern-demo-v1.kimg
     проверка: kernc fsck /tmp/kern-demo-v1.kimg | kernc inspect /tmp/kern-demo-v1.kimg

$ kernc fsck v1.kimg
[fsck] /tmp/kern-demo-v1.kimg
  версия 1.3 · hash_algo 1 · флаги 0x00000000 · объектов 20
  проверено 20, ошибок 0

$ kernc inspect v1.kimg
{"file":"/tmp/kern-demo-v1.kimg","version":"1.3","hash_algo":1,"flags":0,"object_count":20,"objects":[{"path":"build.zig","type":2,"uncompressed_size":1826,"compressed_size":1826,"digest":"c96aff957f9ebd6f2c035d6ca1d02586302a12b2559e4fd23b96aa61ee5b1ee7"},{"path":"example/usage.zig","type":2,"uncompressed_size":798,"compressed_size":798,"digest":"3c5fabbcc64302d0219b325cc3d1388e0ad694b8de56f55a44779d259d6b5b4f"},{"path":"example/subcommands.zig","type":2,"uncompressed_size":3139,"compressed_size":3139,"digest":"d7137273eefb27d7892c069d2d480f236f0b481fe700fa4e277a45413e38354f"},{"path":"example/streaming-clap.zig","type":2,"uncompressed_size":1853,"compressed_size":1853,"digest":"537ad8fb8a01df2fa4897d5b5c1daf48baf6f2fc1f7654fc73d71c185255d4bb"},{"path":"example/simple.zig","type":2,"uncompressed_size":1461,"compressed_size":1461,"digest":"9dad61219f712b9027f55b98b7d1db2515ff33c109a33539b36074bad409bcdb"},{"path":"example/simple-ex.zig","type":2,"uncompressed_size":1881,"compressed_size":1881,"digest":"b242f1381e2adb061b5754d2de28377fe9227178ed15b901ee115c1592a862e7"},{"path":"example/help.zig","type":2,"uncompressed_size":870,"compressed_size":870,"digest":"0092d561f020d7831683ccb3421daa264978120a8bb5125e1fc80b178c321c85"},{"path":"clap/streaming.zig","type":2,"uncompressed_size":15860,"compressed_size":15860,"digest":"d83b237e40f3ec707459dbcb6bf2f8f9fe63414ad04bbb46a66fc259cab4bffe"},{"path":"clap/parsers.zig","type":2,"uncompressed_size":5332,"compressed_size":5332,"digest":"14c15ced7197b8fae02409986c6fb93fd15420455a9875f92bc154175c569905"},{"path":"clap/codepoint_counting_writer.zig","type":2,"uncompressed_size":4041,"compressed_size":4041,"digest":"cfb2b5f22f94fc3786589b2ad7088d6c0cb465564774de887ae1c2e699431871"},{"path":"clap/args.zig","type":2,"uncompressed_size":920,"compressed_size":920,"digest":"243ad3c29c6f4dd571083943ee1b55d7c858d3b7602265b39d12448768c9c836"},{"path":"clap.zig","type":2,"uncompressed_size":72224,"compressed_size":72224,"digest":"9d5051071cc572e30cd7cf9c39269315c808a6e8bf89008745f7625a5b54f7dd"},{"path":"build.zig.zon","type":2,"uncompressed_size":308,"compressed_size":308,"digest":"87c73488df314b1f5e9e167241d703cb5d39366ddd7ecf00297a8bba1569b7c3"},{"path":"README.md","type":2,"uncompressed_size":13729,"compressed_size":13729,"digest":"82f295550cb738a9dae064d54465f05e4cfc948dd0a2a03e117fe43d5d6b873a"},{"path":"LICENSE","type":2,"uncompressed_size":1075,"compressed_size":1075,"digest":"577761d7f162135a446a1cba56d8ccc5d7b581d871a6b83ba5ccbac48cb874f1"},{"path":".gitignore","type":2,"uncompressed_size":19,"compressed_size":19,"digest":"371ec748039a84fecb9f518cf4bf1133614ddce2cac5bfc9ed6bd5d9398ea7e3"},{"path":".github/workflows/main.yml","type":2,"uncompressed_size":694,"compressed_size":694,"digest":"cf04290d4f3ffeca72cbc829cf37062ffefda10af5fa15e0d3ca26f749f1159e"},{"path":".github/workflows/docs.yml","type":2,"uncompressed_size":981,"compressed_size":981,"digest":"578ec0ed441b6d17732e038c6e952a9985ffa368912ff9985f7575417a5a94cf"},{"path":".github/FUNDING.yml","type":2,"uncompressed_size":17,"compressed_size":17,"digest":"3ec7938d036c1a2fbb79c5c4d58edf2ee6be15a094f97c2868be60fa46154e83"},{"path":".gitattributes","type":2,"uncompressed_size":18,"compressed_size":18,"digest":"c578afa028d28541c6d0243595977b4c85d6b325d9e4da59e3694803ae2483a6"}]}

$ make verify-attestation
[OK]   Ed25519-подпись верна (kern-owner.pub)
  [OK]   kid совпадает с ключом (sha256:6da3e85ea5157…)
  [OK]   attests_commit == HEAD~1 (2a260cab0a9d) — двухшаговая схема
  [OK]   dirtyTree = false
  [OK]   kernc-hermetic: sha256 совпал

...
```

