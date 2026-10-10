(set-logic ALL)
(declare-const x Int)
(assert (and (> x 0) (not (> (+ x 1) 1))))
(check-sat)
