# KERN v1.3 — отчёт об устранении дефектов (доказательства)

**Дата:** 2026-10-10 · **Метод:** сборка, запуск, тесты в Debug и ReleaseFast.
**Правило:** каждое утверждение подтверждено командой, кодом возврата и выводом.

Предыдущие аудиты (`KERN34_AUDIT.md`, `KERN9_SUITE_AUDIT.md`) фиксировали
дефекты. Здесь — что ИСПРАВЛЕНО и чем это доказано.

---

## ФИКС 1: Врата Истины обходились ОДНИМ БАЙТОМ

**Было:** `runTrustedChecker` читал вердикт из `payload[0]`:

```zig
const magic = payload[0];          // <-- байт от ИИ
if (magic == 0xAA) return .Proved; // <-- ИИ управлял вердиктом
```

**Стало:** вердикт формирует ТОЛЬКО `TrustedChecker` (внешний процесс-решатель);
`cert.witness_payload` — это ВХОД для чекера, а не вердикт. Без сконфигурированного
чекера → `.Unknown` → `e=0` (безопасно по умолчанию).

**Доказательство (живой запуск `kern-attack`):**

```
########## АТАКА 1: ИИ присылает ОДИН БАЙТ вместо доказательства ##########
Вердикт: N, e=0
>>> ИТОГ: код НЕ допущен — один байт больше не работает <<<
```

**Тесты:** `ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA больше НЕ даёт e=1` (в admission_gate)
и `ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA НЕ даёт e=1 (уязвимость закрыта)`
(в exhaustive_suite) — оба OK. `runTrustedChecker` удалён.

---

## ФИКС 2: KERNFS не находил ни одного файла (Фазы 1/3 несовместимы)

**Было:** золотой вектор v1.2 содержал ОДИН объект типа `0x0001` без пути;
пула строк не было; `payload_offset` трактовался как абсолютный.

**Стало:** образ **v1.3** (`tools/golden_v1_3.py`, 410 байт):

- пул строк между таблицей объектов и полезной нагрузкой;
- объект-источник `0x0002` и объект-утверждение `0x0005` — ОБА с путями;
- `payload_offset` и `logical_path_offset` ОТНОСИТЕЛЬНЫ `data_payload_offset`
  (ровно как в спецификации KIMG: «Смещение данных (от data_payload_offset)»,
  «Индекс имени файла в пуле строк»);
- статус Белнапа вынесен в биты 2-3 флагов, чтобы не конфликтовать с
  `HAS_LOGICAL_PATH` (бит 1 из спецификации).

**Доказательство (живой запуск `kern-attack`):**

```
########## АТАКА 2: KERNFS на согласованном образе v1.3 ##########
  /raw/src/main.zig -> НАЙДЕНО (22 б): pub fn main() void {}
  /claims/L0_AlignmentInvariant.kern/status -> НАЙДЕНО (view): T
  /claims/L0_AlignmentInvariant.kern/contract.json -> НАЙДЕНО (28 б): {"pre":"true","post":"true"}
  запись -> ошибка: AccessDenied (ожидаем AccessDenied)
>>> ИТОГ: роутер находит объекты — Фазы 1 и 3 согласованы <<<
```

**Тесты:** `ФИКС ФАЗ 1/3: mountFromBytes находит файл и отдаёт zero-copy срез` — OK.

---

## ФИКС 3: `MerkleRootMismatch` объявлен, но НИКОГДА не возвращался

**Стало:** `KimgHeader.verifyMerkleRoot` пересчитывает корень по таблице
объектов и сверяет с `root_digest`. Единая схема для Python и Zig:

```
leaf_i = SHA256(0x00 || "KIMG-ENTRY-LEAF-V1\0" || entry_bytes_i)
root   = SHA256(0x00 || "KIMG-MERKLE-ROOT-V1\0" || leaf_0 || ... || leaf_{n-1})
```

**Тесты:** `MERKLE: пересчёт корня совпадает и ловит подмену`,
`ФИКС MERKLE: подмена байта в образе ломает монтирование` — OK.

---

## ФИКС 4: `AccessDenied` объявлен, но возвращался `FileNotFound`

**Стало:** у KERNFS есть явный `write()`, который возвращает `AccessDenied`
(CONF-06). KERNFS — только чтение.

**Тест:** `ФИКС CONF-06: запись в KERNFS отвергается AccessDenied` — OK.

---

## ФИКС 5: семантика маски `allowed_checkers`

Маска — `1 << checker_id`. Значит `allowed_checkers = 1` разрешает checker 0,
а НЕ 1; для checker 1 нужно `2`. Добавлен `VerificationPolicy.allows()` и тест
`политика: allowed_checkers — битовая маска 1 << checker_id`.

---

## ФИКС 6: «Fake Witness Rejection» работал не так, как заявлено

Механизм «отвергать свидетели < 8 байт» УДАЛЁН вместе с ошибкой
`FakeWitnessRejected`: это была не защита, а маскировка. Теперь отказ — прямое
следствие того, что без внешнего чекера вердикта нет (тест
`AI-01b: короткий свидетель без внешнего чекера не допускается`).

---

## ФИКС 7: `verify`/`ls`/`cat`/`report` — заглушки

**Стало:** все команды `kernc` монтируют KERNFS через `mountFromBytes`
(разбор заголовка + сверка Merkle + безопасный разбор таблицы) и реально
читают образ. `report` строит отчёт ИЗ ОБРАЗА.

**Доказательство:**

```
$ kernc check-integrity tests/fixtures/valid_v1_3.kimg
[OK] Целостность: заголовок + Merkle-корень совпали. Эпоха: 1.3, объектов: 2
$ kernc ls tests/fixtures/valid_v1_3.kimg
[L3] Объектов в образе: 2
  type=0x0002 size=22 path=`src/main.zig`
  type=0x0005 size=28 path=`L0_AlignmentInvariant.kern`
$ kernc cat tests/fixtures/valid_v1_3.kimg /raw/src/main.zig
pub fn main() void {}
$ kernc verify tests/fixtures/valid_v1_3.kimg
  claim `L0_AlignmentInvariant.kern`: ЗАЯВЛЕННЫЙ статус в образе = T
    Врата Истины: e=0 (N) — внешний прувер не сконфигурирован
```

---

## KERN-Next: критерии готовности (§20) — все 10 выполнены

| # | Критерий | Доказательство |
|:--|:--|:--|
| 1 | читать `.kern` | `parser.zig`, тест `PARSER: полный проект из примера §6` |
| 2 | SQLite-каталог | `catalog.zig`; `sqlite3 .kernnext/project.kdb "SELECT ..."` работает |
| 3 | утверждения/свидетельства/связи | таблицы `claims`, `evidence`, `relations` заполняются |
| 4 | snapshot | `.kernnext/project.ksnap` (детерминированный, отсортированный) |
| 5 | отчёт | `.kernnext/report.md` |
| 6 | agent packet | `.kernnext/agent_packet.json` |
| 7 | diff снапшотов | `kernx diff` → `[DIFF] +2 / -2` с точными строками |
| 8 | тесты парсера/валидатора | 13 тестов KERN-Next, все OK |
| 9 | стабильные ID | `stableId = kind:slug`; тест на повторный разбор |
| 10 | пропуск неизменённых | повторный `kernx build` → `[=] Без изменений — пропущено (кэш)` |

---

## Итоговые прогоны

| Прогон | Результат |
|:--|:--|
| `zig build` | exit 0 (kernc, kern-attack, kernx) |
| `zig test src/test_root.zig` (Debug) | **36/36 OK** |
| `zig test src/next/test_root.zig -lc -lsqlite3` (Debug) | **13/13 OK** |
| `python3 tools/golden_v1_3.py` | 410 байт, root совпадает с Zig |
| `./zig-out/bin/kern-attack` | обе атаки закрыты |
