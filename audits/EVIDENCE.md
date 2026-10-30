| Project / file | Function | Theory | Verdict | Counterexample | Runtime |
|:--|:--|:--|:--|:--|:--|
| `audits/andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgrees` | QF_BV _ BitVec 32 знаковый | **PROVEN** | — | — |
| `audits/andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgreesBuggy` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `addr = #xc0000001, alignment = #x40000000, result = #xc0000001` | — |
| `audits/bloch/binary_search.zig` | `mid_buggy` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `low = #x00000804, high = #x7ffff7fc, result = #xc0000000` | — |
| `audits/bloch/binary_search.zig` | `mid_safe` | QF_BV _ BitVec 32 знаковый | SKIP | — | — |
| `audits/bloch/binary_search_safe.zig` | `mid_safe_int` | QF_BV _ BitVec 32 знаковый | **PROVEN** | — | — |
| `audits/codecheck/c_clean.c` | `add_bounded` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/codecheck/c_unguarded.c` | `ratio` | QF_LIA (Int) | **REFUTED** — ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b) | `a = -984, b = 0` | yes |
| `audits/codecheck/rust_allman.rs` | `add32Allman` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647]) | `result = 2147483648, b = 1, a = 2147483647` | yes |
| `audits/codecheck/rust_clean.rs` | `add_bounded` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/codecheck/rust_overflow.rs` | `add32` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647]) | `result = 2147483648, b = 1, a = 2147483647` | yes |
| `audits/codecheck/zig_allman.zig` | `addAllman` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/codecheck/zig_clean.zig` | `add` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/codecheck/zig_div.zig` | `ratio` | QF_LIA (Int) | **REFUTED** — ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b) | `a = 8, b = 0` | yes |
| `audits/cwe_twins/cwe190_bad.c` | `mul_bad` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `a = #x2b6270ab, b = #x7d671b62, result = #xd15e2a76` | — |
| `audits/cwe_twins/cwe190_good.c` | `mul_good` | QF_BV _ BitVec 32 знаковый | **PROVEN** | — | — |
| `audits/cwe_twins/cwe191_bad.c` | `sub_bad` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `unsigned` (диапазон [0, 4294967295]) | `result = -1, b = 2, a = 1` | yes |
| `audits/cwe_twins/cwe191_good.c` | `sub_good` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/cwe_twins/cwe680_bad.c` | `buffer_size` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `n = #x2b6270ab, size = #x7d671b62, result = #xd15e2a76` | — |
| `audits/cwe_twins/cwe680_good.c` | `buffer_size` | QF_BV _ BitVec 32 знаковый | **PROVEN** | — | — |
| `audits/cwe_twins/cwe682_bad.c` | `rem_bad` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ ДЕЛЕНИЯ (a = MIN, b = -1 — аппаратный trap) | `a = -2147483648, b = -1` | — |
| `audits/cwe_twins/cwe682_good.c` | `rem_good` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/ghostty/grid_columns.zig` | `gridColumns` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/ghostty/grid_columns.zig` | `gridColumnsBuggy` | QF_LIA (Int) | **REFUTED** | `cell_width = 1, screen_width = 0, result = 0` | yes |
| `audits/musl/abs.c` | `kern_abs` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/musl/abs.c` | `kern_absBroken` | QF_LIA (Int) | **REFUTED** | `a = -1, result = -1` | yes |
| `audits/real_cases/bv_overflow.c` | `mul_bv` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `a = #x2b6270ab, b = #x7d671b62, result = #xd15e2a76` | — |
| `audits/rust-core/midpoint.rs` | `midpoint` | QF_BV _ BitVec 32 беззнаковый | SKIP | — | — |
| `audits/rust-core/midpoint.rs` | `midpointMutated` | QF_BV _ BitVec 32 беззнаковый | **REFUTED** | `a = #x7fd5723f, b = #x28f8ee8b, result = #x3e9bc938` | — |
| `audits/rust-core/saturating_add.rs` | `saturatingAdd` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/rust-core/saturating_add.rs` | `saturatingAddBuggy` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647]) | `result = 2147483648, rhs = 1, a = 2147483647` | yes |
| `audits/tigerbeetle/div_ceil.zig` | `divCeil` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/tigerbeetle/div_ceil.zig` | `divCeilBuggy` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647]) | `numerator = 2147483647, denominator = 1, result = 2147483648` | yes |
| `audits/zig-std/align.zig` | `alignBackwardEqMod` | QF_BV _ BitVec 32 беззнаковый | **PROVEN** | — | — |
| `audits/zig-std/align.zig` | `alignBackwardBuggy` | QF_BV _ BitVec 32 беззнаковый | **REFUTED** | `addr = #xffffbffc, alignment = #x00000001, result = #x00000001` | — |
| `audits/zig-std/align.zig` | `alignForwardAdd` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `u32` (диапазон [0, 4294967295]) | `alignment = 2, result = 4294967296, addr = 4294967295` | yes |
| `audits/zlib/zcalloc.c` | `zcallocSize` | QF_BV _ BitVec 32 беззнаковый | **REFUTED** | `items = #x8e0ff0f1, size = #x5ffeffef, result = #xffffffff` | — |
| `audits/zlib/zcalloc.c` | `zcallocSizeBounded` | QF_BV _ BitVec 32 беззнаковый | **UNKNOWN (N)** | — | — |
