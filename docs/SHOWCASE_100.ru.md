# Витрина практической пользы KERN

Сгенерировано `tools/run_showcase_100.py` за 12.4 с. Каждая строка —
**реальный** запуск KERN и независимого оракула (вызов функции или unittest).

| Десяток | Задача | Сфера | В чём подвох | KERN | Контрпример |
|:--|:--|:--|:--|:--|:--|
| 01_finance_arbitrage | withdraw_fee_bp | Вывод средств | комиссия 0.30% считается вниз: дробление вывода бесплатно | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | cashback_round_up | Кэшбэк | кэшбэк округляется вверх, но вычитается как целое | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | fx_spread | Конвертация | спред берётся с каждой операции, а не с суммы | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | pool_share | Пул ликвидности | доля пула округляется вниз у каждой части | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | lot_tax | Налог с лотов | налог с каждой доли не компенсирует дробление | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | tiered_discount | Ступенчатая скидка | ступень выбирается по части, а не по сумме | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | deposit_interest | Вклад | процент считается по каждой части вклада | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | dividends_split | Дивиденды | дивиденд дробится и теряет остаток | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | bonus_writeoff | Бонусы | бонус списывается по частям без переноса остатка | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 01_finance_arbitrage | micro_billing | Микроплатежи | микроплатёж теряет доли копейки при каждом списании | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
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
| 05_belnap_policies | iam_data_secops | Облачный IAM | Data разрешает чтение бакета, SecOps запрещает без MFA | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | er_doctor_record | Медицина | Врач скорой запрашивает закрытую карту пациента | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | vip_vs_antifraud | Банк | VIP-лимит разрешает перевод, антифрод блокирует | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | vpn_vs_zerotrust | Сеть | Корпоративный VPN разрешает доступ, Zero-Trust сегмент запрещает | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | gdpr_vs_tax | Комплаенс | GDPR требует удалить, налоговый архив требует хранить 5 лет | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | promo_vs_margin | Маркетинг | Промокод разрешает скидку, правило маржи запрещает | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | hotfix_vs_freeze | Прод | Хотфикс БД в аварии разрешён, заморозка пятницы запрещает | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | plc_thrust_vs_temp | Промышленность | ПЛК требует удержания тяги, датчик перегрева запрещает | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | mod_whitelist_vs_stopword | Модерация | Белый список автора разрешает, стоп-слово запрещает | ПОЙМАЛ | JOIN B / BOOL deny |
| 05_belnap_policies | dlp_vs_share | DLP | Внешний шаринг документа разрешён владельцем, DLP отдела запрещает | ПОЙМАЛ | JOIN B / BOOL deny |

**Подтверждено: 40 / 40.**
