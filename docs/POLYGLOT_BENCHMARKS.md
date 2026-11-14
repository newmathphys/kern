# Polyglot benchmarks: HumanEvalPack (Python/C++/Rust) and DebugBench

All three corpora are fetched over plain HTTPS (no keys, no rate limit):
`bigcode/humanevalpack` through the public Datasets Server (the repo ships parquet only,
and `pyarrow` is not installed here), `Rtian/DebugBench` as raw `eval.json`.
The code is authored by others; `buggy_code` in DebugBench is a bug **implanted by GPT-4**.

| Corpus | Language | Tasks | **caught** | not confirmed | no findings / SKIP | outside domain |
|:--|:--|--:|--:|--:|--:|--:|
| HumanEvalPack (canonical vs buggy) | Python | 164 | **6** | 2 | 156 | 0 |
| HumanEvalPack (`--xray`, iron criterion) | C++ | 164 | **0** | 2 | 162 | - |
| HumanEvalPack (`--xray`, iron criterion) | Rust | 164 | **0** | 0 | 164 | - |
| DebugBench (GPT-4 bugs) | Python | 1414 | **2** | 0 | 16 | 1390 |

HumanEvalPack bugs caught by type: {'value misuse': 1, 'excess logic': 3, 'variable misuse': 1, 'missing logic': 1}
DebugBench bugs caught by category: {'logic error': 2}

## Honest negative result for C++ and Rust

The iron criterion for `--xray` was: a finding must be present in the `buggy` function and
**disappear** in the `canonical` one. Measured: **0 wins in C++, 0 in Rust** (162/164 and
164/164 tasks produced no findings at all). Reason is structural: HumanEvalPack's C++/Rust
tasks are `std::vector` / `Vec<String>` algorithms, i.e. dynamic containers and allocations
that the C-like memory model does not cover. This is reported as measured, not padded.

Every Python `DIVERGED` was confirmed by **executing** both implementations on the solver's
counterexample.
