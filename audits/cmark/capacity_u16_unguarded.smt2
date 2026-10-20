; cmark-gfm ac80f7b ДО фикса: `row->n_columns` (uint16_t) инкрементируется
; без проверки `< UINT16_MAX`. Цель: счётчик остаётся в 16-битном диапазоне.
; Ожидание: SAT (счётчик может стать 65536 = переполнение).
(set-logic QF_LIA)
(declare-const n Int)
(assert (>= n 0))
(assert (<= n 65535))
(assert (not (<= (+ n 1) 65535)))
(check-sat)
(get-model)
