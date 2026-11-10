# Готовые обращения в апстрим (черновики)

Два дефекта, найденные KERN на реальном коде. Тексты готовы к отправке через браузер.
**Перед отправкой:** один раз откройте файл на GitHub и сверьте номера строк — они указаны
для конкретных срезов (SHA зафиксированы ниже).

---

## 1. TigerBeetle: `assert len(...)` после индексации

* **Куда:** `https://github.com/tigerbeetle/tigerbeetle/issues`
* **Файл:** `src/clients/python/tests/test_conformance.py`, строки **6169–6170** на срезе `68958eb7`
* **Заголовок:** `test_conformance.py: length guard placed after indexing transfers_1[0]`

```markdown
In `test_conformance.py` (around lines 6169-6170 in `68958eb7`), `transfers_1[0]` is indexed one
line before the length assertion:

    transfer = transfers_1[0]
    assert len(transfers_1) == 1

If `transfers_1` is empty, the index access raises an unhandled
`IndexError: list index out of range` **before** the assertion that would have explained it.

Suggested fix — swap the two lines so the guard precedes the access:

    assert len(transfers_1) == 1
    transfer = transfers_1[0]

(Found with static bounds analysis in KERN — https://github.com/newmathphys/kern)
```

**СВЕРЕНО ПО ФАЙЛУ (2026-11-09):** файл скачан напрямую с `raw.githubusercontent.com` на
срезе `68958eb7` (13 574 строки) и напечатаны строки 6167-6172:

    6169  transfer_lookup_1 = transfers_1[0]      <- индексация
    6170  assert len(transfers_1) == 1            <- гард ПОСЛЕ неё

То есть номер строки и порядок операторов подтверждены на реальном файле — можно отправлять.

---

## 2. xxHash: `updateBit` — базовый случай `level == 0` на знаковом `int`

* **Куда:** `https://github.com/Cyan4973/xxHash/issues`
* **Файл:** `tests/collisions/main.c`, функция `updateBit`, строка **301** (на срезе `2ec67ca`)
* **Заголовок:** `tests/collisions/main.c: updateBit base case checks level == 0 on signed int`

**Сигнатура — ровно как в коде** (сверено с `tests/collisions/main.c:301`):

```c
static int updateBit(void* buffer, size_t* bitIdx, int level, size_t max)
{
    if (level==0) return 0;                     /* can't progress further */
    flipbit(buffer, bitIdx[level]);
    if (bitIdx[level] < max-1) {
        bitIdx[level]++;
        ...
    }
    if (!updateBit(buffer, bitIdx, level-1, max-1)) return 0;   /* line 314 */
```

```markdown
`level` is a signed `int`, but the recursion base case tests exact equality:

    if (level==0) return 0;

For a signed domain this establishes only `level != 0`. If a negative `level` ever reached this
function, `bitIdx[level]` would read out of bounds at a negative offset, and the recursive call
`updateBit(..., level-1, ...)` would descend toward `INT_MIN - 1` (signed overflow).

Existing callers pass non-negative values, so this is a latent robustness issue rather than a
live bug. Making the lower bound explicit (`if (level <= 0) return 0;`) or taking `level` as
`size_t` removes the possibility entirely.

(Found with static analysis in KERN — https://github.com/newmathphys/kern)
```

**Почему это не придирка:** замер на 15-строчном репро (`docs/evidence/xxhash_updatebit_min.c`):

| гард | находки KERN |
|:--|--:|
| `if (level==0) return 0;` (как сейчас) | **2** (`[BOUNDS PATH]`, `[OVERFLOW PATH]`) |
| `if (level<=0) return 0;` (контроль) | **0** |

То есть правка действительно закрывает оба предупреждения, а не «заметает» их.

---

## 3. Независимая квитанция (одна минута любого человека)

```bash
git clone --depth 1 https://github.com/newmathphys/kern.git && cd kern
bash tools/double_lock_demo.sh     # ждём: [OK] ДВОЙНОЙ ЗАМОК СРАБОТАЛ
bash tools/pilot_receipt.sh        # ждём: PILOT RECEIPT: PASS (8/8)
```

Если вывод совпал — это и есть закрытие пункта **T7** (независимая приёмка): доказательство
получено не на машине автора и не бинарником, который автор собрал у себя.

## ОТПРАВЛЕНО 2026-11-09

* `tidwall/hashmap.c` — https://github.com/tidwall/hashmap.c/issues/50
* `TheAlgorithms/C` — https://github.com/TheAlgorithms/C/issues/1598

Квитанции: `docs/upstream/SENT.md`. Статус — ожидание ответа мейнтейнеров.
