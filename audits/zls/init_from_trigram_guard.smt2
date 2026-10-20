; ПОСЛЕ гарда `if (len == 0) return …` (или assert(len > 0)):
; на пути деления len >= 1, значит len != 0.
; Ожидание: UNSAT => PROVEN нашим чекером (trusted: 0).
(set-logic QF_LIA)
(declare-const len Int)
(assert (>= len 1))
(assert (= len 0))
(check-sat)
