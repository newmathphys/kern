; cmark-gfm 198669d ПОСЛЕ фикса: `numdelims < max_delims` => n <= cap-1.
; Ожидание: UNSAT => PROVEN (trusted: 0).
(set-logic QF_LIA)
(declare-const n Int)
(declare-const cap Int)
(assert (>= n 0))
(assert (>= cap 0))
(assert (< n cap))
(assert (not (<= (+ n 1) cap)))
(check-sat)
