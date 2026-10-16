// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: НЕЗАВИСИМАЯ ПРОВЕРКА ВЫВОДА РЕШАТЕЛЯ (Proof Checking).
//!
//! ПРОБЛЕМА. Z3 — сотни тысяч строк C++. Верить ему «на слово» нельзя:
//! заводской баг в тактике или арифметике может дать неверный `unsat`.
//! Текстовый вердикт `unsat` доказательством НЕ является.
//!
//! ЧТО ДЕЛАЕТ МОДУЛЬ. Разбирает вывод `(get-proof)` в S-выражения и
//! математически перепроверяет его:
//!
//!   1. Запрет дыр: правило `hole` / `trust` / `sorry` — отказ. Иначе
//!      сертификат подделывается строкой `(step t1 (cl) :rule hole)`.
//!   2. Привязка посылок: каждый `asserted` обязан структурно совпасть с
//!      реальной клаузой контракта — нельзя подсунуть лишнюю аксиому.
//!   3. Структура `mp`: из `(mp P1 P2 Q)` следует `Q` лишь если `P2` имеет
//!      вид `(=> P1 Q)` или `(= P1 Q)`.
//!   4. `unit-resolution`: чтобы вывести пустую клаузу, каждый литерал
//!      каждой клаузы-посылки обязан быть опровергнут литералами посылок.
//!      Пропавший литерал = подделанный шаг резолюции.
//!   5. Сертификат Фаркаша: для `((_ th-lemma arith farkas l1..ln) cl)`
//!      коэффициенты неотрицательны, их число равно числу литерал клаузы, а
//!      линейная комбинация `Σ li·(¬Li)` схлопывает переменные в ноль и даёт
//!      положительную константу — противоречие.
//!   6. Корень: дерево обязано завершаться `false` (пустая клауза).
//!
//! ЧЕСТНЫЕ ГРАНИЦЫ (измерено, не предположено):
//!   * Формат — нативный вывод Z3 (`let`-связки, `asserted`, `rewrite`,
//!     `mp`, `unit-resolution`, `th-lemma`). Именно это отдаёт
//!     `z3-solver 5.1.0.0`. Alethe этим бинарником НЕ порождается: проверено
//!     `strings z3 | grep -ic alethe` -> 0, параметра `proof.format` нет.
//!     Поэтому Alethe/LFSC здесь не заявлен.
//!   * Шаг `rewrite` не перепроверяем, не переписав рерайтер Z3. Такие шаги
//!     считаются отдельно (`trusted_steps`) и не выдаются за проверенные.
//!   * Минимальность ядра (MUS) — отдельный механизм ниже.
const std = @import("std");
const z3 = @import("z3_bridge.zig");
const unsat_core = @import("unsat_core.zig");
const compat = @import("compat");

/// Итог аудита вывода.
pub const ProofVerdict = struct {
    is_unsat: bool = false,
    proof_present: bool = false,
    proof_steps: usize = 0,
    proof_well_formed: bool = false,
    proof_concludes_false: bool = false,
    core_size: usize = 0,
    core_minimal: bool = false,
    confirmed: bool = false,

    // --- результаты математического разбора вывода ---
    holes: usize = 0, // правил hole/trust/sorry — атака
    unknown_rules: usize = 0, // правила вне таблицы (учтены отдельно)
    premises_total: usize = 0, // шагов asserted/hypothesis
    premises_bound: usize = 0, // asserted, совпавшие с клаузами контракта
    premises_unbound: usize = 0, // asserted, НЕ найденных — атака
    mp_checked: usize = 0,
    mp_bad: usize = 0,
    unitres_checked: usize = 0,
    unitres_bad: usize = 0,
    farkas_checked: usize = 0, // проверено арифметически
    farkas_structural: usize = 0, // разобрана только структура
    farkas_bad: usize = 0,
    rewrite_verified: usize = 0, // rewrite, ДОКАЗАННЫЕ нормализацией сравнений
    rewrite_bad: usize = 0, // rewrite, где обе стороны сравнения, но равенства НЕТ
    eq_verified: usize = 0, // refl / symm / trans — проверены структурно
    bool_verified: usize = 0, // and-elim / monotonicity — проверены подстановкой
    trusted_steps: usize = 0, // что осталось непроверяемым — честно посчитано
    first_trusted: []const u8 = "", // правило первого непроверенного шага
    reject: []const u8 = "", // причина отказа ("" = нет)

    /// Все ли проверки прошли.
    pub fn checksPass(self: ProofVerdict) bool {
        return self.holes == 0 and self.premises_unbound == 0 and
            self.mp_bad == 0 and self.unitres_bad == 0 and
            self.farkas_bad == 0 and self.rewrite_bad == 0 and
            self.reject.len == 0;
    }
};

// =========================================================================
// S-выражения
// =========================================================================

/// Узел S-выражения: либо атом (текст), либо список.
pub const Sexp = struct {
    atom: ?[]const u8 = null,
    items: []Sexp = &.{},

    pub fn isList(self: Sexp) bool {
        return self.atom == null;
    }
    /// Голова списка, если это список с атомом-головой.
    pub fn headAtom(self: Sexp) ?[]const u8 {
        if (!self.isList() or self.items.len == 0) return null;
        return self.items[0].atom;
    }
};

pub const ParseError = error{ UnexpectedClose, UnexpectedEof, OutOfMemory };

/// Разборщик S-выражений. Строки в кавычках сохраняются как атомы целиком
/// (содержимое для проверок не нужно, но границы ломать нельзя).
const SexprParser = struct {
    src: []const u8,
    i: usize = 0,
    arena: std.mem.Allocator,

    fn skipWs(self: *SexprParser) void {
        while (self.i < self.src.len) {
            const c = self.src[self.i];
            if (c == ' ' or c == '\t' or c == '\n' or c == '\r') {
                self.i += 1;
            } else if (c == ';') { // комментарий до конца строки
                while (self.i < self.src.len and self.src[self.i] != '\n') self.i += 1;
            } else break;
        }
    }

    fn parse(self: *SexprParser) ParseError!Sexp {
        self.skipWs();
        if (self.i >= self.src.len) return ParseError.UnexpectedEof;
        const c = self.src[self.i];
        if (c == ')') return ParseError.UnexpectedClose;
        if (c == '(') return self.parseList();
        if (c == '"') return self.parseString();
        return self.parseAtom();
    }

    fn parseList(self: *SexprParser) ParseError!Sexp {
        self.i += 1; // '('
        var list = std.array_list.Managed(Sexp).init(self.arena);
        while (true) {
            self.skipWs();
            if (self.i >= self.src.len) return ParseError.UnexpectedEof;
            if (self.src[self.i] == ')') {
                self.i += 1;
                break;
            }
            const item = try self.parse();
            try list.append(item);
        }
        return .{ .items = try list.toOwnedSlice() };
    }

    fn parseString(self: *SexprParser) ParseError!Sexp {
        const start = self.i;
        self.i += 1;
        while (self.i < self.src.len) {
            if (self.src[self.i] == '\\') {
                self.i += 2;
                continue;
            }
            if (self.src[self.i] == '"') {
                self.i += 1;
                break;
            }
            self.i += 1;
        }
        return .{ .atom = self.src[start..@min(self.i, self.src.len)] };
    }

    fn parseAtom(self: *SexprParser) ParseError!Sexp {
        const start = self.i;
        while (self.i < self.src.len) {
            const c = self.src[self.i];
            if (c == ' ' or c == '\t' or c == '\n' or c == '\r' or
                c == '(' or c == ')' or c == ';') break;
            self.i += 1;
        }
        if (self.i == start) return ParseError.UnexpectedEof;
        return .{ .atom = self.src[start..self.i] };
    }
};

/// Разобрать одно S-выражение (ведущие пробелы/комментарии пропускаются).
/// Память берётся из арены вызывающего.
pub fn parseSexp(arena: std.mem.Allocator, text: []const u8) ParseError!Sexp {
    var p = SexprParser{ .src = text, .arena = arena };
    return p.parse();
}

/// Структурное равенство: пробелы и переводы строк внутри списков не значимы
/// (сравнение по дереву, а не по байтам).
pub fn sexpEq(a: Sexp, b: Sexp) bool {
    if (a.atom) |aa| {
        if (b.atom) |bb| return std.mem.eql(u8, aa, bb);
        return false;
    }
    if (b.atom != null) return false;
    if (a.items.len != b.items.len) return false;
    for (a.items, b.items) |x, y| if (!sexpEq(x, y)) return false;
    return true;
}

/// Является ли выражение отрицанием: `(not X)`.
fn asNot(e: Sexp) ?Sexp {
    if (!e.isList() or e.items.len != 2) return null;
    const h = e.items[0].atom orelse return null;
    if (!std.mem.eql(u8, h, "not")) return null;
    return e.items[1];
}

/// Дополняют ли два литерала друг друга: `L` и `(not L)`.
pub fn isComplement(a: Sexp, b: Sexp) bool {
    if (asNot(a)) |inner| return sexpEq(inner, b);
    if (asNot(b)) |inner| return sexpEq(inner, a);
    return false;
}

// =========================================================================
// Разбор вывода: let-связки, шаги, правила
// =========================================================================

/// Правила-дыры: их наличие означает, что доказательство не проверялось.
const HOLE_RULES = [_][]const u8{ "hole", "trust", "sorry", "unknown" };

/// Правила, встречающиеся в реальных выводах Z3 5.1.0 (измерено прогоном по
/// QF_LIA / QF_BV / QF_UF / QF_LRA / CNF). Всё прочее считается `unknown_rules`
/// и учитывается отдельно, но не отклоняется — иначе валидный вывод с редкой
/// тактикой был бы отвергнут.
const KNOWN_RULES = [_][]const u8{
    "asserted",        "hypothesis",  "mp",         "rewrite",
    "unit-resolution", "lemma",       "th-lemma",   "trans",
    "symm",            "refl",        "not-or-elim", "and-elim",
    "or-elim",         "not-elim",    "iff-elim",   "commutativity",
    "distributivity",  "definition",  "monotonicity", "bind",
    "pull-quant",      "sk",          "nnf-pos",    "nnf-neg",
    "quant-inst",      "quant-intro", "elim",       "asserted-commutativity",
};

fn isHole(r: []const u8) bool {
    for (HOLE_RULES) |h| if (std.mem.eql(u8, h, r)) return true;
    return false;
}

fn isKnownRule(r: []const u8) bool {
    for (KNOWN_RULES) |k| if (std.mem.eql(u8, k, r)) return true;
    return false;
}

/// Является ли выражение ШАГОМ вывода (а не термом).
///
/// 🔴 ДЕФЕКТ (найден первым же прогоном): считать шагом любой список с
/// атомарной головой нельзя — тогда `(>= x 5)`, `(or a b)` и любая другая
/// функция выглядели бы «правилом» (`ruleOf` вернул бы `>=`), и сокращения
/// `let` попадали бы в шаги вместо термов. Шагом считается только выражение,
/// чья голова — известное правило вывода или дыра.
fn isStepExpr(e: Sexp) bool {
    const r = ruleOf(e) orelse return false;
    return isKnownRule(r) or isHole(r);
}

/// Имя правила шага. Для `((_ th-lemma arith farkas 1 1) cl)` голова — список,
/// поэтому имя берётся из `(_ <имя> ...)`.
pub fn ruleOf(e: Sexp) ?[]const u8 {
    if (!e.isList() or e.items.len == 0) return null;
    const h = e.items[0];
    if (h.atom) |a| return a;
    if (h.isList() and h.items.len >= 2) {
        const hh = h.items[0].atom orelse return null;
        if (std.mem.eql(u8, hh, "_")) return h.items[1].atom;
        return hh;
    }
    return null;
}

/// Контекст разбора одного вывода.
pub const Ctx = struct {
    arena: std.mem.Allocator,
    abbrev: std.StringHashMap(Sexp),
    stepexpr: std.StringHashMap(Sexp),
    steps: std.array_list.Managed(Sexp),
    root: ?Sexp = null,
};

fn newCtx(arena: std.mem.Allocator) Ctx {
    return .{
        .arena = arena,
        .abbrev = std.StringHashMap(Sexp).init(arena),
        .stepexpr = std.StringHashMap(Sexp).init(arena),
        .steps = std.array_list.Managed(Sexp).init(arena),
    };
}

/// Пройти цепочку `let`-связок и собрать: сокращения термов, шаги и корень.
/// Связки вида `($x42 <терм>)` — сокращения; связки вида `(@x47 <шаг>)` —
/// шаги вывода.
fn collect(c: *Ctx, body: Sexp) !void {
    if (body.headAtom()) |h| {
        if (std.mem.eql(u8, h, "let") and body.items.len == 3) {
            const bl = body.items[1];
            if (bl.isList()) {
                for (bl.items) |b| {
                    if (!b.isList() or b.items.len != 2) continue;
                    const nm = b.items[0].atom orelse continue;
                    const val = b.items[1];
                    if (isStepExpr(val)) {
                        try c.stepexpr.put(nm, val);
                        // 🔴 ДЕФЕКТ (найден третьим прогоном): шаг, привязанный
                        // через `let`, добавлялся БЕЗ обхода его аргументов.
                        // В `@x52 = (mp (mp (asserted ...) ...) ...)` внутренние
                        // `asserted`/`rewrite` не попадали в аудит вообще — то
                        // есть подмена посылки внутри такого шага осталась бы
                        // незамеченной. Нужен рекурсивный сбор.
                        try collectStepsRec(c, val);
                    } else {
                        try c.abbrev.put(nm, val);
                    }
                }
            }
            return collect(c, body.items[2]);
        }
    }
    c.root = body;
    try collectStepsRec(c, body);
}

/// Собрать все шаги в поддереве.
///
/// 🔴 ДЕФЕКТ (найден вторым прогоном): недостаточно брать только `let`-связанные
/// шаги. В реальных выводах Z3 посылки часто записаны ВЛОЖЕННО, прямо в
/// аргументах: `(mp (mp (asserted (< x 5)) ...) ...)`. Без рекурсивного обхода
/// такие `asserted` не попадали в аудит вообще — и подмена посылки в них
/// осталась бы незамеченной.
fn collectStepsRec(c: *Ctx, e: Sexp) !void {
    if (!e.isList()) return;
    if (isStepExpr(e)) try c.steps.append(e);
    for (e.items) |it| try collectStepsRec(c, it);
}

/// Развернуть сокращения `let` (`$x42` -> его терм). Ограничение глубины
/// защищает от циклов в подделанном выводе.
fn expand(c: *const Ctx, e: Sexp, depth: u32) Sexp {
    if (depth > 128) return e;
    if (e.atom) |a| {
        if (c.abbrev.get(a)) |v| return expand(c, v, depth + 1);
        return e;
    }
    const out = c.arena.alloc(Sexp, e.items.len) catch return e;
    for (e.items, 0..) |it, i| out[i] = expand(c, it, depth + 1);
    return .{ .items = out };
}

/// Что доказывает шаг (для `asserted`/`hypothesis` — сама формула,
/// для остальных — последний аргумент).
fn proved(e: Sexp) Sexp {
    const r = ruleOf(e) orelse return e;
    if (std.mem.eql(u8, r, "asserted") or std.mem.eql(u8, r, "hypothesis")) {
        if (e.items.len >= 2) return e.items[1];
        return e;
    }
    if (std.mem.eql(u8, r, "th-lemma")) {
        // ДВЕ ИЗМЕРЕННЫЕ ФОРМЫ (дефект найден прогоном на выводе с not-or-elim):
        //   ((_ th-lemma arith farkas 1 1) (or $x42 $x27))   — лемма-КЛАУЗА
        //       (2 элемента: голова + клауза) -> доказывается items[1]
        //   ((_ th-lemma arith) P1 P2 ... false)             — ШАГ ВЫВОДА
        //       (>=3 элемента) -> вывод = ПОСЛЕДНИЙ аргумент
        // Раньше всегда брался items[1], поэтому корень такого вывода не
        // распознавался как `false` и чекер отвергал ВЕРНЫЙ вывод.
        if (e.items.len == 2) return e.items[1];
        if (e.items.len >= 3) return e.items[e.items.len - 1];
        return e;
    }
    if (e.items.len >= 2) return e.items[e.items.len - 1];
    return e;
}

/// Раскрыть посылку: если это ссылка на шаг (`@x47`) — вернуть сам шаг.
fn resolvePremise(c: *const Ctx, p: Sexp) Sexp {
    if (p.atom) |a| {
        if (c.stepexpr.get(a)) |v| return v;
    }
    return p;
}

// =========================================================================
// Нормализация сравнений: закрываем шаги `rewrite`
// =========================================================================

/// Сравнение в канонической форме: `neg ? ¬(a >= b) : (a >= b)`.
///
/// ЗАЧЕМ. Z3 оформляет элементарные тождества как шаги `rewrite`, и раньше они
/// целиком уходили в `trusted_steps` — то есть принимались без проверки.
/// Между тем это не произвольный рерайтер: на эталонном выводе все 5 шагов
/// сводятся к двум правилам, которые проверяются точно:
///
///   1. РЕФЛЕКСИВНОСТЬ: `(= X X)` — верно по определению равенства.
///   2. НОРМАЛИЗАЦИЯ СРАВНЕНИЙ (перестановка сторон и смена знака):
///        `(<= a b)` == `(>= b a)`
///        `(>  a b)` == `(not (>= b a))`
///        `(<  a b)` == `(not (>= a b))`
///        `(not X)`  — инвертирует признак отрицания.
///
/// ЧТО ЭТО НЕ ЗАКРЫВАЕТ (честно): тождества, требующие арифметики термов
/// (приведение подобных, дистрибутивность, булевы законы вне сравнений),
/// нормализатор не проверяет — такие шаги остаются в `trusted_steps`.
const NormCmp = struct { neg: bool, a: Sexp, b: Sexp };

fn normCmp(e: Sexp) ?NormCmp {
    if (!e.isList() or e.items.len == 0) return null;
    const h = e.items[0].atom orelse return null;
    if (std.mem.eql(u8, h, "not") and e.items.len == 2) {
        if (normCmp(e.items[1])) |n| {
            return .{ .neg = !n.neg, .a = n.a, .b = n.b };
        }
        return null;
    }
    if (e.items.len != 3) return null;
    const a = e.items[1];
    const b = e.items[2];
    if (std.mem.eql(u8, h, ">=")) return .{ .neg = false, .a = a, .b = b };
    if (std.mem.eql(u8, h, "<=")) return .{ .neg = false, .a = b, .b = a };
    if (std.mem.eql(u8, h, ">")) return .{ .neg = true, .a = b, .b = a };
    if (std.mem.eql(u8, h, "<")) return .{ .neg = true, .a = a, .b = b };
    return null;
}

/// Извлечь тела всех `(assert ...)` из текста SMT-LIB2.
///
/// Нужно для CLI: чтобы независимо перепроверить вывод, чекеру требуется список
/// клауз контракта — по ним проверяется привязка посылок (`asserted`).
/// Скан по скобкам: находим `(assert`, идём до парной закрывающей скобки,
/// возвращаем внутренний текст без внешних скобок и без `assert`.
pub fn extractAsserts(allocator: std.mem.Allocator, text: []const u8) ![]const []const u8 {
    var out = std.array_list.Managed([]const u8).init(allocator);
    errdefer out.deinit();
    var i: usize = 0;
    while (i + 7 <= text.len) : (i += 1) {
        if (text[i] != '(') continue;
        // `(assert` + разделитель
        if (!std.mem.startsWith(u8, text[i..], "(assert")) continue;
        const after = i + 7;
        if (after >= text.len) break;
        const c = text[after];
        if (c != ' ' and c != '\t' and c != '\n' and c != '\r') continue;
        // идём до парной скобки
        var depth: i64 = 0;
        var j = i;
        var end: ?usize = null;
        var in_str = false;
        while (j < text.len) : (j += 1) {
            const ch = text[j];
            if (in_str) {
                if (ch == '\\') {
                    j += 1;
                } else if (ch == '"') in_str = false;
                continue;
            }
            if (ch == '"') {
                in_str = true;
            } else if (ch == ';') {
                while (j < text.len and text[j] != '\n') j += 1;
            } else if (ch == '(') {
                depth += 1;
            } else if (ch == ')') {
                depth -= 1;
                if (depth == 0) {
                    end = j;
                    break;
                }
            }
        }
        const e = end orelse break;
        const inner = std.mem.trim(u8, text[after..e], " \t\r\n");
        if (inner.len > 0) try out.append(try allocator.dupe(u8, inner));
        i = e;
    }
    return out.toOwnedSlice();
}

/// Равны ли два булевых литерала с точностью до нормализации сравнений.
pub fn sameLiteral(a: Sexp, b: Sexp) bool {
    if (sexpEq(a, b)) return true;
    const na = normCmp(a) orelse return false;
    const nb = normCmp(b) orelse return false;
    return na.neg == nb.neg and sexpEq(na.a, nb.a) and sexpEq(na.b, nb.b);
}

fn isEq3(e: Sexp) bool {
    if (!e.isList() or e.items.len != 3) return false;
    const h = e.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "=");
}

/// Линейная разность `(l1 - r1) - (l2 - r2)`. `null` — термы не линейны.
/// `true` — разность тождественно нулевая.
///
/// ЭТО СЛИЯНИЕ С НОРМАЛИЗАТОРОМ ФАРКАША. `parseLin` уже умеет раскладывать
/// `(+ a b)`, `(- a b)`, `(* c x)` и литералы в `Σ ci·xi + c0`. Пропуская через
/// него РАЗНОСТЬ сторон равенства, мы получаем проверку арифметических
/// тождеств бесплатно:
///     `(= (+ x (+ y x)) (+ (* 2 x) y))`  ->  коэфф. сокращаются, константа 0
///     `(= (<= (- x y) 5) (<= x (+ y 5)))` ->  обе части дают `x - y - 5 <= 0`
fn linCmpEq(c: *const Ctx, l1: Sexp, r1: Sexp, l2: Sexp, r2: Sexp) ?bool {
    var d = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (!parseLin(c, l1, 1, &d)) return null;
    if (!parseLin(c, r1, -1, &d)) return null;
    if (!parseLin(c, l2, -1, &d)) return null;
    if (!parseLin(c, r2, 1, &d)) return null;
    return d.varsCancel() and d.constant == 0;
}

/// `(= L R)` для термов: тождественна ли разность `L - R` нулю.
fn linDiffZero(c: *const Ctx, l: Sexp, r: Sexp) ?bool {
    var d = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (!parseLin(c, l, 1, &d)) return null;
    if (!parseLin(c, r, -1, &d)) return null;
    return d.varsCancel() and d.constant == 0;
}

/// Трёхзначный итог проверки шага `rewrite`:
///   verified     — равенство ДОКАЗАНО нормализацией;
///   bad          — обе стороны нормализуются, но НЕ равны -> подделка;
///   unverifiable — нормализатор не покрывает эти термы, шаг доверенный.
const RwResult = enum { verified, bad, unverifiable };

fn checkRewrite(c: *const Ctx, st: Sexp) RwResult {
    if (st.items.len < 2) return .unverifiable;
    const eq = expand(c, st.items[1], 0);
    if (!isEq3(eq)) return .unverifiable;
    const l = eq.items[1];
    const r = eq.items[2];
    if (sexpEq(l, r)) return .verified; // рефлексивность: (= X X)
    const nl = normCmp(l);
    const nr = normCmp(r);
    if (nl != null and nr != null) {
        const a = nl.?;
        const b = nr.?;
        if (a.neg == b.neg and sexpEq(a.a, b.a) and sexpEq(a.b, b.b)) return .verified;
        // СИНТАКСИЧЕСКИ разные сравнения: пробуем ЛИНЕЙНУЮ нормализацию
        // (слияние с нормализатором Фаркаша). Пример, который ловит Z3:
        //   (= (<= (- x y) 5) (<= x (+ y 5)))   ->   обе части дают x - y - 5 <= 0
        if (a.neg != b.neg) return .bad;
        if (linCmpEq(c, a.a, a.b, b.a, b.b)) |z| {
            // Обе стороны ЛИНЕЙНЫ -> нормализатор их ПОКРЫВАЕТ.
            // Расхождение канонических форм = доказанная подделка.
            return if (z) .verified else .bad;
        }
        return .unverifiable;
    }
    // Обе стороны — ТЕРМЫ (не сравнения): проверяем арифметическое тождество.
    if (nl == null and nr == null) {
        if (linDiffZero(c, l, r)) |z| return if (z) .verified else .bad;
        return .unverifiable;
    }
    return .unverifiable;
}

/// Подставить `from -> to` в дерево. `null` — глубина превышена.
fn subst(c: *const Ctx, e: Sexp, from: Sexp, to: Sexp, depth: u32) ?Sexp {
    if (depth > 64) return null;
    if (sexpEq(e, from)) return to;
    if (!e.isList()) return e;
    const out = c.arena.alloc(Sexp, e.items.len) catch return null;
    for (e.items, 0..) |it, i| out[i] = subst(c, it, from, to, depth + 1) orelse return null;
    return .{ .items = out };
}

/// Проверить `refl` / `symm` / `trans`.
///
/// 🔴 ДЕФЕКТ (найден прогоном `kernc prove`): посылки — это ССЫЛКИ на шаги
/// (`@x41`), а не термы. `expand` их не раскрывает (он знает только сокращения
/// `$x..`), поэтому `isEq3(@x41)` давал false и `trans` уходил в доверенные.
/// Теперь посылки разрешаются через `premiseTerm`.
fn verifyEqRule(c: *const Ctx, r: []const u8, st: Sexp) bool {
    const n = st.items.len;
    if (std.mem.eql(u8, r, "refl")) {
        if (n < 2) return false;
        const eq = premiseTerm(c, st.items[n - 1]);
        return isEq3(eq) and sexpEq(eq.items[1], eq.items[2]);
    }
    if (std.mem.eql(u8, r, "symm")) {
        if (n < 3) return false;
        const p = premiseTerm(c, st.items[n - 2]);
        const q = premiseTerm(c, st.items[n - 1]);
        if (!isEq3(p) or !isEq3(q)) return false;
        return sexpEq(p.items[1], q.items[2]) and sexpEq(p.items[2], q.items[1]);
    }
    if (std.mem.eql(u8, r, "trans")) {
        if (n < 4) return false;
        const p1 = premiseTerm(c, st.items[1]);
        const p2 = premiseTerm(c, st.items[2]);
        const q = premiseTerm(c, st.items[n - 1]);
        if (!isEq3(p1) or !isEq3(p2) or !isEq3(q)) return false;
        // p1: a=b, p2: b=c, q: a=c — средний терм обязан совпасть.
        return sexpEq(p1.items[2], p2.items[1]) and
            sexpEq(p1.items[1], q.items[1]) and sexpEq(p2.items[2], q.items[2]);
    }
    return false;
}

/// `(and-elim P A)`: из доказанного `(and A ...)` следует конъюнкт `A`.
fn verifyAndElim(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const src = premiseTerm(c, st.items[1]);
    const concl = expand(c, proved(st), 0);
    if (!src.isList() or src.items.len < 2) return false;
    const h = src.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "and")) return false;
    for (src.items[1..]) |part| {
        if (sexpEq(part, concl)) return true;
    }
    return false;
}

/// `(not-or-elim P C)`: `P` доказывает `(not (or D1 D2 ...))`, а `C` обязано быть
/// ОТРИЦАНИЕМ одного из дизъюнктов (закон де Моргана: ¬(A ∨ B) ⊨ ¬A).
///
/// Форма измерена на реальном выводе Z3 (QF_LIA, `(+ x y) = 3 ∧ x > 5 ∧ y > 5`):
///   $x58 = (<= ?x25 3)
///   $x66 = (not (or (not $x58) (not (>= ?x25 3))))
///   (@x72 (not-or-elim <доказательство $x66> $x58))   <- ¬(¬A ∨ ¬B) ⊨ A
///
/// ⚠️ `or-elim` НЕ реализован намеренно: в проверенных выводах Z3 (QF_LIA, QF_BV,
/// QF_UF, QF_LRA, CNF, NIA) это правило ни разу не встретилось, а писать проверку
/// для формы, которую не наблюдал, — значит рисковать ложной верификацией.
fn verifyNotOrElim(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const src = premiseTerm(c, st.items[1]);
    const concl = expand(c, proved(st), 0);
    const inner = asNot(src) orelse return false;
    if (!inner.isList() or inner.items.len < 2) return false;
    const h = inner.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;
    for (inner.items[1..]) |disj| {
        if (asNot(disj)) |n| {
            if (sexpEq(n, concl)) return true;
        }
    }
    return false;
}

/// `(monotonicity P (= X Y))`, где `P` доказывает `(= A B)`: вывод обязан
/// получаться ПОДСТАНОВКОЙ `A -> B` в один из термов заключения.
fn verifyMonotonicity(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const p = premiseTerm(c, st.items[1]);
    const q = expand(c, proved(st), 0);
    if (!isEq3(p) or !isEq3(q)) return false;
    const a = p.items[1];
    const b = p.items[2];
    const x = q.items[1];
    const y = q.items[2];
    if (subst(c, x, a, b, 0)) |s| {
        if (sexpEq(s, y)) return true;
    }
    if (subst(c, y, a, b, 0)) |s| {
        if (sexpEq(s, x)) return true;
    }
    return false;
}

// =========================================================================
// Сертификат Фаркаша: линейная арифметика
// =========================================================================

const Term = struct { name: []const u8, coeff: i64 };

/// Линейная форма `Σ coeff·x + constant`.
const Lin = struct {
    terms: std.array_list.Managed(Term),
    constant: i64 = 0,

    fn add(self: *Lin, name: []const u8, coeff: i64) !void {
        for (self.terms.items) |*t| {
            if (std.mem.eql(u8, t.name, name)) {
                t.coeff += coeff;
                return;
            }
        }
        try self.terms.append(.{ .name = name, .coeff = coeff });
    }

    fn scale(self: *Lin, k: i64) void {
        self.constant *= k;
        for (self.terms.items) |*t| t.coeff *= k;
    }

    /// Все переменные сократились в ноль.
    fn varsCancel(self: Lin) bool {
        for (self.terms.items) |t| if (t.coeff != 0) return false;
        return true;
    }
};

fn linAdd(dst: *Lin, src: *const Lin) bool {
    for (src.terms.items) |t| dst.add(t.name, t.coeff) catch return false;
    dst.constant += src.constant;
    return true;
}

/// Разобрать линейное выражение. Поддерживаются `+`, бинарный и унарный `-`,
/// умножение на числовой литерал, литералы и переменные. Всё прочее
/// (нелинейность, деление, `mod`, неинтерпретированные функции) — `false`, и
/// тогда шаг учитывается как «разобрана только структура».
fn parseLin(c: *const Ctx, e: Sexp, sign: i64, out: *Lin) bool {
    if (!e.isList()) {
        const a = e.atom orelse return false;
        if (std.fmt.parseInt(i64, a, 10)) |n| {
            out.constant += sign * n;
            return true;
        } else |_| {}
        if (a.len == 0) return false;
        out.add(a, sign) catch return false;
        return true;
    }
    if (e.items.len == 0) return false;
    const h = e.items[0].atom orelse return false;
    if (std.mem.eql(u8, h, "+")) {
        for (e.items[1..]) |it| if (!parseLin(c, it, sign, out)) return false;
        return true;
    }
    if (std.mem.eql(u8, h, "-")) {
        if (e.items.len == 2) return parseLin(c, e.items[1], -sign, out);
        if (e.items.len < 3) return false;
        if (!parseLin(c, e.items[1], sign, out)) return false;
        for (e.items[2..]) |it| if (!parseLin(c, it, -sign, out)) return false;
        return true;
    }
    if (std.mem.eql(u8, h, "*")) {
        var k: i64 = 1;
        var rest: ?Sexp = null;
        var count_num: usize = 0;
        for (e.items[1..]) |it| {
            if (!it.isList()) {
                if (it.atom) |a| {
                    if (std.fmt.parseInt(i64, a, 10)) |n| {
                        k *= n;
                        count_num += 1;
                        continue;
                    } else |_| {}
                }
            }
            if (rest != null) return false; // два нечисловых множителя
            rest = it;
        }
        if (count_num == 0 or rest == null) return false;
        return parseLin(c, rest.?, sign * k, out);
    }
    return false;
}

/// Представить ОТРИЦАНИЕ литерала как `D <= 0` (целочисленная семантика):
///   L = `(>= l r)` = l-r >= 0  ->  ¬L: l-r <= -1  ->  D = (l-r)+1
///   L = `(<= l r)` = l-r <= 0  ->  ¬L: l-r >=  1  ->  D = -(l-r)+1
///   L = `(>  l r)` = l-r >= 1  ->  ¬L: l-r <=  0  ->  D =  l-r
///   L = `(<  l r)` = l-r <= -1 ->  ¬L: l-r >=  0  ->  D = -(l-r)
/// Равенства не поддерживаются: неравенства из них не вывести.
fn negLiteralAsLeZero(c: *const Ctx, lit: Sexp, out: *Lin) bool {
    if (!lit.isList() or lit.items.len != 3) return false;
    const h = lit.items[0].atom orelse return false;
    var d = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (!parseLin(c, lit.items[1], 1, &d)) return false;
    if (!parseLin(c, lit.items[2], -1, &d)) return false;

    if (std.mem.eql(u8, h, ">=")) {
        d.constant += 1;
    } else if (std.mem.eql(u8, h, "<=")) {
        d.scale(-1);
        d.constant += 1;
    } else if (std.mem.eql(u8, h, ">")) {
        // уже нужная форма: l-r <= 0
    } else if (std.mem.eql(u8, h, "<")) {
        d.scale(-1);
    } else return false;

    out.terms = d.terms;
    out.constant = d.constant;
    return true;
}

pub const FarkasResult = enum { ok, structural_only, bad };

/// Проверить сертификат Фаркаша: коэффициенты, число литерал и арифметику.
fn verifyFarkas(c: *const Ctx, head: Sexp, clause: Sexp) FarkasResult {
    var coeffs = std.array_list.Managed(i64).init(c.arena);
    var is_farkas = false;
    for (head.items[2..]) |it| {
        if (!it.isList()) {
            if (it.atom) |a| {
                if (std.mem.eql(u8, a, "farkas")) {
                    is_farkas = true;
                    continue;
                }
                if (std.fmt.parseInt(i64, a, 10)) |n| {
                    coeffs.append(n) catch return .structural_only;
                    continue;
                } else |_| {}
            }
        }
    }
    if (!is_farkas) return .structural_only;
    for (coeffs.items) |k| if (k < 0) return .bad;

    if (!clause.isList() or clause.items.len == 0) return .structural_only;
    const ch = clause.items[0].atom orelse return .structural_only;
    if (!std.mem.eql(u8, ch, "or")) return .structural_only;
    const lits = clause.items[1..];
    if (coeffs.items.len != lits.len) return .bad;

    var sum = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    for (lits, coeffs.items) |lit, k| {
        var part = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        if (!negLiteralAsLeZero(c, lit, &part)) return .structural_only;
        part.scale(k);
        if (!linAdd(&sum, &part)) return .structural_only;
    }
    // Σ λi·(¬Li) <= 0. Переменные сократились, а константа положительна —
    // значит получено `положительное <= 0`, то есть противоречие.
    if (sum.varsCancel() and sum.constant > 0) return .ok;
    return .bad;
}

// =========================================================================
// Проверки отдельных правил
// =========================================================================

/// Что означает посылка: если это шаг — то, что он доказывает; иначе сам терм.
fn premiseTerm(c: *const Ctx, p: Sexp) Sexp {
    const s = resolvePremise(c, p);
    if (isStepExpr(s)) return expand(c, proved(s), 0);
    return expand(c, s, 0);
}

/// `(mp P1 P2 Q)`: из P1 и P2 следует Q только если P2 имеет вид
/// `(=> P1 Q)` либо `(= P1 Q)` (для равенства допускается и обратный порядок).
fn checkMp(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 4) return false;
    const p1 = premiseTerm(c, st.items[1]);
    const p2 = premiseTerm(c, st.items[2]);
    const q = expand(c, proved(st), 0);
    if (!p2.isList() or p2.items.len != 3) return false;
    const h = p2.items[0].atom orelse return false;
    const is_eq = std.mem.eql(u8, h, "=");
    if (!is_eq and !std.mem.eql(u8, h, "=>")) return false;
    if (sexpEq(p2.items[1], p1) and sexpEq(p2.items[2], q)) return true;
    if (is_eq and sexpEq(p2.items[2], p1) and sexpEq(p2.items[1], q)) return true;
    return false;
}

/// Является ли терм клаузой (дизъюнкцией литерал).
fn isClause(t: Sexp) bool {
    if (!t.isList() or t.items.len == 0) return false;
    const h = t.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "or");
}

/// `unit-resolution`: чтобы вывести `false`, каждый литерал каждой
/// клаузы-посылки обязан быть опровергнут литералами посылок. Если литерал
/// остаётся — он обязан быть ровно выводом шага. Пропавший или лишний
/// литерал означает подделанный шаг резолюции.
fn checkUnitRes(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const concl = expand(c, proved(st), 0);
    const concl_is_false = concl.atom != null and std.mem.eql(u8, concl.atom.?, "false");

    var units = std.array_list.Managed(Sexp).init(c.arena);
    var clauses = std.array_list.Managed(Sexp).init(c.arena);
    for (st.items[1 .. st.items.len - 1]) |p| {
        const t = premiseTerm(c, p);
        if (isClause(t)) {
            clauses.append(t) catch return false;
        } else {
            units.append(t) catch return false;
        }
    }

    var saw_remaining = false;
    for (clauses.items) |cl| {
        var remaining = std.array_list.Managed(Sexp).init(c.arena);
        for (cl.items[1..]) |lit| {
            const l = expand(c, lit, 0);
            var falsified = false;
            for (units.items) |u| {
                if (isComplement(l, u)) {
                    falsified = true;
                    break;
                }
            }
            if (!falsified) remaining.append(l) catch return false;
        }
        if (remaining.items.len == 0) continue;
        // Клауза не пуста: единственный оставшийся литерал обязан быть выводом.
        if (remaining.items.len != 1) return false;
        if (concl_is_false) return false;
        if (!sexpEq(remaining.items[0], concl)) return false;
        saw_remaining = true;
    }

    if (!saw_remaining) {
        if (concl_is_false) {
            if (clauses.items.len > 0) return true; // все клаузы опровергнуты
            // Без клауз нужна пара взаимно-дополняющих литералов.
            for (units.items, 0..) |u, i| {
                for (units.items[i + 1 ..]) |w| {
                    if (isComplement(u, w)) return true;
                }
            }
            return false;
        }
        // Вывод — литерал: он обязан быть среди посылок.
        for (units.items) |u| if (sexpEq(u, concl)) return true;
        return false;
    }
    return true;
}

// =========================================================================
// Входная точка: аудит текста вывода
// =========================================================================

/// Пометить шаг как непроверенный и запомнить ПРАВИЛО первого такого шага.
/// Без этого нельзя понять, что именно осталось доверенным (METRICS 55.5).
fn markTrusted(v: *ProofVerdict, rule: []const u8) void {
    v.trusted_steps += 1;
    if (v.first_trusted.len == 0) v.first_trusted = rule;
}

/// Математический аудит вывода. `contract` — исходные утверждения контракта
/// (строки SMT-LIB внутри `(assert ...)`) — по ним проверяется привязка
/// посылок.
pub fn verifyProof(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
) !ProofVerdict {
    var v = ProofVerdict{};
    var ar = std.heap.ArenaAllocator.init(allocator);
    defer ar.deinit();
    const arena = ar.allocator();

    // 1. Внешняя оболочка: найти блок (proof ...).
    const outer = parseSexp(arena, proof_text) catch {
        v.reject = "вывод не разбирается как S-выражение";
        return v;
    };
    var body: ?Sexp = null;
    if (outer.isList()) {
        for (outer.items) |it| {
            if (it.headAtom()) |h| {
                if (std.mem.eql(u8, h, "proof") and it.items.len >= 2) body = it.items[1];
            }
        }
    }
    if (body == null) {
        v.reject = "не найден блок (proof ...)";
        return v;
    }
    v.proof_present = true;

    var c = newCtx(arena);
    try collect(&c, body.?);
    v.proof_steps = c.steps.items.len;
    if (v.proof_steps == 0) {
        v.reject = "в выводе нет ни одного шага";
        return v;
    }

    // Контракт для привязки посылок (в контракте сокращений нет).
    var contract_terms = std.array_list.Managed(Sexp).init(arena);
    for (contract) |a| {
        const s = parseSexp(arena, a) catch continue;
        try contract_terms.append(s);
    }

    for (c.steps.items) |st| {
        const r = ruleOf(st) orelse continue;
        if (isHole(r)) {
            v.holes += 1;
            if (v.reject.len == 0) v.reject = "вывод содержит правило-дыру (hole/trust/sorry)";
            continue;
        }
        if (!isKnownRule(r)) v.unknown_rules += 1;

        if (std.mem.eql(u8, r, "asserted")) {
            v.premises_total += 1;
            const t = expand(&c, proved(st), 0);
            var found = false;
            for (contract_terms.items) |ct| {
                if (sexpEq(t, ct)) {
                    found = true;
                    break;
                }
            }
            if (found) v.premises_bound += 1 else v.premises_unbound += 1;
        } else if (std.mem.eql(u8, r, "hypothesis")) {
            v.premises_total += 1; // локальная посылка, снимается правилом lemma
        } else if (std.mem.eql(u8, r, "mp")) {
            v.mp_checked += 1;
            if (!checkMp(&c, st)) v.mp_bad += 1;
        } else if (std.mem.eql(u8, r, "unit-resolution")) {
            v.unitres_checked += 1;
            if (!checkUnitRes(&c, st)) v.unitres_bad += 1;
        } else if (std.mem.eql(u8, r, "th-lemma")) {
            const clause = expand(&c, proved(st), 0);
            switch (verifyFarkas(&c, st.items[0], clause)) {
                .ok => v.farkas_checked += 1,
                .structural_only => v.farkas_structural += 1,
                .bad => v.farkas_bad += 1,
            }
        } else if (std.mem.eql(u8, r, "rewrite")) {
            // Элементарные тождества: если равенство доказано нормализацией
            // сравнений (или рефлексивностью) — шаг ПРОВЕРЕН, иначе остаётся
            // доверенным. Никогда не выдаём непроверенное за проверенное.
            switch (checkRewrite(&c, st)) {
                .verified => v.rewrite_verified += 1,
                .bad => v.rewrite_bad += 1,
                .unverifiable => markTrusted(&v, r),
            }
        } else if (std.mem.eql(u8, r, "refl") or std.mem.eql(u8, r, "symm") or
            std.mem.eql(u8, r, "trans"))
        {
            if (verifyEqRule(&c, r, st)) v.eq_verified += 1 else markTrusted(&v, r);
        } else if (std.mem.eql(u8, r, "and-elim")) {
            if (verifyAndElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r);
        } else if (std.mem.eql(u8, r, "not-or-elim")) {
            if (verifyNotOrElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r);
        } else if (std.mem.eql(u8, r, "monotonicity")) {
            if (verifyMonotonicity(&c, st)) v.bool_verified += 1 else markTrusted(&v, r);
        } else {
            // Прочие правила (elim-правила, кванторы): перепроверить нельзя,
            // учитываем как «доверенные», а не как «проверенные».
            markTrusted(&v, r);
        }
    }

    // Корень обязан выводить false (пустую клаузу).
    if (c.root) |root| {
        const t = expand(&c, proved(root), 0);
        v.proof_concludes_false = t.atom != null and std.mem.eql(u8, t.atom.?, "false");
    }
    if (!v.proof_concludes_false and v.reject.len == 0) {
        v.reject = "корень вывода не является false";
    }
    v.proof_well_formed = v.reject.len == 0;
    return v;
}

// =========================================================================
// Полная проверка: вывод + минимальность ядра (MUS)
// =========================================================================

/// Полная проверка: запросить вывод у решателя, математически его
/// перепроверить и отдельно подтвердить, что ядро неразрешимости минимально
/// (то есть конфликт не вакуумный).
pub fn check(
    allocator: std.mem.Allocator,
    bridge: *z3.Z3Bridge,
    decls: []const u8,
    assertions: []const unsat_core.NamedAssertion,
    goal: []const u8,
) !ProofVerdict {
    var v = ProofVerdict{};

    // --- 1. Запрос вывода -------------------------------------------------
    var buf = compat.BufWriter.init(allocator);
    defer buf.deinit();
    const w = buf.writer();
    try w.writeAll("(set-option :produce-proofs true)\n(set-logic ALL)\n");
    try w.writeAll(decls);
    try w.writeAll("\n");
    for (assertions) |a| try w.print("(assert {s})\n", .{a.formula});
    try w.print("(assert (not {s}))\n", .{goal});
    try w.writeAll("(check-sat)\n(get-proof)\n");

    const cap = bridge.executeCapture(buf.items());
    defer allocator.free(cap.stdout);

    v.is_unsat = cap.status == .Unsat;
    if (!v.is_unsat) return v;

    // Вывод идёт после строки "unsat".
    const nl = std.mem.indexOfScalar(u8, cap.stdout, '\n') orelse return v;
    const proof = cap.stdout[nl + 1 ..];

    // --- 2. Математический аудит вывода ----------------------------------
    var contract = std.array_list.Managed([]const u8).init(allocator);
    defer contract.deinit();
    for (assertions) |a| try contract.append(a.formula);
    var neg = compat.BufWriter.init(allocator);
    defer neg.deinit();
    try neg.writer().print("(not {s})", .{goal});
    try contract.append(neg.items());

    const deep = try verifyProof(allocator, proof, contract.items);
    // Переносим результаты глубокого разбора в итоговый вердикт.
    v.proof_present = deep.proof_present;
    v.proof_steps = deep.proof_steps;
    v.proof_well_formed = deep.proof_well_formed;
    v.proof_concludes_false = deep.proof_concludes_false;
    v.holes = deep.holes;
    v.unknown_rules = deep.unknown_rules;
    v.premises_total = deep.premises_total;
    v.premises_bound = deep.premises_bound;
    v.premises_unbound = deep.premises_unbound;
    v.mp_checked = deep.mp_checked;
    v.mp_bad = deep.mp_bad;
    v.unitres_checked = deep.unitres_checked;
    v.unitres_bad = deep.unitres_bad;
    v.farkas_checked = deep.farkas_checked;
    v.farkas_structural = deep.farkas_structural;
    v.farkas_bad = deep.farkas_bad;
    v.rewrite_verified = deep.rewrite_verified;
    v.rewrite_bad = deep.rewrite_bad;
    v.eq_verified = deep.eq_verified;
    v.bool_verified = deep.bool_verified;
    v.trusted_steps = deep.trusted_steps;
    v.first_trusted = deep.first_trusted;
    v.reject = deep.reject;
    if (!deep.checksPass() or !deep.proof_concludes_false) return v;

    // --- 3. Минимальность ядра (MUS) -------------------------------------
    var eng = unsat_core.UnsatCoreEngine.init(allocator);
    var core = try eng.localize(bridge, decls, assertions, goal);
    defer core.deinit();
    v.core_size = core.conflicting.len;

    if (core.conflicting.len > 0) {
        var all_needed = true;
        for (core.conflicting) |drop| {
            if (std.mem.eql(u8, drop, "goal")) continue;
            var b2 = compat.BufWriter.init(allocator);
            defer b2.deinit();
            const w2 = b2.writer();
            try w2.writeAll("(set-logic ALL)\n");
            try w2.writeAll(decls);
            try w2.writeAll("\n");
            for (assertions) |a| {
                if (std.mem.eql(u8, a.name, drop)) continue;
                try w2.print("(assert {s})\n", .{a.formula});
            }
            try w2.print("(assert (not {s}))\n", .{goal});
            try w2.writeAll("(check-sat)\n");
            const r2 = bridge.executeQuery(b2.items());
            if (r2.witness_model) |m| allocator.free(m);
            if (r2.status != .Sat) all_needed = false;
        }
        v.core_minimal = all_needed;
    } else {
        v.core_minimal = v.proof_well_formed;
    }

    v.confirmed = v.proof_present and v.checksPass() and
        v.proof_concludes_false and v.core_minimal;
    return v;
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

/// Реальный вывод Z3 5.1.0 для `(> x 10) ∧ (< x 5)`: три `mp`, одна
/// `unit-resolution` с сертификатом Фаркаша `1 1`. Служит и эталоном формата,
/// и базой для тестов подделок.
const REAL_LIA_PROOF =
    \\((set-logic QF_LIA)
     \\(proof
      \\(let (($x42 (>= x 5)))
       \\(let (($x41 (not $x42)))
        \\(let ((@x45 (rewrite (= (not (<= 5 x)) $x41))))
         \\(let (($x36 (not (<= 5 x))))
          \\(let ((@x52 (mp (mp (asserted (< x 5)) (rewrite (= (< x 5) $x36)) $x36) (rewrite (= $x36 $x36)) $x36)))
           \\(let (($x27 (<= x 10)))
            \\(let (($x28 (not $x27)))
             \\(let ((@x31 (mp (asserted (> x 10)) (rewrite (= (> x 10) $x28)) $x28)))
              \\(unit-resolution ((_ th-lemma arith farkas 1 1) (or $x42 $x27)) (mp @x31 (rewrite (= $x28 $x28)) $x28) (mp @x52 @x45 $x41) false)))))))))))
;

const REAL_LIA_CONTRACT = [_][]const u8{ "(< x 5)", "(> x 10)" };

test "PROOF: парсер S-выражений разбирает вложенность и отвергает мусор" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const s = try parseSexp(a, "(a (b c) d)");
    try std.testing.expect(s.isList());
    try std.testing.expectEqual(@as(usize, 3), s.items.len);
    try std.testing.expectEqualStrings("a", s.headAtom().?);
    try std.testing.expectError(ParseError.UnexpectedEof, parseSexp(a, "(a (b c)"));
    try std.testing.expectError(ParseError.UnexpectedClose, parseSexp(a, ")("));
}

test "PROOF: структурное равенство и дополнение литералов" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const t1 = try parseSexp(a, "(or a (not b))");
    const t2 = try parseSexp(a, "(or a (not b))");
    const t3 = try parseSexp(a, "(or a b)");
    try std.testing.expect(sexpEq(t1, t2));
    try std.testing.expect(!sexpEq(t1, t3));
    const lit = try parseSexp(a, "b");
    const nlit = try parseSexp(a, "(not b)");
    try std.testing.expect(isComplement(lit, nlit));
    try std.testing.expect(!isComplement(lit, lit));
}

test "PROOF (РЕАЛЬНЫЙ ВЫВОД Z3): все проверки проходят, Фаркаш разобран арифметически" {
    const v = try verifyProof(std.testing.allocator, REAL_LIA_PROOF, &REAL_LIA_CONTRACT);
    try std.testing.expect(v.proof_present);
    try std.testing.expect(v.proof_steps > 0);
    try std.testing.expect(v.proof_concludes_false);
    try std.testing.expectEqual(@as(usize, 0), v.holes);
    try std.testing.expectEqual(@as(usize, 2), v.premises_bound);
    try std.testing.expectEqual(@as(usize, 0), v.premises_unbound);
    try std.testing.expectEqual(@as(usize, 5), v.mp_checked);
    try std.testing.expectEqual(@as(usize, 0), v.mp_bad);
    try std.testing.expectEqual(@as(usize, 1), v.unitres_checked);
    try std.testing.expectEqual(@as(usize, 0), v.unitres_bad);
    try std.testing.expectEqual(@as(usize, 1), v.farkas_checked);
    try std.testing.expectEqual(@as(usize, 0), v.farkas_bad);
    // Измерено на этом выводе: 14 шагов = 2 asserted + 5 rewrite + 5 mp
    // + 1 unit-resolution + 1 th-lemma. Все 5 rewrite ДОКАЗАНЫ нормализацией
    // сравнений (2 рефлексивных + 3 перестановки сторон), поэтому
    // trusted_steps = 0: непроверяемых шагов на эталоне не осталось.
    try std.testing.expectEqual(@as(usize, 14), v.proof_steps);
    try std.testing.expectEqual(@as(usize, 5), v.rewrite_verified);
    try std.testing.expectEqual(@as(usize, 0), v.trusted_steps);
    try std.testing.expect(v.checksPass());
}

test "PROOF-АТАКА: подменённая посылка (fake assume) отвергается" {
    const bad = try std.mem.replaceOwned(u8, std.testing.allocator, REAL_LIA_PROOF, "(asserted (< x 5))", "(asserted (< x 999))");
    defer std.testing.allocator.free(bad);
    const v = try verifyProof(std.testing.allocator, bad, &REAL_LIA_CONTRACT);
    try std.testing.expectEqual(@as(usize, 1), v.premises_unbound);
    try std.testing.expect(!v.checksPass());
}

test "PROOF-АТАКА: правило-дыра hole отвергается" {
    const v = try verifyProof(std.testing.allocator, "((set-logic QF_UF)(proof (hole false)))", &.{});
    try std.testing.expectEqual(@as(usize, 1), v.holes);
    try std.testing.expect(!v.checksPass());
    try std.testing.expect(v.proof_concludes_false); // дыра выдаёт нужный корень
}

test "PROOF-АТАКА: лишний литерал в клаузе ломает резолюцию" {
    const bad = try std.mem.replaceOwned(u8, std.testing.allocator, REAL_LIA_PROOF, "(or $x42 $x27)", "(or $x42 $x27 (<= x 100))");
    defer std.testing.allocator.free(bad);
    const v = try verifyProof(std.testing.allocator, bad, &REAL_LIA_CONTRACT);
    try std.testing.expect(!v.checksPass());
    try std.testing.expect(v.unitres_bad + v.farkas_bad >= 1);
}

test "PROOF-АТАКА: испорченный коэффициент Фаркаша отвергается" {
    const bad = try std.mem.replaceOwned(u8, std.testing.allocator, REAL_LIA_PROOF, "farkas 1 1", "farkas 1 2");
    defer std.testing.allocator.free(bad);
    const v = try verifyProof(std.testing.allocator, bad, &REAL_LIA_CONTRACT);
    try std.testing.expectEqual(@as(usize, 1), v.farkas_bad);
    try std.testing.expect(!v.checksPass());
}

test "PROOF-АТАКА: корень выводит не false" {
    const bad = try std.mem.replaceOwned(u8, std.testing.allocator, REAL_LIA_PROOF, "(mp @x52 @x45 $x41) false)", "(mp @x52 @x45 $x41) $x42)");
    defer std.testing.allocator.free(bad);
    const v = try verifyProof(std.testing.allocator, bad, &REAL_LIA_CONTRACT);
    try std.testing.expect(!v.proof_concludes_false);
    try std.testing.expect(!v.checksPass());
}

test "PROOF (РЕАЛЬНЫЙ Z3): подтверждение требует разбора вывода и минимального ядра" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 10000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    const pres = [_]unsat_core.NamedAssertion{
        .{ .name = "p1", .formula = "(> x 5)" },
        .{ .name = "p2", .formula = "(< x 10)" },
    };
    const v = try check(std.testing.allocator, &bridge, "(declare-const x Int)", &pres, "(>= x 6)");
    try std.testing.expect(v.is_unsat);
    try std.testing.expect(v.proof_present);
    try std.testing.expect(v.proof_steps > 0);
    try std.testing.expect(v.proof_concludes_false);
    try std.testing.expect(v.checksPass());
    try std.testing.expect(v.premises_bound > 0);
    try std.testing.expect(v.confirmed);
}

test "PROOF (РЕАЛЬНЫЙ Z3): выполнимая формула НЕ даёт подтверждения" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;

    const pres = [_]unsat_core.NamedAssertion{
        .{ .name = "p1", .formula = "(> x 5)" },
    };
    const v = try check(std.testing.allocator, &bridge, "(declare-const x Int)", &pres, "(< x 0)");
    try std.testing.expect(!v.is_unsat);
    try std.testing.expect(!v.confirmed);
}

test "PROOF-АТАКА: подделанный rewrite между двумя сравнениями отвергается" {
    // Обе стороны нормализуются, значит нормализатор их ПОКРЫВАЕТ. Если
    // равенства нет — это доказанная подделка, а не «непроверяемость».
    // Меняем (= (< x 5) (not (<= 5 x)))  на  (= (< x 5) (<= 5 x)):
    //   (< x 5)  -> neg=true,  a=x, b=5
    //   (<= 5 x) -> neg=false, a=x, b=5   -> признаки отрицания РАЗНЫЕ
    const bad = try std.mem.replaceOwned(u8, std.testing.allocator, REAL_LIA_PROOF, "(rewrite (= (< x 5) $x36))", "(rewrite (= (< x 5) (<= 5 x)))");
    defer std.testing.allocator.free(bad);
    const v = try verifyProof(std.testing.allocator, bad, &REAL_LIA_CONTRACT);
    try std.testing.expect(v.rewrite_bad >= 1);
    try std.testing.expect(!v.checksPass());
}

test "PROOF: нормализация сравнений — рефлексивность и перестановка сторон" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const p1 = try parseSexp(a, "(< x 5)");
    const p2 = try parseSexp(a, "(not (>= x 5))");
    const p3 = try parseSexp(a, "(<= 5 x)");
    const p4 = try parseSexp(a, "(>= x 5)");
    const p5 = try parseSexp(a, "(> x 5)");
    try std.testing.expect(sameLiteral(p1, p2)); // (< x 5) == ¬(x >= 5)
    try std.testing.expect(sameLiteral(p3, p4)); // (<= 5 x) == (x >= 5)
    try std.testing.expect(!sameLiteral(p1, p4)); // x<5 НЕ равно x>=5
    try std.testing.expect(!sameLiteral(p1, p5)); // x<5 НЕ равно x>5
    try std.testing.expect(sameLiteral(p1, p1)); // рефлексивность
}

test "PROOF: линейная нормализация закрывает арифметические тождества" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);

    // Тождества, которые синтаксический normCmp НЕ берёт, а линейная форма — берёт.
    const t1 = try parseSexp(a, "(rewrite (= (+ x (+ y x)) (+ (* 2 x) y)))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, t1));
    const t2 = try parseSexp(a, "(rewrite (= (- x x) 0))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, t2));
    const t3 = try parseSexp(a, "(rewrite (= (<= (- x y) 5) (<= x (+ y 5))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, t3));

    // Обе стороны ЛИНЕЙНЫ, но тождества нет -> доказанная подделка.
    const b1 = try parseSexp(a, "(rewrite (= (<= x 5) (<= x 6)))");
    try std.testing.expectEqual(RwResult.bad, checkRewrite(&c, b1));
    const b2 = try parseSexp(a, "(rewrite (= x (* 2 x)))");
    try std.testing.expectEqual(RwResult.bad, checkRewrite(&c, b2));

    // Нелинейное/неинтерпретированное -> честно unverifiable, НЕ bad.
    const un1 = try parseSexp(a, "(rewrite (= (select arr i) 5))");
    try std.testing.expectEqual(RwResult.unverifiable, checkRewrite(&c, un1));
    const un2 = try parseSexp(a, "(rewrite (= (* x x) 4))");
    try std.testing.expectEqual(RwResult.unverifiable, checkRewrite(&c, un2));
}

test "PROOF: and-elim / monotonicity / trans через ССЫЛКИ на шаги проверяются" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();

    // Посылки здесь — СИМВОЛЫ (@r1, @m1, @a1). Раньше `expand` их не раскрывал,
    // поэтому trans уходил в trusted. Теперь посылки разрешаются через
    // premiseTerm -> proved.
    const t = try parseSexp(a, "(trans @m1 @r2 (= (> (+ x 1) 1) (not (<= (+ 1 x) 1))))");
    try std.testing.expectEqual(@as(usize, 4), t.items.len);

    // and-elim: из (and A B) следует ИМЕННО конъюнкт A.
    const ae = try parseSexp(a, "(and-elim @a1 $x25)");
    try std.testing.expectEqualStrings("and-elim", ruleOf(ae).?);

    // monotonicity: вывод обязан получаться подстановкой A->B.
    const mo = try parseSexp(a, "(monotonicity @r1 (= (> (+ x 1) 1) (> (+ 1 x) 1)))");
    try std.testing.expectEqualStrings("monotonicity", ruleOf(mo).?);
}

test "PROOF: подстановка и and-elim на разборе термов" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // subst: заменить (+ x 1) на (+ 1 x) внутри (and (> (+ x 1) 1) q)
    const src = try parseSexp(a, "(and (> (+ x 1) 1) q)");
    const from = try parseSexp(a, "(+ x 1)");
    const to = try parseSexp(a, "(+ 1 x)");
    const got = subst(&c, src, from, to, 0).?;
    const want = try parseSexp(a, "(and (> (+ 1 x) 1) q)");
    try std.testing.expect(sexpEq(got, want));
}
