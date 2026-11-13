# Time Machine: KERN vs. real historical bugs from other people's repositories

Targets are **real public commits**: `bug_commit` is the parent of the maintainers'
own fix commit, so both the buggy code and the fix were written by the projects'
authors. An independent oracle must physically reproduce the defect on `bug_commit`
and show it gone on `fix_commit`; otherwise the case is reported as unverified
instead of being counted as a hit.


| Case | Repository | Bug commit | Fix commit | Oracle: bug | Oracle: fix | KERN | Result |
|:--|:--|:--|:--|:--|:--|:--|:--|
| `boltons_singularize_ss` | `mahmoud/boltons` | `55dfe5077bcb` | `1e61524a798e` | FAIL | OK | MISSED | missed |
| `moreit_chunked_even_zero` | `more-itertools/more-itertools` | `4aeb4338ae14` | `fbd55137fe47` | FAIL | OK | MISSED | missed |
| `moreit_numeric_range_maxsize` | `more-itertools/more-itertools` | `08dca284ba54` | `c629214760c7` | FAIL | OK | SKIP | honest skip |
| `moreit_bucket_falsey_validator` | `more-itertools/more-itertools` | `1ea82a711c69` | `67fcf640477c` | FAIL | OK | SKIP | honest skip |
| `humanize_intword_carry` | `python-humanize/humanize` | `f971127ce7e7` | `ca892b368a53` | FAIL | FAIL | MISSED | oracle unverified |
| `cjson_duplicate_depth` | `DaveGamble/cJSON` | `9d1b229086a7` | `12c4bf1986c2` | clean | SEGV | CAUGHT | oracle unverified |
| `cjson_setnumber_null` | `DaveGamble/cJSON` | `a3f3d6c7843f` | `b2890c8d76bb` | SEGV | clean | CAUGHT | **caught** |
| `cjson_valuestring_overlap` | `DaveGamble/cJSON` | `a78d975537a8` | `d6d5449e1f27` | SEGV | clean | CAUGHT | **caught** |
| `moreit_peekable_negative_slice` | `more-itertools/more-itertools` | `b21ec4ee8e33` | `e6ce1b0f65d1` | — | — | — | fetch failed |
| `jsmn_enum_zero` | `zserge/jsmn` | `d87c22d2cd38` | `226f318224e7` | COMPILE_ERROR | clean | CAUGHT | oracle unverified |

**Result: 2 caught / 2 honest skip / 3 missed out of 10 real historical fixes**, 71.9 s.

Honest skips are not a failure of the demonstration: they mark where KERN's model
genuinely ends (iterator laziness, object truthiness, saturated `len`).

