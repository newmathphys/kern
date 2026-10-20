; cmark-gfm ac80f7b ПОСЛЕ фикса: `if (row->n_columns == UINT16_MAX) break;`
; => на пути инкремента n <= 65534, значит n+1 <= 65535.
; Ожидание: UNSAT => PROVEN нашим чекером (trusted: 0).
(set-logic QF_LIA)
(declare-const n Int)
(assert (>= n 0))
(assert (<= n 65534))
(assert (not (<= (+ n 1) 65535)))
(check-sat)
