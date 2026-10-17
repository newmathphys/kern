; CONTROL: the same function with the classic off-by-one (alignment-2 instead of alignment-1).
; A checker that cannot say NO is worthless, so this must be REFUTED with a counterexample.
(set-logic QF_BV)
(declare-const addr (_ BitVec 32))
(declare-const alignment (_ BitVec 32))
(assert (and (not (= alignment #x00000000))
             (= (bvand alignment (bvsub alignment #x00000001)) #x00000000)))
(assert (not (= (= (bvand addr (bvnot (bvsub alignment #x00000002))) addr)
               (= (bvurem addr alignment) #x00000000))))
(check-sat)
