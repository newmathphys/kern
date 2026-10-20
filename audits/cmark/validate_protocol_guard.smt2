; ============================================================================
; cmark-gfm, коммит 2cb4a20 (Fix out-of-bounds read in validate_protocol).
; ГАРД ФИКСА:  if (len == (size_t)(max_rewind - rewind)) return true;
;              char prev_char = data[-rewind - len - 1];
; Т.е. на пути к чтению выполняется len < max_rewind - rewind.
; УТВЕРЖДЕНИЕ: при этом смещение назад не выходит за доступный префикс:
;              rewind + len + 1 <= max_rewind
; Это ровно то, чего не хватало ДО фикса (там i доходил до len без границы).
; ============================================================================
(set-logic QF_LIA)
(declare-const rewind Int)
(declare-const len Int)
(declare-const max_rewind Int)
(assert (>= rewind 0))
(assert (>= max_rewind 0))
(assert (< len (- max_rewind rewind)))
; ОТРИЦАНИЕ цели (ищем контрпример):
(assert (not (<= (+ rewind len 1) max_rewind)))
(check-sat)
