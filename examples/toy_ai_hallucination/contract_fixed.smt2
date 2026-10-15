; KERN: контракт для ИСПРАВЛЕННОЙ версии `withdraw`.
;
; Та же схема, но тело уже содержит потерянную проверку `amount <= 0`.
; Формула должна стать НЕВЫПОЛНИМОЙ (unsat) — контрпримера нет.
;
; Постусловие: result <= balance
; Тело исправленной функции:
;   amount <= 0                 -> result = -1   (отказ)
;   0 < amount <= balance       -> result = balance - amount
;   amount > balance            -> result = -1   (отказ)
(set-logic QF_LIA)

(declare-const balance Int)
(declare-const amount  Int)
(declare-const result  Int)

(assert (> balance 0))

; исправленное тело
(assert (=> (<= amount 0) (= result (- 0 1))))
(assert (=> (and (> amount 0) (<= amount balance)) (= result (- balance amount))))
(assert (=> (and (> amount 0) (> amount balance)) (= result (- 0 1))))

; ОТРИЦАНИЕ постусловия — нарушений быть не должно
(assert (> result balance))

(check-sat)
