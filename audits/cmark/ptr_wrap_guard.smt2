; cmark-gfm 4682993 ПОСЛЕ фикса: проверяются ОБА условия — нет заворота
; (a >= b) и ёмкости хватает (cap >= a - b). Тогда off = a - b <= cap.
; Случай a < b исключён гардом, поэтому нет ни заворота, ни огромного смещения.
; Ожидание: UNSAT => PROVEN нашим чекером (trusted: 0).
(set-logic QF_LIA)
(declare-const a Int)
(declare-const b Int)
(declare-const cap Int)
(assert (>= a 0))
(assert (< a 4294967296))
(assert (>= b 0))
(assert (< b 4294967296))
(assert (>= cap 0))
(assert (< cap 4294967296))
; ГАРД ФИКСА: заворота нет и ёмкости хватает
(assert (>= a b))
(assert (>= cap (- a b)))
(assert (not (<= (- a b) cap)))
(check-sat)
