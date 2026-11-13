# Витрина практической пользы KERN

Сгенерировано `tools/run_showcase_100.py` за 6.9 с. Каждая строка —
**реальный** запуск KERN и независимого оракула (вызов функции или unittest).

| Десяток | Задача | Сфера | В чём подвох | KERN | Контрпример |
|:--|:--|:--|:--|:--|:--|
| 02_ai_refactoring_diff | pagination_pages | API-пагинация | число страниц считается без округления вверх: последняя страница теряется | ПОЙМАЛ | [КОНТРПРИМЕР] per_page = 0, n = 0, res_old = -1, res_new = 0 |
| 02_ai_refactoring_diff | clamp_swap | Числовые лимиты | переставлены ветви clamp: при lo > hi поведение меняется | ПОЙМАЛ | [КОНТРПРИМЕР] res_old = 1, res_new = -1, hi = -1, lo = 1, x = 0 |
| 02_ai_refactoring_diff | rate_limit_off_by_one | Лимит запросов | строгое сравнение заменено на нестрогое: пропускается лишний запрос | ПОЙМАЛ | [КОНТРПРИМЕР] used = 0, cap = 0, res_old = 0, res_new = 1 |
| 02_ai_refactoring_diff | delivery_free_threshold | Расчёт доставки | порог бесплатной доставки съехал на 1 копейку | ПОЙМАЛ | [КОНТРПРИМЕР] total = 3000, res_old = 0, res_new = 300 |
| 02_ai_refactoring_diff | retry_fee_rounding | Комиссия при повторах | «оптимизация» порядка операций: сначала деление, потом умножение — копейки теряются | ПОЙМАЛ | [КОНТРПРИМЕР] amount = 34, res_old = 1, res_new = 0 |
| 02_ai_refactoring_diff | vat_rounding | Налог/НДС | НДС считается с уже округлённой базы: копейки уходят в бюджет | ПОЙМАЛ | [КОНТРПРИМЕР] net = -1, res_old = -1, res_new = -20 |
| 02_ai_refactoring_diff | quota_gb | Квота диска | остаток квоты не ограничен снизу: пользователь уходит в минус | ПОЙМАЛ | [КОНТРПРИМЕР] res_new = -1, res_old = 0, used = 0, quota = -1 |
| 02_ai_refactoring_diff | bonus_points_threshold | Бонусные баллы | порог списания проверяется по модулю: баллы списываются всегда | ПОЙМАЛ | [КОНТРПРИМЕР] points = 0, res_new = -1, cost = 1, res_old = 0 |
| 02_ai_refactoring_diff | cooldown_window | Окно кулдауна | граница окна стала открытой: запрос на самой границе пропускается | ПОЙМАЛ | [КОНТРПРИМЕР] now = 0, win = 0, last = 0, res_old = 1, res_new = 0 |
| 02_ai_refactoring_diff | group_seats | Распределение мест | остаток мест делится без учёта минимума на группу | ПОЙМАЛ | [КОНТРПРИМЕР] groups = 0, seats = -1, res_old = 0, res_new = -1 |
| 03_ai_anticheat | swallowed_exception | Финансовый тест | исключение проглочено: тест зелёный, перевод не выполнен | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | swallowed_assert | API-тест | assert внутри try, а except гасит падение | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | exit_in_test | Проверка прав | тест завершает процесс кодом 0 до проверок | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | vacuous_test | Расчёт комиссии | тест без единого утверждения: rc=0 при нулевой проверке | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | mock_of_subject | Складской учёт | проверяемая функция подменена моком с нужным ответом | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | disabled_by_decorator | Налоговый расчёт | тест отключён декоратором skip и никогда не выполняется | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | unconditional_skip | Модерация | безусловный skip внутри тела теста | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | always_true_eq | Сверка балансов | переопределён __eq__ так, что любой объект равен ожидаемому | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | monkeypatch_module | Лимиты API | подмена функции модуля присваиванием перед проверкой | ПОЙМАЛ | unittest rc=0 (слеп) |
| 03_ai_anticheat | dunder_setattr | Проверка доставки | динамическая подмена dunder через setattr | ПОЙМАЛ | unittest rc=0 (слеп) |

**Подтверждено: 20 / 20.**
