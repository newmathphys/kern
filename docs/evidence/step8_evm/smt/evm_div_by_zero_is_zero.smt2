(set-logic ALL)
(declare-const a Int)
(declare-const b Int)
(assert (and (>= a -2147483648) (<= a 2147483647)))
(assert (and (>= b -2147483648) (<= b 2147483647)))
;; EVM SDIV: при b = 0 -> 0; при (a=MIN и b=-1) -> MIN; иначе усечение к нулю
(define-fun evm_sdiv ((x Int) (y Int)) Int
  (ite (= y 0) 0
    (ite (and (= x -2147483648) (= y (- 1))) -2147483648
      (ite (or (and (>= x 0) (> y 0)) (and (< x 0) (< y 0)))
           (div (ite (>= x 0) x (- x)) (ite (>= y 0) y (- y)))
           (- (div (ite (>= x 0) x (- x)) (ite (>= y 0) y (- y))))))))
;; EVM DIV (беззнаковое): при y = 0 -> 0
(define-fun evm_div ((x Int) (y Int)) Int (ite (= y 0) 0 (div x y)))
;; DIV(a, 0) == 0 — ОПРЕДЕЛЕНО (Yellow Paper), а не падение.
(assert (not (= (evm_div a 0) 0)))
(check-sat)
