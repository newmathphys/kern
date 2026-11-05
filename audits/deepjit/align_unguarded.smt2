; DeepJIT — align_kernel_arg БЕЗ верхней границы на offset (тот же класс, что баг
; `alignForward` в zig std). При offset > M - (align-1) сложение
; `offset + align - 1` ЗАВОРАЧИВАЕТСЯ через ноль, и результат маскирования
; оказывается МЕНЬШЕ offset: выравнивание уходит не вверх, а вниз.
; Ожидание: SAT — контрпример offset = M-1, align = 4 даёт result = 0 < offset.
(set-logic QF_LIA)
(declare-const offset Int)
(declare-const align Int)
(declare-const M Int)
(assert (= M 4294967296))
(assert (>= offset 0))
(assert (< offset M))
(assert (>= align 4))
(assert (< align M))
; ГАРДА НЕТ: сложение переполняется
(assert (>= (+ offset align -1) M))
; завёрнутое значение x = offset + align - 1 - M
(declare-const x Int)
(assert (= x (+ offset align -1 (- M))))
(declare-const result Int)
(assert (<= result x))
(assert (>= result 0))
; ОБЯЗАТЕЛЬСТВО нарушено: result < offset
(assert (< result offset))
(check-sat)
(get-model)
