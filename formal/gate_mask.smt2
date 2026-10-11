; KERN — машинный контракт для утверждения о Вратах Истины.
;
; ТЕКСТ (README §4): «checker_id >= 32 НЕ получает прав checker 0».
;
; Что доказываем: в ИСПРАВЛЕННОЙ логике не существует недоверенного чекера
; (id >= 32), который получил бы доступ. Если Z3 вернёт UNSAT — утверждение
; ДОКАЗАНО (опасный случай недостижим). SAT означал бы наличие контрпримера.
;
; Исторический контекст: ДО фикса использовался `@truncate(id)` (u32 -> u5),
; из-за чего id=32 заворачивался в 0 и получал права checker 0. Контракт
; кодирует ИСПРАВЛЕННУЮ логику (явный guard `id < 32`).

(set-logic QF_BV)
(declare-const cid (_ BitVec 32))
(declare-const allowed (_ BitVec 32))

; grants(cid, allowed) = «доступ разрешён».
; ИСПРАВЛЕННАЯ логика: guard `cid < 32` + проверка бита маски.
; Младшие 5 бит индекса (то, что берёт @intCast(u5)) расширяем до 32 бит
; для сдвига: (_ zero_extend 27) ((_ extract 4 0) c).
(define-fun grants ((c (_ BitVec 32)) (a (_ BitVec 32))) Bool
  (and (bvult c (_ bv32 32))
       (= (bvand a (bvshl (_ bv1 32) ((_ zero_extend 27) ((_ extract 4 0) c))))
          (bvshl (_ bv1 32) ((_ zero_extend 27) ((_ extract 4 0) c))))))

; ОПАСНЫЙ случай: id >= 32, но доступ РАЗРЕШЁН.
(assert (and (bvuge cid (_ bv32 32)) (grants cid allowed)))

(check-sat)
