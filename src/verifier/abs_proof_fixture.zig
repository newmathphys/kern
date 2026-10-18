// СГЕНЕРИРОВАНО из tests/fixtures (не редактировать вручную).
// Реальный вывод Z3 для musl src/stdlib/abs.c (51 шаг, trusted: 0 | holes: 0)
// и 30 точечных подделок для адверсариального фаззера (Испытание А).

pub const ABS_CONTRACT = "(set-logic ALL)\n(declare-const a Int)\n(declare-const result Int)\n(assert (and (>= a -2147483648) (<= a 2147483647)))\n(assert (> a (- 2147483648)))\n(assert (= result (ite (< a 0) (- a) a)))\n(assert (not (>= result 0)))\n(check-sat)\n";

pub const ABS_PROOF = "((set-logic ALL)\n(declare-fun z3name!1 () Int)\n(proof\n(let ((?x206 (* (- 1) z3name!1)))\n(let ((?x87 (+ a ?x206)))\n(let (($x94 (<= ?x87 0)))\n(let (($x102 (not $x94)))\n(let (($x103 (or (not (>= ?x87 0)) $x102)))\n(let (($x104 (not $x103)))\n(let (($x61 (>= a 0)))\n(let ((?x116 (+ a z3name!1)))\n(let (($x121 (>= ?x116 0)))\n(let (($x89 (not $x121)))\n(let (($x90 (or (not (<= ?x116 0)) $x89)))\n(let (($x59 (not (>= result 0))))\n(let ((@x60 (asserted $x59)))\n(let ((@x147 (mp @x60 (rewrite (= $x59 $x59)) $x59)))\n(let ((@x223 (hypothesis $x121)))\n(let (($x143 (>= (+ result ?x206) 0)))\n(let ((?x176 (+ result (* (- 1) (ite $x61 a (* (- 1) a))))))\n(let (($x167 (>= ?x176 0)))\n(let (($x189 (not (or (not (<= ?x176 0)) (not $x167)))))\n(let ((@x193 (trans (rewrite (= (= ?x176 0) (and (<= ?x176 0) $x167))) (rewrite (= (and (<= ?x176 0) $x167) $x189)) (= (= ?x176 0) $x189))))\n(let (($x177 (= ?x176 0)))\n(let ((?x66 (* (- 1) a)))\n(let ((?x72 (ite $x61 a ?x66)))\n(let (($x77 (= result ?x72)))\n(let (($x55 (<= 0 a)))\n(let ((?x131 (ite $x55 a ?x66)))\n(let (($x159 (= result ?x131)))\n(let ((@x181 (trans (monotonicity (rewrite (= ?x131 ?x72)) (= $x159 $x77)) (rewrite (= $x77 $x177)) (= $x159 $x177))))\n(let (($x53 (= result (ite (< a 0) (- a) a))))\n(let ((@x54 (asserted $x53)))\n(let ((@x169 (mp (mp @x54 (rewrite (= $x53 $x159)) $x159) (rewrite (= $x159 $x159)) $x159)))\n(let ((@x224 (mp (not-or-elim (mp (mp @x169 @x181 $x177) @x193 $x189) $x167) (rewrite (= $x167 $x143)) $x143)))\n(let ((@x84 (def-axiom (or $x103 $x94))))\n(let (($x62 (not $x61)))\n(let (($x112 (or $x62 $x104)))\n(let (($x132 (not (or (not $x112) (not (or $x61 (not $x90)))))))\n(let (($x200 (= z3name!1 ?x66)))\n(let (($x201 (or $x61 $x200)))\n(let (($x199 (or $x62 (= z3name!1 a))))\n(let (($x202 (and $x199 $x201)))\n(let (($x226 (not $x90)))\n(let (($x232 (or $x61 $x226)))\n(let (($x233 (= $x201 $x232)))\n(let (($x117 (<= ?x116 0)))\n(let (($x140 (and $x117 $x121)))\n(let (($x82 (>= z3name!1 ?x66)))\n(let (($x67 (<= z3name!1 ?x66)))\n(let (($x110 (and $x67 $x82)))\n(let ((@x141 (monotonicity (rewrite (= $x67 $x117)) (rewrite (= $x82 $x121)) (= $x110 $x140))))\n(let ((@x231 (trans (rewrite (= $x200 $x110)) (trans @x141 (rewrite (= $x140 $x226)) (= $x110 $x226)) (= $x200 $x226))))\n(let ((@x74 (monotonicity (rewrite (= $x199 $x112)) (trans (monotonicity @x231 $x233) (rewrite (= $x232 $x232)) $x233) (= $x202 (and $x112 $x232)))))\n(let ((@x164 (mp (intro-def $x202) (trans @x74 (rewrite (= (and $x112 $x232) $x132)) (= $x202 $x132)) $x132)))\n(let ((@x165 (not-or-elim @x164 $x112)))\n(let ((@x214 (unit-resolution @x165 (unit-resolution @x84 ((_ th-lemma arith) @x223 @x224 @x147 $x102) $x103) ((_ th-lemma arith) @x224 @x223 @x147 $x61) false)))\n(let ((@x153 (unit-resolution (not-or-elim @x164 $x232) (unit-resolution (def-axiom (or $x90 $x121)) (lemma @x214 $x89) $x90) $x61)))\n((_ th-lemma arith) @x153 @x224 @x147 (unit-resolution @x84 (unit-resolution @x165 @x153 $x104) $x94) false))))))))))))))))))))))))))))))))))))))))))))))))))))))))))\n\n";

/// Одна точечная подделка вывода.
pub const Tamper = struct { needle: []const u8, repl: []const u8, occ: usize };

pub const TAMPERS = [_]Tamper{
    .{ .needle = "(<= ", .repl = "(< ", .occ = 0 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 1 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 2 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 3 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 4 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 5 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 6 },
    .{ .needle = "(<= ", .repl = "(< ", .occ = 7 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 0 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 1 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 2 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 3 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 4 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 5 },
    .{ .needle = "(>= ", .repl = "(> ", .occ = 6 },
    .{ .needle = "(+ ", .repl = "(- ", .occ = 0 },
    .{ .needle = "(+ ", .repl = "(- ", .occ = 1 },
    .{ .needle = "(+ ", .repl = "(- ", .occ = 2 },
    .{ .needle = "(+ ", .repl = "(- ", .occ = 3 },
    .{ .needle = "(* ", .repl = "(+ ", .occ = 0 },
    .{ .needle = "(* ", .repl = "(+ ", .occ = 1 },
    .{ .needle = "(* ", .repl = "(+ ", .occ = 2 },
    .{ .needle = "(* ", .repl = "(+ ", .occ = 3 },
    .{ .needle = "(- 1)", .repl = "(- 2)", .occ = 0 },
    .{ .needle = "(- 1)", .repl = "(- 2)", .occ = 1 },
    .{ .needle = "(- 1)", .repl = "(- 2)", .occ = 2 },
    .{ .needle = "(- 1)", .repl = "(- 2)", .occ = 3 },
    .{ .needle = "(or ", .repl = "(and ", .occ = 0 },
    .{ .needle = "(or ", .repl = "(and ", .occ = 1 },
    .{ .needle = "(or ", .repl = "(and ", .occ = 2 },
};
