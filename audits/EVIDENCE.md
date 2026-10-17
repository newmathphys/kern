| Project / file | Function | Theory | Verdict | Counterexample | Runtime |
|:--|:--|:--|:--|:--|:--|
| `audits/andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgrees` | QF_BV _ BitVec 32 знаковый | **PROVEN** | — | — |
| `audits/andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgreesBuggy` | QF_BV _ BitVec 32 знаковый | **REFUTED** | `addr = #xc0000001, alignment = #x40000000, result = #xc0000001` | — |
| `audits/ghostty/grid_columns.zig` | `gridColumns` | QF_LIA (Int) | SKIP | — | — |
| `audits/ghostty/grid_columns.zig` | `gridColumnsBuggy` | QF_LIA (Int) | **REFUTED** | `cell_width = 1, screen_width = 0, result = 0` | yes |
| `audits/tigerbeetle/div_ceil.zig` | `divCeil` | QF_LIA (Int) | **PROVEN** | — | — |
| `audits/tigerbeetle/div_ceil.zig` | `divCeilBuggy` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647]) | `numerator = 2147483647, denominator = 1, result = 2147483648` | yes |
| `audits/zig-std/align.zig` | `alignBackwardEqMod` | QF_BV _ BitVec 32 беззнаковый | **PROVEN** | — | — |
| `audits/zig-std/align.zig` | `alignBackwardBuggy` | QF_BV _ BitVec 32 беззнаковый | **REFUTED** | `addr = #xffffbffc, alignment = #x00000001, result = #x00000001` | — |
| `audits/zig-std/align.zig` | `alignForwardAdd` | QF_LIA (Int) | **REFUTED** — ПЕРЕПОЛНЕНИЕ типа `u32` (диапазон [0, 4294967295]) | `alignment = 2, result = 4294967296, addr = 4294967295` | yes |
