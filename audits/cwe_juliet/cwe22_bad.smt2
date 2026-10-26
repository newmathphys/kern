; CWE-22 Path Traversal (NIST Juliet-style `bad` twin) на уровне QF_S-контракта.
;
; Настоящий дефект: санитайзер вырезает только одиночный `/`, но НЕ `../`,
; поэтому утверждение «результат НЕ содержит ../» НЕ доказывается — движок
; обязан предъявить контрпример. `good`-близнец (cwe22_good.smt2) вырезает
; именно `../` и доказывается с `trusted: 0 | holes: 0`.
(set-logic QF_SLIA)
(declare-const s String)
(declare-const result String)
(assert (or (and (str.contains s "/") (= result "safe"))
            (and (not (str.contains s "/")) (= result s))))
(assert (str.contains result "../"))
(check-sat)
