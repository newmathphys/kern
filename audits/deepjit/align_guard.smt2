; DeepJIT — align_kernel_arg С ВЕРХНЕЙ ГРАНИЦЕЙ на offset (гард против заворота).
; (offset + align - 1) в беззнаковом не переполняется, поэтому результат
; маскирования `& ~(align-1)` округляет ВВЕРХ: result >= offset.
; Случай переполнения исключён гардом `offset + align - 1 < M`.
; Ожидание: UNSAT => PROVEN нашим чекером (trusted: 0).
(set-logic QF_LIA)
(declare-const offset Int)
(declare-const align Int)
(declare-const M Int)
(assert (= M 4294967296))
(assert (>= offset 0))
(assert (< offset M))
(assert (>= align 4))
(assert (< align M))
; ГАРД: сложение не переполняется
(assert (< (+ offset align -1) M))
; точное значение x = offset + align - 1
(declare-const x Int)
(assert (= x (+ offset align -1)))
; маскирование округляет ВНИЗ до кратного align: x - (align-1) <= result <= x
(declare-const result Int)
(assert (<= result x))
(assert (>= result (- x align -1)))
; ОБЯЗАТЕЛЬСТВО (result >= offset) ОТРИЦАЕТСЯ
(assert (< result offset))
(check-sat)
