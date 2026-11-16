# Full Spectrum 70 — окно №1: блоки 02 и 04 (20 из 20 подтверждено)

Два режима KERN, которые до сих пор были показаны РОВНО на одном примере каждый,
теперь прогоняются по корпусу боевых карточек. Каждая карточка проверяется
**дважды**: вердикт KERN (символически) и **независимый физический оракул**
(CPython реально исполняет код).

**Закон целостности:** `confirmed == total`. Если хотя бы одна карточка не
подтверждена, раннер завершается с `rc=1` и витрины НЕ пишет вообще.

Корпуса: `02_auto_heal_cegis.json`, `04_state_machines.json`.

## Карточки

| № | блок | карточка | сфера | сюжет | KERN | физический оракул | статус |
|---|------|----------|-------|-------|------|-------------------|--------|
| 1 | 02 | `heal_conversion_zero` | Логистика | доля выполненных заявок при нулевых попытках | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 2 | 02 | `heal_avg_check_empty` | Финтех | средний чек при пустой корзине | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 3 | 02 | `heal_delivery_share_zero` | Доставка | доля бесплатных доставок при нулевом числе заказов (делитель — выражение) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 4 | 02 | `heal_quota_floor_zero` | SaaS-квоты | целых единиц квоты на место при нуле мест (//) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 5 | 02 | `heal_sla_window_zero` | Платежи/SLA | минуты внутри окна эскалации при нулевом окне (%) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 6 | 02 | `heal_discount_rate_zero` | Маркетплейс | ставка скидки при полностью перекрытом подытоге | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 7 | 02 | `heal_tax_rate_zero` | Налоги | эффективная ставка при нулевом обороте | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 8 | 02 | `heal_fill_rate_zero` | Склад/буфер | заполнение буфера нулевой ёмкости | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 9 | 02 | `heal_burn_rate_zero` | Крипто-казначейство | норма расхода при нулевой прибыли | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 10 | 02 | `heal_multi_site_metrics` | Аналитика/BI | две точки деления в одном возврате (счётчик и бонусы) | T (1,0), 2 crash-paths before → 0 after | python3 rc 1 → 0 · 2 guard(s) · normal inputs exact | OK |
| 11 | 04 | `inv_double_refund` | Эскроу | двойной возврат средств по одному заказу | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 32 concrete violation(s) found · 375 safe sequences, 0 violation(s) | OK |
| 12 | 04 | `inv_ship_after_cancel` | Приёмка/склад | отгрузка после отмены заказа и с пустого склада | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 8 concrete violation(s) found · 30 safe sequences, 0 violation(s) | OK |
| 13 | 04 | `inv_wallet_double_debit` | Кошелёк | два списания подряд уводят баланс в минус | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 44 concrete violation(s) found · 192 safe sequences, 0 violation(s) | OK |
| 14 | 04 | `inv_coupon_reactivation` | Маркетплейс | повторная активация одноразового купона | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 15 | 04 | `inv_frozen_withdrawal` | Комплаенс | снятие средств с замороженного счёта | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 10 concrete violation(s) found · 60 safe sequences, 0 violation(s) | OK |
| 16 | 04 | `inv_credit_limit` | Кредит | серия микрозаймов превышает кредитный лимит | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 17 concrete violation(s) found · 243 safe sequences, 0 violation(s) | OK |
| 17 | 04 | `inv_subscription_bypass` | Подписки | переход expired -> active мимо оплаты | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 26 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 18 | 04 | `inv_double_release` | Ресурсы/мьютекс | двойное освобождение ресурса | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 23 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 19 | 04 | `inv_double_vote` | Кворум | один участник голосует дважды | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 20 | 04 | `inv_escrow_reference` | Эскроу | эталонный защищённый автомат: PROVEN + снятие гарда валит доказательство | [PASS] reference, 0 UNKNOWN + [FAIL] after guard removal | 57 violation(s) on the unguarded twin · 204 safe sequences, 0 violation(s) | OK |

## Что доказывает блок 02 (авто-ремонт без ИИ, `--heal`)

Каждая карточка проходит ВСЮ ДУГУ, а не печать рецепта:

1. ДО: файл реально падает в `python3` (`ZeroDivisionError`), а `--xray`
   печатает краш-путь;
2. РЕМОНТ: `kern_contracts.py --heal` сам синтезирует гарды, вносит их в
   исходник и печатает `T (1,0)` вместе с `после патча: 0`;
3. ПОСЛЕ: вылеченный файл исполняется в `python3` без падения, `--xray` даёт
   ноль краш-путей, повторная проверка контрактов — `нарушено 0 / НЕ РЕШЕНО 0`,
   а **обычные входы по-прежнему дают математически верный результат** (гард не
   превратил функцию в константу «0»).

Бэкап `<file>.bak` проверяется на то, что в нём лежит ИСХОДНЫЙ код без патча.

## Что доказывает блок 04 (машины состояний во времени, `--state-inv`)

Каждая карточка — многошаговый бизнес-автомат, где каждый метод по отдельности
выглядит безобидно, но **цепочка переходов** ломает инвариант состояния:

1. KERN печатает `[FAIL] <naive>: STATE INVARIANT VIOLATED` с конкретным
   контрпримером и `[PASS] <guarded>: PROVEN` для защищённого перехода; ни один
   `[UNKNOWN]` не принимается за доказательство;
2. физический оракул реально проигрывает последовательности вызовов на объекте,
   считает наблюдённые нарушения и исчерпывающе проверяет, что защищённый
   переход не нарушает инвариант на сетке последовательностей.

Карточка 10 добавляет **проверку мутацией**: снимите гарды эталонного эскроу —
и доказательство KERN рассыпается в `[FAIL]`, а физический оракул показывает
уход баланса в минус. Доказательство, которое выживает после снятия гарда, ничего
не стоит.

## Честные границы

- `--heal` синтезирует гарды **только для деления на ноль** (`/`, `//`, `%`) —
  ровно то, что ищет `_crash_sites`. Выход за границы списка и «сдвинутый порог»
  он НЕ лечит, поэтому таких карточек здесь нет и не заявляется.
- `--state-inv` доказывает аннотированный инвариант на **каждом пути возврата**
  аннотированной функции; это не инвариант объекта на всю программу.
- Карточки — **данные** (`benchmarks/full_spectrum/*.json`). Код материализуется
  во временный каталог, поэтому в дерево репозитория не попадает аннотированный `.py`,
  а `docs/contracts.lock.json` продолжает запечатывать ровно свои файлы спецификаций

## Воспроизвести

```bash
.venv/bin/python tools/run_full_spectrum.py
```

Нужен интерпретатор с `z3` (штатно `.venv/bin/python`). Без `z3` раннер
завершается с `rc=2` и явным сообщением, а не зелёной галочкой.

ИТОГ: карточек 20 | подтверждено KERN **и** физическим оракулом 20 | rc=0
