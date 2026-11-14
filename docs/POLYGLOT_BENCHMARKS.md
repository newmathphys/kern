# Polyglot benchmarks: HumanEvalPack and DebugBench under KERN

Both corpora are fetched over plain HTTPS (no keys, no rate limit):
`bigcode/humanevalpack` via the public Datasets Server (repo ships parquet only), and
`Rtian/DebugBench` as `eval.json` (20 MB). The code is authored by others; DebugBench's
`buggy_code` is a bug **implanted by GPT-4** into a working LeetCode solution.

| Corpus | Language | Tasks | confirmed diverged | unconfirmed | honest SKIP | out of domain |
|:--|:--|--:|--:|--:|--:|--:|
| HumanEvalPack (canonical vs buggy) | Python | 164 | **6** | 2 | 156 | 0 |
| DebugBench (GPT-4 bugs) | Python | 1414 | **2** | 0 | 16 | 1390 |

HumanEvalPack bugs caught by type: {'value misuse': 1, 'excess logic': 3, 'variable misuse': 1, 'missing logic': 1}
DebugBench bugs caught by category: {'logic error': 2}

## Honest limits

Both corpora are overwhelmingly list/string algorithms: `SKIP` and `out of domain` are the
declared boundary of KERN's model, not hidden failures. Every `DIVERGED` was confirmed by
**executing** both implementations in Python on the solver's counterexample.

C++ and Rust splits of HumanEvalPack are **not** covered: they need the `--xray` iron
criterion (finding present on `buggy_solution`, absent on `canonical_solution`) - a
separate pipeline that was not built in this window.
