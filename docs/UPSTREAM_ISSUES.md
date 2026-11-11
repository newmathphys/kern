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

## 2. xxHash: `updateBit` — СНЯТО С ОТПРАВКИ (тот же класс, что #50)

**Не отправлять.** `updateBit` — тоже `static`-хелпер, а `level` внутри
`tests/collisions/main.c` всегда неотрицателен. Это ЛАТЕНТНЫЙ случай, не заявка
(см. `docs/upstream/SENT.md`: правило «нет живого бага — нет заявки» и диалог
с мейнтейнером `tidwall/hashmap.c` #50). Класс закрыт механически: правило Б
(`#617`) подавляет такие находки, метка `[LATENT / CALLER-CONST]` — `#616`.

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
