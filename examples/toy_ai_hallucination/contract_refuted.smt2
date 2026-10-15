; KERN: контракт для `withdraw` из toy_ai_hallucination.
;
; Кодируем ТЕЛО, которое написал ИИ-агент, и ОТРИЦАНИЕ постусловия.
; Если формула ВЫПОЛНИМА (sat) — постусловие нарушается, найден контрпример.
;
; Постусловие (что должно быть верно): result <= balance
; Тело агента: result = balance - amount   (проверка `amount <= 0` ЗАБЫТА)
;
; (result = balance - amount) AND NOT(result <= balance)
;   -> balance - amount > balance  ->  amount < 0
; => контрпример amount = -1: баланс УВЕЛИЧИВАЕТСЯ при списании.
(set-logic QF_LIA)

(declare-const balance Int)
(declare-const amount  Int)
(declare-const result  Int)

; предусловие: счёт открыт
(assert (> balance 0))

; тело агента (проверка отрицательной суммы отсутствует)
(assert (= result (- balance amount)))

; ОТРИЦАНИЕ постусловия — ищем нарушение
(assert (> result balance))

(check-sat)
(get-model)
