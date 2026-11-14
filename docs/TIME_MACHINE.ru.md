# Машина времени: KERN против реальных исторических багов чужих репозиториев

Каждая мишень — **реальная публичная пара коммитов**: `bug_commit` это parent
коммита-исправления самих мейнтейнеров (`fix_commit`). И дефектный код, и фикс
написали авторы проекта, а не мы.

**Железный критерий победы (добавлен после ревью).** Победа засчитывается только
если одна и та же находка присутствует в *изолированной целевой функции* на
`bug_commit` и **исчезает** на `fix_commit`. Сканирование всего файла на 3000
строк отвергнуто: фоновый хинт в другом конце файла был бы посчитан как победа.
Этот критерий отменил обе наши прежние C-победы.

Статусы: поймано (критерий выполнен), честный пропуск (вне модели KERN, с
собственной формулировкой движка), не подтверждено (функция просканирована,
разницы нет), СБОЙ KERN (дефект в самом KERN), оракул не подтвердил (наше
воспроизведение не удалось — ничего не заявляем).


| Кейс | Репозиторий | Коммит с багом | Коммит-фикс | Оракул: баг | Оракул: фикс | KERN (строго) | Итог |
|:--|:--|:--|:--|:--|:--|:--|:--|
| `boltons_singularize_ss` | `mahmoud/boltons` | `55dfe5077bcb5fa76611b5f2a557ea6c442ad87c` | `1e61524a798ea73632029a013a7686036d5c126f` | FAIL | OK | [XRAY SUMMARY] checked 0 / 1 functions (SMT-verified 0, no obligations 0), skipped 1 with expli | честный пропуск |
| `moreit_chunked_even_zero` | `more-itertools/more-itertools` | `4aeb4338ae1407d8da9723e86da99efeb446f719` | `fbd55137fe47b44f55190c3714c75f1b21bf834d` | FAIL | OK | CRASH: SyntaxError: invalid syntax | **СБОЙ KERN** |
| `moreit_numeric_range_maxsize` | `more-itertools/more-itertools` | `08dca284ba5446a026afdc34067b658f9da989eb` | `c629214760c78c0a2235e896d335cccfb3a64466` | FAIL | FAIL | равенство по насыщенному len — свойство объекта, вне арифметической модели kernc | оракул не подтвердил |
| `moreit_bucket_falsey_validator` | `more-itertools/more-itertools` | `1ea82a711c69f590054987b5cb194157f8ce8ac4` | `67fcf640477c78605580f5ee703a54c73c1e7a8a` | FAIL | OK | истинность объекта через __len__ — динамическая семантика Python | честный пропуск |
| `humanize_intword_carry` | `python-humanize/humanize` | `f971127ce7e7770d3ff5be05cfc484bdf9302e04` | `ca892b368a535a79cc5e2181d052245b94fd6652` | FAIL | OK | [XRAY SUMMARY] checked 0 / 1 functions (SMT-verified 0, no obligations 0), skipped 1 with expli | честный пропуск |
| `cjson_duplicate_depth` | `DaveGamble/cJSON` | `9d1b229086a7b069fb5f4e3be0226a22480a6707` | `12c4bf1986c288950a3d06da757109a6aa1ece38` | clean | SEGV | драйвер даёт инверсию (clean на баге, SEGV на фиксе): воспроизведение не отражает намерение авт | исключено (наш брак) |
| `cjson_setnumber_null` | `DaveGamble/cJSON` | `a3f3d6c7843f3021b648623d13bc4fbca0084838` | `b2890c8d76bbb64e710585ebc0a917196b9c67e7` | SEGV | clean | [XRAY SUMMARY] checked 0 / 1 functions (trivial 0), skipped 1 with explicit reasons, findings 0 | честный пропуск |
| `cjson_valuestring_overlap` | `DaveGamble/cJSON` | `a78d975537a8df40d58a96f8ce326d7fb625e1e5` | `d6d5449e1f271556ea8e6ec0f3026ceb0b4a9508` | SEGV | clean | находок баг=0 фикс=0; исчезло 0 \| [XRAY SUMMARY] checked 1 / 1 functions (trivial 0), skipped 0 | не подтверждено |
| `moreit_peekable_negative_slice` | `more-itertools/more-itertools` | `b21ec4ee8e139ebe297e2221980a694bebb69523` | `e6ce1b0f65a57c459fc5004ad84158447b65b0ac` | OK | OK | по реальным коммитам b21ec4ee8e13 -> e6ce1b0f65a5 поведение peekable не изменилось: мой оракул  | исключено (наш брак) |
| `jsmn_enum_zero` | `zserge/jsmn` | `d87c22d2cd38bb4065d2b33cb683792c2dc9eed3` | `226f318224e772edf3109da3af1d283e6dee3d57` | COMPILE_ERROR | clean | функция jsmntype_t не найдена в jsmn.h | не подтверждено |

**Итог: поймано 0 / честный пропуск 4 / не подтверждено 2 / СБОЙ KERN 1 / оракул не подтвердил 1 / сбой загрузки 0 из 10 реальных исторических исправлений**, 45.8 с. **Ложных заявлений: 0.**

## Что это измеряет, а что нет

Низкий hit-rate здесь — честное измерение KERN в **режиме без аннотаций** на коде,
которого он никогда не видел: рекурсия, вещественная арифметика и ленивость
итераторов лежат вне модели и помечены самим движком как пропуск, а не спрятаны
нами. Ни один случай не засчитан как пойманный, если находка не исчезает ровно
на исправлении мейнтейнеров.

## Найден дефект в самом KERN (строка СБОЙ KERN)

«Машина времени» нашла реальный дефект замороженного анализатора, воспроизводимый одной командой:

```
python3 tools/kern_contracts.py --xray <файл с obj[:n]>
  File "tools/kern_contracts.py", line 7521, in _bounds_one
    _sl = _rw.visit(ast.parse(ast.unparse(sub.slice), mode="eval").body)
  SyntaxError: invalid syntax  ->  ":n"
```

`ast.unparse` для открытого среза (`x[:n]`) даёт `:n` — это не выражение, и `--xray`
падает вместо анализа функции. Блокирует мишень `chunked_even` и вообще любой код с
`x[:n]`. Зафиксировано, но не обойдено: ядро заморожено.
