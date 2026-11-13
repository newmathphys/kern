# Витрина практической пользы KERN

Сгенерировано `tools/run_showcase_100.py` за 28.6 с. Каждая строка —
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
| 04_c_memory_xray | c11_promo_bounds | Память C | uint8_t i-1 при i=0 -> b[-1] (C11 6.3.1.1 promotion) | ПОЙМАЛ | gcc: UB/ASan (rc=1) |
| 04_c_memory_xray | size_t_wrap_bounds | Память C | size_t i-1 при i=0 -> wrap-around | ПОЙМАЛ | gcc: UB/ASan (rc=1) |
| 04_c_memory_xray | int64_neg_index | Память C | int64_t индекс без гарда: b[i-1] при i=0 | ПОЙМАЛ | gcc: UB/ASan (rc=1) |
| 04_c_memory_xray | uint16_promo | Память C | uint16_t i-1 при i=0: promotion до int даёт -1 -> b[-1] | ПОЙМАЛ | gcc: UB/ASan (rc=1) |
| 04_c_memory_xray | neg_int_min | Арифметика | унарный минус на INT_MIN без гарда | ПОЙМАЛ | [OVERFLOW PATH] f: переполнение типа `i32` ([-2147483648, 2147483647]) в `-w` —  |
| 04_c_memory_xray | guard_reset | Арифметика | гард сброшен переприсваиванием w = y; -w | ПОЙМАЛ | [OVERFLOW PATH] f: переполнение типа `i32` ([-2147483648, 2147483647]) в `-w` —  |
| 04_c_memory_xray | div_zero_path | Деление | деление на параметр без гарда != 0 | ПОЙМАЛ | gcc: UB/ASan (rc=1) |
| 04_c_memory_xray | promo_guarded | Память C (близнец) | тот же b[i-1], но под гардом i>=1 | ПОЙМАЛ | gcc: чисто (rc=0) |
| 04_c_memory_xray | neg_guarded | Арифметика (близнец) | -w под гардом w < -MAXWB | ПОЙМАЛ | gcc: чисто (rc=0) |
| 04_c_memory_xray | div_guarded | Деление (близнец) | то же деление, но под гардом b != 0 | ПОЙМАЛ | gcc: чисто (rc=0) |
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
| 06_business_laws_lia | stock_reserve | Склад | зарезервировано не больше остатка: reserve <= stock | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | change_split | Сдача по чеку | сумма частей == итог: parts(a,b) суммируются без потерь | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | quorum_votes | Кворум | кворум требует строгого большинства: 2*for > total | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | slot_overlap | Расписание | слоты не пересекаются: start2 >= end1 | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | sla_penalty_cap | SLA | штраф не выше потолка: penalty <= cap | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | credit_score_range | Скоринг | скоринг в [300, 850] | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | vacation_rollover | Отпускные | перенос дней не больше лимита: carry <= limit | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | worker_pool | Пул воркеров | воркеров не меньше 1 и не больше максимума | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | wholesale_monotone | Опт-скидка | скидка не убывает с объёмом: disc(b) >= disc(a) при b > a | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 06_business_laws_lia | tick_normalize | Биржевой тик | цена кратна шагу тика | ПОЙМАЛ | [КОНТРПРИМЕР] a2 = 1, a1 = 1, _havoc_1 = -1, result = -1 |
| 07_bitvec_protocols | bloch_midpoint | Алгоритмы | midpoint (lo+hi)>>1 переполняется на u32 | ПОЙМАЛ | [КОНТРПРИМЕР] lo = #x03000005, hi = #xfefffff5, m = #x00fffffd |
| 07_bitvec_protocols | align_bad_mask | Аллокатор | выравнивание addr & ~(align-2) не кратно align | ПОЙМАЛ | [КОНТРПРИМЕР] x = #x00000001, y = #x00000001 |
| 07_bitvec_protocols | align_forward_overflow | Аллокатор | addr + (align-1) переполняется на 0xFFFFFFFF | ПОЙМАЛ | [КОНТРПРИМЕР] a = #xffffffff, r = #x00000006 |
| 07_bitvec_protocols | pow2_false_positive | Битовые проверки | (x & (x-1)) == 0 верно и для x == 0 | ПОЙМАЛ | [КОНТРПРИМЕР] x = #x00000000 |
| 07_bitvec_protocols | rgb565_misshift | Графика | сдвиг канала на 1 бит мимо маски теряет биты | ПОЙМАЛ | [КОНТРПРИМЕР] p = #x0001f000, r = #x000000ff |
| 07_bitvec_protocols | ipv4_dirty_net | Сети | net с ненулевыми хост-битами ломает сравнение | ПОЙМАЛ | [КОНТРПРИМЕР] ip = #xc0a80101, net = #xc0a80201, mask = #xffffff00 |
| 07_bitvec_protocols | flags_toggle_bug | Права | flags ^ bit меняет чужой флаг вместо снятия | ПОЙМАЛ | [КОНТРПРИМЕР] f = #x00000006, bit = #x00000001, r = #x00000007 |
| 07_bitvec_protocols | byte_shift_nomask | Кодек | старший байт без & 0xFF даёт отрицательное | ПОЙМАЛ | [КОНТРПРИМЕР] v = #x80000000, hi = #x00000080 |
| 07_bitvec_protocols | mul32_overflow | Аллокатор | items*size переполняет 32-битный размер | ПОЙМАЛ | [КОНТРПРИМЕР] s = #x00010000, n = #x00000000, i = #x00010000 |
| 07_bitvec_protocols | align_good_mask | Аллокатор (эталон) | корректное addr & ~(align-1) всегда кратно align | ПОЙМАЛ | контрпримеров нет (эталон доказан) |
| 08_float_ieee754 | fp_div_zero_nan | IEEE-754 | 0.0/0.0 даёт NaN: NaN != NaN (провал рефлексивности) | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_nan_guard_bypass | IEEE-754 | сравнение с NaN ложно: гард if x > limit пропускает атаку | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_neg_zero_div | IEEE-754 | -0.0 == +0.0, но 1/-0.0 = -oo | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_absorption_2_24 | IEEE-754 | (2^24 + 1.0) - 2^24 == 0: списание 1.0 потеряно | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_assoc_break | IEEE-754 | неассоциативность сложения Float32 | ПОЙМАЛ | IEEE-754 Python: True |
| 08_float_ieee754 | fp_mul_overflow_inf | IEEE-754 | конечные числа переполняются в +oo | ПОЙМАЛ | IEEE-754 Python: True |
| 08_float_ieee754 | fp_inf_minus_inf | IEEE-754 | (+oo) - (+oo) = NaN | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_stick_counter | IEEE-754 | x + 1.0 == x при x = 2^24: счётчик цикла залипает | ПОЙМАЛ | [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет) |
| 08_float_ieee754 | fp_distributivity | IEEE-754 | дистрибутивность в Float32 нарушается | ПОЙМАЛ | IEEE-754 Python: True |
| 08_float_ieee754 | fp_proven_invariant | IEEE-754 (эталон) | доказанный инвариант NaN-модели (trusted: 0), мутант обязан падать | ПОЙМАЛ | контрпримеров нет (эталон доказан) |
| 09_strings_and_mcp | mcp_zero_width | ИИ-инструменты | скрытый U+200B в описании тула | ПОЙМАЛ | json.loads: валиден (слеп) |
| 09_strings_and_mcp | mcp_prompt_injection | ИИ-инструменты | прямая инъекция ignore previous instructions | ПОЙМАЛ | json.loads: валиден (слеп) |
| 09_strings_and_mcp | mcp_bidi_override | ИИ-инструменты | Bidi-переопределение направления текста U+202E | ПОЙМАЛ | json.loads: валиден (слеп) |
| 09_strings_and_mcp | mcp_secret_exfil | ИИ-инструменты | инструкция скрытой отправки секретов в description | ПОЙМАЛ | json.loads: валиден (слеп) |
| 09_strings_and_mcp | mcp_zero_width_joiner | ИИ-инструменты | невидимый zero-width joiner U+200D в схеме | ПОЙМАЛ | json.loads: валиден (слеп) |
| 10_noninterference_and_proofs | proof_const_tamper | Сертификаты Z3 | искажена константа внутри шага вывода | ПОЙМАЛ | kernc.wasm: ОТКЛОНЁН; наивный чекер: нет unsat |
| 10_noninterference_and_proofs | proof_drop_false | Сертификаты Z3 | оборван финальный вывод false | ПОЙМАЛ | kernc.wasm: ОТКЛОНЁН; наивный чекер: нет unsat |
| 10_noninterference_and_proofs | proof_inject_trust | Сертификаты Z3 | внедрено недоверенное правило trust | ПОЙМАЛ | kernc.wasm: ОТКЛОНЁН; наивный чекер: нет unsat |
| 10_noninterference_and_proofs | proof_break_parens | Сертификаты Z3 | нарушена скобочная целостность DAG | ПОЙМАЛ | kernc.wasm: ОТКЛОНЁН; наивный чекер: нет unsat |
| 10_noninterference_and_proofs | proof_broken_mid | Сертификаты Z3 | разрыв скобочной структуры в СЕРЕДИНЕ DAG (ядро не должно доверять) | ПОЙМАЛ | kernc.wasm: ОТКЛОНЁН; наивный чекер: нет unsat |
| 10_noninterference_and_proofs | nf_balance_leak | Банк | чужой баланс влияет на публичный код ошибки | ПОЙМАЛ | [FAIL] transfer_status: SECRET LEAK / NON-INTERFERENCE VIOLATED — [КОНТРПРИМЕР]  |
| 10_noninterference_and_proofs | nf_pin_timing | Аутентификация | секретный PIN меняет публичный ответ | ПОЙМАЛ | [FAIL] login: SECRET LEAK / NON-INTERFERENCE VIOLATED — [КОНТРПРИМЕР] pin__1 = 0 |
| 10_noninterference_and_proofs | nf_salary_report | HR | зарплата влияет на агрегированный отчёт из одного | ПОЙМАЛ | [FAIL] dept_stat: SECRET LEAK / NON-INTERFERENCE VIOLATED — [КОНТРПРИМЕР] salary |
| 10_noninterference_and_proofs | nf_tenant_limit | SaaS | секретный лимит соседнего тенанта меняет ответ API | ПОЙМАЛ | [FAIL] api_quota: SECRET LEAK / NON-INTERFERENCE VIOLATED — [КОНТРПРИМЕР] limit_ |
| 10_noninterference_and_proofs | nf_debug_branch | Отладка | скрытая ветка по секретному ключу меняет вывод | ПОЙМАЛ | [FAIL] render: SECRET LEAK / NON-INTERFERENCE VIOLATED — [КОНТРПРИМЕР] key__1 =  |

**Подтверждено: 95 / 95.**
