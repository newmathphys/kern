# Time Machine: KERN vs. real historical bugs in other people's repositories

Every target is a **real public commit pair**: `bug_commit` is the parent of the
maintainers' own fix (`fix_commit`). Both the defective code and the fix were
written by the project authors, not by us.

**Iron criterion for a win (added after review).** A win counts only if the same
finding appears in the *target function in isolation* on `bug_commit` and
**disappears** on `fix_commit`. Scanning the whole 3,000-line file was rejected:
a background hint elsewhere in the file would have been miscounted as a catch.
This criterion invalidated both of our earlier C "wins".

Statuses: caught (iron criterion met), honest skip (outside KERN's model, with
the engine's own stated reason), not confirmed (function scanned, no difference),
KERN CRASH (a defect in KERN itself), oracle unverified (our reproduction failed,
so nothing is claimed).


| Case | Repository | Bug commit | Fix commit | Oracle: bug | Oracle: fix | KERN (strict) | Result |
|:--|:--|:--|:--|:--|:--|:--|:--|
| `boltons_singularize_ss` | `mahmoud/boltons` | `55dfe5077bcb5fa76611b5f2a557ea6c442ad87c` | `1e61524a798ea73632029a013a7686036d5c126f` | FAIL | OK | [XRAY SUMMARY] checked 0 / 1 functions (SMT-verified 0, no obligations 0), skipped 1 with expli | honest skip |
| `moreit_chunked_even_zero` | `more-itertools/more-itertools` | `4aeb4338ae1407d8da9723e86da99efeb446f719` | `fbd55137fe47b44f55190c3714c75f1b21bf834d` | FAIL | OK | находок баг=0 фикс=0; исчезло 0 \| [XRAY SUMMARY] checked 1 / 1 functions (SMT-verified 1, no ob | not confirmed |
| `moreit_numeric_range_maxsize` | `more-itertools/more-itertools` | `08dca284ba5446a026afdc34067b658f9da989eb` | `c629214760c78c0a2235e896d335cccfb3a64466` | FAIL | FAIL | равенство по насыщенному len — свойство объекта, вне арифметической модели kernc | oracle unverified |
| `moreit_bucket_falsey_validator` | `more-itertools/more-itertools` | `1ea82a711c69f590054987b5cb194157f8ce8ac4` | `67fcf640477c78605580f5ee703a54c73c1e7a8a` | FAIL | OK | истинность объекта через __len__ — динамическая семантика Python | honest skip |
| `humanize_intword_carry` | `python-humanize/humanize` | `f971127ce7e7770d3ff5be05cfc484bdf9302e04` | `ca892b368a535a79cc5e2181d052245b94fd6652` | FAIL | OK | [XRAY SUMMARY] checked 0 / 1 functions (SMT-verified 0, no obligations 0), skipped 1 with expli | honest skip |
| `cjson_duplicate_depth` | `DaveGamble/cJSON` | `9d1b229086a7b069fb5f4e3be0226a22480a6707` | `12c4bf1986c288950a3d06da757109a6aa1ece38` | clean | SEGV | драйвер даёт инверсию (clean на баге, SEGV на фиксе): воспроизведение не отражает намерение авт | dropped (our fault) |
| `cjson_setnumber_null` | `DaveGamble/cJSON` | `a3f3d6c7843f3021b648623d13bc4fbca0084838` | `b2890c8d76bbb64e710585ebc0a917196b9c67e7` | SEGV | clean | [XRAY SUMMARY] checked 0 / 1 functions (trivial 0), skipped 1 with explicit reasons, findings 0 | honest skip |
| `cjson_valuestring_overlap` | `DaveGamble/cJSON` | `a78d975537a8df40d58a96f8ce326d7fb625e1e5` | `d6d5449e1f271556ea8e6ec0f3026ceb0b4a9508` | SEGV | clean | находок баг=0 фикс=0; исчезло 0 \| [XRAY SUMMARY] checked 1 / 1 functions (trivial 0), skipped 0 | not confirmed |
| `moreit_peekable_negative_slice` | `more-itertools/more-itertools` | `b21ec4ee8e139ebe297e2221980a694bebb69523` | `e6ce1b0f65a57c459fc5004ad84158447b65b0ac` | OK | OK | по реальным коммитам b21ec4ee8e13 -> e6ce1b0f65a5 поведение peekable не изменилось: мой оракул  | dropped (our fault) |
| `jsmn_enum_zero` | `zserge/jsmn` | `d87c22d2cd38bb4065d2b33cb683792c2dc9eed3` | `226f318224e772edf3109da3af1d283e6dee3d57` | COMPILE_ERROR | clean | функция jsmntype_t не найдена в jsmn.h | not confirmed |

**Result: 0 caught / 4 honest skip / 3 not confirmed / 0 KERN crash / 1 oracle unverified / 0 fetch failed out of 10 real historical fixes**, 47.9 s. **False claims: 0.**

## What this measures, and what it does not

A low hit rate here is the honest measurement of KERN in **zero-annotation mode**
on code it has never seen: recursion, floating-point arithmetic and iterator
laziness fall outside the model and are reported as skips by the engine itself,
not hidden by us. No case is counted as caught unless the finding disappears
exactly at the maintainers' fix.


## Part B: target-domain scan of a real C repository (no REST API)

`tools/probe_part_b.py` clones `TheAlgorithms/C` with plain git (Smart HTTP has no
60-requests-per-hour limit), walks the last 400 commits, keeps non-merge commits whose
subject looks like a fix and that touch exactly one `.c` file (40 candidates), and applies
the same iron criterion to every function of those files: a `--xray` finding must exist
in the isolated function at the parent commit and disappear at the fix commit.

**Result: 40 real fix commits scanned, 0 satisfied the criterion.** The probe is kept in
the repository so the number can be re-measured; it is reported as it is, not padded.
