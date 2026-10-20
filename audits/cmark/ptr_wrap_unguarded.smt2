; cmark-gfm 4682993 ДО фикса: беззнаковая разность смещений БЕЗ проверки `a >= b`.
; Разбор по СЛУЧАЯМ (как рассуждает человек; эквивалент записи через `ite`):
;   случай a < b  =>  off = a - b + M (заворот, M = 2^32 как у bufsize_t = int32).
; Обязательство: off укладывается в остаток ёмкости `cap`.
; Ожидание: SAT — при a = 0, b = 1 заворот даёт M-1, что больше cap.
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
; ГАРДА НЕТ: допускается a < b
(assert (< a b))
; заворот: off = a - b + M
(assert (not (<= (+ a (- b) 4294967296) cap)))
(check-sat)
(get-model)
