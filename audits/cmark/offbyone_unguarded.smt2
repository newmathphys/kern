; cmark-gfm 198669d ДО фикса: `numdelims <= max_delims`.
; Цель: индекс счётчика не превосходит ёмкость (numdelims+1 <= max_delims).
; Ожидание: SAT (numdelims == max_delims -> запись за границу).
(set-logic QF_LIA)
(declare-const n Int)
(declare-const cap Int)
(assert (>= n 0))
(assert (>= cap 0))
(assert (<= n cap))
(assert (not (<= (+ n 1) cap)))
(check-sat)
(get-model)
