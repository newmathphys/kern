; zigtools/zls src/TrigramStore.zig:519 `initFromTrigram(trigram, len: u32)`
; ДО гарда: `split.index_1 % len` при len == 0 — деление на ноль (panic).
; Цель: делитель не равен нулю. Ожидание: SAT (len = 0).
(set-logic QF_LIA)
(declare-const len Int)
(assert (>= len 0))
(assert (= len 0))
(check-sat)
(get-model)
