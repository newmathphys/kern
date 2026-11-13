# Машина времени: KERN против реальных исторических багов чужих репозиториев

Мишени — **настоящие публичные коммиты**: `bug_commit` это parent коммита-исправления
самих авторов проекта, то есть и багованный код, и фикс написали мейнтейнеры.
Независимый оракул обязан физически воспроизвести дефект на `bug_commit` и показать,
что на `fix_commit` он исчез; иначе случай идёт как неподтверждённый, а не как «поймано».


| Кейс | Репозиторий | Коммит с багом | Коммит-фикс | Оракул: баг | Оракул: фикс | KERN | Итог |
|:--|:--|:--|:--|:--|:--|:--|:--|
| `boltons_singularize_ss` | `mahmoud/boltons` | `55dfe5077bcb` | `1e61524a798e` | FAIL | OK | MISSED | пропущено |
| `moreit_chunked_even_zero` | `more-itertools/more-itertools` | `4aeb4338ae14` | `fbd55137fe47` | FAIL | OK | MISSED | пропущено |
| `moreit_numeric_range_maxsize` | `more-itertools/more-itertools` | `08dca284ba54` | `c629214760c7` | FAIL | OK | SKIP | честный пропуск |
| `moreit_bucket_falsey_validator` | `more-itertools/more-itertools` | `1ea82a711c69` | `67fcf640477c` | FAIL | OK | SKIP | честный пропуск |
| `humanize_intword_carry` | `python-humanize/humanize` | `f971127ce7e7` | `ca892b368a53` | FAIL | FAIL | MISSED | оракул не подтвердил |
| `cjson_duplicate_depth` | `DaveGamble/cJSON` | `9d1b229086a7` | `12c4bf1986c2` | clean | SEGV | CAUGHT | оракул не подтвердил |
| `cjson_setnumber_null` | `DaveGamble/cJSON` | `a3f3d6c7843f` | `b2890c8d76bb` | SEGV | clean | CAUGHT | **поймано** |
| `cjson_valuestring_overlap` | `DaveGamble/cJSON` | `a78d975537a8` | `d6d5449e1f27` | SEGV | clean | CAUGHT | **поймано** |
| `moreit_peekable_negative_slice` | `more-itertools/more-itertools` | `b21ec4ee8e33` | `e6ce1b0f65d1` | — | — | — | сбой загрузки |
| `jsmn_enum_zero` | `zserge/jsmn` | `d87c22d2cd38` | `226f318224e7` | COMPILE_ERROR | clean | CAUGHT | оракул не подтвердил |

**Итог: поймано 2 / честный пропуск 2 / пропущено 3 из 10 реальных исторических исправлений**, 71.9 с.

Честные пропуски — не провал демонстрации: они показывают, где модель KERN
действительно заканчивается (ленивость итераторов, истинность объектов, насыщение `len`).

