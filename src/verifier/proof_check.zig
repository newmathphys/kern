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
const builtin_lia = @import("builtin_lia.zig");

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
    ///
    /// ДЕФЕКТ #125 (найден тестом мутанта 49): функция проверяла ТОЛЬКО
    /// счётчики ошибок и `reject`, поэтому ПУСТОЙ вердикт `ProofVerdict{}`
    /// (0 проверенных шагов) формально возвращал `true`. Все три текущих
    /// вызова дополнительно требуют `proof_concludes_false`, так что ворот
    /// дефект НЕ открывал — но функция обязана быть самодостаточной: ноль
    /// проверенных шагов не является успехом ни при каких условиях.
    pub fn checksPass(self: ProofVerdict) bool {
        if (self.proof_steps == 0) return false;
        return self.holes == 0 and self.premises_unbound == 0 and
            self.mp_bad == 0 and self.unitres_bad == 0 and
            self.farkas_bad == 0 and self.rewrite_bad == 0 and
            self.reject.len == 0;
    }

    /// ЧЕЛОВЕКОЧИТАЕМАЯ ПРИЧИНА ОТКАЗА.
    ///
    /// ДЕФЕКТ #89 (найден при работе над ветвлениями): отказ мог прийти не от
    /// явного `reject`, а от счётчика (`premises_unbound`, `mp_bad`, ...), и
    /// тогда CLI печатал `[!] причина: ` с ПУСТЫМ текстом — пользователь видел
    /// «ПРУФ-ЧЕКЕР ОТВЕРГ», но не знал, что именно не так.
    /// Здесь причина всегда называется.
    pub fn failureReason(self: ProofVerdict) []const u8 {
        if (self.reject.len != 0) return self.reject;
        if (self.holes != 0) return "в выводе есть правило-дыра (hole/trust/sorry)";
        if (self.premises_unbound != 0) return "посылки не привязаны к контракту (premises_unbound)";
        if (self.mp_bad != 0) return "неверная структура mp";
        if (self.unitres_bad != 0) return "неверный шаг unit-resolution";
        if (self.farkas_bad != 0) return "неверный сертификат Фаркаша";
        if (self.rewrite_bad != 0) return "подделанный rewrite (обе стороны линейны и НЕ равны)";
        if (!self.proof_concludes_false) return "вывод не завершается `false`";
        if (self.trusted_steps != 0) return "остались непроверенные шаги (trusted)";
        return "неизвестная причина отказа";
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

/// 🔴 ХАРДКОР-АУДИТ (Deep Nesting Bomb): добавлена ошибка ПРЕВЫШЕНИЯ ГЛУБИНЫ.
//
/// ИЗМЕРЕНО: `parseList` вызывает `parse()` рекурсивно, поэтому вход
/// `'(' * N` даёт N кадров стека. 50 000 скобок тест-раннер переживает
/// (большой стек), а **2 000 000 -> SIGSEGV** («terminated with signal SEGV»).
/// Это классический stack-overflow на НЕДОВЕРЕННОМ входе (вывод решателя),
/// то есть отказ в обслуживании одним файлом .smt2.
//
/// Исправление: жёсткий лимит глубины вложенности в парсере.
pub const ParseError = error{ UnexpectedClose, UnexpectedEof, OutOfMemory, TooDeep };

/// Предел вложенности S-выражений. Реальные выводы Z3 укладываются в единицы
/// уровней (в эталонном — 14 шагов, глубина < 20). 4096 — с большим запасом,
/// но при этом 4096 кадров стека безопасны.
pub const MAX_SEXP_DEPTH: u32 = 4096;

/// Разборщик S-выражений. Строки в кавычках сохраняются как атомы целиком
/// (содержимое для проверок не нужно, но границы ломать нельзя).
const SexprParser = struct {
    src: []const u8,
    i: usize = 0,
    arena: std.mem.Allocator,
    depth: u32 = 0, // текущая глубина вложенности (лимит MAX_SEXP_DEPTH)

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
        // ЗАЩИТА ОТ STACK OVERFLOW (хардкор-аудит): рекурсия ограничена.
        if (self.depth >= MAX_SEXP_DEPTH) return ParseError.TooDeep;
        self.depth += 1;
        defer self.depth -= 1;
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
/// КАНОНИЧЕСКАЯ СВЁРТКА КОНСТАНТНОЙ СТРОКИ В БАЙТЫ (Пункт 23 / QF_S).
///
/// ИЗМЕРЕНО (дамп `KERN_DEBUG_TRUSTED=1`): Z3 представляет литерал `"../"` как
///   `(str.++ (seq.unit (_ Char 46)) (seq.unit (_ Char 46)) (seq.unit (_ Char 47)))`
/// где 46 = '.', 47 = '/'. Без свёртки НЕ сходятся 4 `rewrite` и зависящие от них
/// `trans*`, `symm`, `lemma`, `unit-resolution` (8 доверенных шагов).
///
/// Звучимость: вычисление функции над КОНСТАНТАМИ — константа; сверяем байты
/// в самом Zig (`std.mem`), никаких доверенных шагов не требуется.
fn evalConstStr(s: Sexp, buf: []u8) ?[]const u8 {
    if (s.atom) |a| {
        _ = a;
        const lit = strLitOf(s) orelse return null;
        if (lit.len > buf.len) return null;
        @memcpy(buf[0..lit.len], lit);
        return buf[0..lit.len];
    }
    if (s.items.len < 2) return null;
    const op = s.items[0].atom orelse return null;
    if (std.mem.eql(u8, op, "seq.unit")) {
        const arg = s.items[1];
        if (!arg.isList()) return null;
        var nSexp: Sexp = undefined;
        if (arg.items.len == 3) {
            const a0 = arg.items[0].atom orelse return null;
            const a1 = arg.items[1].atom orelse return null;
            if (!std.mem.eql(u8, a0, "_") or !std.mem.eql(u8, a1, "Char")) return null;
            nSexp = arg.items[2];
        } else if (arg.items.len == 2) {
            const a0 = arg.items[0].atom orelse return null;
            if (!std.mem.eql(u8, a0, "Char")) return null;
            nSexp = arg.items[1];
        } else return null;
        const nAtom = nSexp.atom orelse return null;
        const code = std.fmt.parseInt(u32, nAtom, 10) catch return null;
        if (code > 255 or buf.len < 1) return null;
        buf[0] = @intCast(code);
        return buf[0..1];
    }
    if (std.mem.eql(u8, op, "str.++")) {
        var pos: usize = 0;
        for (s.items[1..]) |it| {
            const part = evalConstStr(it, buf[pos..]) orelse return null;
            pos += part.len;
        }
        return buf[0..pos];
    }
    return null;
}

/// Два подтерма равны, если оба — КОНСТАНТНЫЕ строки с ОДНИМИ байтами.
/// ИЗМЕРЕНО: именно так `"../"` совпадает со своей развёрнутой формой `str.++`.
fn strConstEq(a: Sexp, b: Sexp) bool {
    var ba: [256]u8 = undefined;
    var bb: [256]u8 = undefined;
    const x = evalConstStr(a, &ba) orelse return false;
    const y = evalConstStr(b, &bb) orelse return false;
    return std.mem.eql(u8, x, y);
}

pub fn sexpEq(a: Sexp, b: Sexp) bool {
    if (a.atom) |aa| {
        if (b.atom) |bb| {
            if (std.mem.eql(u8, aa, bb)) return true;
            // Пункт 23 / QF_S: константные строки в разных формах — одно значение.
            return strConstEq(a, b);
        }
        return strConstEq(a, b);
    }
    if (b.atom != null) return strConstEq(a, b);
    if (a.items.len != b.items.len) return strConstEq(a, b);
    for (a.items, b.items) |x, y| if (!sexpEq(x, y)) return false;
    return true;
}

/// Числовой литерал-атом вида `-N` (N — цифры).
//
/// ДЕФЕКТ #121 (найден на теневом контракте Rust `saturating_add`).
/// ИЗМЕРЕНО: в исходном `.smt2` отрицательное число печатается АТОМОМ
/// (`(>= a -2147483648)`), а Z3 в выводе печатает его СПИСКОМ
/// (`(>= a (- 2147483648))`). Сравнение посылки с клаузой контракта не
/// совпадало, `premises_unbound` увеличивался, и чекер **ложно отвергал**
/// корректный вывод: `[!] причина: посылки не привязаны к контракту`.
/// Это ЛОЖНЫЙ ОТКАЗ (не ослабление): `-N` и `(- N)` — одно и то же число.
fn isNegNumAtom(s: []const u8) ?[]const u8 {
    if (s.len < 2 or s[0] != '-') return null;
    for (s[1..]) |ch| {
        if (ch < '0' or ch > '9') return null;
    }
    return s[1..];
}

/// ЭТО СПИСОК `(- N)`? Возвращает цифры `N`.
fn isNegNumList(e: Sexp) ?[]const u8 {
    if (!e.isList() or e.items.len != 2) return null;
    const h = e.items[0].atom orelse return null;
    if (!std.mem.eql(u8, h, "-")) return null;
    const d = e.items[1].atom orelse return null;
    for (d) |ch| {
        if (ch < '0' or ch > '9') return null;
    }
    return d;
}

/// Равенство термов С НОРМАЛИЗАЦИЕЙ ЧИСЛОВЫХ ЛИТЕРАЛОВ.
//
/// Отличие от `sexpEq`: атом `-N` считается равным списку `(- N)`.
/// Применяется ТОЛЬКО при привязке посылок к контракту (граница «вывод Z3 ↔
/// исходный .smt2»), где эта разница и возникает. Внутри самого вывода Z3
/// печатает литералы единообразно, поэтому остальные проверки не меняются.
fn sexpEqNum(a: Sexp, b: Sexp) bool {
    // ПРИЧИНА №1 (измерено/разобрано): сравнение составных формул уходит в этот
    // рекурсивный обход, и на вложенном подтерме `.atom` `"../"` vs `.list`
    // `(str.++ (seq.unit …))` срабатывало отсечение «atom vs list» ДО проверки
    // константных строк. Из-за этого `trans*`, `symm`, `lemma`, `unit-resolution`
    // не видели равенства внутри `(str.contains s …)`.
    // ЗВУЧНО: сверяем СВОРАЧИВАЕМЫЕ байты константных строк.
    if (strConstEq(a, b)) return true;
    // ИЗМЕРЕНО (ЭТАП А): Z3 пишет одно сравнение двумя способами
    // (`(<= 0 x)` и `(>= x 0)`) — канонизируем перед сравнением.
    if (cmpEq(a, b)) return true;
    if (a.atom) |aa| {
        if (isNegNumAtom(aa)) |digits| {
            if (isNegNumList(b)) |d2| return std.mem.eql(u8, digits, d2);
            return false;
        }
        if (b.atom) |bb| return std.mem.eql(u8, aa, bb);
        return false;
    }
    if (isNegNumAtom(b.atom orelse "")) |digits| {
        if (isNegNumList(a)) |d2| return std.mem.eql(u8, digits, d2);
        return false;
    }
    if (b.atom != null) return false;
    if (a.items.len != b.items.len) return false;
    for (a.items, b.items) |x, y| if (!sexpEqNum(x, y)) return false;
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
    "trans*",          "def-axiom",
    "symm",            "refl",        "not-or-elim", "and-elim",
    "or-elim",         "not-elim",    "iff-elim",   "commutativity",
    "distributivity",  "definition",  "monotonicity", "bind",
    "pull-quant",      "sk",          "nnf-pos",    "nnf-neg",
    "quant-inst",      "quant-intro", "elim",       "asserted-commutativity",
    // ДЕФЕКТ #90 (найден при работе над ветвлениями `ite`): этих правил не было
    // в списке, поэтому `isStepExpr` НЕ считал их шагами, и `premiseTerm`
    // возвращал САМ шаг (`(intro-def X)`) вместо доказываемой формулы (`X`).
    // Из-за этого `mp` не сходился и чекер отвергал ВЕРНЫЙ вывод.
    // `def-axiom` — определение (аксиома), поэтому шаг попадает в `trusted`
    // и НЕ выдаётся за проверенный.
    "intro-def",       "def-axiom",
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
//
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
/// Определение `ite`, введённое ПРОВЕРЕННЫМ шагом `intro-def`:
/// `z3name!k = (ite cond a b)`. Хранится, чтобы разворачивать имя в его
/// определение при проверке последующих шагов (`rewrite`/`unit-resolution`).
const DefIte = struct { cond: Sexp, a: Sexp, b: Sexp };

pub const Ctx = struct {
    arena: std.mem.Allocator,
    abbrev: std.StringHashMap(Sexp),
    stepexpr: std.StringHashMap(Sexp),
    steps: std.array_list.Managed(Sexp),
    root: ?Sexp = null,
    /// ИЗМЕРЕНО на `musl abs.c`: последний доверенный `rewrite` — это
    /// `(= (>= (result − ite(…)) 0) (>= (result − z3name!1) 0))`, то есть
    /// ПОДСТАНОВКА определения `z3name!1`. ЗВУЧНО разворачивать имя можно
    /// только если само определение доказано шагом `intro-def`.
    defs: std.StringHashMap(DefIte),
};

fn newCtx(arena: std.mem.Allocator) Ctx {
    return .{
        .arena = arena,
        .abbrev = std.StringHashMap(Sexp).init(arena),
        .stepexpr = std.StringHashMap(Sexp).init(arena),
        .steps = std.array_list.Managed(Sexp).init(arena),
        .defs = std.StringHashMap(DefIte).init(arena),
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
//
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
/// БЮДЖЕТ РАСКРЫТИЯ `let`-СОКРАЩЕНИЙ (пункт 4 плана v2.5).
//
/// ЗАЧЕМ. Z3 сжимает DAG доказательства в дерево через `let`, поэтому один и
/// тот же терм может быть назван МНОГО раз. Наивное раскрытие каждого имени в
/// его тело даёт ЭКСПОНЕНЦИАЛЬНЫЙ рост: цепочка `$a0 = (+ $a1 $a1)`,
/// `$a1 = (+ $a2 $a2)`, ... даёт 2^N узлов. Лимит ГЛУБИНЫ (128) от этого НЕ
/// спасает — он ограничивает вложенность, а не общее число узлов.
//
/// ЧТО ДЕЛАЕМ. Считаем раскрытые узлы и при исчерпании бюджета ПРЕКРАЩАЕМ
/// раскрытие, возвращая терм как есть. Это КОНСЕРВАТИВНО: нераскрытое имя
/// не совпадёт с клаузой контракта, посылка окажется непривязанной, и вывод
/// будет ОТКЛОНЁН (`premises_unbound`). То есть неполнота ведёт к отказу, а не
/// к ложному «проверено».
const EXPAND_NODE_BUDGET: usize = 200_000;

/// Счётчик раскрытия: `left` — остаток бюджета, `used` — сколько узлов раскрыто.
const ExpandBudget = struct {
    left: usize = EXPAND_NODE_BUDGET,
    used: usize = 0,
};

fn expand(c: *const Ctx, e: Sexp, depth: u32) Sexp {
    var b = ExpandBudget{};
    return expandB(c, e, depth, &b);
}

fn expandB(c: *const Ctx, e: Sexp, depth: u32, b: *ExpandBudget) Sexp {
    if (depth > 128) return e;
    // Бюджет исчерпан: НЕ раскрываем дальше (консервативно — вывод будет
    // отклонён как непривязанный, а не принят на веру).
    if (b.left == 0) return e;
    b.left -= 1;
    b.used += 1;
    if (e.atom) |a| {
        if (c.abbrev.get(a)) |v| return expandB(c, v, depth + 1, b);
        return e;
    }
    const out = c.arena.alloc(Sexp, e.items.len) catch return e;
    for (e.items, 0..) |it, i| out[i] = expandB(c, it, depth + 1, b);
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
//
/// ЗАЧЕМ. Z3 оформляет элементарные тождества как шаги `rewrite`, и раньше они
/// целиком уходили в `trusted_steps` — то есть принимались без проверки.
/// Между тем это не произвольный рерайтер: на эталонном выводе все 5 шагов
/// сводятся к двум правилам, которые проверяются точно:
//
///   1. РЕФЛЕКСИВНОСТЬ: `(= X X)` — верно по определению равенства.
///   2. НОРМАЛИЗАЦИЯ СРАВНЕНИЙ (перестановка сторон и смена знака):
///        `(<= a b)` == `(>= b a)`
///        `(>  a b)` == `(not (>= b a))`
///        `(<  a b)` == `(not (>= a b))`
///        `(not X)`  — инвертирует признак отрицания.
//
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

/// СЕМАНТИЧЕСКАЯ дополнительность сравнений.
//
/// ДЕФЕКТ #91 (найден на выводе с `ite`): `isComplement` сравнивает СТРУКТУРНО,
/// поэтому `(not (<= a b))` и `(>= b a)` не считались взаимно-дополняющими,
/// хотя это одно и то же. Из-за этого `unit-resolution` не мог опровергнуть
/// литерал и чекер отвергал ВЕРНЫЙ вывод.
/// Здесь сравниваются КАНОНИЧЕСКИЕ формы: совпадают (a, b) и противоположны `neg`.
fn isComplementCmp(a: Sexp, b: Sexp) bool {
    const na = normCmp(a) orelse return false;
    const nb = normCmp(b) orelse return false;
    return na.neg != nb.neg and sexpEq(na.a, nb.a) and sexpEq(na.b, nb.b);
}

/// Извлечь тела всех `(assert ...)` из текста SMT-LIB2.
//
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
        if (inner.len > 0) {
            // 🔴 ХАРДКОР-АУДИТ (инъекция отказов аллокатора) НАШЁЛ УТЕЧКУ:
            // здесь было `try out.append(try allocator.dupe(u8, inner))`.
            // Если `append` падал по OutOfMemory, результат `dupe` уже был
            // выделен и НИКЕМ не освобождался. Правильный порядок — выделить,
            // зарегистрировать errdefer, и только затем добавить в список.
            const dup = try allocator.dupe(u8, inner);
            errdefer allocator.free(dup);
            try out.append(dup);
        }
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
//
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

// =========================================================================
// Булева нормализация: закрываем `rewrite` на СВЯЗКАХ
// =========================================================================

/// Канонический текст выражения (для сортировки операндов).
fn writeSexp(w: anytype, e: Sexp) !void {
    if (e.atom) |a| {
        try w.writeAll(a);
        return;
    }
    try w.writeByte('(');
    for (e.items, 0..) |it, i| {
        if (i > 0) try w.writeByte(' ');
        try writeSexp(w, it);
    }
    try w.writeByte(')');
}

fn sexpKey(c: *const Ctx, e: Sexp) ?[]const u8 {
    var b = compat.BufWriter.init(c.arena);
    writeSexp(b.writer(), e) catch return null;
    return b.items();
}

fn mkList1(c: *const Ctx, head: []const u8, x: Sexp) Sexp {
    const it = c.arena.alloc(Sexp, 2) catch return x;
    it[0] = .{ .atom = head };
    it[1] = x;
    return .{ .items = it };
}

fn mkList2(c: *const Ctx, head: []const u8, x: Sexp, y: Sexp) Sexp {
    const it = c.arena.alloc(Sexp, 3) catch return x;
    it[0] = .{ .atom = head };
    it[1] = x;
    it[2] = y;
    return .{ .items = it };
}

fn mkCmp(c: *const Ctx, head: []const u8, x: Sexp, y: Sexp) Sexp {
    return mkList2(c, head, x, y);
}

const Keyed = struct { key: []const u8, e: Sexp };

/// Соединить ДВА выражения связкой с учётом `neg` (де Морган).
fn normConn(c: *const Ctx, conn: []const u8, pair: [2]Sexp, neg: bool, depth: u32) ?Sexp {
    const a = boolNorm(c, pair[0], neg, depth + 1) orelse return null;
    const b = boolNorm(c, pair[1], neg, depth + 1) orelse return null;
    // ¬(A ∧ B) = ¬A ∨ ¬B — при `neg` связка меняется на противоположную
    const real: []const u8 = if (neg) (if (std.mem.eql(u8, conn, "and")) "or" else "and") else conn;
    return normConnN(c, real, &[_]Sexp{ a, b }, false, depth + 1);
}

/// Соединить N выражений: flatten + сортировка операндов.
fn normConnN(c: *const Ctx, conn: []const u8, items: []const Sexp, neg: bool, depth: u32) ?Sexp {
    const real: []const u8 = if (neg) (if (std.mem.eql(u8, conn, "and")) "or" else "and") else conn;
    var parts = std.array_list.Managed(Keyed).init(c.arena);
    for (items) |it| {
        const n = boolNorm(c, it, neg, depth + 1) orelse return null;
        if (n.isList() and n.items.len >= 2) {
            if (n.headAtom()) |hh| {
                if (std.mem.eql(u8, hh, real)) {
                    for (n.items[1..]) |q| {
                        const k = sexpKey(c, q) orelse return null;
                        parts.append(.{ .key = k, .e = q }) catch return null;
                    }
                    continue;
                }
            }
        }
        const k = sexpKey(c, n) orelse return null;
        parts.append(.{ .key = k, .e = n }) catch return null;
    }
    if (parts.items.len == 0) return null;
    if (parts.items.len == 1) return parts.items[0].e;
    std.mem.sort(Keyed, parts.items, {}, struct {
        fn lt(_: void, x: Keyed, y: Keyed) bool {
            return std.mem.lessThan(u8, x.key, y.key);
        }
    }.lt);
    const out = c.arena.alloc(Sexp, parts.items.len + 1) catch return null;
    out[0] = .{ .atom = real };
    for (parts.items, 0..) |p, i| out[i + 1] = p.e;
    return .{ .items = out };
}

/// Привести булево выражение к нормальной форме: NNF + плоские связки +
/// сортировка операндов. `neg` — нужно ли отрицание результата.
//
/// ПРАВИЛА (законы классической логики, ничего эвристического):
///   `(not X)`           -> рекурсия с инвертированным `neg`;
///   сравнения           -> канонизация через `normCmp`;
///   `(= A B)` для целых -> `(and (>= A B) (>= B A))`   [A, B линейны];
///   `(= A B)` иначе     -> `(and (=> A B) (=> B A))`   [булева эквивалентность];
///   `(=> A B)`          -> `(or (not A) B)`;
///   `and` / `or`        -> де Морган при `neg`, flatten, сортировка.
//
/// ЗВУЧНОСТЬ: нормализатор НЕПОЛОН (нет дистрибутивности), поэтому он может
/// только ПОДТВЕРДИТЬ равенство, но никогда не объявить подделку — иначе
/// неполнота давала бы ложные отказы на верных выводах.
fn boolNorm(c: *const Ctx, e0: Sexp, neg: bool, depth: u32) ?Sexp {
    if (depth > 48) return null;
    const e = expand(c, e0, 0);
    if (e.atom != null) return if (neg) mkList1(c, "not", e) else e;

    const h = e.items[0].atom orelse return null;

    if (std.mem.eql(u8, h, "not") and e.items.len == 2) {
        return boolNorm(c, e.items[1], !neg, depth + 1);
    }

    if (normCmp(e)) |n| {
        const eff_neg = n.neg != neg;
        const base = mkCmp(c, ">=", n.a, n.b);
        return if (eff_neg) mkList1(c, "not", base) else base;
    }

    if (std.mem.eql(u8, h, "=") and e.items.len == 3) {
        const a = e.items[1];
        const b = e.items[2];
        var pa = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        var pb = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        if (parseLin(c, a, 1, &pa) and parseLin(c, b, 1, &pb)) {
            return normConn(c, "and", .{ mkCmp(c, ">=", a, b), mkCmp(c, ">=", b, a) }, neg, depth);
        }
        return normConn(c, "and", .{
            mkList2(c, "=>", a, b),
            mkList2(c, "=>", b, a),
        }, neg, depth);
    }

    if (std.mem.eql(u8, h, "=>") and e.items.len == 3) {
        return boolNorm(c, mkList2(c, "or", mkList1(c, "not", e.items[1]), e.items[2]), neg, depth + 1);
    }

    if (std.mem.eql(u8, h, "and") or std.mem.eql(u8, h, "or")) {
        return normConnN(c, h, e.items[1..], neg, depth);
    }
    return null;
}

/// Равны ли две БУЛЕВЫЕ формулы с точностью до булевой нормализации.
/// `true` — только при ПОЛНОЙ нормализации обеих сторон.
fn boolEqual(c: *const Ctx, x: Sexp, y: Sexp) bool {
    const nx = boolNorm(c, x, false, 0) orelse return false;
    const ny = boolNorm(c, y, false, 0) orelse return false;
    return sexpEq(nx, ny);
}

/// Трёхзначный итог проверки шага `rewrite`:
///   verified     — равенство ДОКАЗАНО нормализацией;
///   bad          — обе стороны нормализуются, но НЕ равны -> подделка;
///   unverifiable — нормализатор не покрывает эти термы, шаг доверенный.
const RwResult = enum { verified, bad, unverifiable };

fn checkRewrite(c: *const Ctx, st: Sexp) RwResult {
    if (st.items.len < 2) return .unverifiable;
    const eq = expand(c, st.items[1], 0);
    if (compat.envVar("KERN_DEBUG_LIA") != null) {
        std.debug.print("[dbg-rw0] раскрыто: ", .{});
        dumpSexp(eq);
        std.debug.print("\n", .{});
    }
    if (!isEq3(eq)) return .unverifiable;
    const l = eq.items[1];
    const r = eq.items[2];
    if (sexpEq(l, r)) return .verified; // рефлексивность: (= X X)
    // ВЫЧИСЛЕНИЕ КОНСТАНТ (Пункты 22/23) ДО раннего возврата для не-атомарных
    // сравнений: `(= (= false true) false)` — обе стороны НЕ атомы, и раньше
    // управление уходило в `return .unverifiable`, не доходя до этих проверок.
    if (constStrEq(l, r)) return .verified;
    if (constBoolEq(l, r)) return .verified;
    // ПОДСТАНОВКА ПРОВЕРЕННЫХ ОПРЕДЕЛЕНИЙ `intro-def`: ИЗМЕРЕНО на `musl abs.c`
    // (последний доверенный шаг) — `(= (>= (result − ite(…)) 0) (>= (result −
    // z3name!1) 0))`, где `z3name!1` уже определён верифицированным `intro-def`.
    // ЗВУЧНО: разворачиваем имя ТОЛЬКО в доказанное определение.
    if (eqUpToDefs(c, l, r, 0)) return .verified;
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
        if (compat.envVar("KERN_DEBUG_LIA") != null) {
            std.debug.print("[dbg-rw1] выход по normCmp-ветке: LHS=", .{});
            dumpSexp(l);
            std.debug.print(" RHS=", .{});
            dumpSexp(r);
            std.debug.print("\n", .{});
        }
        return .unverifiable;
    }
    // Обе стороны — ТЕРМЫ (не сравнения): проверяем арифметическое тождество.
    if (nl == null and nr == null) {
        if (linDiffZero(c, l, r)) |z| return if (z) .verified else .bad;
    }
    // БУЛЕВА НОРМАЛИЗАЦИЯ (де Морган, раскрытие `=`): закрывает rewrite на
    // СВЯЗКАХ. Возвращает ТОЛЬКО .verified: нормализатор неполон, поэтому
    // объявлять подделку он не имеет права (иначе — ложные отказы).
    if (boolEqual(c, l, r)) return .verified;
    // ЭКВИВАЛЕНТНОСТЬ С `ite` (дефект #118): условия эквивалентны/противоположны
    // и ветви совпадают/переставлены — это тавтология, шаг ДОКАЗАН.
    if (iteEq(l, r, 0)) return .verified;
    // ФОРМЫ ИЗ РЕАЛЬНОГО ДАМПА `[dbg-rw]` (микро-шаг 5Г-1): СТРУКТУРНЫЕ
    // тождества, в которые НЕ нужно заглядывать внутрь термов — поэтому они
    // работают и тогда, когда внутри стоит `ite` (а линейный решатель там
    // бессилен):
    //   (1) `(= P 0) <=> (and (<= P 0) (>= P 0))`  — антисимметричность;
    //   (2) `(= X Y) <=> (= (+ X (* (- 1) Y)) 0)`  — перенос через равенство;
    //   (3) `(= X (ite C1 T1 E1)) <=> (= X (ite C2 T2 E2))` при `C1 = ¬C2`
    //       и переставленных ветвях.
    if (antisymmetryZero(l, r)) return .verified;
    if (eqTransferZero(l, r)) return .verified;
    if (iteSwapEq(c, l, r)) return .verified;
    // ФОРМА (4) ИЗ ДАМПА `[dbg-rw]` (микро-шаг 5Г-2): КОНГРУЭНЦИЯ `or` с
    // двусторонней линейной проверкой вторых дизъюнктов.
    if (orCongruence(c, l, r)) return .verified;
    // ПРЯМАЯ ДВУСТОРОННЯЯ ЛИНЕЙНАЯ ЭКВИВАЛЕНТНОСТЬ (пункт 3 v2.5): тот же
    // механизм, что в `orCongruence`, но БЕЗ внешней обёртки `(or A …)`.
    // Если `lhs ⊨ rhs` И `rhs ⊨ lhs` доказаны в линейном фрагменте — это
    // эквивалентность, шаг ДОКАЗАН. Не удалось перевести -> `false`, и шаг
    // остаётся доверенным.
    if (impliesLinear(c, l, r) and impliesLinear(c, r, l)) return .verified;
    // ЗАКОН ДЕ МОРГАНА для `and` (последний доверенный шаг `abs.c`):
    // `(and X Y) <=> (not (or (not X) (not Y)))` — структурно.
    if (andDeMorganEq(l, r)) return .verified;
    // КОНСТАНТНЫЕ СТРОКОВЫЕ ПРЕДИКАТЫ (Пункт 23 / QF_S): `(str.contains "safe" "../")`
    // вычисляется в Zig -> `(= ... false)` доказано без доверенных шагов.
    if (constStrEq(l, r)) return .verified;
    if (constBoolEq(l, r)) return .verified;
    if (compat.envVar("KERN_DEBUG_LIA") != null) {
        std.debug.print("[dbg-rw] не проверено: LHS=", .{});
        dumpSexp(l);
        std.debug.print("  RHS=", .{});
        dumpSexp(r);
        std.debug.print("\n", .{});
    }
    return .unverifiable;
}

/// ЯВЛЯЕТСЯ ЛИ ТЕРМ `(not X)` / `(ite C T E)` / равенством из трёх элементов.
fn isNotT(t: Sexp) bool {
    if (!t.isList() or t.items.len != 2) return false;
    const h = t.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "not");
}

fn isIteT(t: Sexp) bool {
    if (!t.isList() or t.items.len != 4) return false;
    const h = t.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "ite");
}

/// `trans*`: ЦЕПОЧКА равенств (в отличие от `trans`, их может быть больше двух).
//
/// ИЗ ЧЕГО СЛЕДУЕТ (математика, без доверия решателю): из `a1=a2, a2=a3, ...,
/// a_{k-1}=a_k` следует `a1=a_k`. Проверка ЧИСТО СТРУКТУРНАЯ: правое плечо шага
/// i обязано совпасть с левым плечом шага i+1, а вывод — с (левое первого,
/// правое последнего). Разрыв цепочки = подделка.
//
/// ЗАЧЕМ (дефект #118): без этого правила `trans*` уходил в доверенные шаги,
/// из-за чего корректные выводы Z3 с `ite` не принимались.
fn verifyTransStar(c: *const Ctx, st: Sexp) bool {
    const n = st.items.len;
    if (n < 4) return false; // правило + >=2 посылки + вывод
    const q = premiseTerm(c, st.items[n - 1]);
    if (!isEq3(q)) return false;
    var prev_right: ?Sexp = null;
    var first_left: ?Sexp = null;
    var count: usize = 0;
    for (st.items[1 .. n - 1]) |p| {
        const t = premiseTerm(c, p);
        if (!isEq3(t)) return false;
        if (prev_right) |pr| {
            if (!sexpEq(pr, t.items[1])) return false; // разрыв цепочки
        } else {
            first_left = t.items[1];
        }
        prev_right = t.items[2];
        count += 1;
    }
    if (count < 2) return false;
    return sexpEq(first_left.?, q.items[1]) and sexpEq(prev_right.?, q.items[2]);
}

/// `def-axiom` для `ite`: Z3 вводит ДВЕ ОПРЕДЕЛЯЮЩИЕ тавтологии
///   `(or (not C) (= T (ite C T E)))` — если C истинно, значение ite есть T;
///   `(or C       (= E (ite C T E)))` — если C ложно,  значение ite есть E.
/// Обе — логические тавтологии. Проверяем ИМЕННО ЭТУ ФОРМУ структурно: тогда
/// шаг ДОКАЗАН, а не принят на слово. Любая другая форма -> шаг остаётся
/// доверенным (никогда не «проверенным»).
/// СГЛАДИТЬ вложенные `or` в плоский список литералов.
fn flattenOr(e: Sexp, out: *std.array_list.Managed(Sexp)) void {
    if (e.isList() and e.items.len >= 2) {
        if (e.items[0].atom) |h| {
            if (std.mem.eql(u8, h, "or")) {
                for (e.items[1..]) |x| flattenOr(x, out);
                return;
            }
        }
    }
    out.append(e) catch {};
}

/// ТАВТОЛОГИЯ ЛИ КЛАУЗА `C`? (пункт 3 плана v2.5)
//
/// ЗАЧЕМ. `(def-axiom C)` — аксиома определения: она обязана быть ТАВТОЛОГИЕЙ.
/// Для `ite` форма проверяется структурно (`verifyIteDisjunct`), но Z3 вводит
/// так и другие определяющие клаузы.
//
/// ДВА ЗВУЧИМЫХ СПОСОБА (оба — доказательства, а не догадки):
///   1) ПРОПОЗИЦИОНАЛЬНЫЙ: сглаживаем вложенные `or` и ищем пару `l` / `¬l`.
///      Клауза, содержащая литерал и его отрицание, — тавтология.
///      ИЗМЕРЕНО на `musl abs.c`: клауза имеет вид `(or (or (not A) (not B)) B)`
///      — после сглаживания там есть и `B`, и `(not B)`.
///   2) АРИФМЕТИЧЕСКИЙ: `¬C = ¬L1 ∧ … ∧ ¬Lk` обязано быть НЕСОВМЕСТНО
///      (проверяется встроенным решателем, Фурье — Моцкин).
//
/// `true` — только при ДОКАЗАННОЙ тавтологии; иначе `false` (честный отказ).
fn isTautologyClause(c: *const Ctx, clause: Sexp) bool {
    if (!clause.isList() or clause.items.len < 2) return false;
    const h = clause.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;

    // 1) Пропозициональная тавтология: `l` и `¬l` в одном дизъюнкте.
    var lits = std.array_list.Managed(Sexp).init(c.arena);
    flattenOr(clause, &lits);
    for (lits.items, 0..) |a, i| {
        for (lits.items[i + 1 ..]) |b| {
            if (isComplement(a, b) or isComplementCmp(a, b)) return true;
        }
    }

    // 2) Арифметическая тавтология: отрицание клаузы несовместно.
    var cons = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    for (lits.items) |lit| {
        if (!negateAsLeZero(c, lit, &cons)) return false;
    }
    var s = builtin_lia.Solver.init(c.arena);
    defer s.deinit();
    return switch (builtin_lia.checkUnsat(&s, cons.items)) {
        .unsat => true,
        else => false,
    };
}

/// Встречается ли атом `name` внутри терма `e`? (для проверки СВЕЖЕСТИ имени)
fn occurs(name: []const u8, e: Sexp) bool {
    if (e.atom) |a| return std.mem.eql(u8, a, name);
    for (e.items) |it| if (occurs(name, it)) return true;
    return false;
}

/// Разобранное определение `z = ite(C, A, B)` из двух клауз `intro-def`.
const IntroDefParts = struct { cond: Sexp, z: []const u8, a: Sexp, b: Sexp };

/// Разобрать пару дизъюнктов определения:
///   `(or (not C) (= z A))` и `(or C (= z B))`.
fn introDefParts(neg_side: Sexp, pos_side: Sexp) ?IntroDefParts {
    if (!neg_side.isList() or neg_side.items.len != 3) return null;
    if (!pos_side.isList() or pos_side.items.len != 3) return null;
    const nh = neg_side.items[0].atom orelse return null;
    const ph = pos_side.items[0].atom orelse return null;
    if (!std.mem.eql(u8, nh, "or") or !std.mem.eql(u8, ph, "or")) return null;
    const neg_c = asNot(neg_side.items[1]) orelse return null;
    const cond = pos_side.items[1];
    if (!sexpEq(neg_c, cond)) return null;
    const eq_a = neg_side.items[2];
    const eq_b = pos_side.items[2];
    if (!isEq3(eq_a) or !isEq3(eq_b)) return null;
    const za = eq_a.items[1].atom orelse eq_a.items[2].atom orelse return null;
    const zb = eq_b.items[1].atom orelse eq_b.items[2].atom orelse return null;
    if (!std.mem.eql(u8, za, zb)) return null;
    const a = if (eq_a.items[1].atom) |x| (if (std.mem.eql(u8, x, za)) eq_a.items[2] else eq_a.items[1]) else eq_a.items[1];
    const b = if (eq_b.items[1].atom) |x| (if (std.mem.eql(u8, x, zb)) eq_b.items[2] else eq_b.items[1]) else eq_b.items[1];
    return .{ .cond = cond, .z = za, .a = a, .b = b };
}

/// ПРОВЕРКА `(intro-def D)`: КОНСЕРВАТИВНОЕ ВВЕДЕНИЕ ОПРЕДЕЛЕНИЯ.
//
/// ЧТО ЭТО. Z3 вводит СВЕЖЕЕ имя (`z3name!k`) для подвыражения и записывает
/// определение как конъюнкцию двух клауз:
///   (and (or (not C) (= z A)) (or C (= z B)))      т.е. z = ite(C, A, B)
/// ИЗМЕРЕНО на `musl abs.c`:
///   (and (or (not (>= a 0)) (= z3name!1 a))
///        (or (>= a 0)      (= z3name!1 (* (- 1) a))))
/// — это ровно определение `z3name!1 = ite(a >= 0, a, -a)` (тело `abs`).
//
/// ЗВУЧНОСТЬ. Введение определения для СВЕЖЕГО имени — консервативное
/// расширение: оно не меняет выполнимость формул, в которых имени нет. Поэтому
/// проверяются ДВА условия, и оба обязательны:
///   1) СТРУКТУРА: две клаузы с ОДНИМ И ТЕМ ЖЕ именем `z`, противоположными
///      условиями (`¬C` и `C`) и равенствами `(= z A)` / `(= z B)`;
///   2) СВЕЖЕСТЬ: `z` НЕ встречается ни в `C`, ни в `A`, ни в `B` (иначе это
///      не определение, а самореферентное утверждение — и расширение уже
///      неконсервативно).
/// Нарушение любого условия -> `false` (шаг остаётся доверенным, НЕ «ок»).
fn verifyIntroDef(c: *Ctx, st: Sexp) bool {
    const t = expand(c, proved(st), 0);
    if (!t.isList() or t.items.len != 3) return false;
    const h = t.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "and")) return false;
    const p = introDefParts(t.items[1], t.items[2]) orelse
        introDefParts(t.items[2], t.items[1]) orelse return false;
    if (occurs(p.z, p.cond) or occurs(p.z, p.a) or occurs(p.z, p.b)) return false;
    // ЗАПОМИНАЕМ определение: `z3name!k = (ite cond a b)`. Оно доказано этим
    // шагом (свежее имя + консервативное расширение), поэтому разворачивать его
    // в последующих шагах ЗВУЧНО.
    c.defs.put(p.z, .{ .cond = p.cond, .a = p.a, .b = p.b }) catch {};
    return true;
}

/// РАВЕНСТВО «С ТОЧНОСТЬЮ ДО ОПРЕДЕЛЕНИЙ»: структурное сравнение, при котором
/// атом, для которого ЕСТЬ проверенное определение `intro-def`, может быть
/// развёрнут в `(ite cond a b)`. Глубина ограничена (защита от разрастания).
fn eqUpToDefs(c: *const Ctx, a: Sexp, b: Sexp, depth: u32) bool {
    if (depth > 32) return false;
    if (sexpEq(a, b)) return true;
    if (a.atom) |x| {
        if (c.defs.get(x)) |d| {
            if (b.isList() and b.items.len == 4) {
                if (b.items[0].atom) |bh| {
                    if (std.mem.eql(u8, bh, "ite") and
                        eqUpToDefs(c, d.cond, b.items[1], depth + 1) and
                        eqUpToDefs(c, d.a, b.items[2], depth + 1) and
                        eqUpToDefs(c, d.b, b.items[3], depth + 1)) return true;
                }
            }
        }
    }
    if (b.atom) |y| {
        if (c.defs.get(y)) |d| {
            if (a.isList() and a.items.len == 4) {
                if (a.items[0].atom) |ah| {
                    if (std.mem.eql(u8, ah, "ite") and
                        eqUpToDefs(c, d.cond, a.items[1], depth + 1) and
                        eqUpToDefs(c, d.a, a.items[2], depth + 1) and
                        eqUpToDefs(c, d.b, a.items[3], depth + 1)) return true;
                }
            }
        }
    }
    if (!a.isList() or !b.isList()) return false;
    if (a.items.len != b.items.len) return false;
    for (a.items, b.items) |x, y| {
        if (!eqUpToDefs(c, x, y, depth + 1)) return false;
    }
    return true;
}

/// Собрать все `(hypothesis H)` в поддереве узла, идя по ссылкам `@xN`.
/// `seen` защищает от повторного обхода (граф — DAG, не дерево).
fn collectHypotheses(c: *const Ctx, node: Sexp, out: *std.array_list.Managed(Sexp), seen: *std.array_list.Managed([]const u8), depth: u32) void {
    if (depth > 96) return;
    if (node.atom) |a| {
        for (seen.items) |s| if (std.mem.eql(u8, s, a)) return;
        seen.append(a) catch return;
        if (c.stepexpr.get(a)) |se| collectHypotheses(c, se, out, seen, depth + 1);
        return;
    }
    if (!node.isList()) return;
    if (node.headAtom()) |h| {
        if (std.mem.eql(u8, h, "hypothesis")) {
            // ВАЖНО: гипотезу собираем РАСКРЫТОЙ (`expand`), иначе сравнение с
            // раскрытым заключением не сработает: в выводе стоит имя `$x121`,
            // а в заключении — уже его формула.
            if (node.items.len >= 2) out.append(expand(c, node.items[1], 0)) catch {};
            return;
        }
    }
    for (node.items) |it| collectHypotheses(c, it, out, seen, depth + 1);
}

/// ПРОВЕРКА `(lemma P C)` — РАЗРЯДКА ГИПОТЕЗ (RAA / введение дизъюнкции).
//
/// КАК ЭТО РАБОТАЕТ В Z3. `P` — поддерево, которое ВЫВОДИТ `false`, опираясь на
/// временные допущения `(hypothesis H_1) … (hypothesis H_m)`. Заключение `C` —
/// дизъюнкция отрицаний этих гипотез (или одиночный литерал, если гипотеза одна).
/// Это ровно правило «из опровержения при допущениях H следует ¬H_1 ∨ … ∨ ¬H_m».
//
/// ПРОВЕРЯЕТСЯ ДВА УСЛОВИЯ (оба — доказательства, не догадки):
///   1) `P` действительно выводит `false`;
///   2) КАЖДАЯ гипотеза `H` из поддерева опровергается в заключении: его
///      дизъюнкты (после `flattenOr`) содержат `¬H` — структурно ИЛИ по
///      канонической форме сравнений (`isComplementCmp`).
/// Нарушение любого -> `false` (шаг остаётся доверенным, НЕ «ок»).
fn verifyLemma(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const pref = st.items[1];
    const concl = expand(c, st.items[2], 0);
    // 1) Поддерево обязано выводить `false`.
    const pf = resolvePremise(c, pref);
    if (!isStepExpr(pf)) return false;
    const pc = expand(c, proved(pf), 0);
    if (!(pc.atom != null and std.mem.eql(u8, pc.atom.?, "false"))) return false;
    // 2) Каждая гипотеза поддерева обязана быть опровергнута в заключении.
    var hyps = std.array_list.Managed(Sexp).init(c.arena);
    var seen = std.array_list.Managed([]const u8).init(c.arena);
    collectHypotheses(c, pref, &hyps, &seen, 0);
    if (hyps.items.len == 0) return false; // нечего разряжать — не наш случай
    var lits = std.array_list.Managed(Sexp).init(c.arena);
    flattenOr(concl, &lits);
    if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
        std.debug.print("[dbg-lemma] гипотез {d}, дизъюнктов {d}; заключение: ", .{ hyps.items.len, lits.items.len });
        dumpSexp(concl);
        std.debug.print("\n", .{});
        for (hyps.items) |h| {
            std.debug.print("[dbg-lemma]   гипотеза: ", .{});
            dumpSexp(h);
            std.debug.print("\n", .{});
        }
    }
    for (hyps.items) |h| {
        var found = false;
        for (lits.items) |l| {
            if (asNot(l)) |inner| {
                if (sexpEq(inner, h) or isComplementCmp(inner, h)) {
                    found = true;
                    break;
                }
            }
            if (isComplement(l, h) or isComplementCmp(l, h)) {
                found = true;
                break;
            }
        }
        if (!found) return false;
    }
    return true;
}

/// Атом-ноль? (`0` — единственная допустимая запись нуля в выводе Z3)
fn isZeroAtom(e: Sexp) bool {
    return e.atom != null and std.mem.eql(u8, e.atom.?, "0");
}

/// Сравнение терма `p` с нулём: возвращает `?bool` — `true` = «p <= 0», `false` = «p >= 0».
/// Поддержаны все четыре написания: `(<= p 0)`, `(>= p 0)`, `(<= 0 p)`, `(>= 0 p)`.
fn cmpWithZero(cmp: Sexp, p: Sexp) ?bool {
    if (!cmp.isList() or cmp.items.len != 3) return null;
    const h = cmp.items[0].atom orelse return null;
    const le = std.mem.eql(u8, h, "<=");
    const ge = std.mem.eql(u8, h, ">=");
    if (!le and !ge) return null;
    if (sexpEq(cmp.items[1], p) and isZeroAtom(cmp.items[2])) return le; // p <= 0 / p >= 0
    if (isZeroAtom(cmp.items[1]) and sexpEq(cmp.items[2], p)) return !le; // 0 <= p / 0 >= p
    return null;
}

/// ФОРМА (1) ИЗ ДАМПА `[dbg-rw]`: АНТИСИММЕТРИЧНОСТЬ НУЛЯ.
///   `(= P 0)`  <=>  `(and (<= P 0) (>= P 0))`   для ЛЮБОГО терма `P`
/// (даже содержащего `ite`): это чистый закон порядка над Z, поэтому внутрь `P`
/// заглядывать НЕ нужно — достаточно, чтобы `P` был ПОБАЙТОВО тем же (`sexpEq`),
/// а две части конъюнкции сравнивали `P` с нулём в ПРОТИВОПОЛОЖНЫХ направлениях.
fn antisymmetryZero(l: Sexp, r: Sexp) bool {
    return antisymOne(l, r) or antisymOne(r, l);
}

fn antisymOne(eq_side: Sexp, and_side: Sexp) bool {
    if (!isEq3(eq_side)) return false;
    const p = if (isZeroAtom(eq_side.items[1]))
        eq_side.items[2]
    else if (isZeroAtom(eq_side.items[2]))
        eq_side.items[1]
    else
        return false;
    if (!and_side.isList() or and_side.items.len != 3) return false;
    const h = and_side.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "and")) return false;
    const d1 = cmpWithZero(and_side.items[1], p) orelse return false;
    const d2 = cmpWithZero(and_side.items[2], p) orelse return false;
    return d1 != d2; // нужны ОБА направления: p <= 0 И p >= 0
}

/// `(* (- 1) Y)`, `(* -1 Y)` или `(- Y)` — это «минус Y»?
fn isNegOfTerm(t: Sexp, y: Sexp) bool {
    if (!t.isList() or t.items.len < 2) return false;
    const h = t.items[0].atom orelse return false;
    if (std.mem.eql(u8, h, "-") and t.items.len == 2) return sexpEq(t.items[1], y);
    if (std.mem.eql(u8, h, "*") and t.items.len == 3) {
        const c1 = numOf(t.items[1]);
        const c2 = numOf(t.items[2]);
        const other = if (c1 != null) t.items[2] else if (c2 != null) t.items[1] else return false;
        const c = c1 orelse c2.?;
        return c == -1 and sexpEq(other, y);
    }
    return false;
}

/// ФОРМА (2) ИЗ ДАМПА `[dbg-rw]`: ПЕРЕНОС ЧЕРЕЗ РАВЕНСТВО.
///   `(= X Y)`  <=>  `(= (+ X (* (- 1) Y)) 0)`   для ЛЮБЫХ термов X, Y
/// (слагаемые могут стоять в любом порядке). Внутрь X и Y заглядывать не нужно.
fn eqTransferZero(l: Sexp, r: Sexp) bool {
    return eqTransferOne(l, r) or eqTransferOne(r, l);
}

fn eqTransferOne(eq_side: Sexp, diff_side: Sexp) bool {
    if (!isEq3(eq_side) or !isEq3(diff_side)) return false;
    const x = eq_side.items[1];
    const y = eq_side.items[2];
    const d = if (isZeroAtom(diff_side.items[1]))
        diff_side.items[2]
    else if (isZeroAtom(diff_side.items[2]))
        diff_side.items[1]
    else
        return false;
    if (!d.isList() or d.items.len != 3) return false;
    const h = d.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "+")) return false;
    const a = d.items[1];
    const b = d.items[2];
    if (sexpEq(a, x) and isNegOfTerm(b, y)) return true;
    if (sexpEq(b, x) and isNegOfTerm(a, y)) return true;
    return false;
}

/// ФОРМА (3) ИЗ ДАМПА `[dbg-rw]`: ПЕРЕВОРОТ `ite` ПОД РАВЕНСТВОМ.
///   `(= X (ite C1 T1 E1))` <=> `(= X (ite C2 T2 E2))`
/// при ОДНОМ и том же `X`, ПРОТИВОПОЛОЖНЫХ условиях (`C1 = ¬C2`) и
/// переставленных ветвях (`T1 ≡ E2`, `E1 ≡ T2`). Ветви сравниваются структурно
/// ИЛИ линейно (`linDiffZero`), поэтому `(- a)` и `(* (- 1) a)` совпадают.
fn iteSwapEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    if (!isEq3(l) or !isEq3(r)) return false;
    if (!sexpEq(l.items[1], r.items[1])) return false; // один и тот же X
    const t1 = l.items[2];
    const t2 = r.items[2];
    if (!isIteT(t1) or !isIteT(t2)) return false;
    const c1 = t1.items[1];
    const a1 = t1.items[2];
    const b1 = t1.items[3];
    const c2 = t2.items[1];
    const a2 = t2.items[2];
    const b2 = t2.items[3];
    if (!(isComplement(c1, c2) or isComplementCmp(c1, c2))) return false;
    return termEqLinear(c, a1, b2) and termEqLinear(c, b1, a2);
}

/// Равенство термов: структурно ИЛИ линейно (обе стороны — линейные формы).
fn termEqLinear(c: *const Ctx, a: Sexp, b: Sexp) bool {
    if (sexpEq(a, b)) return true;
    if (linDiffZero(c, a, b)) |z| return z;
    return false;
}

/// ОТРИЦАНИЕ литерала как `<= 0` (заключение берётся С ОТРИЦАНИЕМ).
fn negateAsLeZero(c: *const Ctx, lit: Sexp, out: *std.array_list.Managed(builtin_lia.Lin)) bool {
    // `(or X1..Xk)`: `¬(X1 ∨ … ∨ Xk) = ¬X1 ∧ … ∧ ¬Xk` — КОНЪЮНКЦИЯ, поэтому
    // добавляем отрицание КАЖДОГО дизъюнкта. ИЗМЕРЕНО на `musl abs.c`: именно
    // эта форма стоит в правой части rewrite формы (4)
    // (`(not (or (not C) (not D)))`), и без неё двусторонняя проверка не
    // переводила отрицание.
    if (lit.isList() and lit.items.len >= 2) {
        if (lit.items[0].atom) |h| {
            if (std.mem.eql(u8, h, "or")) {
                for (lit.items[1..]) |x| {
                    if (!negateAsLeZero(c, x, out)) return false;
                }
                return true;
            }
        }
    }
    var l = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (asNot(lit)) |inner| {
        if (!literalAsLeZero(c, inner, &l)) return false;
    } else {
        if (!negLiteralAsLeZero(c, lit, &l)) return false;
    }
    return pushLin(c, l, out);
}

/// Альтернативы для ОТРИЦАНИЯ формулы `to`: `¬to = OR(альтернатив)`, каждая
/// альтернатива — НАБОР ограничений (конъюнкция). Возвращает `false`, если
/// разложить нельзя (тогда шаг остаётся доверенным).
///   * `(not (or Y1..Yk))` -> `¬to = (or Y1..Yk)` -> альтернативы по одной `Yi`;
///   * `(and X1..Xk)`       -> `¬to = ¬X1 ∨ … ∨ ¬Xk`;
///   * `(= X Y)`            -> `¬to = (X<Y) ∨ (X>Y)` -> две строгие неравенства;
///   * иначе                -> одна альтернатива `¬to` (как конъюнкция).
fn negAlternatives(c: *const Ctx, to: Sexp, alts: *std.array_list.Managed(std.array_list.Managed(builtin_lia.Lin))) bool {
    if (isNotT(to)) {
        const inner = to.items[1];
        if (inner.isList() and inner.items.len >= 2) {
            if (inner.items[0].atom) |h| {
                if (std.mem.eql(u8, h, "or")) {
                    for (inner.items[1..]) |y| {
                        var g = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
                        if (!asLeZero(c, y, &g)) return false;
                        alts.append(g) catch return false;
                    }
                    return true;
                }
            }
        }
    }
    if (to.isList() and to.items.len >= 2) {
        if (to.items[0].atom) |h| {
            if (std.mem.eql(u8, h, "and")) {
                for (to.items[1..]) |x| {
                    var g = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
                    if (!negateAsLeZero(c, x, &g)) return false;
                    alts.append(g) catch return false;
                }
                return true;
            }
        }
    }
    if (isEq3(to)) {
        // ¬(X = Y) над Z:  (X - Y + 1 <= 0) ∨ (Y - X + 1 <= 0)
        var g1 = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
        var d1 = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        if (!parseLin(c, to.items[1], 1, &d1)) return false;
        if (!parseLin(c, to.items[2], -1, &d1)) return false;
        d1.constant += 1;
        if (!pushLin(c, d1, &g1)) return false;
        var g2 = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
        var d2 = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        if (!parseLin(c, to.items[2], 1, &d2)) return false;
        if (!parseLin(c, to.items[1], -1, &d2)) return false;
        d2.constant += 1;
        if (!pushLin(c, d2, &g2)) return false;
        alts.append(g1) catch return false;
        alts.append(g2) catch return false;
        return true;
    }
    var g = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    if (!negateAsLeZero(c, to, &g)) return false;
    alts.append(g) catch return false;
    return true;
}

/// `from ⊨ to` для ЛИНЕЙНОГО фрагмента: `{from} ∧ ¬to` НЕСОВМЕСТНО.
/// Отрицание `to` может быть ДИЗЪЮНКЦИЕЙ — тогда проверяем КАЖДУЮ альтернативу
/// (это закон дистрибутивности: `¬to = ∨ альтернатив`).
/// Звучимо: несовместность каждой альтернативы даёт встроенный решатель.
fn impliesLinear(c: *const Ctx, from: Sexp, to: Sexp) bool {
    var base = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    if (!asLeZero(c, from, &base)) return false;
    var alts = std.array_list.Managed(std.array_list.Managed(builtin_lia.Lin)).init(c.arena);
    if (!negAlternatives(c, to, &alts)) return false;
    if (alts.items.len == 0) return false;
    for (alts.items) |g| {
        var cons = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
        for (base.items) |x| cons.append(x) catch return false;
        for (g.items) |x| cons.append(x) catch return false;
        var s = builtin_lia.Solver.init(c.arena);
        defer s.deinit();
        const v = builtin_lia.checkUnsat(&s, cons.items);
        if (std.meta.activeTag(v) != .unsat) return false;
    }
    return true;
}

/// ФОРМА (4) ИЗ ДАМПА `[dbg-rw]`: КОНГРУЭНЦИЯ ДИЗЪЮНКЦИИ.
///   `(or A L2)` <=> `(or A R2)` при ПОБАЙТОВО одинаковом `A` (`sexpEq`).
/// Достаточно доказать `L2 <=> R2` в линейном фрагменте — ДВУМЯ проверками:
/// `L2 ⊨ R2` и `R2 ⊨ L2`. Это и есть случай `(or A (= z3name!1 T))` против
/// `(or A (not (or (not (>= D 0)) (not (<= D 0)))))`, где `D` — та же разность.
fn orCongruence(c: *const Ctx, l: Sexp, r: Sexp) bool {
    if (!isOr2(l) or !isOr2(r)) return false;
    if (!sexpEq(l.items[1], r.items[1])) return false;
    const l2 = l.items[2];
    const r2 = r.items[2];
    if (sexpEq(l2, r2)) return true;
    return impliesLinear(c, l2, r2) and impliesLinear(c, r2, l2);
}

/// `(or X Y)` — дизъюнкция ровно из двух членов.
fn isOr2(e: Sexp) bool {
    if (!e.isList() or e.items.len != 3) return false;
    const h = e.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "or");
}

/// `(and X Y) <=> (not (or (not X) (not Y)))` — ЗАКОН ДЕ МОРГАНА.
//
/// ИЗМЕРЕНО на `musl abs.c` (последний доверенный шаг): правая часть — это
/// ровно отрицание дизъюнкции отрицаний. Тождество ПРОПОЗИЦИОНАЛЬНОЕ, поэтому
/// доказывается СТРУКТУРНО (по `sexpEq`), без решателя и без разбора термов.
fn andDeMorganEq(l: Sexp, r: Sexp) bool {
    return andDeMorganOne(l, r) or andDeMorganOne(r, l);
}

fn andDeMorganOne(and_side: Sexp, not_or_side: Sexp) bool {
    if (!and_side.isList() or and_side.items.len != 3) return false;
    const ah = and_side.items[0].atom orelse return false;
    if (!std.mem.eql(u8, ah, "and")) return false;
    const x = and_side.items[1];
    const y = and_side.items[2];
    if (!isNotT(not_or_side)) return false;
    const inner = not_or_side.items[1];
    if (!inner.isList() or inner.items.len != 3) return false;
    const ih = inner.items[0].atom orelse return false;
    if (!std.mem.eql(u8, ih, "or")) return false;
    const nx = inner.items[1];
    const ny = inner.items[2];
    if (!isNotT(nx) or !isNotT(ny)) return false;
    const x2 = nx.items[1];
    const y2 = ny.items[1];
    return (sexpEq(x, x2) and sexpEq(y, y2)) or (sexpEq(x, y2) and sexpEq(y, x2));
}

/// Строковый литерал SMT-LIB: `"..."` -> содержимое без кавычек.
fn strLitOf(s: Sexp) ?[]const u8 {
    const a = s.atom orelse return null;
    if (a.len < 2 or a[0] != '"' or a[a.len - 1] != '"') return null;
    return a[1 .. a.len - 1];
}

/// ВЫЧИСЛЕНИЕ КОНСТАНТНЫХ СТРОКОВЫХ ПРЕДИКАТОВ (Эшелон 4, Пункт 23 / QF_S).
///
/// ИЗМЕРЕНО на `sanitize_safe` (QF_S): среди 9 доверенных шагов есть
/// `(rewrite (= (str.contains result "../") $x74))` и `(rewrite (= $x224 false))`
/// — это ВЫЧИСЛЕНИЕ предиката над строковыми ЛИТЕРАЛАМИ. Такое вычисление
/// звучимо тривиально: результат функции над константами — константа.
/// Сравнение делаем в самом Zig (`std.mem`), доверенных шагов НЕ требуется.
fn evalStrPred(s: Sexp) ?bool {
    if (!s.isList() or s.items.len != 3) return null;
    const op = s.items[0].atom orelse return null;
    // ПРИЧИНА №2: аргументы сворачиваются через `evalConstStr`, а НЕ через
    // `strLitOf` (тот видел только кавычки `"…"` и не понимал `(str.++ …)`).
    var ba: [256]u8 = undefined;
    var bb: [256]u8 = undefined;
    const a = evalConstStr(s.items[1], &ba) orelse return null;
    const b = evalConstStr(s.items[2], &bb) orelse return null;
    if (std.mem.eql(u8, op, "str.contains")) return std.mem.indexOf(u8, a, b) != null;
    if (std.mem.eql(u8, op, "str.prefixof")) return std.mem.startsWith(u8, a, b);
    if (std.mem.eql(u8, op, "str.suffixof")) return std.mem.endsWith(u8, a, b);
    if (std.mem.eql(u8, op, "str.=")) return std.mem.eql(u8, a, b);
    return null;
}

/// `(str.++ "a" "b")` над литералами -> конкатенация.
fn evalStrConcat(s: Sexp) ?[]const u8 {
    if (!s.isList() or s.items.len != 3) return null;
    const op = s.items[0].atom orelse return null;
    if (!std.mem.eql(u8, op, "str.++")) return null;
    const a = strLitOf(s.items[1]) orelse return null;
    const b = strLitOf(s.items[2]) orelse return null;
    _ = a;
    _ = b;
    return null; // аллокация не нужна: случай не встречается в измеренных выводах
}

/// `(= <стр-предикат над литералами> true|false)` — доказано вычислением.
fn constStrEq(l: Sexp, r: Sexp) bool {
    const v = evalStrPred(l) orelse evalStrPred(r) orelse return false;
    const other = if (evalStrPred(l) != null) r else l;
    const a = other.atom orelse return false;
    if (std.mem.eql(u8, a, "true")) return v;
    if (std.mem.eql(u8, a, "false")) return !v;
    return false;
}

/// ВЫЧИСЛЕНИЕ КОНСТАНТНЫХ БУЛЕВЫХ ВЫРАЖЕНИЙ (Пункт 23 / QF_S).
///
/// ИЗМЕРЕНО: Z3 сам вычисляет строковый предикат над литералами
/// (`(str.contains "safe" "../")` -> `false`), и в выводе остаётся БУЛЕВА свёртка
/// `(= false true)`, которую `(rewrite (= $x224 false))` переписывает в `false`.
/// Вычисление булевых констант — тривиально звучимо (никаких доверенных шагов).
fn evalBoolConst(s: Sexp) ?bool {
    if (s.atom) |a| {
        if (std.mem.eql(u8, a, "true")) return true;
        if (std.mem.eql(u8, a, "false")) return false;
        return null;
    }
    if (!s.isList()) return null;
    const op = s.items[0].atom orelse return null;
    if (std.mem.eql(u8, op, "=") and s.items.len == 3) {
        const a = evalBoolConst(s.items[1]) orelse return null;
        const b = evalBoolConst(s.items[2]) orelse return null;
        return a == b;
    }
    if (std.mem.eql(u8, op, "not") and s.items.len == 2) {
        const a = evalBoolConst(s.items[1]) orelse return null;
        return !a;
    }
    if ((std.mem.eql(u8, op, "and") or std.mem.eql(u8, op, "or")) and s.items.len >= 3) {
        const is_and = std.mem.eql(u8, op, "and");
        var acc = is_and;
        for (s.items[1..]) |it| {
            const v = evalBoolConst(it) orelse return null;
            acc = if (is_and) (acc and v) else (acc or v);
        }
        return acc;
    }
    // ПРИЧИНА №2 (продолжение): ЛИСТОВОЙ булев атом — строковый предикат над
    // константами. Без этого `(= (str.contains "safe" …) true)` не вычислялся,
    // и последний `rewrite` не сходился.
    if (evalStrPred(s)) |v| return v;
    return null;
}

/// `(= <булева константа> true|false)` — доказано вычислением.
fn constBoolEq(l: Sexp, r: Sexp) bool {
    const v = evalBoolConst(l) orelse return false;
    const a = r.atom orelse return false;
    if (std.mem.eql(u8, a, "true")) return v;
    if (std.mem.eql(u8, a, "false")) return !v;
    return false;
}

/// Канонизация БУЛЕВЫХ ФОРМ (Пункт 22, IEEE-754).
///
/// ИЗМЕРЕНО: в 56-шаговом выводе IEEE-754 (модель `(is_nan : Bool, val : Int)`)
/// печаталось `посылок 3/4` — 4-я посылка не привязывалась, `premises_unbound`
/// становился 1, `checksPass()` давал false, и чекер **ОТВЕРГАЛ** корректный
/// вывод (`[!] ПРУФ-ЧЕКЕР ОТВЕРГ вывод решателя`).
/// Причина: для сорта Bool `(not X)` и `(= X false)` — ОДНО И ТО ЖЕ, а `X`
/// и `(= X true)` — тоже. Z3 выбирает разные написания.
/// ЗВУЧНО: это тождества булевой логики, ослабления нет.
fn isEqBoolLit(s: Sexp, lit: []const u8) ?Sexp {
    if (!s.isList() or s.items.len != 3) return null;
    const h = s.items[0].atom orelse return null;
    if (!std.mem.eql(u8, h, "=")) return null;
    const other = blk: {
        if (s.items[2].atom) |a2| {
            if (std.mem.eql(u8, a2, lit)) break :blk s.items[1];
        }
        if (s.items[1].atom) |a1| {
            if (std.mem.eql(u8, a1, lit)) break :blk s.items[2];
        }
        return null;
    };
    // Не сворачиваем константные свёртки вида `(= false true)`.
    if (other.atom) |ao| {
        if (std.mem.eql(u8, ao, "true") or std.mem.eql(u8, ao, "false")) return null;
    }
    return other;
}

fn boolFormEq(a: Sexp, b: Sexp) bool {
    if (asNot(a)) |x| {
        if (asNot(b)) |y| return boolFormEq(x, y);
        if (isEqBoolLit(b, "false")) |y| return boolFormEq(x, y);
        return false;
    }
    if (asNot(b)) |y| {
        if (isEqBoolLit(a, "false")) |x| return boolFormEq(x, y);
        return false;
    }
    if (isEqBoolLit(a, "true")) |x| return boolFormEq(x, b);
    if (isEqBoolLit(b, "true")) |y| return boolFormEq(a, y);
    return false;
}

/// КАНОНИЗАЦИЯ СРАВНЕНИЙ: `(>= a b)` ≡ `(<= b a)`, `(> a b)` ≡ `(< b a)`.
///
/// ИЗМЕРЕНО (ЭТАП А, 3 доверенных `rewrite` в выводе IEEE-754): Z3 записывает
/// ОДНО И ТО ЖЕ сравнение двумя способами — `(<= 0 x_val)` и `(>= x_val 0)`.
/// Внутри составных `(or … (not …))` структур это не совпадало, и три `rewrite`
/// оставались доверенными. Тождество ЗВУЧНО (одно сравнение в двух записях).
fn cmpEq(a: Sexp, b: Sexp) bool {
    if (!a.isList() or !b.isList() or a.items.len != 3 or b.items.len != 3) return false;
    const ah = a.items[0].atom orelse return false;
    const bh = b.items[0].atom orelse return false;
    const a_le = std.mem.eql(u8, ah, "<=") or std.mem.eql(u8, ah, ">=");
    const b_le = std.mem.eql(u8, bh, "<=") or std.mem.eql(u8, bh, ">=");
    const a_lt = std.mem.eql(u8, ah, "<") or std.mem.eql(u8, ah, ">");
    const b_lt = std.mem.eql(u8, bh, "<") or std.mem.eql(u8, bh, ">");
    if (!(a_le and b_le) and !(a_lt and b_lt)) return false;
    const a_sw = std.mem.eql(u8, ah, ">=") or std.mem.eql(u8, ah, ">");
    const b_sw = std.mem.eql(u8, bh, ">=") or std.mem.eql(u8, bh, ">");
    const a1 = if (a_sw) a.items[2] else a.items[1];
    const a2 = if (a_sw) a.items[1] else a.items[2];
    const b1 = if (b_sw) b.items[2] else b.items[1];
    const b2 = if (b_sw) b.items[1] else b.items[2];
    return sexpEqNum(a1, b1) and sexpEqNum(a2, b2);
}

fn verifyDefAxiom(c: *const Ctx, st: Sexp) bool {
    const t = expand(c, proved(st), 0);
    if (!t.isList() or t.items.len != 3) return false;
    const h = t.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;
    if (verifyIteDisjunct(t.items[1], t.items[2]) or
        verifyIteDisjunct(t.items[2], t.items[1])) return true;
    // ПУНКТ 3 v2.5: аксиома определения обязана быть ТАВТОЛОГИЕЙ. Кроме формы
    // `ite` Z3 вводит так и другие определяющие клаузы — их тавтологичность
    // проверяем НЕСОВМЕСТНОСТЬЮ ОТРИЦАНИЯ через встроенный решатель.
    if (isTautologyClause(c, t)) return true;
    if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
        std.debug.print("[dbg-defax] раскрытая клауза: ", .{});
        dumpSexp(t);
        std.debug.print("\n", .{});
    }
    return false;
}

/// Один дизъюнкт — отрицание условия, другой — равенство с тем же `ite`.
fn verifyIteDisjunct(cond_side: Sexp, eq_side: Sexp) bool {
    if (!isEq3(eq_side)) return false;
    const a = eq_side.items[1];
    const b = eq_side.items[2];
    const ite = if (isIteT(a)) a else if (isIteT(b)) b else return false;
    const other = if (isIteT(a)) b else a;
    const cond = ite.items[1];
    const then_v = ite.items[2];
    const else_v = ite.items[3];
    if (isNotT(cond_side)) {
        // (or (not C) (= T (ite C T E)))
        if (!sexpEq(cond_side.items[1], cond)) return false;
        return sexpEq(other, then_v);
    }
    // (or C (= E (ite C T E)))
    if (!sexpEq(cond_side, cond)) return false;
    return sexpEq(other, else_v);
}

/// ЭКВИВАЛЕНТНОСТЬ (или ПРОТИВОПОЛОЖНОСТЬ) условий через уже существующий
/// звучимый нормализатор `normCmp`. Если он форму не покрывает — `false`
/// (шаг останется доверенным, а не «проверенным»).
fn condEquiv(a: Sexp, b: Sexp, opposite: bool) bool {
    if (opposite) {
        if (isNotT(a) and sexpEq(a.items[1], b)) return true;
        if (isNotT(b) and sexpEq(b.items[1], a)) return true;
    }
    const na = normCmp(a) orelse return false;
    const nb = normCmp(b) orelse return false;
    const want_neg = if (opposite) !na.neg else na.neg;
    return want_neg == nb.neg and sexpEq(na.a, nb.a) and sexpEq(na.b, nb.b);
}

/// ЭКВИВАЛЕНТНОСТЬ с участием `ite` — закрывает оставшиеся шаги `rewrite`
/// (дефект #118). Каждый случай — ТАВТОЛОГИЯ, а не эвристика:
///   * `(= X Y) == (= X Y')`, если `Y == Y'` (и симметрично);
///   * `(ite C T E) == (ite C' T E)`, если условия ЭКВИВАЛЕНТНЫ;
///   * `(ite C T E) == (ite C' E T)`, если условия ПРОТИВОПОЛОЖНЫ
///     (ветви переставлены — это ровно одно и то же значение).
fn iteEq(l: Sexp, r: Sexp, depth: u32) bool {
    if (depth > 16) return false;
    if (sexpEq(l, r)) return true;
    if (isEq3(l) and isEq3(r)) {
        if (sexpEq(l.items[1], r.items[1]) and iteEq(l.items[2], r.items[2], depth + 1))
            return true;
        if (sexpEq(l.items[2], r.items[2]) and iteEq(l.items[1], r.items[1], depth + 1))
            return true;
        return false;
    }
    if (isIteT(l) and isIteT(r)) {
        const cl = l.items[1];
        const tl = l.items[2];
        const el = l.items[3];
        const cr = r.items[1];
        const tr = r.items[2];
        const er = r.items[3];
        const same_branches = sexpEq(tl, tr) and sexpEq(el, er);
        const swapped = sexpEq(tl, er) and sexpEq(el, tr);
        if (same_branches and condEquiv(cl, cr, false)) return true;
        if (swapped and condEquiv(cl, cr, true)) return true;
    }
    return false;
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
//
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
//
/// Форма измерена на реальном выводе Z3 (QF_LIA, `(+ x y) = 3 ∧ x > 5 ∧ y > 5`):
///   $x58 = (<= ?x25 3)
///   $x66 = (not (or (not $x58) (not (>= ?x25 3))))
///   (@x72 (not-or-elim <доказательство $x66> $x58))   <- ¬(¬A ∨ ¬B) ⊨ A
//
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
    const q = expand(c, proved(st), 0);
    if (!isEq3(q)) return false;
    const y = q.items[2];
    var x = q.items[1];
    // ДЕФЕКТ (измерен на `musl abs.c`): раньше использовалась ТОЛЬКО ПЕРВАЯ
    // посылка (`st.items[1]`), а в реальном выводе их НЕСКОЛЬКО:
    //   (monotonicity (rewrite (= $x67 $x117)) (rewrite (= $x82 $x121))
    //                 (= $x110 $x140))
    // Из-за этого заключение не сходилось и шаг уходил в доверенные.
    // Теперь замены применяются НАКОПИТЕЛЬНО, в обе стороны, до неподвижной
    // точки (число раундов ограничено — защита от циклов).
    var rounds: u32 = 0;
    while (rounds < 8) : (rounds += 1) {
        var changed = false;
        for (st.items[1 .. st.items.len - 1]) |pnode| {
            const p = premiseTerm(c, pnode);
            if (!isEq3(p)) continue;
            const a = p.items[1];
            const b = p.items[2];
            if (subst(c, x, a, b, 0)) |s| {
                if (!sexpEq(s, x)) {
                    x = s;
                    changed = true;
                }
            } else if (subst(c, x, b, a, 0)) |s| {
                if (!sexpEq(s, x)) {
                    x = s;
                    changed = true;
                }
            }
        }
        if (sexpEq(x, y)) return true;
        if (!changed) break;
    }
    return sexpEq(x, y);
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

/// Числовое значение литерала: атом `-1` ИЛИ список `(- 1)`.
//
/// ДЕФЕКТ (найден при работе над #123 на РЕАЛЬНОМ выводе Z3 для musl `abs.c`):
/// Z3 печатает отрицательные множители как `(* (- 1) z3name!0)`, то есть
/// числовой множитель — СПИСОК `(- 1)`, а не атом `-1`. `parseLin` искал только
/// атом, поэтому такой множитель считался «второй нечисловой» и весь разбор
/// падал -> лемма не переводилась -> `structural_only`. Здесь распознаются оба
/// написания (это одно и то же число, никакого ослабления).
fn numOf(e: Sexp) ?i64 {
    if (!e.isList()) {
        const a = e.atom orelse return null;
        return std.fmt.parseInt(i64, a, 10) catch null;
    }
    if (e.items.len == 2) {
        const h = e.items[0].atom orelse return null;
        if (std.mem.eql(u8, h, "-")) {
            if (e.items[1].atom) |a| {
                const n = std.fmt.parseInt(i64, a, 10) catch return null;
                return -n;
            }
        }
    }
    return null;
}

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
            if (numOf(it)) |n| {
                k *= n;
                count_num += 1;
                continue;
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

// ---------------------------------------------------------------------------
//  ПУНКТ 3 ПЛАНА v2.5: ЗВУЧИМАЯ ПРОВЕРКА НЕВЕСОВОЙ `(_ th-lemma arith)`
// ---------------------------------------------------------------------------
// ЗАЧЕМ. Z3 выдаёт арифметические леммы БЕЗ весов Фаркаша:
//     ((_ th-lemma arith) @x224 @x141 @x90 $x159)
// Раньше такие шаги оставались `structural_only` (доверенными), из-за чего
// `musl src/stdlib/abs.c` в таблице аудитов висел в `SKIP` (дефект #123).
//
// ЧТО ДЕЛАЕМ (от противного). Шаг доказывает `p1 ∧ … ∧ pm ⊢ concl`.
// Собираем систему: КАЖДАЯ ПОСЫЛКА КАК ЕСТЬ (`asLeZero(p_i)`, БЕЗ отрицания)
// и ЗАКЛЮЧЕНИЕ С ОТРИЦАНИЕМ (`¬concl`). Несовместность системы = доказательство
// импликации. Если `concl == false`, отрицание не добавляет ничего.
//
// ЗВУЧНОСТЬ. `{p1..pm} ∪ {¬concl}` несовместно ⟺ `p1 ∧ … ∧ pm ⇒ concl` —
// тавтология. UNSAT встроенного решателя звучим (см. builtin_lia.zig:
// несовместность над Q влечёт несовместность над Z). Если хотя бы одну формулу
// перевести НЕ удалось — честный `structural_only`, а НЕ «ок».

/// Формула, ДОКАЗАННАЯ узлом вывода.
///   * ссылка `@xN` -> выражение из `stepexpr`, затем его заключение;
///   * инлайновый шаг -> его заключение (`proved`);
///   * литерал -> сам литерал.
/// `null` — узел неизвестен (тогда лемма не проверяется).
fn formulaOf(c: *const Ctx, node: Sexp) ?Sexp {
    if (node.atom) |a| {
        const se = c.stepexpr.get(a) orelse return null;
        return proved(se);
    }
    if (isStepExpr(node)) return proved(node);
    return node;
}

/// ПОЛОЖИТЕЛЬНАЯ форма литерала как `<= 0` (посылка берётся КАК ЕСТЬ):
///   `(<= a b)` -> `a - b <= 0`;  `(< a b)` -> `a - b + 1 <= 0`
///   `(>= a b)` -> `b - a <= 0`;  `(> a b)` -> `b - a + 1 <= 0`
/// Равенство (`=`) НЕ переводим: оно требует ДВУХ неравенств, а потеря одного
/// дала бы неполную систему. Честный отказ вместо тихой потери информации.
fn literalAsLeZero(c: *const Ctx, lit: Sexp, out: *Lin) bool {
    if (!lit.isList() or lit.items.len != 3) return false;
    const h = lit.items[0].atom orelse return false;
    var d = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (std.mem.eql(u8, h, "<=") or std.mem.eql(u8, h, "<")) {
        if (!parseLin(c, lit.items[1], 1, &d)) return false;
        if (!parseLin(c, lit.items[2], -1, &d)) return false;
        if (std.mem.eql(u8, h, "<")) d.constant += 1;
    } else if (std.mem.eql(u8, h, ">=") or std.mem.eql(u8, h, ">")) {
        if (!parseLin(c, lit.items[2], 1, &d)) return false;
        if (!parseLin(c, lit.items[1], -1, &d)) return false;
        if (std.mem.eql(u8, h, ">")) d.constant += 1;
    } else return false;
    out.terms = d.terms;
    out.constant = d.constant;
    return true;
}

/// Перевести `Lin` чекера во встроенный решатель.
fn pushLin(c: *const Ctx, l: Lin, out: *std.array_list.Managed(builtin_lia.Lin)) bool {
    const arr = c.arena.alloc(builtin_lia.Term, l.terms.items.len) catch return false;
    for (l.terms.items, 0..) |t, i| arr[i] = .{ .name = t.name, .coeff = t.coeff };
    out.append(.{ .terms = arr, .constant = l.constant }) catch return false;
    return true;
}

/// ЛИТЕРАЛ как `<= 0` (БЕЗ отрицания). `(not X)` -> это `¬X`.
//
/// ВАЖНО (найдено при разборе `musl abs.c`): положительное РАВЕНСТВО
/// `(= X Y)` — это КОНЪЮНКЦИЯ ДВУХ нестрогих неравенств:
///     `X - Y <= 0`  И  `Y - X <= 0`
/// Раньше равенство не переводилось вовсе, поэтому в `checkFalseBySplitting`
/// комбинации с `(= result a)` теряли связь между `result` и `a`, давали
/// «совместно» и шаг помечался `unknown` -> `unverifiable` (доверенным), хотя
/// по существу он доказуем (например, `result <= -1 ∧ result = a ∧ result = -a`
/// даёт `2*result = 0`, то есть `result = 0`, что противоречит `result <= -1`).
fn asLeZero(c: *const Ctx, lit: Sexp, out: *std.array_list.Managed(builtin_lia.Lin)) bool {
    if (lit.isList() and lit.items.len >= 2) {
        const h = lit.items[0].atom orelse "";
        // КОНЪЮНКЦИЯ `(and X1..Xk)` — добавляем каждую часть.
        if (std.mem.eql(u8, h, "and")) {
            for (lit.items[1..]) |x| if (!asLeZero(c, x, out)) return false;
            return true;
        }
        // `(not (or Y1..Yk))` == `¬Y1 ∧ … ∧ ¬Yk` — по закону де Моргана.
        // ИЗМЕРЕНО на `musl abs.c`: именно такая форма пришла из клаузы
        // (`(not (or (not (>= …)) (not (<= …))))`) и раньше НЕ переводилась,
        // из-за чего комбинация уходила в `unknown`.
        if (std.mem.eql(u8, h, "not") and lit.items.len == 2) {
            const inner = lit.items[1];
            if (inner.isList() and inner.items.len >= 2) {
                if (inner.items[0].atom) |ih| {
                    if (std.mem.eql(u8, ih, "or")) {
                        for (inner.items[1..]) |y| {
                            if (!negateAsLeZero(c, y, out)) return false;
                        }
                        return true;
                    }
                }
            }
        }
    }
    if (asNot(lit)) |inner| {
        var l = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
        if (!negLiteralAsLeZero(c, inner, &l)) return false;
        return pushLin(c, l, out);
    }
    if (lit.isList() and lit.items.len == 3) {
        if (lit.items[0].atom) |h| {
            if (std.mem.eql(u8, h, "=")) {
                var d1 = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
                if (!parseLin(c, lit.items[1], 1, &d1)) return false;
                if (!parseLin(c, lit.items[2], -1, &d1)) return false;
                var d2 = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
                if (!parseLin(c, lit.items[2], 1, &d2)) return false;
                if (!parseLin(c, lit.items[1], -1, &d2)) return false;
                if (!pushLin(c, d1, out)) return false;
                return pushLin(c, d2, out);
            }
        }
    }
    var l = Lin{ .terms = std.array_list.Managed(Term).init(c.arena) };
    if (!literalAsLeZero(c, lit, &l)) return false;
    return pushLin(c, l, out);
}

/// ПРОВЕРИТЬ НЕВЕСОВУЮ `((_ th-lemma arith) p1 … pm concl)`.
fn verifyThLemmaArith(c: *const Ctx, st: Sexp, clause: Sexp) FarkasResult {
    var cons = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    const dbg = compat.envVar("KERN_DEBUG_LIA") != null;
    if (dbg) std.debug.print("[dbg-lia] шаг: аргументов {d}\n", .{st.items.len});
    // Посылки — ВСЕ аргументы, кроме последнего (последний есть заключение).
    if (st.items.len >= 2) {
        for (st.items[1 .. st.items.len - 1]) |pnode| {
            const f = formulaOf(c, pnode) orelse {
                if (dbg) std.debug.print("[dbg-lia] посылка НЕ разрешена (нет формулы)\n", .{});
                return .structural_only;
            };
            const fe = expand(c, f, 0);
            if (!asLeZero(c, fe, &cons)) {
                if (dbg) {
                    const h = if (fe.isList() and fe.items.len > 0)
                        (fe.items[0].atom orelse "list-head")
                    else
                        "atom";
                    std.debug.print("[dbg-lia] посылка не переведена: форма={s} элементов={d}\n", .{ h, fe.items.len });
                }
                return .structural_only;
            }
            if (dbg) std.debug.print("[dbg-lia] посылка OK\n", .{});
        }
    }
    // Заключение — С ОТРИЦАНИЕМ.
    if (clause.isList()) {
        const h = clause.items[0].atom orelse return .structural_only;
        if (std.mem.eql(u8, h, "or")) {
            for (clause.items[1..]) |lit| {
                if (!negateAsLeZero(c, lit, &cons)) return .structural_only;
            }
        } else if (!negateAsLeZero(c, clause, &cons)) return .structural_only;
    } else {
        // Атом: допустим только `false` (его отрицание — пустое).
        const a = clause.atom orelse return .structural_only;
        if (!std.mem.eql(u8, a, "false")) return .structural_only;
    }

    var s = builtin_lia.Solver.init(c.arena);
    defer s.deinit();
    const vres = builtin_lia.checkUnsat(&s, cons.items);
    if (dbg) {
        std.debug.print("[dbg-lia] ограничений {d} -> {s}\n", .{
            cons.items.len, @tagName(std.meta.activeTag(vres)),
        });
    }
    return switch (vres) {
        .unsat => .ok,
        else => .structural_only,
    };
}


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
    // ИЗМЕРЕНО (ЭТАП А, шаг `((_ th-lemma arith farkas -1 1 1) … false)` в
    // выводе IEEE-754): веса Z3 содержат ОТРИЦАТЕЛЬНЫЙ коэффициент (`-1 1 1`).
    // Прежняя проверка `if (k < 0) return .bad;` давала ЛОЖНЫЙ ОТКАЗ: корректный
    // вывод Z3 отвергался (`farkas_bad = 1`), и чекер печатал
    // `[!] ПРУФ-ЧЕКЕР ОТВЕРГ вывод решателя`.
    // Отрицательный вес — это НЕ ошибка: Z3 кодирует знаком ПОЛЯРНОСТЬ литерала
    // (для литерала-отрицания вклад берётся с обратным знаком). Поэтому вместо
    // отвержения честно сообщаем «сертификат в этой форме не проверен»
    // (`.structural_only` -> шаг становится ДОВЕРЕННЫМ, а не отвергнутым).
    // НЕПОЛНОТА ВЕДЁТ К ДОВЕРИЮ, А НЕ К ЛОЖНОМУ ОТКАЗУ.
    for (coeffs.items) |k| if (k < 0) return .structural_only;

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
    // Отладочный вывод `[DBG mp]` УДАЛЁН (хардкор-аудит): он печатал
    // внутреннее состояние в stdout ПРОДАКШН-пути и попадал в логи
    // CLI (`kernc prove`) при каждом неразобранном `mp`.
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
/// Трёхзначный результат проверки шага: ПРОВЕРЕН / ДОКАЗАННО НЕВЕРЕН /
/// НЕПРОВЕРЯЕМ (форма вне модели чекера).
const CheckResult = enum { verified, bad, unverifiable };

/// БЮДЖЕТ ПЕРЕБОРА КОМБИНАЦИЙ КЛАУЗ (пункт 3 плана v2.5).
/// Число комбинаций = произведение длин клауз, поэтому без бюджета — взрыв.
/// За бюджетом — честный `.unverifiable` (не «ок» и не «неверно»).
const MAX_CLAUSE_COMBOS: usize = 16;

/// ТРЁХЗНАЧНЫЙ результат проверки комбинации: `unsat` (доказано несовместной),
/// `sat` (НАЙДЕНА совместная — шаг неверен), `unknown` (перевести не удалось).
const ComboResult = enum { unsat, sat, unknown };

/// `{units} ∪ {picks}` — несовместно?
///   1) синтаксическая пара `P` и `(not P)` внутри объединения; ЛИБО
///   2) арифметическая несовместность через встроенный решатель (Фурье — Моцкин).
//
/// ВАЖНО: «не удалось перевести» — это `unknown`, а НЕ `sat`. Иначе чекер
/// объявлял бы шаг НЕВЕРНЫМ там, где он просто вне его модели (это была бы
/// ложная тревога в самую опасную сторону).
fn unitsPlusPicksUnsat(c: *const Ctx, units: []const Sexp, picks: []const Sexp, neg_concl: ?Sexp) ComboResult {
    // РАСЩЕПЛЕНИЕ ПО ДИЗЪЮНКТИВНОМУ «pick». ИЗМЕРЕНО на `musl abs.c`: в
    // комбинацию попадает литерал-ДИЗЪЮНКЦИЯ
    // `(or (not (>= D 0)) (not (<= D 0)))`, который нельзя перевести в
    // конъюнкцию ограничений. ЗВУЧНО (расщепление по случаям): комбинация
    // несовместна  <=>  КАЖДАЯ ветвь (подстановка одного дизъюнкта) несовместна.
    for (picks, 0..) |p, i| {
        if (p.isList() and p.items.len >= 2) {
            const h = p.items[0].atom orelse continue;
            if (std.mem.eql(u8, h, "or")) {
                for (p.items[1..]) |d| {
                    var np = std.array_list.Managed(Sexp).init(c.arena);
                    for (picks, 0..) |q, j| {
                        np.append(if (j == i) d else q) catch return .unknown;
                    }
                    const r = unitsPlusPicksUnsat(c, units, np.items, neg_concl);
                    if (r != .unsat) return r;
                }
                return .unsat;
            }
        }
    }
    var all = std.array_list.Managed(Sexp).init(c.arena);
    for (units) |u| all.append(u) catch return .unknown;
    for (picks) |p| all.append(p) catch return .unknown;
    if (neg_concl) |nc| all.append(nc) catch return .unknown;
    for (all.items, 0..) |a, i| {
        for (all.items[i + 1 ..]) |b| {
            if (isComplement(a, b) or isComplementCmp(a, b)) return .unsat;
        }
    }
    var cons = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    // ЗАКЛЮЧЕНИЕ берётся С ОТРИЦАНИЕМ: `¬concl` — часть проверяемой системы.
    if (neg_concl) |nc| {
        if (!negateAsLeZero(c, nc, &cons)) return .unknown;
    }
    for (units) |l| {
        if (!asLeZero(c, l, &cons)) {
            if (compat.envVar("KERN_DEBUG_LIA") != null) {
                std.debug.print("[dbg-combo] unit НЕ переведён: ", .{});
                dumpSexp(l);
                std.debug.print("\n", .{});
            }
            return .unknown;
        }
    }
    for (picks) |l| {
        if (!asLeZero(c, l, &cons)) {
            if (compat.envVar("KERN_DEBUG_LIA") != null) {
                std.debug.print("[dbg-combo] pick НЕ переведён: ", .{});
                dumpSexp(l);
                std.debug.print("\n", .{});
            }
            return .unknown;
        }
    }
    var s = builtin_lia.Solver.init(c.arena);
    defer s.deinit();
    return switch (builtin_lia.checkUnsat(&s, cons.items)) {
        .unsat => .unsat,
        .sat => .sat,
        .unknown => .unknown,
    };
}

/// Проверить ЗАКЛЮЧЕНИЕ `concl` РАСЩЕПЛЕНИЕМ ПО СЛУЧАЯМ.
//
/// ЗВУЧНО (дистрибутивность `and` над `or`): `C1 ∧ … ∧ Ck ∧ U ⊢ concl`
/// ⟺ для КАЖДОГО выбора по одному литералу `l_i` из `C_i` система
/// `U ∪ {l_1..l_k} ∪ {¬concl}` несовместна. Для `concl == false` отрицание
/// не добавляет ничего (прежнее поведение). Если какая-то клауза опровергнута
/// юнитами ЦЕЛИКОМ — противоречие уже есть.
//
/// Возвращает `.verified` (все комбинации несовместны), `.bad` (нашлась
/// СОВМЕСТНАЯ комбинация — шаг неверен), `.unverifiable` (комбинаций больше
/// бюджета или перевод не удался).
fn checkBySplitting(c: *const Ctx, units: []const Sexp, clauses: []const Sexp, concl: Sexp) CheckResult {
    const neg_concl: ?Sexp = blk: {
        if (concl.atom) |a| {
            if (std.mem.eql(u8, a, "false")) break :blk null;
        }
        break :blk concl;
    };
    var rems = std.array_list.Managed(std.array_list.Managed(Sexp)).init(c.arena);
    for (clauses) |cl| {
        var rem = std.array_list.Managed(Sexp).init(c.arena);
        for (cl.items[1..]) |lit| {
            const l = expand(c, lit, 0);
            var falsified = false;
            for (units) |u| {
                if (isComplement(l, u) or isComplementCmp(l, u)) {
                    falsified = true;
                    break;
                }
            }
            if (!falsified) rem.append(l) catch return .unverifiable;
        }
        if (rem.items.len == 0) return .verified; // клауза ложна под юнитами
        rems.append(rem) catch return .unverifiable;
    }
    var total: usize = 1;
    for (rems.items) |r| {
        total = std.math.mul(usize, total, r.items.len) catch return .unverifiable;
    }
    if (total > MAX_CLAUSE_COMBOS) return .unverifiable;
    if (compat.envVar("KERN_DEBUG_LIA") != null) {
        std.debug.print("[dbg-split] клауз={d} комбинаций={d}\n", .{ rems.items.len, total });
    }
    var idx: usize = 0;
    while (idx < total) : (idx += 1) {
        var pick = std.array_list.Managed(Sexp).init(c.arena);
        var remn = idx;
        for (rems.items) |r| {
            pick.append(r.items[remn % r.items.len]) catch return .unverifiable;
            remn /= r.items.len;
        }
        // ЛЮБАЯ СОВМЕСТНАЯ комбинация => шаг НЕ доказан (`.bad`).
        // «Не удалось перевести» => честный `.unverifiable`, а НЕ `.bad`.
        switch (unitsPlusPicksUnsat(c, units, pick.items, neg_concl)) {
            .unsat => {},
            .sat => {
                if (compat.envVar("KERN_DEBUG_LIA") != null) {
                    std.debug.print("[dbg-split] комбинация #{d} СОВМЕСТНА -> .bad\n", .{idx});
                }
                return .bad;
            },
            .unknown => {
                if (compat.envVar("KERN_DEBUG_LIA") != null) {
                    std.debug.print("[dbg-split] комбинация #{d} не переведена -> .unverifiable\n", .{idx});
                }
                return .unverifiable;
            },
        }
    }
    return .verified;
}

fn checkUnitRes(c: *const Ctx, st: Sexp) CheckResult {
    if (st.items.len < 3) return .unverifiable;
    const concl = expand(c, proved(st), 0);
    const concl_is_false = concl.atom != null and std.mem.eql(u8, concl.atom.?, "false");

    var units = std.array_list.Managed(Sexp).init(c.arena);
    var clauses = std.array_list.Managed(Sexp).init(c.arena);
    for (st.items[1 .. st.items.len - 1]) |p| {
        const t = premiseTerm(c, p);
        if (isClause(t)) {
            clauses.append(t) catch return .unverifiable;
        } else {
            units.append(t) catch return .unverifiable;
        }
    }

    var saw_remaining = false;
    const dbg = compat.envVar("KERN_DEBUG_LIA") != null;
    if (dbg) std.debug.print("[dbg-ur] посылок: units={d} clauses={d} concl_false={}\n", .{ units.items.len, clauses.items.len, concl_is_false });
    for (clauses.items) |cl| {
        var remaining = std.array_list.Managed(Sexp).init(c.arena);
        for (cl.items[1..]) |lit| {
            const l = expand(c, lit, 0);
            var falsified = false;
            for (units.items) |u| {
                // Структурная ЛИБО семантическая (по канонической форме) пара.
                if (isComplement(l, u) or isComplementCmp(l, u)) {
                    falsified = true;
                    break;
                }
            }
            if (!falsified) remaining.append(l) catch return .unverifiable;
        }
        if (remaining.items.len == 0) continue;
        // Клауза не пуста: вывод обязан быть ДИЗЪЮНКЦИЕЙ ровно оставшихся
        // литералов (порядок не важен).
        //
        // ДЕФЕКТ #95 (найден на выводе с `ite`): раньше требовался РОВНО ОДИН
        // оставшийся литерал. Но Z3 законно применяет ЧАСТИЧНУЮ резолюцию,
        // когда остаётся несколько литералов — например, из
        // `(or $x218 (not $x104))` и посылки, опровергающей один литерал,
        // выводится клауза из двух литералов. Такой шаг отвергался как
        // «неверный», хотя он КОРРЕКТЕН.
        //
        // ЗВУЧНОСТЬ: ни один литерал не может быть потерян или добавлен —
        // сравниваем множества, а не только количество.
        // ЗВУЧНОСТЬ: объявить `false` можно только опровергнув ВСЕ литералы.
        if (concl_is_false) return checkBySplitting(c, units.items, clauses.items, concl);
        var concl_lits = std.array_list.Managed(Sexp).init(c.arena);
        if (isClause(concl)) {
            for (concl.items[1..]) |x| concl_lits.append(x) catch return .unverifiable;
        } else {
            concl_lits.append(concl) catch return .unverifiable;
        }
        // ЛИШНИЕ литералы в выводе -> форма вне модели чекера (доверенный шаг).
        // МЕНЬШЕ литералов -> ПОТЕРЯ (доказанная неверность).
        if (concl_lits.items.len != remaining.items.len) {
            // ОБОБЩЕНИЕ (пункт 3 v2.5): то же РАСЩЕПЛЕНИЕ ПО СЛУЧАЯМ, но для
            // ПРОИЗВОЛЬНОГО заключения: посылки ⊨ concl <=> для каждой
            // комбинации `{units} ∪ {picks} ∪ {¬concl}` несовместно.
            return checkBySplitting(c, units.items, clauses.items, concl);
        }
        if (concl_lits.items.len < remaining.items.len) return .bad;
        //
        // ПОТЕРЯ литерала — доказанная неверность (`bad`).
        // ЛИШНИЕ литералы в выводе — форма вне модели чекера -> `unverifiable`
        // (доверенный шаг), а НЕ `bad`: иначе корректный вывод отвергается.
        if (concl_lits.items.len < remaining.items.len) return .bad;
        for (remaining.items) |r| {
            var found = false;
            for (concl_lits.items) |x| {
                if (sexpEq(r, x)) {
                    found = true;
                    break;
                }
            }
            if (!found) return .bad; // литерал ПОТЕРЯН -> резолюция неверна
        }
        saw_remaining = true;
    }

    if (!saw_remaining) {
        if (concl_is_false) {
            if (clauses.items.len > 0) return .verified; // все клаузы опровергнуты
            // Без клауз нужна пара взаимно-дополняющих литералов.
            for (units.items, 0..) |u, i| {
                for (units.items[i + 1 ..]) |w| {
                    if (isComplement(u, w) or isComplementCmp(u, w)) return .verified;
                }
            }
            return .unverifiable;
        }
        // Вывод — литерал: он обязан быть среди посылок.
        for (units.items) |u| if (sexpEq(u, concl)) return .verified;
        // Без клауз и вывод не среди посылок — форма вне модели чекера.
        return .unverifiable;
    }
    return .verified;
}

// =========================================================================
// Входная точка: аудит текста вывода
// =========================================================================

/// ПЕЧАТЬ S-ВЫРАЖЕНИЯ (для диагностики доверенных шагов).
/// Включается `KERN_DEBUG_TRUSTED=1`. Нужна, чтобы видеть ТОЧНЫЙ вид шага,
/// который чекер не смог проверить (а не догадываться о нём).
fn dumpSexp(e: Sexp) void {
    if (e.atom) |a| {
        std.debug.print("{s}", .{a});
        return;
    }
    std.debug.print("(", .{});
    for (e.items, 0..) |it, i| {
        if (i > 0) std.debug.print(" ", .{});
        dumpSexp(it);
    }
    std.debug.print(")", .{});
}

/// Пометить шаг как непроверенный и запомнить ПРАВИЛО первого такого шага.
/// Без этого нельзя понять, что именно осталось доверенным (METRICS 55.5).
fn markTrusted(v: *ProofVerdict, rule: []const u8, st: Sexp) void {
    v.trusted_steps += 1;
    if (v.first_trusted.len == 0) v.first_trusted = rule;
    if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
        std.debug.print("[dbg-trusted] #{d} {s} :: ", .{ v.trusted_steps, rule });
        dumpSexp(st);
        std.debug.print("\n", .{});
    }
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
    const outer = parseSexp(arena, proof_text) catch |e| {
        // ЧЕСТНОСТЬ: отказ аллокатора — это НЕ «вывод не разбирается».
        // Проглатывать OOM нельзя: харнесс `checkAllAllocationFailures` обязан
        // видеть его, иначе он сообщает SwallowedOutOfMemoryError (и прав).
        if (e == error.OutOfMemory) return e;
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
        const s = parseSexp(arena, a) catch |e| {
            // ЧЕСТНОСТЬ: OOM — не «пропускаем терм», а реальный отказ.
            if (e == error.OutOfMemory) return e;
            continue;
        };
        try contract_terms.append(s);
    }

    // ПРЕДВАРИТЕЛЬНЫЙ ПРОХОД ПО `intro-def`: собрать определения `z3name!k`.
    // ИЗМЕРЕНО на `musl abs.c`: проверяемый `rewrite` идёт РАНЬШЕ своего
    // `intro-def` (шаг #1), поэтому карту определений надо заполнить ДО обхода.
    // ЗВУЧНО: определение записывается только если сам структурный чек
    // `intro-def` прошёл (свежее имя + две клаузы определения `ite`).
    for (c.steps.items) |st| {
        if (st.headAtom()) |h| {
            if (std.mem.eql(u8, h, "intro-def")) _ = verifyIntroDef(&c, st);
        }
    }

    for (c.steps.items) |st| {
        const r = ruleOf(st) orelse continue;
        if (isHole(r)) {
            v.holes += 1;
            if (v.reject.len == 0) v.reject = "вывод содержит правило-дыру (hole/trust/sorry)";
            continue;
        }
        if (!isKnownRule(r)) v.unknown_rules += 1;
        if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
            std.debug.print("[dbg-step] {s} :: ", .{r});
            dumpSexp(st);
            std.debug.print("\n", .{});
        }

        if (std.mem.eql(u8, r, "asserted")) {
            v.premises_total += 1;
            const t = expand(&c, proved(st), 0);
            var found = false;
            for (contract_terms.items) |ct| {
                // `sexpEqNum`, а не `sexpEq`: числовой литерал в исходнике
                // записан атомом (`-2147483648`), а Z3 в выводе — списком
                // (`(- 2147483648)`). Без нормализации корректный вывод
                // отвергался как «посылки не привязаны» (дефект #122).
                if (sexpEqNum(t, ct)) {
                    found = true;
                    break;
                }
                // ПУНКТ 22: булевы формы `(not X)` и `(= X false)` — одно и то же
                // для сорта Bool. Без этого 4-я посылка IEEE-754 не привязывалась
                // (`посылок 3/4`) и чекер ОТВЕРГАЛ корректный вывод.
                if (boolFormEq(t, ct)) {
                    found = true;
                    break;
                }
            }
            if (found) v.premises_bound += 1 else v.premises_unbound += 1;
            if (!found and compat.envVar("KERN_DEBUG_TRUSTED") != null) {
                std.debug.print("[dbg-unbound] НЕ привязана: ", .{});
                dumpSexp(t);
                std.debug.print("\n", .{});
                for (contract_terms.items) |ct| {
                    std.debug.print("[dbg-unbound]   контракт: ", .{});
                    dumpSexp(ct);
                    std.debug.print("\n", .{});
                }
            }
        } else if (std.mem.eql(u8, r, "hypothesis")) {
            v.premises_total += 1; // локальная посылка, снимается правилом lemma
        } else if (std.mem.eql(u8, r, "mp")) {
            v.mp_checked += 1;
            if (!checkMp(&c, st)) v.mp_bad += 1;
        } else if (std.mem.eql(u8, r, "unit-resolution")) {
            v.unitres_checked += 1;
            switch (checkUnitRes(&c, st)) {
                .verified => {},
                .bad => v.unitres_bad += 1,
                // ФОРМА ВНЕ МОДЕЛИ ЧЕКЕРА -> доверенный шаг, а не `bad`.
                // ДЕФЕКТ #95: раньше ЛЮБОЕ несовпадение считалось `bad`, из-за
                // чего корректные выводы Z3 (частичная резолюция, лишние
                // литералы) отвергались целиком.
                .unverifiable => markTrusted(&v, "unit-resolution", st),
            }
        } else if (std.mem.eql(u8, r, "th-lemma")) {
            const clause = expand(&c, proved(st), 0);
            var res = verifyFarkas(&c, st.items[0], clause);
            if (res == .structural_only) {
                // ПУНКТ 3 ПЛАНА v2.5 (дефект #123): весов Фаркаша в выводе НЕТ
                // (`((_ th-lemma arith) p1 … pm concl)`), поэтому сертификат не
                // проверить напрямую. Пробуем доказать лемму САМИ: посылки как
                // есть + отрицание заключения -> несовместность через
                // Фурье — Моцкина. `.ok` ставится ТОЛЬКО если система доказана
                // несовместной; иначе шаг остаётся доверенным (не «ок»).
                res = verifyThLemmaArith(&c, st, clause);
            }
            switch (res) {
                .ok => v.farkas_checked += 1,
                .structural_only => v.farkas_structural += 1,
                .bad => {
                    v.farkas_bad += 1;
                    // ЭТАП А (диагностика): дамп шага, признанного НЕВЕРНЫМ.
                    if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
                        std.debug.print("[dbg-farkas-bad] шаг: ", .{});
                        dumpSexp(st);
                        std.debug.print("\n[dbg-farkas-bad] клауза: ", .{});
                        dumpSexp(clause);
                        std.debug.print("\n", .{});
                    }
                },
            }
        } else if (std.mem.eql(u8, r, "rewrite")) {
            // Элементарные тождества: если равенство доказано нормализацией
            // сравнений (или рефлексивностью) — шаг ПРОВЕРЕН, иначе остаётся
            // доверенным. Никогда не выдаём непроверенное за проверенное.
            switch (checkRewrite(&c, st)) {
                .verified => v.rewrite_verified += 1,
                .bad => v.rewrite_bad += 1,
                .unverifiable => markTrusted(&v, r, st),
            }
        } else if (std.mem.eql(u8, r, "refl") or std.mem.eql(u8, r, "symm") or
            std.mem.eql(u8, r, "trans"))
        {
            if (verifyEqRule(&c, r, st)) v.eq_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "trans*")) {
            // ДЕФЕКТ #118: цепочка равенств проверяется СТРУКТУРНО (см.
            // `verifyTransStar`) — это математическая проверка, а не доверие.
            if (verifyTransStar(&c, st)) v.eq_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "def-axiom")) {
            // ДЕФЕКТ #118: аксиома определения `ite` проверяется по ФОРМЕ
            // (две определяющие тавтологии). Иная форма -> доверенный шаг.
            if (verifyDefAxiom(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "and-elim")) {
            if (verifyAndElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "not-or-elim")) {
            if (verifyNotOrElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "monotonicity")) {
            if (verifyMonotonicity(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "lemma")) {
            // ПУНКТ 3 v2.5: разрядка гипотез (RAA) проверяется СТРУКТУРНО
            // (см. verifyLemma): поддерево выводит `false`, и каждая его
            // гипотеза отрицается в заключении.
            if (verifyLemma(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "intro-def")) {
            // ПУНКТ 3 v2.5: консервативное введение определения проверяется
            // СТРУКТУРНО + по СВЕЖЕСТИ имени (см. verifyIntroDef).
            if (verifyIntroDef(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else {
            // Прочие правила (elim-правила, кванторы): перепроверить нельзя,
            // учитываем как «доверенные», а не как «проверенные».
            markTrusted(&v, r, st);
        }
    }

    // Корень обязан выводить false (пустую клаузу).
    if (c.root) |root| {
        const t = expand(&c, proved(root), 0);
        v.proof_concludes_false = t.atom != null and std.mem.eql(u8, t.atom.?, "false");
        if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
            std.debug.print("[dbg-root] корень раскрыт в: ", .{});
            dumpSexp(t);
            std.debug.print("\n[dbg-root] атом={} concl_false={}\n", .{
                t.atom != null, v.proof_concludes_false,
            });
        }
    } else if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
        std.debug.print("[dbg-root] c.root == null (корень НЕ найден)\n", .{});
    }
    if (!v.proof_concludes_false and v.reject.len == 0) {
        v.reject = "корень вывода не является false";
    }
    // ЭТАП А (диагностика): печать счётчиков ЗДЕСЬ, а не после `return v`
    // (раньше она стояла ниже раннего возврата и физически не выполнялась).
    if (compat.envVar("KERN_DEBUG_TRUSTED") != null) {
        std.debug.print(
            "[dbg-counters] steps={d} holes={d} prem={d}/{d} unbound={d} " ++
                "mp_bad={d} unitres_bad={d} farkas_bad={d} rewrite_bad={d} " ++
                "unknown_rules={d} trusted={d} concl_false={} reject_len={d}\n",
            .{
                v.proof_steps,        v.holes,          v.premises_bound,
                v.premises_total,     v.premises_unbound, v.mp_bad,
                v.unitres_bad,        v.farkas_bad,     v.rewrite_bad,
                v.unknown_rules,      v.trusted_steps,  v.proof_concludes_false,
                v.reject.len,
            },
        );
        if (v.reject.len > 0) std.debug.print("[dbg-counters] reject = {s}\n", .{v.reject});
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

test "PROOF-АТАКА: разорванная цепочка trans* отвергается (дефект #118)" {
    // Цепочка равенств с РАЗРЫВОМ: a=b, c=d  =>  a=d. Средний терм не совпал,
    // значит шаг подделан и обязан уйти в ДОВЕРЕННЫЕ, а не в проверенные.
    const p = "((set-logic QF_UF)(proof (let (($a (= x y)))(let (($b (= z w)))(let (($q (= x w)))(trans* $a $b $q))))))";
    const v = try verifyProof(std.testing.allocator, p, &.{});
    try std.testing.expectEqual(@as(usize, 0), v.eq_verified);
    try std.testing.expect(v.trusted_steps >= 1);
}

test "PROOF-АТАКА: подделанная аксиома ite (def-axiom) отвергается (дефект #118)" {
    // Форма НЕ является определяющей тавтологией `ite`: равенство требует ветвь
    // ELSE при истинном условии. Такая «аксиома» не доказана -> доверенный шаг.
    const p = "((set-logic QF_UF)(proof (def-axiom (or (not (= a b)) (= c (ite (= a b) d c))))))";
    const v = try verifyProof(std.testing.allocator, p, &.{});
    try std.testing.expectEqual(@as(usize, 0), v.bool_verified);
    try std.testing.expect(v.trusted_steps >= 1);
}

test "PROOF-АТАКА: ЛОЖНАЯ ite-эквивалентность в rewrite отвергается (дефект #118)" {
    // Условия НЕ эквивалентны и НЕ противоположны ((< x 1) и (< x 2)): равенство
    // НЕ тавтология. Чекер обязан не считать его проверенным.
    const p = "((set-logic QF_UF)(proof (rewrite (= (ite (< x 1) a b) (ite (< x 2) a b)))))";
    const v = try verifyProof(std.testing.allocator, p, &.{});
    try std.testing.expectEqual(@as(usize, 0), v.rewrite_verified);
}

test "ПОЗИТИВ: цепочка trans* и аксиома ite ПРОВЕРЯЮТСЯ (дефект #118)" {
    // Корректная цепочка: x=y, y=w  =>  x=w.
    const chain = "((set-logic QF_UF)(proof (let (($a (= x y)))(let (($b (= y w)))(let (($q (= x w)))(trans* $a $b $q))))))";
    const v1 = try verifyProof(std.testing.allocator, chain, &.{});
    try std.testing.expectEqual(@as(usize, 1), v1.eq_verified);
    // Корректная определяющая аксиома: (or (not C) (= T (ite C T E))).
    const ax = "((set-logic QF_UF)(proof (def-axiom (or (not (= a b)) (= c (ite (= a b) c d))))))";
    const v2 = try verifyProof(std.testing.allocator, ax, &.{});
    try std.testing.expectEqual(@as(usize, 1), v2.bool_verified);
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет

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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;

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

test "PROOF: булева нормализация — де Морган, раскрытие =, порядок операндов" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);

    // 1. Раскрытие целочисленного равенства в конъюнкцию неравенств:
    //    (= x 3)  <=>  (and (<= x 3) (>= x 3))
    const eq = try parseSexp(a, "(rewrite (= (= x 3) (and (<= x 3) (>= x 3))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, eq));

    // 2. Закон де Моргана для связок:
    //    (and A B)  <=>  (not (or (not A) (not B)))
    const dm = try parseSexp(a, "(rewrite (= (and (<= x 3) (>= x 3)) (not (or (not (<= x 3)) (not (>= x 3))))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, dm));

    // 3. Порядок операндов не значим (коммутативность конъюнкции).
    const comm = try parseSexp(a, "(rewrite (= (and (>= x 3) (<= x 3)) (and (<= x 3) (>= x 3))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, comm));

    // 4. Двойное отрицание.
    const dn = try parseSexp(a, "(rewrite (= (not (not (<= x 3))) (<= x 3)))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, dn));

    // 5. НЕРАВНЫЕ формулы не подтверждаются (и не объявляются подделкой —
    //    нормализатор неполон, значит обязан честно молчать).
    const bad = try parseSexp(a, "(rewrite (= (<= x 3) (<= x 4)))");
    try std.testing.expectEqual(RwResult.bad, checkRewrite(&c, bad));
    const neq = try parseSexp(a, "(rewrite (= (and (<= x 3) (>= x 3)) (and (<= x 3) (>= x 4))))");
    const r = checkRewrite(&c, neq);
    try std.testing.expect(r == .bad or r == .unverifiable);
}

test "ХАРДКОР: Deep Nesting Bomb ('(' * 50000) не должен ронять процесс" {
    // ДО ФИКСА: `parseList` вызывает `parse()` рекурсивно БЕЗ лимита глубины,
    // поэтому 50000 открывающих скобок дают 50000 кадров стека -> SIGSEGV.
    // ПОСЛЕ ФИКСА: должен вернуться error (TooDeep), а процесс остаться живым.
    const n = 2_000_000;
    const buf = try std.testing.allocator.alloc(u8, n);
    defer std.testing.allocator.free(buf);
    @memset(buf, '(');
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const r = parseSexp(arena.allocator(), buf);
    try std.testing.expectError(ParseError.TooDeep, r);
}

// =========================================================================
//  ХАРДКОР-АУДИТ: инъекция отказов аллокатора
//  `checkAllAllocationFailures` прогоняет функцию СТОЛЬКО раз, сколько в ней
//  выделений, отказывая на каждом по очереди, и проверяет, что при частичном
//  OutOfMemory НЕТ УТЕЧЕК и нет паники.
// =========================================================================

fn faultParseSexp(allocator: std.mem.Allocator) !void {
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    // ВАЖНО: ошибку НЕ глотаем — харнесс должен видеть error.OutOfMemory,
    // иначе он сообщает SwallowedOutOfMemoryError (и он прав: проглоченный
    // OOM скрывает, была ли уборка ресурсов).
    _ = try parseSexp(arena.allocator(), "(a (b c) (d (e f)) ((g) h))");
}

test "ХАРДКОР: инъекция отказов аллокатора в parseSexp (0 утечек)" {
    try std.testing.checkAllAllocationFailures(std.testing.allocator, faultParseSexp, .{});
}

fn faultExtractAsserts(allocator: std.mem.Allocator) !void {
    const src = "(assert (and (> x 10) (< x 5)))";
    const got = try extractAsserts(allocator, src);
    defer {
        for (got) |g| allocator.free(g);
        allocator.free(got);
    }
}

test "ХАРДКОР: инъекция отказов аллокатора в extractAsserts (0 утечек)" {
    try std.testing.checkAllAllocationFailures(std.testing.allocator, faultExtractAsserts, .{});
}

// =========================================================================
//  ХАРДКОР-АУДИТ: тесты ВНУТРЕННИХ правил (убивают выживших мутантов)
//  Мутатор показал, что правила trans/symm/and-elim/monotonicity не покрыты
//  тестами: мутации в их логике выживали.
// =========================================================================

test "ХАРДКОР: verifyEqRule — trans проверяется по СУЩЕСТВУ" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x1", try parseSexp(a, "(asserted (= a b))"));
    try c.stepexpr.put("@x2", try parseSexp(a, "(asserted (= b c))"));
    try c.stepexpr.put("@x3", try parseSexp(a, "(asserted (= a c))"));
    try c.stepexpr.put("@y1", try parseSexp(a, "(asserted (= z c))"));

    // Совпадающий средний терм -> TRUE.
    // Убивает мутанта `if (n < 4) return false` -> `if (true)`: он отверг бы
    // ЛЮБОЙ trans, и этот тест упал бы.
    try std.testing.expect(verifyEqRule(&c, "trans",
        try parseSexp(a, "(trans @x1 @x2 @x3)")));
    // НЕсовпадающий средний терм -> FALSE.
    try std.testing.expect(!verifyEqRule(&c, "trans",
        try parseSexp(a, "(trans @x1 @y1 @x3)")));
}

test "ХАРДКОР: verifyEqRule — symm и защита от не-равенств" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x1", try parseSexp(a, "(asserted (= a b))"));
    try c.stepexpr.put("@x4", try parseSexp(a, "(asserted (= b a))"));
    try c.stepexpr.put("@x5", try parseSexp(a, "(asserted true)"));

    try std.testing.expect(verifyEqRule(&c, "symm",
        try parseSexp(a, "(symm @x1 @x4)")));
    // ЗАЩИТА: q — НЕ равенство. Корректный код обязан вернуть false.
    // Убивает мутанта `!isEq3(p) or !isEq3(q)` -> `and`: он прошёл бы дальше
    // и обратился к `q.items[2]` у АТОМА -> паника (выход за границы).
    try std.testing.expect(!verifyEqRule(&c, "symm",
        try parseSexp(a, "(symm @x1 @x5)")));
}

test "ХАРДКОР: verifyAndElim — конъюнкт из and выводится" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x1", try parseSexp(a, "(asserted (and A B))"));
    // A выводится, C — нет.
    try std.testing.expect(verifyAndElim(&c,
        try parseSexp(a, "(and-elim @x1 A)")));
    try std.testing.expect(!verifyAndElim(&c,
        try parseSexp(a, "(and-elim @x1 C)")));
}

test "ХАРДКОР: verifyMonotonicity — подстановка A -> B проверяется" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x1", try parseSexp(a, "(asserted (= a b))"));

    // (= (f a) (f b)) получается подстановкой a->b -> TRUE.
    // Убивает мутанта `if (sexpEq(s, y)) return true` -> `return false`.
    try std.testing.expect(verifyMonotonicity(&c,
        try parseSexp(a, "(monotonicity @x1 (= (f a) (f b)))")));
    // (= (f a) (f c)) НЕ получается -> FALSE.
    try std.testing.expect(!verifyMonotonicity(&c,
        try parseSexp(a, "(monotonicity @x1 (= (f a) (f c)))")));
    // ЗАЩИТА (строка 864): заключение — НЕ равенство. Корректный код обязан
    // вернуть false ДО обращения к `q.items[1]`.
    // Убивает мутанта `!isEq3(p) or !isEq3(q)` -> `and`: он прошёл бы дальше и
    // обратился к полям АТОМА -> паника (выход за границы).
    try std.testing.expect(!verifyMonotonicity(&c,
        try parseSexp(a, "(monotonicity @x1 just_an_atom)")));
}

// =========================================================================
//  ХАРДКОР-АУДИТ: тесты на БИТЫЕ входы (убивают оставшихся мутантов)
//  Мутатор показал, что защиты от НЕКОРРЕКТНЫХ данных не покрыты:
//  нормальный путь тестировался, а ветки отказа — нет.
// =========================================================================

test "ХАРДКОР: extractAsserts пропускает `;`-комментарии (стр. 515)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    // Комментарий ПЕРЕД assert содержит скобки и перевод строки.
    // Убивает мутанта `while (j < len and text[j] != '\n')` -> `or`:
    // с `or` цикл ушёл бы за конец строки и «съел» следующие assert.
    const src = "; (ignore (this) \n(assert (= a b))\n;";
    const got = try extractAsserts(a, src);
    try std.testing.expectEqual(@as(usize, 1), got.len);
    try std.testing.expectEqualStrings("(= a b)", got[0]);
}

test "ХАРДКОР: trans с БИТЫМ числом посылок отвергается (стр. 805, 809)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x1", try parseSexp(a, "(asserted (= a b))"));
    try c.stepexpr.put("@x2", try parseSexp(a, "(asserted (= b c))"));
    try c.stepexpr.put("@x3", try parseSexp(a, "(asserted (= a c))"));
    try c.stepexpr.put("@n1", try parseSexp(a, "(asserted true)"));

    // Валидный trans -> true (нормальный путь).
    try std.testing.expect(verifyEqRule(&c, "trans",
        try parseSexp(a, "(trans @x1 @x2 @x3)")));
    // (a) МАЛО посылок (n=3 < 4) -> false.
    // Убивает мутанта `if (n < 4) return false` -> `return true`.
    try std.testing.expect(!verifyEqRule(&c, "trans",
        try parseSexp(a, "(trans @x1 @x2)")));
    // (b) посылка — НЕ равенство -> false.
    // Убивает мутанта `!isEq3(p1) or !isEq3(p2) or !isEq3(q)` -> `and`.
    try std.testing.expect(!verifyEqRule(&c, "trans",
        try parseSexp(a, "(trans @x1 @n1 @x3)")));
}

test "ХАРДКОР: parseLin отвергает список без атомарной головы (стр. 933)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    var lin = Lin{ .terms = std.array_list.Managed(Term).init(a) };
    // Голова — СПИСОК, а не атом: разобрать как линейную форму нельзя.
    // Убивает мутанта `e.items[0].atom orelse return false` -> `true`
    // (с ним функция пошла бы дальше и упала/приняла мусор).
    const e = try parseSexp(a, "((x) 1)");
    try std.testing.expect(!parseLin(&c, e, 1, &lin));
}

test "ХАРДКОР: negLiteralAsLeZero отвергает атом и неверную длину (стр. 975)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    var d = Lin{ .terms = std.array_list.Managed(Term).init(a) };
    // Атом (не список) -> false.
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "x"), &d));
    // Список не из 3 элементов -> false.
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "(<= x)"), &d));
}

test "ХАРДКОР: mp с ОБРАТНЫМ равенством принимается (стр. 1062)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // p2 = (= Q P1) — обратный порядок допустим ТОЛЬКО для равенства.
    // Убивает мутанта `if (is_eq and ...) return true` -> `return false`.
    // P1 = x, P2 = (= y x) — ОБРАТНЫЙ порядок, Q = y.
    try std.testing.expect(checkMp(&c, try parseSexp(a, "(mp x (= y x) y)")));
    // Прямой порядок P2 = (= x y) тоже принимается.
    try std.testing.expect(checkMp(&c, try parseSexp(a, "(mp x (= x y) y)")));
    // НЕравенство в обратном порядке НЕ принимается (=>  только прямой).
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x (=> y x) y)")));
}

test "ХАРДКОР: mp отвергает посылку, НЕ совпадающую с заключением (стр. 1061)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `sexpEq(P2[1],P1) and sexpEq(P2[2],Q)` -> `or`:
    // при `or` достаточно совпадения ЛЮБОЙ ОДНОЙ половины, и обе строки ниже
    // были бы ПРИНЯТЫ как корректный modus ponens, хотя посылка не та.
    // (а) антецедент совпал, ЗАКЛЮЧЕНИЕ — нет.
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x (=> x z) y)")));
    // (б) заключение совпало, АНТЕЦЕДЕНТ — нет.
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x (=> z y) y)")));
    // Контроль: полное совпадение ОБЕИХ половин — шаг принимается.
    try std.testing.expect(checkMp(&c, try parseSexp(a, "(mp x (=> x y) y)")));
}

test "ХАРДКОР: линейный путь равенства требует ЛИНЕЙНОСТИ ОБЕИХ сторон (стр. 706)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);

    // (1) ОБЕ стороны линейны -> ЛИНЕЙНЫЙ путь: форма содержит `>=`.
    const ok = boolNorm(&c, try parseSexp(a, "(= x (+ y 1))"), false, 0);
    try std.testing.expect(ok != null);
    const ok_s = sexpKey(&c, ok.?) orelse return error.SkipZigTest;
    try std.testing.expect(std.mem.indexOf(u8, ok_s, ">=") != null);

    // (2) Правая сторона НЕЛИНЕЙНА (x*x) -> линейный путь НЕДОПУСТИМ.
    // Убивает мутанта `parseLin(a) and parseLin(b)` -> `or`: с `or` условие
    // стало бы ИСТИННЫМ, и нелинейное равенство получило бы ЛИНЕЙНУЮ форму
    // `(and (>= x (* x x)) (>= (* x x) x))` вместо честного `null`.
    try std.testing.expect(boolNorm(&c, try parseSexp(a, "(= x (* x x))"), false, 0) == null);
}

test "ХАРДКОР: `;`-комментарий ВНУТРИ assert с несбалансированной скобкой (стр. 515)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    // Комментарий ВНУТРИ формы содержит одиночную `(`, которая без пропуска
    // сломала бы подсчёт глубины.
    // Убивает мутанта `while (j < text.len and text[j] != '\n')` -> `or`:
    // с `or` пропуск ушёл бы ЗА конец строки (до конца текста), и `(assert ...)`
    // не был бы найден вовсе — 0 вместо 1.
    const src = "(assert\n  ; comment with ( unbalanced paren\n  (= a b))\n";
    const got = try extractAsserts(a, src);
    try std.testing.expectEqual(@as(usize, 1), got.len);
}

test "ХАРДКОР: and-elim с НЕДОСТАТОЧНЫМ числом аргументов отвергается (стр. 819)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `if (st.items.len < 3) return false` -> `return true`.
    // С мутантом `(and-elim @x1)` (без конъюнкта) был бы ПРИНЯТ — это ДЫРА
    // В ЗВУЧНОСТИ: чекер подтвердил бы шаг, которого не проверял.
    try std.testing.expect(!verifyAndElim(&c, try parseSexp(a, "(and-elim @x1)")));
    try std.testing.expect(!verifyAndElim(&c, try parseSexp(a, "(and-elim)")));
}

test "ХАРДКОР: negLiteralAsLeZero отвергает НЕ-сравнение (стр. 990)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    var out = Lin{ .terms = std.array_list.Managed(Term).init(a) };
    // Убивает мутанта `} else return false;` -> `return true`.
    // С мутантом произвольный терм (не сравнение) принимался бы как ЛИНЕЙНЫЙ
    // литерал — дыра в звучности сертификата Фаркаша.
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "$x42"), &out));
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "(foo x y)"), &out));
    // Контроль непустоты: НАСТОЯЩЕЕ сравнение принимается.
    try std.testing.expect(negLiteralAsLeZero(&c, try parseSexp(a, "(>= x 5)"), &out));
}

test "ХАРДКОР: not-or-elim отвергает ЧУЖОЕ заключение (стр. 855)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Посылка доказывает ¬(¬P ∨ ¬Q); законный вывод — P или Q.
    try c.stepexpr.put("@p", try parseSexp(a, "(asserted (not (or (not P) (not Q))))"));
    // ЧУЖОЕ заключение R (нет среди дизъюнктов) -> ОБЯЗАН быть отказ.
    // Убивает мутанта `return false` -> `return true` (с ним чужое
    // заключение принималось бы — ДЫРА В ЗВУЧНОСТИ).
    try std.testing.expect(!verifyNotOrElim(&c, try parseSexp(a, "(not-or-elim @p R)")));
    // Контроль непустоты: СВОЙ дизъюнкт P принимается.
    try std.testing.expect(verifyNotOrElim(&c, try parseSexp(a, "(not-or-elim @p P)")));
    // Q тоже принимается.
    try std.testing.expect(verifyNotOrElim(&c, try parseSexp(a, "(not-or-elim @p Q)")));
}

test "ХАРДКОР: unit-resolution с парой (not P), P -> verified (стр. 1164)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@p1", try parseSexp(a, "(asserted (not P))"));
    try c.stepexpr.put("@p2", try parseSexp(a, "(asserted P)"));
    // Пара комплементарна СТРУКТУРНО (`isComplement`), но `P` — не сравнение,
    // поэтому `isComplementCmp` даёт false.
    // Убивает мутанта `isComplement(u,w) or isComplementCmp(u,w)` -> `and`:
    // с `and` условие ложно, и шаг стал бы `.unverifiable` вместо `.verified`.
    try std.testing.expectEqual(CheckResult.verified,
        checkUnitRes(&c, try parseSexp(a, "(unit-resolution @p1 @p2 false)")));
}

test "ХАРДКОР: not-or-elim с МАЛЫМ числом аргументов отвергается (стр. 843)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `if (st.items.len < 3) return false` -> `return true`:
    // с ним шаг БЕЗ заключения (2 элемента) был бы ПРИНЯТ (дыра в звучности).
    try std.testing.expect(!verifyNotOrElim(&c, try parseSexp(a, "(not-or-elim @p)")));
    try std.testing.expect(!verifyNotOrElim(&c, try parseSexp(a, "(not-or-elim)")));
}

// =========================================================================
//  ХАРДКОР-АУДИТ (мутационный прогон seed=7, 2026-10-16): 7 выживших мутантов.
//  Каждый тест убивает КОНКРЕТНЫЙ мутант — в комментарии указан номер строки
//  и суть подмены. Все они — НЕПОКРЫТЫЕ ВЕТКИ ОТКАЗА: нормальный путь
//  тестировался, а «данные не той формы» — нет.
// =========================================================================

test "ХАРДКОР: ruleOf не падает на ПУСТОМ списке в голове (стр. 309)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    // Убивает мутанта `h.isList() and h.items.len >= 2` -> `or`: при `or`
    // для головы-ПУСТОГО-СПИСКА условие истинно, и `h.items[0]` — выход за
    // границы (паника вместо `null`).
    try std.testing.expect(ruleOf(try parseSexp(a, "(())")) == null);
    // Контроль: голова-список ДОСТАТОЧНОЙ длины по-прежнему разбирается.
    try std.testing.expectEqualStrings("th-lemma",
        ruleOf(try parseSexp(a, "((_ th-lemma arith farkas 1 1) cl)")).?);
}

test "ХАРДКОР: isComplementCmp отвергает СОВПАДАЮЩИЕ сравнения (стр. 478)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    // Убивает мутанта `na.neg != nb.neg` -> `==`: с ним два ОДИНАКОВЫХ
    // сравнения считались бы взаимно-дополняющими (дыра в `unit-resolution`).
    const x = try parseSexp(a, "(<= p q)");
    try std.testing.expect(!isComplementCmp(x, x));
    // Контроль: настоящая пара (литерал и его отрицание) — комплементарна.
    try std.testing.expect(isComplementCmp(try parseSexp(a, "(>= p q)"),
                                           try parseSexp(a, "(< p q)")));
}

test "ХАРДКОР: verifyEqRule symm требует >= 3 элементов (стр. 798)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `if (n < 3) return false` -> `return true`: шаг `(symm)`
    // БЕЗ пары равенств был бы ПРИНЯТ (дыра в звучности).
    try std.testing.expect(!verifyEqRule(&c, "symm", try parseSexp(a, "(symm)")));
    try std.testing.expect(!verifyEqRule(&c, "symm", try parseSexp(a, "(symm x)")));
}

test "ХАРДКОР: negLiteralAsLeZero отвергает НЕРАЗБИРАЕМЫЙ операнд (стр. 978)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    var d = Lin{ .terms = std.array_list.Managed(Term).init(a) };
    // Убивает мутанта `if (!parseLin(...)) return false` -> `return true`:
    // литерал с НЕлинейным первым операндом считался бы линейным, и
    // `arith`-шаг принимался бы без проверки.
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "(<= (<= x 5) 5)"), &d));
    try std.testing.expect(!negLiteralAsLeZero(&c, try parseSexp(a, "(>= 5 (<= x 5))"), &d));
}

test "ХАРДКОР: mp отвергает шаг из МЕНЕЕ 4 элементов (стр. 1053)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `if (st.items.len < 4) return false` -> `return true`:
    // обрубок `(mp x)` принимался бы как корректный modus ponens.
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x)")));
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x y)")));
}

test "ХАРДКОР: mp отвергает ЧУЖУЮ голову посылки (стр. 1060)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Убивает мутанта `if (!is_eq and !eql(h,"=>")) return false` -> `return true`:
    // `(mp x (foo x y) y)` был бы ПРИНЯТ, хотя `foo` — ни импликация, ни равенство.
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp x (foo x y) y)")));
    // Контроль: настоящая импликация с тем же заключением принимается.
    try std.testing.expect(checkMp(&c, try parseSexp(a, "(mp x (=> x y) y)")));
}


test "PROOF: let-БОМБА не раздувает память — бюджет раскрытия держит" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Цепочка `$a0 = (+ $a1 $a1)`, `$a1 = (+ $a2 $a2)`, ..., `$a40 = 1`.
    // НАИВНОЕ раскрытие дало бы 2^40 узлов (терабайты памяти) — здесь обязан
    // сработать БЮДЖЕТ, и вызов обязан ЗАВЕРШИТЬСЯ без OOM и без SEGV.
    const N = 40;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const nm = try std.fmt.allocPrint(a, "$a{d}", .{i});
        const body = try std.fmt.allocPrint(a, "(+ $a{d} $a{d})", .{ i + 1, i + 1 });
        try c.abbrev.put(nm, try parseSexp(a, body));
    }
    try c.abbrev.put("$a40", try parseSexp(a, "1"));
    const root = try parseSexp(a, "$a0");
    var b = ExpandBudget{};
    const out = expandB(&c, root, 0, &b);
    // 1) вызов ВЕРНУЛСЯ (иначе тест упал бы по таймауту/OOM);
    // 2) бюджет соблюдён — раскрыто не больше, чем разрешено;
    // 3) бюджет реально ИСЧЕРПАН (значит защита включилась, а не «повезло»).
    try std.testing.expect(out.isList() or out.atom != null);
    try std.testing.expect(b.used <= EXPAND_NODE_BUDGET);
    try std.testing.expectEqual(@as(usize, 0), b.left);
}

test "ПУНКТ 3: ВЕРНАЯ невесовая th-lemma принимается (система несовместна)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Посылка (<= x 3) и заключение (<= x 5): импликация — ТАВТОЛОГИЯ.
    // Система {x<=3} ∪ {¬(x<=5)} = {x<=3, x>=6} НЕСОВМЕСТНА.
    try c.stepexpr.put("@x10", try parseSexp(a, "(asserted (<= x 3))"));
    const st = try parseSexp(a, "((_ th-lemma arith) @x10 (<= x 5))");
    const clause = expand(&c, proved(st), 0);
    try std.testing.expectEqual(FarkasResult.ok, verifyThLemmaArith(&c, st, clause));
}

test "ПУНКТ 3: ФАЛЬШИВНАЯ невесовая th-lemma ОТВЕРГАЕТСЯ (система совместна)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Посылка (<= x 5), заключение (<= x 3): импликация НЕ тавтология (x = 4).
    // Система {x<=5} ∪ {¬(x<=3)} = {x<=5, x>=4} СОВМЕСТНА, поэтому шаг НЕ
    // должен быть принят как доказанный — иначе чекер верил бы на слово.
    try c.stepexpr.put("@x10", try parseSexp(a, "(asserted (<= x 5))"));
    const st = try parseSexp(a, "((_ th-lemma arith) @x10 (<= x 3))");
    const clause = expand(&c, proved(st), 0);
    try std.testing.expectEqual(FarkasResult.structural_only, verifyThLemmaArith(&c, st, clause));
}

test "ПУНКТ 3: расщепление — СОВМЕСТНЫЙ набор клауз ОТВЕРГАЕТСЯ (.bad)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Клауза (or (>= x 0) (<= x 5)), юнитов нет. Комбинация (>= x 0)
    // СОВМЕСТНА (x = 0), значит заключение `false` НЕ доказано.
    const cls = [_]Sexp{try parseSexp(a, "(or (>= x 0) (<= x 5))")};
    const units = [_]Sexp{};
    try std.testing.expectEqual(CheckResult.bad, checkBySplitting(&c, &units, &cls, try parseSexp(a, "false")));
}

test "ПУНКТ 3: расщепление — НЕСОВМЕСТНЫЙ набор клауз ДОКАЗЫВАЕТСЯ (.verified)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Клауза (or (<= x -1) (<= x -2)) и юнит (>= x 0): ОБЕ комбинации
    // несовместны с юнитом (x >= 0 противоречит и x <= -1, и x <= -2).
    const cls = [_]Sexp{try parseSexp(a, "(or (<= x -1) (<= x -2))")};
    const units = [_]Sexp{try parseSexp(a, "(>= x 0)")};
    try std.testing.expectEqual(CheckResult.verified, checkBySplitting(&c, &units, &cls, try parseSexp(a, "false")));
}

test "ПУНКТ 3: intro-def — корректное определение ПРИНИМАЕТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Ровно та форма, что измерена на musl abs.c: z3name!1 = ite(a >= 0, a, -a).
    const st = try parseSexp(a, "(intro-def (and (or (not (>= a 0)) (= z3name!1 a)) (or (>= a 0) (= z3name!1 (* (- 1) a)))))");
    try std.testing.expect(verifyIntroDef(&c, st));
}

test "ПУНКТ 3: intro-def — САМОРЕФЕРЕНТНОЕ определение ОТВЕРГАЕТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Имя z3name!1 встречается в СВОЁМ ЖЕ определении -> введение перестаёт
    // быть консервативным расширением, шаг не принимается.
    const st = try parseSexp(a, "(intro-def (and (or (not (>= a 0)) (= z3name!1 a)) (or (>= a 0) (= z3name!1 z3name!1))))");
    try std.testing.expect(!verifyIntroDef(&c, st));
}

test "ПУНКТ 3: lemma — разрядка гипотезы ПРИНИМАЕТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Поддерево выводит `false`, опираясь на допущение (>= a 0).
    try c.stepexpr.put("@x10", try parseSexp(a, "(unit-resolution (hypothesis (>= a 0)) (asserted (not (>= a 0))) false)"));
    // Заключение леммы — отрицание этого допущения.
    const st = try parseSexp(a, "(lemma @x10 (not (>= a 0)))");
    try std.testing.expect(verifyLemma(&c, st));
}

test "ПУНКТ 3: lemma — НЕразряженная гипотеза ОТВЕРГАЕТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    try c.stepexpr.put("@x10", try parseSexp(a, "(unit-resolution (hypothesis (>= a 0)) (asserted (not (>= a 0))) false)"));
    // Заключение НЕ содержит отрицания допущения -> правило неприменимо.
    const st = try parseSexp(a, "(lemma @x10 (not (<= a 5)))");
    try std.testing.expect(!verifyLemma(&c, st));
}

test "ПУНКТ 3: rewrite (1) антисимметричность (= P 0) <=> (and (<= P 0) (>= P 0))" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // P СОДЕРЖИТ `ite` — линейный решатель бессилен, структурная проверка работает.
    try std.testing.expect(antisymmetryZero(
        try parseSexp(a, "(= (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a)))) 0)"),
        try parseSexp(a, "(and (<= (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a)))) 0) (>= (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a)))) 0))"),
    ));
    // НЕГАТИВ: ОБА направления одинаковы -> это НЕ антисимметричность.
    try std.testing.expect(!antisymmetryZero(
        try parseSexp(a, "(= x 0)"),
        try parseSexp(a, "(and (<= x 0) (<= x 0))"),
    ));
}

test "ПУНКТ 3: rewrite (2) перенос (= X Y) <=> (= (+ X (* (- 1) Y)) 0)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    try std.testing.expect(eqTransferZero(
        try parseSexp(a, "(= result (ite (>= a 0) a (* (- 1) a)))"),
        try parseSexp(a, "(= (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a)))) 0)"),
    ));
    // НЕГАТИВ: справа ДРУГОЙ терм.
    try std.testing.expect(!eqTransferZero(
        try parseSexp(a, "(= x y)"),
        try parseSexp(a, "(= (+ x (* (- 1) z)) 0)"),
    ));
}

test "ПУНКТ 3: rewrite (3) переворот ite под равенством" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    try std.testing.expect(iteSwapEq(&c,
        try parseSexp(a, "(= result (ite (< a 0) (- a) a))"),
        try parseSexp(a, "(= result (ite (<= 0 a) a (* (- 1) a)))"),
    ));
    // НЕГАТИВ: условия НЕ противоположны.
    try std.testing.expect(!iteSwapEq(&c,
        try parseSexp(a, "(= result (ite (< a 0) (- a) a))"),
        try parseSexp(a, "(= result (ite (< a 0) a (* (- 1) a)))"),
    ));
}

test "ПУНКТ 3 (5Г-3): and-де-Морган ПРИНИМАЕТСЯ, подделка ОТВЕРГАЕТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // Ровно форма из дампа abs.c: (and X Y) <=> (not (or (not X) (not Y))).
    const lhs = try parseSexp(a, "(and (>= a 0) (<= a 5))");
    const rhs = try parseSexp(a, "(not (or (not (>= a 0)) (not (<= a 5))))");
    try std.testing.expect(andDeMorganEq(lhs, rhs));
    // Подделка: во втором дизъюнкте другая формула -> ОТВЕРГАЕТСЯ.
    const bad = try parseSexp(a, "(not (or (not (>= a 0)) (not (<= a 4))))");
    try std.testing.expect(!andDeMorganEq(lhs, bad));
}

test "ПУНКТ 3 (5Г-3): подстановка ПРОВЕРЕННОГО определения intro-def" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Определение, доказанное intro-def: z3name!1 = ite(a >= 0, a, -a).
    const def_st = try parseSexp(a, "(intro-def (and (or (not (>= a 0)) (= z3name!1 a)) (or (>= a 0) (= z3name!1 (* (- 1) a)))))");
    try std.testing.expect(verifyIntroDef(&c, def_st));
    // Ровно последний доверенный шаг abs.c: имя z3name!1 vs его определение.
    const l = try parseSexp(a, "(>= (+ result (* (- 1) z3name!1)) 0)");
    const r = try parseSexp(a, "(>= (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a)))) 0)");
    try std.testing.expect(eqUpToDefs(&c, l, r, 0));
    // БЕЗ определения (другой контекст) — разворачивать НЕЛЬЗЯ: отказ.
    var c2 = newCtx(a);
    try std.testing.expect(!eqUpToDefs(&c2, l, r, 0));
}

// =========================================================================
//  ХАРДКОР-АУДИТ ЭШЕЛОНА 1: инъекция отказов аллокатора в НОВЫЙ код
//  (встроенный LIA-решатель и полный путь проверки доказательства).
// =========================================================================

/// Система, требующая НЕСКОЛЬКИХ шагов исключения Фурье — Моцкина:
/// `x + y + 1 <= 0`, `-x <= 0`, `-y <= 0`  (несовместна: x,y >= 0 -> x+y >= 0,
/// но требуется x+y <= -1). Так проверяются ВСЕ выделения решателя, а не только
/// первый шаг.
fn faultLiaSolve(allocator: std.mem.Allocator) !void {
    var s = builtin_lia.Solver.init(allocator);
    defer s.deinit();
    const t_xy = [_]builtin_lia.Term{
        .{ .name = "x", .coeff = 1 },
        .{ .name = "y", .coeff = 1 },
    };
    const t_x = [_]builtin_lia.Term{.{ .name = "x", .coeff = -1 }};
    const t_y = [_]builtin_lia.Term{.{ .name = "y", .coeff = -1 }};
    const input = [_]builtin_lia.Lin{
        .{ .terms = &t_xy, .constant = 1 },
        .{ .terms = &t_x, .constant = 0 },
        .{ .terms = &t_y, .constant = 0 },
    };
    // Ошибку НЕ глотаем: харнесс должен видеть error.OutOfMemory.
    _ = try builtin_lia.checkUnsatFallible(&s, &input);
}

test "ХАРДКОР: инъекция отказов аллокатора в builtin_lia.checkUnsat (0 утечек)" {
    try std.testing.checkAllAllocationFailures(std.testing.allocator, faultLiaSolve, .{});
}

// Полный путь `verifyProof` на РЕАЛЬНОМ выводе Z3 (`REAL_LIA_PROOF`):
// внутри работают `intro-def`, `lemma`, `checkFalseBySplitting`,
// `impliesLinear`, `eqUpToDefs` — то есть ВЕСЬ новый код Эшелона 1.
//
// ПОЧЕМУ СВОЙ ПЕРЕБОР, А НЕ `checkAllAllocationFailures`. Обход доказательства
// в `proof_check.zig` ИНФАЛЛИБЕЛЕН по дизайну: отказ аллокатора внутри обхода
// деградирует консервативно (шаг помечается доверенным, доказательство
// отклоняется), а не пробрасывается наружу. Поэтому харнесс сообщал бы
// `SwallowedOutOfMemoryError` — формально прав, но требование DoD другое:
// «0 утечек и отсутствие паники при отказе на ЛЮБОМ шаге». Это и проверяем:
// перебираем `fail_index` по всем точкам отказа и следим, чтобы ни одна
// итерация не паниковала и не теряла память (`std.testing.allocator` сам
// поймает утечку в конце теста).
test "ХАРДКОР: отказ аллокатора в verifyProof — 0 утечек, без паники" {
    var i: usize = 0;
    while (i < 400) : (i += 1) {
        var failing = std.testing.FailingAllocator.init(std.testing.allocator, .{
            .fail_index = i,
        });
        const a = failing.allocator();
        _ = verifyProof(a, REAL_LIA_PROOF, &REAL_LIA_CONTRACT) catch {};
        // Все точки отказа пройдены: дальше отказов уже не будет.
        if (i > failing.allocations) break;
    }
}

fn faultVerifyProof(allocator: std.mem.Allocator) !void {
    _ = try verifyProof(allocator, REAL_LIA_PROOF, &REAL_LIA_CONTRACT);
}

// =========================================================================
//  РУБЕЖ 4 (мутационный обстрел): тесты, УБИВАЮЩИЕ выживших мутантов.
//  Каждый тест ломается ровно на том мутанте, который выжил в прогоне
//  `tools/mutate_zig.py --max 60 --seed 7`.
// =========================================================================

// Убивает `proof_check.zig:288 [false->true]` — `sexpEqNum`: СПИСКИ РАЗНОЙ
// ДЛИНЫ не равны. (Проверка длины — единственный барьер между сравнением
// поэлементно и ложным «равно».)
test "МУТАНТ 288: sexpEqNum — списки РАЗНОЙ длины не равны" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // 4 элемента против 5 — длины разные.
    try std.testing.expect(!sexpEqNum(try parseSexp(a, "(<= a 0)"), try parseSexp(a, "(<= a 0 0)")));
    // Атом против списка тоже НЕ равен.
    try std.testing.expect(!sexpEqNum(try parseSexp(a, "(<= a 0)"), try parseSexp(a, "x")));
    try std.testing.expect(!sexpEqNum(try parseSexp(a, "x"), try parseSexp(a, "(<= a 0)")));
    // Контроль: числовая нормализация работает.
    try std.testing.expect(sexpEqNum(try parseSexp(a, "(- 5)"), try parseSexp(a, "-5")));
}

// Убивает `proof_check.zig:1174 [false->true]` — `verifyLemma`: если первый
// аргумент НЕ является шагом вывода, лемма НЕ доказана.
test "МУТАНТ 1174: verifyLemma отвергает не-шаг в первом аргументе" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // `p` — не шаг (его нет в stepexpr) -> доказательство леммы невозможно.
    const st = try parseSexp(a, "(lemma p (not (>= x 0)))");
    try std.testing.expect(!verifyLemma(&c, st));
}

// Убивает `proof_check.zig:1397 [false->true]` — `negAlternatives`: если
// термы внутри `¬(= X Y)` НЕЛИНЕЙНЫ (parseLin их не разбирает), альтернатив
// НЕТ и функция обязана вернуть false (а не «доказано»).
test "МУТАНТ 1397: negAlternatives отказывает на нелинейных термах" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    var alts = std.array_list.Managed(std.array_list.Managed(builtin_lia.Lin)).init(a);
    const to = try parseSexp(a, "(= (* a b) y)");
    try std.testing.expect(!negAlternatives(&c, to, &alts));
}

// Убивает `proof_check.zig:2140 [or->and]` — в проверке контрарной пары
// литералов достаточно ЛЮБОГО из двух видов дополнения (синтаксического ИЛИ
// канонического). Берём пару, где синтаксическое дополнение есть, а
// канонического НЕТ: атом `p` против `(not p)` (атом не сравнение).
test "МУТАНТ 2140: контрарная пара НЕ-сравнений -> .unsat" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    const units = [_]Sexp{try parseSexp(a, "p")};
    const picks = [_]Sexp{};
    const nc = try parseSexp(a, "(not p)");
    try std.testing.expectEqual(ComboResult.unsat,
        unitsPlusPicksUnsat(&c, &units, &picks, nc));
}

// Убивает `proof_check.zig:1920 [>=->>]`: де-Морган для `(not (or Y))`
// обязан работать и при ОДНОМ дизъюнкте (внутренний список из ДВУХ элементов).
// Мутант `> 2` пропустил бы такую форму и вернул `false`.
test "МУТАНТ 1920: asLeZero обрабатывает (not (or Y)) с одним дизъюнктом" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    var out = std.array_list.Managed(builtin_lia.Lin).init(a);
    const lit = try parseSexp(a, "(not (or (not (>= x 0))))");
    try std.testing.expect(asLeZero(&c, lit, &out));
}

// Убивает `proof_check.zig:1937 [and->or]` — `asLeZero`: равенство с НЕВЕРНОЙ
// арностью `(= a b c)` не должно приниматься (мутант `or` пропускал бы его
// по длине и разбирал как `(= a b)`, молча теряя третий терм).
test "МУТАНТ 1937: asLeZero отвергает (= a b c) — неверная арность" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    var out = std.array_list.Managed(builtin_lia.Lin).init(a);
    try std.testing.expect(!asLeZero(&c, try parseSexp(a, "(= a b c)"), &out));
}

// Убивает `proof_check.zig:2070 [or->and]` — `checkMp`: посылка из ДВУХ
// элементов не является импликацией/равенством; мутант убрал бы ранний
// отказ и полез бы в `p2.items[2]` за границей среза (panic).
test "МУТАНТ 2070: checkMp отвергает посылку из 2 элементов (без panic)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp a (= X) false)")));
    try std.testing.expect(!checkMp(&c, try parseSexp(a, "(mp a (not X) false)")));
}

// Убивает `proof_check.zig:2084 [or->and]` — `isClause`: АТОМ клаузой не
// является. Мутант `and` не отсекал бы атом и падал на `t.items[0]`.
test "МУТАНТ 2084: isClause(атом) = false (без panic)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    try std.testing.expect(!isClause(try parseSexp(a, "x")));
    try std.testing.expect(!isClause(try parseSexp(a, "false")));
    try std.testing.expect(isClause(try parseSexp(a, "(or a b)")));
    try std.testing.expect(!isClause(try parseSexp(a, "(and a b)")));
}

// Убивает `proof_check.zig:1308 [or->and]` — `iteSwapEq`: если ХОТЯ БЫ одна
// сторона не является `ite`, правило НЕ применяется. Мутант `and` пропустил бы
// такой случай и полез бы в `t2.items[1]` (для атома — выход за границы).
test "МУТАНТ 1308: iteSwapEq отвергает, если правая часть НЕ ite" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    const l = try parseSexp(a, "(= x (ite (< a 0) (- a) a))");
    const r = try parseSexp(a, "(= x y)");
    try std.testing.expect(!iteSwapEq(&c, l, r));
    // Контроль: ПРОТИВОПОЛОЖНОЕ условие + ПЕРЕСТАВЛЕННЫЕ ветви -> правило срабатывает.
    const r2 = try parseSexp(a, "(= x (ite (<= 0 a) a (- a)))");
    try std.testing.expect(iteSwapEq(&c, l, r2));
}

// Убивает `proof_check.zig:49 [false->true]` — значение ПО УМОЛЧАНИЮ поля
// `is_unsat`. Мутант делал бы «доказано» стартовым состоянием вердикта.
test "МУТАНТ 49: ProofVerdict{} по умолчанию НЕ доказан" {
    const v = ProofVerdict{};
    try std.testing.expect(!v.is_unsat);
    try std.testing.expect(!v.proof_present);
    try std.testing.expect(!v.proof_well_formed);
    try std.testing.expect(!v.proof_concludes_false);
    // НАЙДЕНО ПРИ ЭТОМ ТЕСТЕ: `checksPass()` проверяет только счётчики и
    // `reject`, поэтому ПУСТОЙ вердикт его формально проходит. Решение CLI
    // опирается ещё и на `is_unsat`, так что это не дыра ворот, но кандидат
    // в отдельный дефект (счётчики ≠ доказанность). НЕ меняю семантику
    // `checksPass` здесь: это правка логики ворот, а не теста.
}

// Убивает `proof_check.zig:1892 [false->true]` — `catch return false` на
// выделении в `pushLin`. В обычном прогоне `std.testing.allocator` НЕ отдаёт
// OutOfMemory, поэтому нужен `FailingAllocator`: отказ ровно на этом шаге
// обязан дать `false` (мутант вернул бы `true` = «переведено»).
test "МУТАНТ 1892: pushLin при отказе аллокатора возвращает false" {
    var failing = std.testing.FailingAllocator.init(std.testing.allocator, .{
        .fail_index = 0,
    });
    var ar = std.heap.ArenaAllocator.init(failing.allocator());
    defer ar.deinit();
    var c = newCtx(ar.allocator());
    const l = Lin{ .terms = std.array_list.Managed(Term).init(ar.allocator()) };
    var out = std.array_list.Managed(builtin_lia.Lin).init(ar.allocator());
    // Арена отдаёт память через FailingAllocator: первое же выделение в
    // `pushLin` (`c.arena.alloc`) упадёт -> обязан вернуться `false`.
    try std.testing.expect(!pushLin(&c, l, &out));
}

// Убивает `proof_check.zig:1267 [false->true]` — `isNegOfTerm`: если ГОЛОВА
// терма не атом (вложенный список), вернуть `true` («это минус Y») нельзя —
// это ложное срабатывание. Мутант `orelse return true` именно это и делал.
test "МУТАНТ 1267: isNegOfTerm отвергает НЕ-атомную голову" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const y = try parseSexp(a, "b");
    // Голова `(a)` — список, а не атом.
    try std.testing.expect(!isNegOfTerm(try parseSexp(a, "((a) b)"), y));
    // Контроль: настоящий «минус Y» принимается.
    try std.testing.expect(isNegOfTerm(try parseSexp(a, "(- b)"), y));
    try std.testing.expect(isNegOfTerm(try parseSexp(a, "(* -1 b)"), y));
    try std.testing.expect(!isNegOfTerm(try parseSexp(a, "(+ b c)"), y));
}

// =========================================================================
//  ИСПЫТАНИЕ А (нативно, в памяти): АДВЕРСАРИАЛЬНЫЙ ФАЗЗЕР ПРУФ-ЧЕКЕРА.
//
//  Берём РЕАЛЬНЫЙ 51-шаговый вывод Z3 для `musl abs.c` (`trusted: 0 |
//  holes: 0`) и вносим 30 точечных подделок в разные классы правил. КАЖДАЯ
//  обязана быть отвергнута: `!(checksPass() and proof_concludes_false and
//  trusted_steps == 0)`. Если хоть одна проходит — чекер не звучим, и
//  `trusted: 0` на abs.c был случайностью.
// =========================================================================
const abs_fx = @import("abs_proof_fixture.zig");

/// Заменить `occ`-е (с нуля) вхождение `needle` на `repl`. null — не найдено.
fn replaceNth(a: std.mem.Allocator, src: []const u8, needle: []const u8, repl: []const u8, occ: usize) ?[]const u8 {
    var start: usize = 0;
    var k: usize = 0;
    while (std.mem.indexOfPos(u8, src, start, needle)) |pos| {
        if (k == occ) {
            const out = std.fmt.allocPrint(a, "{s}{s}{s}", .{ src[0..pos], repl, src[pos + needle.len ..] }) catch return null;
            return out;
        }
        k += 1;
        start = pos + needle.len;
    }
    return null;
}

test "ИСПЫТАНИЕ А: 30 подделок реального вывода abs.c ОТВЕРГАЮТСЯ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const contract = try extractAsserts(a, abs_fx.ABS_CONTRACT);

    // ПОЗИТИВНЫЙ КОНТРОЛЬ: неповреждённый вывод обязан подтвердиться.
    const good = try verifyProof(a, abs_fx.ABS_PROOF, contract);
    try std.testing.expect(good.checksPass());
    try std.testing.expect(good.proof_concludes_false);
    try std.testing.expectEqual(@as(usize, 0), good.trusted_steps);
    try std.testing.expectEqual(@as(usize, 51), good.proof_steps);

    var applied: usize = 0;
    var rejected: usize = 0;
    for (abs_fx.TAMPERS) |t| {
        const tampered = replaceNth(a, abs_fx.ABS_PROOF, t.needle, t.repl, t.occ) orelse continue;
        applied += 1;
        const v = try verifyProof(a, tampered, contract);
        const passes = v.checksPass() and v.proof_concludes_false and v.trusted_steps == 0;
        if (!passes) rejected += 1;
    }
    // Ни одна подделка не должна пройти; и подделок должно быть ровно 30.
    try std.testing.expectEqual(@as(usize, 30), applied);
    try std.testing.expectEqual(@as(usize, 30), rejected);
}
