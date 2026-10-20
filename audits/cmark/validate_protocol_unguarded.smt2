; ============================================================================
; cmark-gfm ДО фикса 2cb4a20: проверки `len <= max_rewind - rewind` НЕТ.
; Цель та же — смещение назад не выходит за доступный префикс.
; Ожидание: SAT (контрпример существует) => функция небезопасна.
; ============================================================================
(set-logic QF_LIA)
(declare-const rewind Int)
(declare-const len Int)
(declare-const max_rewind Int)
(assert (>= rewind 0))
(assert (>= len 1))
(assert (>= max_rewind 0))
(assert (not (<= (+ rewind len 1) max_rewind)))
(check-sat)
(get-model)
