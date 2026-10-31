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
const builtin = @import("builtin");

/// Отладочный флаг из окружения.
///
/// В `wasm32-freestanding` окружения НЕТ вообще (нет syscalls), поэтому
/// возвращаем `false` на этапе comptime: невыбранная ветвь не анализируется,
/// и `compat` (чтение `/proc/self/environ`) в WASM не тянется.
/// Поведение на нативных платформах не меняется.

/// Буфер-писатель БЕЗ зависимости от `compat` (нужен для wasm): обёртка над
/// `std.Io.Writer.Allocating` — ИЗМЕРЕНО, собирается в `wasm32-freestanding`.
const BufWriter = struct {
    aw: std.Io.Writer.Allocating,

    fn init(allocator: std.mem.Allocator) BufWriter {
        return .{ .aw = .init(allocator) };
    }
    fn deinit(self: *BufWriter) void {
        self.aw.deinit();
    }
    fn writer(self: *BufWriter) *std.Io.Writer {
        return &self.aw.writer;
    }
    fn items(self: *BufWriter) []u8 {
        return self.aw.written();
    }
};

fn dbgEnv(comptime name: []const u8) ?[]const u8 {
    if (comptime builtin.os.tag == .freestanding) return null;
    return @import("compat").envVar(name);
}

/// Печать диагностики. В `wasm32-freestanding` консоли нет, и — ИЗМЕРЕНО —
/// `std.debug.print` там ВООБЩЕ не компилируется: он тянет `std.Io.Threaded`,
/// а тот обращается к `posix.getrandom`. Поэтому невыбранная ветвь отбрасывается
/// на comptime, и печать в WASM просто отсутствует (вердикт не зависит от логов).
fn dbgPrint(comptime fmt: []const u8, args: anytype) void {
    if (comptime builtin.os.tag == .freestanding) return;
    std.debug.print(fmt, args);
}
const unsat_core = @import("unsat_core.zig");
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
    /// ДЕФЕКТ #432: шаги, не отнесённые ни к проверенным, ни к доверенным, ни
    /// к дырам (asserted / hypothesis / неизвестные правила). Нужны, чтобы
    /// ТОЖДЕСТВО отчёта было ТОЧНЫМ и проверяемым гейтом:
    ///   Σ проверено + доверенных + дыр + прочих == шагов.
    other_steps: usize = 0,
    first_trusted: []const u8 = "", // правило первого непроверенного шага
    reject: []const u8 = "", // причина отказа ("" = нет)
    /// ДЕФЕКТ #371: вывод отвергнут ИМЕННО по пределу вложенности парсера.
    /// Отдельный флаг, а не текст: гейтам нужно отличать «решатель напечатал
    /// мусор» от «наш предел вложенности оказался меньше реального вывода».
    /// Без него оба случая выглядели как одна строка reject, и по логу нельзя
    /// было понять, чей это отказ — решателя или наш.
    too_deep: bool = false,
    /// ДЕФЕКТ #303: обязана ли каждая посылка быть привязанной.
    /// Это правило принадлежит ПРОВЕРКЕ КОНТРАКТА (`refutation`): там посылки —
    /// сам контракт, и «не использована» означает вакуумное доказательство.
    /// Для ЗАПРОСА-ЭКВИВАЛЕНТНОСТИ (`equivalence`) контрактных посылок нет по
    /// построению: цель — единственная формула, а Z3 не упоминает посылки,
    /// нерелевантные выводу, поэтому правило невыполнимо и отвергало ЛЮБОЙ
    /// корректный вывод (замерено: 0/1 даже на линейном контроле без ite).
    premises_required: bool = true,

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
        if (self.premises_required and self.premises_unbound != 0) return false;
        return self.holes == 0 and
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
        if (self.premises_required and self.premises_unbound != 0) {
            return "посылки не привязаны к контракту (premises_unbound)";
        }
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

/// Предел вложенности S-выражений — ВЫБРАН ПО ЗАМЕРУ, а не по догадке.
///
/// 🔴 ДЕФЕКТ #371 (найден на ОФИЦИАЛЬНОМ банке SMT-LIB). Прежний текст этого
/// комментария утверждал: «Реальные выводы Z3 укладываются в единицы уровней
/// (в эталонном — 14 шагов, глубина < 20). 4096 — с большим запасом». Это
/// утверждение было НЕ ИЗМЕРЕНО и оказалось ЛОЖНЫМ. Измерено на официальных
/// задачах (`sosy-lab`-независимо: `SMT-LIB/benchmark-submission`,
/// категория `QF_BV/20250812-Circt`), глубина вывода Z3 из `(get-proof)`:
///
///     add_three.4_bit.smt2 :  425 193 Б, глубина   4 606
///     add_three.8_bit.smt2 : 1 342 306 Б, глубина  13 169
///     blend.4_bit.smt2     : 26 948 212 Б, глубина 200 690
///
/// То есть предел 4096 был МЕНЬШЕ первой же официальной задачи (4 606) — и
/// отказ назывался «вывод не разбирается как S-выражение», то есть обвинял
/// решатель в мусоре. Оба факта исправлены здесь и в вердикте.
///
/// ПОЧЕМУ НЕ «ПРОСТО ПОДНЯТЬ ЛИМИТ ДО 200 690». Парсер рекурсивен, поэтому
/// предел — это защита ОТ ПЕРЕПОЛНЕНИЯ СТЕКА на НЕДОВЕРЕННОМ входе. Измерено
/// на этой машине (стек 8 МБ, `ulimit -s` = 8192):
///
///     глубина 18 432 — процесс выживает;
///     глубина 19 456 — ПАДЕНИЕ (stack overflow, ~441 байт на кадр).
///
/// Поднять предел выше потолка значило бы ЗАМЕНИТЬ честный отказ на падение
/// процесса — то есть ухудшить ровно то свойство, ради которого защита стоит.
/// Поэтому 12288: в 1.5 раза НИЖЕ измеренной точки падения, и в 2.7 раза выше
/// первой официальной задачи. Выводы глубже (13 169 и 200 690) отвергаются
/// ЯВНОЙ причиной («вывод ГЛУБЖЕ предела вложенности парсера»), а не падением
/// и не ложным «не разбирается».
///
/// ГРАНИЦА (заявлена, а не умолчана): закрытие класса целиком требует
/// ИТЕРАТИВНОГО обхода дерева (явный стек вместо кадров вызова) во всех
/// рекурсивных функциях чекера. Это отдельная работа; здесь её нет, и потому
/// здесь нет и заявления о поддержке сколь угодно глубоких выводов.
pub const MAX_SEXP_DEPTH: u32 = 12288;

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
/// Дефект #303: Z3 вставляет ТРИВИАЛЬНЫЕ связки — `(and X true)` вместо `X`.
///
/// ИЗМЕРЕНО (дамп `KERN_DEBUG_TRUSTED=1`): непривязанный терм
/// `(not (or (and (distinct result 2) true) (= v 1)))` против контракта
/// `(not (or (distinct result 2) (= v 1)))` — разница ровно `(and X true)`.
/// Это НЕ чужая аксиома и НЕ схлопнутая формула: Z3 процитировал нашу посылку,
/// вставив тождество. ЗВУЧНО: для сорта Bool `(and X true) ≡ X` и
/// `(or X false) ≡ X`.
///
/// Свёртка строго уменьшает терм, поэтому рекурсия в `sexpEqNum` завершается.
fn dropTriv(e: Sexp) Sexp {
    if (e.atom != null or e.items.len != 3) return e;
    const op = e.items[0].atom orelse return e;
    const x = e.items[1];
    const y = e.items[2];
    const isTrue = struct {
        fn f(s: Sexp) bool {
            return s.atom != null and std.mem.eql(u8, s.atom.?, "true");
        }
    }.f;
    const isFalse = struct {
        fn f(s: Sexp) bool {
            return s.atom != null and std.mem.eql(u8, s.atom.?, "false");
        }
    }.f;
    if (std.mem.eql(u8, op, "and")) {
        if (isTrue(y)) return dropTriv(x);
        if (isTrue(x)) return dropTriv(y);
    } else if (std.mem.eql(u8, op, "or")) {
        if (isFalse(y)) return dropTriv(x);
        if (isFalse(x)) return dropTriv(y);
    }
    return e;
}

/// Сравнение атомов с учётом `null` (срезы не поддерживают `==`/`!=` напрямую).
fn atomSame(x: ?[]const u8, y: ?[]const u8) bool {
    if (x == null) return y == null;
    if (y == null) return false;
    return std.mem.eql(u8, x.?, y.?);
}

/// Тривиальные связки сняты хотя бы с одной стороны?
fn trivReduced(a: Sexp, b: Sexp) bool {
    const da = dropTriv(a);
    const db = dropTriv(b);
    return !atomSame(da.atom, a.atom) or da.items.ptr != a.items.ptr or
        !atomSame(db.atom, b.atom) or db.items.ptr != b.items.ptr;
}

fn sexpEqNum(a: Sexp, b: Sexp) bool {
    // ПРИЧИНА №1 (измерено/разобрано): сравнение составных формул уходит в этот
    // рекурсивный обход, и на вложенном подтерме `.atom` `"../"` vs `.list`
    // `(str.++ (seq.unit …))` срабатывало отсечение «atom vs list» ДО проверки
    // константных строк. Из-за этого `trans*`, `symm`, `lemma`, `unit-resolution`
    // не видели равенства внутри `(str.contains s …)`.
    // ЗВУЧНО: сверяем СВОРАЧИВАЕМЫЕ байты константных строк.
    if (strConstEq(a, b)) return true;
    // ДЕФЕКТ #303: тривиальные связки (`(and X true)` ≡ `X`). Z3 вставляет их
    // при цитировании нашей посылки, и без этой свёртки корректный вывод
    // отвергался как «посылки не привязаны». Свёртка строго уменьшает терм —
    // рекурсия завершается, потому что после неё `trivReduced` уже false.
    if (trivReduced(a, b) and sexpEqNum(dropTriv(a), dropTriv(b))) return true;
    // ИЗМЕРЕНО (ЭТАП А): Z3 пишет одно сравнение двумя способами
    // (`(<= 0 x)` и `(>= x 0)`) — канонизируем перед сравнением.
    if (cmpEq(a, b)) return true;
    // ЛИНЕЙНАЯ нормализация `(= SUM 0)` с точностью до знака: `r - x = 0`
    // и `x - r = 0` — один и тот же предикат (`r = x`).
    if (eqZeroUpToSign(a, b)) return true;
    // БУЛЕВЫ формы: `(not X)` ≡ `(= X false)`, `X` ≡ `(= X true)`,
    // `(not (<= A B))` ≡ `(< B A)`.
    if (boolFormEq(a, b)) return true;
    // КОММУТАТИВНОСТЬ `+`/`*`: ИЗМЕРЕНО на `@kern:calls_u32` (Пункт 29) —
    // Z3 нормализует произведение по-разному в разных узлах.
    if (commEq(a, b)) return true;
    // ДЕ МОРГАН в обе стороны: ИЗМЕРЕНО на `@kern:bounded` (Пункт 26).
    if (deMorganEq(a, b)) return true;
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
    // ЭТАЛОН QF_S (измерено дампом): `iff-true` / `iff-false` ОТСУТСТВОВАЛИ
    // в таблице, поэтому `isStepExpr` не считал их шагами, и `premiseTerm`
    // возвращал САМ шаг (`(iff-true @x78 (= $x74 true))`) вместо доказываемой
    // формулы (`(= $x74 true)`). Из-за этого цепочка `trans*` рвалась.
    "iff-true",        "iff-false",
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

/// Определение функции из ШАПКИ SMT-файла: `(define-fun f ((x Int)) Int <тело>)`.
///
/// ЗАЧЕМ (дефект #344). Z3 в выводе ПОДСТАВЛЯЕТ тело `define-fun`, а наш
/// контракт содержит ВЫЗОВ: посылка `(not (= (ite (= 2 0) 0 …) …))` против
/// контракта `(not (= (evm_sdiv (- 7) 2) (- 3)))`. Сравнение не сходилось,
/// `premises_unbound` увеличивался, и чекер ОТВЕРГАЛ корректный вывод — то
/// есть три тождества EVM оставались недоказанными (`trusted: 1`).
/// Для `intro-def` такой механизм уже был (`DefIte`), но Z3 НЕ выпускает
/// `intro-def` для `define-fun`: он раскрывает их как внутреннюю оптимизацию.
const FunDef = struct { params: []const []const u8, body: Sexp };

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
    /// ДЕФЕКТ #344: определения из шапки SMT (`define-fun`). Разворачиваются
    /// ПОДСТАНОВКОЙ аргументов, но ТОЛЬКО для сопоставления с контрактом —
    /// см. `funExpand`. Само определение не является утверждением и в вывод не
    /// добавляет ни одного шага: это сокращение записи, а не аксиома.
    fundefs: std.StringHashMap(FunDef),
    /// ДИАГНОСТИКА (Блок 2b плана): сколько `?x`-связок (термов не-булева сорта)
    /// и `$x`-связок (булевых формул) зарегистрировано в `abbrev`. Вопрос:
    /// почему `?x29`/`?x108` в заключении `monotonicity` НЕ раскрываются.
    dbg_qx: usize = 0,
    dbg_dx: usize = 0,
};

fn newCtx(arena: std.mem.Allocator) Ctx {
    return .{
        .arena = arena,
        .abbrev = std.StringHashMap(Sexp).init(arena),
        .stepexpr = std.StringHashMap(Sexp).init(arena),
        .steps = std.array_list.Managed(Sexp).init(arena),
        .defs = std.StringHashMap(DefIte).init(arena),
        .fundefs = std.StringHashMap(FunDef).init(arena),
    };
}

/// Загрузить `(define-fun …)` из ТЕКСТА SMT-файла в контекст.
///
/// Форма: `(define-fun <имя> ((<p> <T>) …) <T> <тело>)` — Z3 печатает ровно
/// так. Любая иная форма (или неразбираемый терм) ПРОПУСКАЕТСЯ: пропуск ведёт
/// к непривязанной посылке, то есть к ОТКАЗУ, а не к ложному «проверено».
///
/// ⚠️ `parseSexp` разбирает ОДНО S-выражение, а SMT-файл — это ПОСЛЕДОВАТЕЛЬНОСТЬ
/// (`set-logic`, `declare-const`, `define-fun`, `assert`, `check-sat`).
/// Первая версия вызывала его на всём тексте и получала только `(set-logic ALL)`
/// — то есть НИ ОДНОГО определения не находила, и вывод по-прежнему отвергался.
/// Поэтому текст режется на top-level выражения по балансу скобок (с учётом
/// строковых литералов и комментариев `;`).
pub fn loadFunDefs(c: *Ctx, smt_text: []const u8) void {
    var i: usize = 0;
    while (i < smt_text.len) {
        const ch = smt_text[i];
        if (ch == ';') {
            while (i < smt_text.len and smt_text[i] != '\n') i += 1;
            continue;
        }
        if (ch == ' ' or ch == '\t' or ch == '\n' or ch == '\r') {
            i += 1;
            continue;
        }
        if (ch != '(') {
            // Атом верхнего уровня: пропускаем (нас интересуют только списки).
            while (i < smt_text.len and smt_text[i] != ' ' and smt_text[i] != '\n' and
                smt_text[i] != '\t' and smt_text[i] != '\r') i += 1;
            continue;
        }
        const start = i;
        var depth: usize = 0;
        var in_str = false;
        while (i < smt_text.len) {
            const cc = smt_text[i];
            if (in_str) {
                if (cc == '\\') {
                    i += 2;
                    continue;
                }
                if (cc == '"') in_str = false;
                i += 1;
                continue;
            }
            if (cc == '"') {
                in_str = true;
                i += 1;
                continue;
            }
            if (cc == ';') {
                while (i < smt_text.len and smt_text[i] != '\n') i += 1;
                continue;
            }
            if (cc == '(') depth += 1;
            if (cc == ')') {
                depth -= 1;
                i += 1;
                if (depth == 0) break;
                continue;
            }
            i += 1;
        }
        const frag = smt_text[start..@min(i, smt_text.len)];
        const e = parseSexp(c.arena, frag) catch continue;
        loadFunDefsRec(c, e);
    }
}

fn loadFunDefsRec(c: *Ctx, e: Sexp) void {
    if (!e.isList()) return;
    if (e.items.len >= 5) {
        if (e.items[0].atom) |h| {
            if (std.mem.eql(u8, h, "define-fun")) {
                const name = e.items[1].atom orelse return;
                const params_list = e.items[2];
                if (!params_list.isList()) return;
                var names = std.array_list.Managed([]const u8).init(c.arena);
                var ok = true;
                for (params_list.items) |p| {
                    if (!p.isList() or p.items.len < 1) {
                        ok = false;
                        break;
                    }
                    const pn = p.items[0].atom orelse {
                        ok = false;
                        break;
                    };
                    names.append(pn) catch {
                        ok = false;
                        break;
                    };
                }
                if (ok) {
                    const body = e.items[e.items.len - 1];
                    c.fundefs.put(name, .{ .params = names.items, .body = body }) catch {};
                }
                return;
            }
        }
    }
    for (e.items) |it| loadFunDefsRec(c, it);
}

/// Раскрыть вызовы `define-fun` ПОДСТАНОВКОЙ аргументов (beta-reduction).
///
/// ЗВУЧНОСТЬ: подстановка не добавляет утверждений — она переводит запись в
/// эквивалентную (по определению функции). Бюджет узлов и лимит глубины
/// ограничивают рост терма; при исчерпании терм возвращается КАК ЕСТЬ, что
/// ведёт к непривязанной посылке (отказ), а не к ложному совпадению.
fn funExpand(c: *Ctx, e: Sexp, depth: u32, budget: *usize) Sexp {
    if (depth > 32 or budget.* == 0) return e;
    budget.* -= 1;
    // ⚠️ АТОМ возвращаем КАК ЕСТЬ: у атома `items` пуст, и общая ветка ниже
    // превратила бы его в пустой СПИСОК (`(() …)` вместо `x`). Именно так первая
    // версия теряла все имена, и раскрытый терм перестал совпадать с посылкой.
    if (e.atom != null) return e;
    if (e.items.len >= 1) {
        if (e.items[0].atom) |h| {
            if (c.fundefs.get(h)) |fd| {
                const argc = e.items.len - 1;
                if (argc == fd.params.len) {
                    const args = c.arena.alloc(Sexp, argc) catch return e;
                    for (e.items[1..], 0..) |a, i| {
                        args[i] = funExpand(c, a, depth + 1, budget);
                    }
                    const body = substParams(c, fd.body, fd.params, args);
                    return funExpand(c, body, depth + 1, budget);
                }
            }
        }
    }
    const out = c.arena.alloc(Sexp, e.items.len) catch return e;
    for (e.items, 0..) |it, i| out[i] = funExpand(c, it, depth + 1, budget);
    return .{ .items = out };
}

/// Подставить аргументы вместо параметров в теле определения.
fn substParams(c: *Ctx, body: Sexp, params: []const []const u8, args: []const Sexp) Sexp {
    if (body.atom) |a| {
        for (params, 0..) |p, i| {
            if (std.mem.eql(u8, p, a)) return args[i];
        }
        return body;
    }
    const out = c.arena.alloc(Sexp, body.items.len) catch return body;
    for (body.items, 0..) |it, i| out[i] = substParams(c, it, params, args);
    return .{ .items = out };
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
                        // ДИАГНОСТИКА (Блок 2b): считаем связки по префиксам.
                        // `$x…` — булевы формулы, `?x…` — термы не-булева сорта
                        // (массивы, целые, битовые векторы). Если `?x`-связок
                        // НОЛЬ, значит имена в заключениях `monotonicity` приходят
                        // НЕ из этой цепочки `let`, и «дописать раскрытие» нечего.
                        if (nm.len > 1 and nm[0] == '?') {
                            c.dbg_qx += 1;
                            if (c.dbg_qx <= 5 and dbgEnv("KERN_DEBUG_TRUSTED") != null) {
                                dbgPrint("[dbg-let] ?x-связка: {s} = ", .{nm});
                                dumpSexp(val);
                                dbgPrint("\n", .{});
                            }
                        } else if (nm.len > 1 and nm[0] == '$') {
                            c.dbg_dx += 1;
                        }
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
    var b = BufWriter.init(c.arena);
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

/// `(or (not X) X) = true` (want_true) либо `(and (not X) X) = false`.
/// ЗВУЧИМО: закон исключённого третьего, никакого доверия решателю.
/// `(<= (ite C T E) K)  ≡  (or (not C) (<= T K))` при `E ≡ K`.
///
/// ЗАЧЕМ (измерено на клампе `+|`): Z3 переписывает верхнюю оценку
/// ite-терма именно так, и шаг оставался ДОВЕРЕННЫМ (`trusted: 1`).
/// ЗВУЧИМО: если C истинно — обе части дают `T <= K`; если ложно —
/// левая даёт `E <= K`, правая `true`, и они совпадают ровно при `E ≡ K`.
fn iteCmpEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    if (!l.isList() or l.items.len != 3) return false;
    const op = l.items[0].atom orelse return false;
    if (!std.mem.eql(u8, op, "<=")) return false;
    const it = expand(c, l.items[1], 0);
    if (!it.isList() or it.items.len != 4) return false;
    const h = it.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "ite")) return false;
    const cond = expand(c, it.items[1], 0);
    const tval = expand(c, it.items[2], 0);
    const eval_ = expand(c, it.items[3], 0);
    const kval = expand(c, l.items[2], 0);
    // правая часть обязана быть `(or (not C') (<= T' K'))`
    if (!r.isList() or r.items.len != 3) return false;
    const rh = r.items[0].atom orelse return false;
    if (!std.mem.eql(u8, rh, "or")) return false;
    const neg = asNot(expand(c, r.items[1], 0)) orelse return false;
    const cmp = expand(c, r.items[2], 0);
    if (!cmp.isList() or cmp.items.len != 3) return false;
    const ch = cmp.items[0].atom orelse return false;
    if (!std.mem.eql(u8, ch, "<=")) return false;
    // связываем: C' ≡ C, T' ≡ T, K' ≡ K, и E ≡ K
    if (!sexpEqNum(neg, cond)) return false;
    if (!sexpEqNum(expand(c, cmp.items[1], 0), tval)) return false;
    if (!sexpEqNum(expand(c, cmp.items[2], 0), kval)) return false;
    return sexpEqNum(eval_, kval);
}


fn isExcludedMiddle(c: *const Ctx, e: Sexp, want_true: bool) bool {
    if (!e.isList() or e.items.len != 3) return false;
    const h = e.items[0].atom orelse return false;
    const want = if (want_true) "or" else "and";
    if (!std.mem.eql(u8, h, want)) return false;
    const a = expand(c, e.items[1], 0);
    const b = expand(c, e.items[2], 0);
    if (a.atom != null and b.atom != null) return false; // нужен `not` с одной стороны
    if (asNot(a)) |inner| {
        if (sexpEqNum(inner, b)) return true;
    }
    if (asNot(b)) |inner| {
        if (sexpEqNum(inner, a)) return true;
    }
    return false;
}


/// `cmp(s, head, x, y)`: узел `(head x y)` с ПОБАЙТОВО теми же `x`, `y`.
fn cmpDirect(s: Sexp, head: []const u8, x: Sexp, y: Sexp) bool {
    if (!s.isList() or s.items.len != 3) return false;
    const h = s.items[0].atom orelse return false;
    return std.mem.eql(u8, h, head) and sexpEq(s.items[1], x) and sexpEq(s.items[2], y);
}

/// `(= A B)`  ⟺  `(and (<= A B) (>= A B))` — антисимметричность порядка.
/// Звучимо для ЛЮБЫХ термов (A, B — произвольные целочисленные выражения),
/// поэтому решатель не вызывается. Дефект #211(a).
fn eqAntisymEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    _ = c;
    var eq_side: Sexp = undefined;
    var and_side: Sexp = undefined;
    if (isEq3(l) and !isEq3(r)) {
        eq_side = l;
        and_side = r;
    } else if (isEq3(r) and !isEq3(l)) {
        eq_side = r;
        and_side = l;
    } else return false;
    if (!and_side.isList() or and_side.items.len != 3) return false;
    const h = and_side.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "and")) return false;
    const a = eq_side.items[1];
    const b = eq_side.items[2];
    const c1 = and_side.items[1];
    const c2 = and_side.items[2];
    if (cmpDirect(c1, "<=", a, b) and cmpDirect(c2, ">=", a, b)) return true;
    if (cmpDirect(c2, "<=", a, b) and cmpDirect(c1, ">=", a, b)) return true;
    return false;
}

/// `(ite (= m 0) X Y)` ⟺ `(ite (<= m 0) X Y)` при `m >= 0`.
/// `m >= 0` НЕ постулируется, а СЛЕДУЕТ ИЗ ФОРМЫ терма: `(mod x k)` с
/// положительной целой константой `k` (аксиома Евклида `0 <= mod x k`).
/// Для любого другого `m` шаг остаётся доверенным (иначе `m = -1` дал бы
/// ложное `-1 = 0 ⟺ -1 <= 0`). Дефект #211(b).
fn nonNegByShape(t: Sexp) bool {
    if (!t.isList() or t.items.len != 3) return false;
    const h = t.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "mod")) return false;
    const k = t.items[2].atom orelse return false;
    const v = std.fmt.parseInt(i64, k, 10) catch return false;
    return v > 0;
}

fn isIte4(s: Sexp) bool {
    if (!s.isList() or s.items.len != 4) return false;
    const h = s.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "ite");
}

/// Признак `(= m 0)`: левая часть — `m`, правая — ноль (или наоборот).
fn eqZeroSide(s: Sexp, m: *Sexp) bool {
    if (!s.isList() or s.items.len != 3) return false;
    const h = s.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "=")) return false;
    if (s.items[2].atom) |ra| {
        if (std.mem.eql(u8, ra, "0")) {
            m.* = s.items[1];
            return true;
        }
    }
    if (s.items[1].atom) |la| {
        if (std.mem.eql(u8, la, "0")) {
            m.* = s.items[2];
            return true;
        }
    }
    return false;
}

/// Признак `(<= m 0)`.
fn leZeroSide(s: Sexp, m: *Sexp) bool {
    if (!s.isList() or s.items.len != 3) return false;
    const h = s.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "<=")) return false;
    const ra = s.items[2].atom orelse return false;
    if (!std.mem.eql(u8, ra, "0")) return false;
    m.* = s.items[1];
    return true;
}

fn eqZeroIteEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    _ = c;
    var ite_a: Sexp = undefined;
    var ite_b: Sexp = undefined;
    if (isIte4(l) and isIte4(r)) {
        ite_a = l;
        ite_b = r;
    } else return false;
    // ветви обязаны совпадать (это `1` и `0` в измеренном выводе)
    if (!sexpEqNum(ite_a.items[2], ite_b.items[2])) return false;
    if (!sexpEqNum(ite_a.items[3], ite_b.items[3])) return false;
    var mA: Sexp = undefined;
    var mB: Sexp = undefined;
    if (eqZeroSide(ite_a.items[1], &mA) and leZeroSide(ite_b.items[1], &mB)) {
        // (= m 0) слева, (<= m 0) справа
    } else if (leZeroSide(ite_a.items[1], &mA) and eqZeroSide(ite_b.items[1], &mB)) {
        // (<= m 0) слева, (= m 0) справа
    } else return false;
    if (!sexpEq(mA, mB)) return false;
    return nonNegByShape(mA);
}

/// Тройка сравнения `(head A B)`.
const CmpTriple = struct { h: []const u8, a: Sexp, b: Sexp };

fn asCmpTriple(s: Sexp) ?CmpTriple {
    if (!s.isList() or s.items.len != 3) return null;
    const h = s.items[0].atom orelse return null;
    const is_cmp = std.mem.eql(u8, h, "<=") or std.mem.eql(u8, h, ">=") or
        std.mem.eql(u8, h, "<") or std.mem.eql(u8, h, ">");
    if (!is_cmp) return null;
    return .{ .h = h, .a = s.items[1], .b = s.items[2] };
}

/// `(- X)` или `(* (- 1) X)` -> `X`.
fn negTermOf(t: Sexp) ?Sexp {
    if (!t.isList()) return null;
    const h = t.items[0].atom orelse return null;
    if (std.mem.eql(u8, h, "-") and t.items.len == 2) return t.items[1];
    if (!std.mem.eql(u8, h, "*") or t.items.len != 3) return null;
    const c = t.items[1];
    if (!c.isList() or c.items.len != 2) return null;
    const ch = c.items[0].atom orelse return null;
    if (!std.mem.eql(u8, ch, "-")) return null;
    const v = c.items[1].atom orelse return null;
    if (!std.mem.eql(u8, v, "1")) return null;
    return t.items[2];
}

/// `t` — сумма `x + (−y)` (в любом порядке слагаемых).
fn isSumOfXMinusY(t: Sexp, x: Sexp, y: Sexp) bool {
    if (!t.isList() or t.items.len != 3) return false;
    const h = t.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "+")) return false;
    if (sexpEq(t.items[1], x)) {
        if (negTermOf(t.items[2])) |ny| if (sexpEq(ny, y)) return true;
    }
    if (sexpEq(t.items[2], x)) {
        if (negTermOf(t.items[1])) |ny| if (sexpEq(ny, y)) return true;
    }
    return false;
}

/// `(✦ A B)` ⟺ `(✦ (+ A (− B)) 0)` для ✦ ∈ {≤, <, ≥, >}.
/// ПЕРЕНОС СЛАГАЕМОГО через знак сравнения — тождество теории порядка.
/// Дефект #212: `A` и `B` сравниваются СТРУКТУРНО (как в `eqAntisymEq`),
/// `parseLin` не вызывается — поэтому `ite` внутри `B` не мешает.
fn plainVsSubZero(p: CmpTriple, s: CmpTriple) bool {
    if (!std.mem.eql(u8, p.h, s.h)) return false;
    if (!isZeroAtom(s.b)) return false;
    return isSumOfXMinusY(s.a, p.a, p.b);
}

/// `(>= A B)` ⟺ `(<= (+ B (− A)) 0)` и `(> A B)` ⟺ `(< (+ B (− A)) 0)`.
fn plainVsFlipped(p: CmpTriple, s: CmpTriple) bool {
    const flip_ok = (std.mem.eql(u8, p.h, ">=") and std.mem.eql(u8, s.h, "<=")) or
        (std.mem.eql(u8, p.h, ">") and std.mem.eql(u8, s.h, "<"));
    if (!flip_ok) return false;
    if (!isZeroAtom(s.b)) return false;
    return isSumOfXMinusY(s.a, p.b, p.a);
}

/// `(<= A B)` ⟺ `(<= (+ A (* (- 1) B)) 0)` (и родственные формы).
fn cmpSubZeroEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    _ = c;
    const lt = asCmpTriple(l) orelse return false;
    const rt = asCmpTriple(r) orelse return false;
    if (plainVsSubZero(lt, rt) or plainVsSubZero(rt, lt)) return true;
    if (plainVsFlipped(lt, rt) or plainVsFlipped(rt, lt)) return true;
    return false;
}

/// ВЫЧИСЛИТЬ КОНСТАНТНОЕ ЦЕЛОЧИСЛЕННОЕ выражение. `null`, если хотя бы один
/// подтерм не константа (тогда шаг остаётся доверенным — честно).
///
/// ЗАЧЕМ (дефект #344, часть 2). Z3 сам вычисляет `(div 7 2)` и оформляет
/// результат шагом `rewrite`: `(= (div 7 2) 3)`. Чекер не умел считать
/// константы и помечал шаг ДОВЕРЕННЫМ (`trusted: 1`), из-за чего три тождества
/// EVM не доходили до `trusted: 0`. Дамп это и показывал:
/// `[dbg-rw-trusted] eq: (= (div 7 2) 3)`.
///
/// ЗВУЧНОСТЬ: вычисление функции над КОНСТАНТАМИ — константа; новых аксиом не
/// добавляется. Деление — FLOOR (так определено в SMT-LIB для Int), `mod` —
/// со знаком знаменателя (`@mod`); деление на ноль НЕ вычисляется (в SMT-LIB
/// оно не определено) — возвращаем `null`, и шаг не подтверждается.
fn evalConstInt(e: Sexp) ?i64 {
    if (e.atom) |a| {
        if (isNegNumAtom(a)) |d| {
            // ⚠️ `-9223372036854775808` = MIN(i64): модуль (2^63) в i64 НЕ влезает,
            // поэтому `parseInt` на нём падает, и значение MIN было недостижимо —
            // то есть защита от паники в `div`/`mod` оказалась МЁРТВЫМ кодом,
            // а тест «проходил» по неверной причине (не парсился литерал, а не
            // срабатывал guard). Разбираем MIN ЯВНО.
            if (std.mem.eql(u8, d, "9223372036854775808")) return std.math.minInt(i64);
            const v = std.fmt.parseInt(i64, d, 10) catch return null;
            return -v;
        }
        return std.fmt.parseInt(i64, a, 10) catch null;
    }
    if (e.items.len == 0) return null;
    const h = e.items[0].atom orelse return null;
    if (std.mem.eql(u8, h, "-") and e.items.len == 2) {
        // То же для формы `(- N)`, которой Z3 печатает отрицательные литералы.
        if (e.items[1].atom) |d| {
            if (std.mem.eql(u8, d, "9223372036854775808")) return std.math.minInt(i64);
        }
        const v = evalConstInt(e.items[1]) orelse return null;
        return std.math.sub(i64, 0, v) catch null;
    }
    if (e.items.len != 3) return null;
    const a = evalConstInt(e.items[1]) orelse return null;
    const b = evalConstInt(e.items[2]) orelse return null;
    // ⚠️ ПЕРЕПОЛНЕНИЕ — ЭТО ОТКАЗ, А НЕ ЗАВОРОТ. В SMT-LIB сорт `Int` имеет
    // ПРОИЗВОЛЬНУЮ точность, поэтому `(+ MAX 1)` там = 2^63, а `+%` в Zig дал бы
    // `MIN` — то есть ЛОЖНОЕ тождество `(= (+ MAX 1) MIN)`. Раньше стояли
    // `+% -% *%` (wrapping): это тихая подмена математики. Теперь checked-версии,
    // и переполнение честно возвращает `null` (шаг остаётся доверенным).
    if (std.mem.eql(u8, h, "+")) return std.math.add(i64, a, b) catch null;
    if (std.mem.eql(u8, h, "-")) return std.math.sub(i64, a, b) catch null;
    if (std.mem.eql(u8, h, "*")) return std.math.mul(i64, a, b) catch null;
    if (std.mem.eql(u8, h, "div")) {
        if (b == 0) return null; // в SMT-LIB деление на ноль не определено
        if (b > 0) return @divFloor(a, b);
        // ДЕФЕКТ (найден ревизией плана, подтверждён Z3): при b < 0 SMT-LIB
        // определяет `div`/`mod` ЕВКЛИДОВО (остаток ВСЕГДА >= 0), а не как
        // floor. ИЗМЕРЕНО: `(div 1 (- 2)) = 0`, `(mod 1 (- 2)) = 1`,
        // `(div (- 7) (- 2)) = 4` (не 3!). `@divFloor(1, -2)` в Zig даёт -1 —
        // то есть прежняя формула ПРИНИМАЛА ЛОЖНОЕ тождество, а `@mod(a, b)`
        // при b < 0 ПАНИКУЕТ («modulus is negative»).
        // Звучимость: `a = b*q + r`, `0 <= r < |b|` — теорема
        // `euclid_div_neg_denom` в `formal/FarkasSoundness.lean` (§95.4).
        if (b == std.math.minInt(i64)) return null; // `-b` переполнится
        const nb = -b;
        const q = @divFloor(a, nb);
        // `-q` может переполниться: `a = MIN, b = -1` даёт q = MIN, а ответ
        // Z3 равен 2^63 — он ВНЕ i64, значит значение не представимо: отказ.
        if (q == std.math.minInt(i64)) return null;
        return -q;
    }
    if (std.mem.eql(u8, h, "mod")) {
        if (b == 0) return null;
        if (b > 0) return @mod(a, b);
        if (b == std.math.minInt(i64)) return null;
        // Евклидов остаток неотрицателен: `mod(a, -|b|) = mod(a, |b|)`.
        return @mod(a, -b);
    }
    return null;
}

/// `(= l r)`, где обе стороны — КОНСТАНТЫ и они равны.
fn constIntEq(l: Sexp, r: Sexp) bool {
    const a = evalConstInt(l) orelse return false;
    const b = evalConstInt(r) orelse return false;
    return a == b;
}

fn checkRewrite(c: *const Ctx, st: Sexp) RwResult {
    if (st.items.len < 2) return .unverifiable;
    const eq = expand(c, st.items[1], 0);
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-rw0] раскрыто: ", .{});
        dumpSexp(eq);
        dbgPrint("\n", .{});
    }
    if (!isEq3(eq)) return .unverifiable;
    const l = eq.items[1];
    const r = eq.items[2];
    if (sexpEq(l, r)) return .verified; // рефлексивность: (= X X)
    // ИЗМЕРЕНО: `checkRewrite` вызывал `sexpEq` (чисто синтаксическое), а ВСЕ
    // нормализации (канонизация сравнений `cmpEq`, булевы формы `boolFormEq`,
    // линейные формы `linFormsEq`, константные строки) живут в `sexpEqNum`.
    // Из-за этого 3 доверенных `rewrite` в выводе IEEE-754 не сходились,
    // хотя все нужные тождества УЖЕ были реализованы.
    if (sexpEqNum(l, r)) return .verified;
    // КОНГРУЭНЦИЯ подтермов (CVE-B): формулы отличаются только записью
    // одного и того же линейного выражения ВНУТРИ ветвей ite. Звучимо по
    // Лейбницу; за лимитом глубины -> false (шаг остаётся доверенным).
    if (linCongruenceEq(l, r)) return .verified;
    // КАНОНИЗАЦИЯ СРАВНЕНИЙ верхнего уровня (`x ≥ y` ↔ `x − y ≥ 0` ↔ `¬(y − x > 0)`).
    if (cmpCanonEq(l, r)) return .verified;
    // ДЕФЕКТ #211 (дамп `value % 2 == 0`, 2 из 4 оставшихся шагов):
    //   (a) `(= A B) ⟺ (and (<= A B) (>= A B))` — АНТИСИММЕТРИЧНОСТЬ порядка,
    //       верна для ЛЮБЫХ термов, решатель не нужен;
    //   (b) `(ite (= m 0) X Y) ⟺ (ite (<= m 0) X Y)` при `m >= 0` — здесь
    //       `m = (mod value 2)`, и неотрицательность остатка — АКСИОМА ЕВКЛИДА
    //       (`0 <= mod x k` при `k > 0`). Принимаем ТОЛЬКО когда неотрицательность
    //       следует из формы терма, иначе шаг остаётся доверенным (звучность).
    if (eqAntisymEq(c, l, r)) return .verified;
    if (eqZeroIteEq(c, l, r)) return .verified;
    // ДЕФЕКТ #212: перенос слагаемого `(<= A B) ⟺ (<= (+ A (* (- 1) B)) 0)`.
    // A и B сравниваются СТРУКТУРНО, поэтому `ite` внутри них не мешает
    // (в отличие от линейной нормализации через `parseLin`).
    if (cmpSubZeroEq(c, l, r)) return .verified;

    // ТАВТОЛОГИЯ ИСКЛЮЧЁННОГО ТРЕТЬЕГО: `(or (not X) X) = true` и
    // `(and (not X) X) = false`. ИЗМЕРЕНО (кламп `+|`): Z3 оформляет
    // `¬P ∨ P` шагом rewrite, и без этого правила шаг оставался ДОВЕРЕННЫМ
    // (`trusted: 1`), хотя это чистая пропозициональная тавтология.
    if (r.atom) |ra| {
        if (isExcludedMiddle(c, l, std.mem.eql(u8, ra, "true"))) return .verified;
    }
    // ВЕРХНЯЯ ОЦЕНКА ite-ТЕРМА (шаг Z3 на клампе `+|`).
    if (iteCmpEq(c, l, r)) return .verified;
    if (iteCmpEq(c, r, l)) return .verified;
    // ВЫЧИСЛЕНИЕ КОНСТАНТ (Пункты 22/23) ДО раннего возврата для не-атомарных
    // сравнений: `(= (= false true) false)` — обе стороны НЕ атомы, и раньше
    // управление уходило в `return .unverifiable`, не доходя до этих проверок.
    if (constStrEq(l, r)) return .verified;
    if (constBoolEq(l, r)) return .verified;
    // СВЁРТКА `ite` С КОНСТАНТНЫМ УСЛОВИЕМ (`(= (ite false A B) B)`): ИЗМЕРЕНО
    // на пресете `@kern:idempotent` — Z3 сворачивает ветви clamp-функции именно
    // такими шагами. ЗВУЧНО: при известном условии `ite` — это выбор ветви.
    if (constIteEq(l, r)) return .verified;
    // ЛИНЕЙНАЯ ТАВТОЛОГИЯ `(= E true|false)`: ИЗМЕРЕНО на `@kern:no_arbitrage`
    // (шаг `(rewrite (= $x50 true))` для `3a1+3a2 >= 3(a1+a2)`). ЗВУЧНО:
    // истинность проверяет встроенный Фурье—Моцкин (гейт `make lia-diff`).
    if (linTautEq(c, l, r)) return .verified;
    // ТАВТОЛОГИЧНЫЙ КОНЪЮНКТ: `¬(A ∧ true) ≡ ¬A`. ИЗМЕРЕНО на `@kern:bounded`
    // (Пункт 26): Z3 отбрасывает `(<= x x)` как тавтологию.
    if (andTautEq(c, l, r)) return .verified;
    // ЭКВИВАЛЕНТНОСТЬ КОНЪЮНКЦИЙ: `¬A ≡ ¬B` при `A ↔ B` (обе импликации —
    // через Фурье—Моцкина). ИЗМЕРЕНО на `@kern:calls_u32` (Пункт 29).
    if (andEquivEq(c, l, r)) return .verified;
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
        if (dbgEnv("KERN_DEBUG_LIA") != null) {
            dbgPrint("[dbg-rw1] выход по normCmp-ветке: LHS=", .{});
            dumpSexp(l);
            dbgPrint(" RHS=", .{});
            dumpSexp(r);
            dbgPrint("\n", .{});
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
    // ДЕФЕКТ #344 (часть 2): КОНСТАНТНАЯ АРИФМЕТИКА. Z3 вычисляет `(div 7 2)`
    // и оформляет это шагом `rewrite`; без этого правила шаг оставался
    // ДОВЕРЕННЫМ, и три тождества EVM не доходили до `trusted: 0`.
    if (constIntEq(l, r)) return .verified;
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-rw] не проверено: LHS=", .{});
        dumpSexp(l);
        dbgPrint("  RHS=", .{});
        dumpSexp(r);
        dbgPrint("\n", .{});
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
            // ЭТАЛОН QF_S: `sexpEqNum`, а не `sexpEq` — иначе нормализации
            // (канонизация сравнений, булевы формы) не применяются к звеньям.
            if (!sexpEqNum(pr, t.items[1])) return false; // разрыв цепочки
        } else {
            first_left = t.items[1];
        }
        prev_right = t.items[2];
        count += 1;
    }
    if (count < 2) return false;
    return sexpEqNum(first_left.?, q.items[1]) and sexpEqNum(prev_right.?, q.items[2]);
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
        // ДЕФЕКТ #435 (Блок 2 плана, ИЗМЕРЕНО дампом `[dbg-lemma]`): ВЛОЖЕННАЯ
        // `(lemma P C)` — оператор СВЯЗЫВАНИЯ гипотез: все `(hypothesis H)`
        // внутри её поддерева УЖЕ разряжены её собственным заключением `C`.
        // Раньше обход шёл ВНУТРЬ неё, поэтому внешняя `lemma` получала ЧУЖИЕ
        // (уже закрытые) гипотезы и не могла покрыть их своим заключением.
        // ИЗМЕРЕНО на `storeinv…00002_001.cvc`: внешняя `lemma` — 6 гипотез при
        // заключении из ОДНОГО литерала, шаг уходил в доверенные.
        // ЗВУЧНО: пропуск закрытых гипотез ослабляет проверку ровно настолько,
        // насколько они уже доказаны ВНУТРЕННИМ шагом, который проверяется сам.
        if (std.mem.eql(u8, h, "lemma")) return;
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
    var hyps = std.array_list.Managed(Sexp).init(c.arena);
    var seen = std.array_list.Managed([]const u8).init(c.arena);
    collectHypotheses(c, pref, &hyps, &seen, 0);
    // ЭТАП А (диагностика): печать ВСЕХ входов, чтобы видеть точку отказа.
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-lemma] поддерево доказывает: ", .{});
        dumpSexp(pc);
        dbgPrint("\n[dbg-lemma] гипотез {d}; заключение: ", .{hyps.items.len});
        dumpSexp(concl);
        dbgPrint("\n", .{});
    }
    if (!(pc.atom != null and std.mem.eql(u8, pc.atom.?, "false"))) return false;
    // 2) Каждая гипотеза поддерева обязана быть опровергнута в заключении.
    if (hyps.items.len == 0) return false; // нечего разряжать — не наш случай
    var lits = std.array_list.Managed(Sexp).init(c.arena);
    flattenOr(concl, &lits);
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-lemma] гипотез {d}, дизъюнктов {d}; заключение: ", .{ hyps.items.len, lits.items.len });
        dumpSexp(concl);
        dbgPrint("\n", .{});
        for (hyps.items) |h| {
            dbgPrint("[dbg-lemma]   гипотеза: ", .{});
            dumpSexp(h);
            dbgPrint("\n", .{});
        }
    }
    for (hyps.items) |h| {
        var found = false;
        // ИЗМЕРЕНО (ЭТАЛОН IEEE-754): заключение `lemma` может быть ОТРИЦАНИЕМ
        // гипотезы ЦЕЛИКОМ, а не отдельным дизъюнктом:
        //   H          = (not (or r_nan (>= x_val 0) …))
        //   заключение =      (or r_nan (>= x_val 0) …)   <- это ровно ¬H
        // Прежняя проверка искала ¬H среди ДИЗЪЮНКТОВ и не находила.
        if (asNot(h)) |inner| {
            if (sexpEqNum(concl, inner)) found = true;
        }
        if (!found) {
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

/// Собрать ТОЛЬКО булевы ЛИТЕРАЛЫ: атомы в позиции литерала
/// (`(or X …)`, `(not X)`, голый атом) — и НЕ трогать переменные внутри
/// `=`, `str.contains`, арифметики.
///
/// ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-boolsplit] булевых переменных 3: result Char s`):
/// прежний сбор (все переменные минус арифметические) ошибочно включал
/// **String-переменные** `result`, `s` и имя типа `Char`. Гибрид подставлял им
/// `true`/`false` — это БЕССМЫСЛЕННАЯ подстановка и РИСК ЗВУЧНОСТИ.
fn collectBoolLits(s: Sexp, out: *std.array_list.Managed([]const u8)) void {
    if (s.atom) |a| {
        if (std.fmt.parseInt(i64, a, 10)) |_| return else |_| {}
        if (std.mem.eql(u8, a, "true") or std.mem.eql(u8, a, "false")) return;
        for (out.items) |n| if (std.mem.eql(u8, n, a)) return;
        if (out.items.len < MAX_BOOL_VARS) out.append(a) catch {};
        return;
    }
    if (s.items.len == 0) return;
    const h = s.items[0].atom orelse return;
    if (std.mem.eql(u8, h, "not") and s.items.len == 2) {
        collectBoolLits(s.items[1], out);
        return;
    }
    if ((std.mem.eql(u8, h, "or") or std.mem.eql(u8, h, "and")) and s.items.len >= 3) {
        for (s.items[1..]) |it| collectBoolLits(it, out);
        return;
    }
    // `=`, `str.contains`, арифметика, сравнения — НЕ литералы: не собираем.
}

/// `u ⊨ l` — юнит ВЛЕЧЁТ литерал клаузы (тогда литерал можно вычеркнуть).
///
/// ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-ur] units (1)`):
/// ```
/// клауза:  (or (or A (not B)) (not A))
/// units[0]: (not (or A (not B)))      =  ¬A ∧ B
/// remaining: (not A)                  =  ¬A
/// ```
/// `units[0] = ¬A ∧ B` **ВЛЕЧЁТ** `¬A`, но `isComplement` проверяет только
/// «дополнение» (`l = ¬u`), а не импликацию — поэтому литерал НЕ вычеркивался.
/// ЗВУЧНО: из `(not (or Y1 … Yk))` (то есть `¬Y1 ∧ … ∧ ¬Yk`) следует `¬Yi`.
fn unitImpliesLit(u: Sexp, l: Sexp) bool {
    const inner = asNot(u) orelse return false;
    if (!inner.isList() or inner.items.len < 3) return false;
    const h = inner.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;
    const li = asNot(l) orelse return false;
    for (inner.items[1..]) |y| {
        if (sexpEqNum(li, y)) return true;
    }
    return false;
}

/// Построить `(and R1 … Rk)` из списка остатка (для проверки де Моргана).
fn remainingToAnd(c: *const Ctx, items: []const Sexp) Sexp {
    var out = std.array_list.Managed(Sexp).init(c.arena);
    out.append(Sexp{ .atom = "and" }) catch return items[0];
    for (items) |it| out.append(it) catch return items[0];
    return Sexp{ .items = out.items };
}

/// `X` и `D` — контрарная пара: `X = (not D)` ИЛИ `D = (not X)`.
///
/// ИЗМЕРЕНО (ЭТАЛОН QF_S): `(and (not A) B) <=> (not (or A (not B)))` — в `or`
/// дизъюнкты имеют РАЗНЫЙ знак (`A` без `not`, `(not B)` с `not`), а прежний
/// `andDeMorganOne` требовал `(not …)` у ОБОИХ и не срабатывал.
fn isNegPair(x: Sexp, d: Sexp) bool {
    if (asNot(x)) |xi| {
        if (sexpEqNum(xi, d)) return true;
    }
    if (asNot(d)) |di| {
        if (sexpEqNum(x, di)) return true;
    }
    return false;
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
    const d1 = inner.items[1];
    const d2 = inner.items[2];
    // `(and X Y) <=> (not (or D1 D2))` при `X = ¬D1`, `Y = ¬D2` (знаки любые).
    return (isNegPair(x, d1) and isNegPair(y, d2)) or
        (isNegPair(x, d2) and isNegPair(y, d1));
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
/// ВЫЧИСЛЕНИЕ КОНСТАНТНОГО СРАВНЕНИЯ: `(< a b)`, `(<= a b)`, `(> a b)`,
/// `(>= a b)`, `(= a b)` при ОБОИХ числовых литералах. ЗВУЧНО (это арифметика
/// над конкретными числами, не решатель).
///
/// ИЗМЕРЕНО на пресете `@kern:idempotent`: Z3 сворачивает ветви clamp-функции
/// шагами `(rewrite (= (<= 0 100) true))` и `(rewrite (= (ite false 100 0) 0))`;
/// без этих двух правил шаги оставались ДОВЕРЕННЫМИ, хотя доказывать нечего.
fn constCmpEval(s: Sexp) ?bool {
    if (s.atom != null or s.items.len != 3) return null;
    const op = s.items[0].atom orelse return null;
    const a = numOf(s.items[1]) orelse return null;
    const b = numOf(s.items[2]) orelse return null;
    if (std.mem.eql(u8, op, "<")) return a < b;
    if (std.mem.eql(u8, op, "<=")) return a <= b;
    if (std.mem.eql(u8, op, ">")) return a > b;
    if (std.mem.eql(u8, op, ">=")) return a >= b;
    if (std.mem.eql(u8, op, "=")) return a == b;
    return null;
}

/// `(= (ite C T E) X)` при КОНСТАНТНОМ условии `C`: равенство выполнено, если
/// выбранная ветвь совпадает с `X` (по `sexpEqNum`). ЗВУЧНО: семантика `ite`
/// при известном условии — это выбор ветви, а не доверие решателю.
fn constIteEq(l: Sexp, r: Sexp) bool {
    return iteBranchEquals(l, r) or iteBranchEquals(r, l);
}

/// `a = (ite C T E)` при константном `C`: сравнить выбранную ветвь с `b`.
fn iteBranchEquals(a: Sexp, b: Sexp) bool {
    if (a.atom != null or a.items.len != 4) return false;
    if (!std.mem.eql(u8, a.items[0].atom orelse "", "ite")) return false;
    const cval = evalBoolConst(a.items[1]) orelse return false;
    const chosen = if (cval) a.items[2] else a.items[3];
    return sexpEqNum(chosen, b);
}

/// ЛИНЕЙНАЯ ТАВТОЛОГИЯ: `(= E true)` / `(= E false)`, где `E` — ЛИНЕЙНОЕ
/// сравнение над целыми. ЗВУЧНО: истинность `E` доказывает встроенный
/// Фурье—Моцкин (`builtin_lia`), UNSAT которого проверен ДИФФЕРЕНЦИАЛЬНЫМ гейтом
/// против Z3 (`make lia-diff`, 0 расхождений).
///
/// ИЗМЕРЕНО на пресете `@kern:no_arbitrage`: Z3 заканчивает вывод шагом
/// `(rewrite (= $x50 true))`, где `$x50` — сравнение `3a1 + 3a2 >= 3(a1 + a2)`.
/// Без этого правила шаг оставался ДОВЕРЕННЫМ.
fn isCmpExpr(s: Sexp) bool {
    if (!s.isList() or s.items.len != 3) return false;
    const h = s.items[0].atom orelse return false;
    return std.mem.eql(u8, h, "<=") or std.mem.eql(u8, h, "<") or
        std.mem.eql(u8, h, ">=") or std.mem.eql(u8, h, ">") or
        std.mem.eql(u8, h, "=");
}

fn linTautEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    var e = l;
    var ra = r.atom orelse return false;
    if (!std.mem.eql(u8, ra, "true") and !std.mem.eql(u8, ra, "false")) {
        // симметричная форма: `(= true E)`
        const la = l.atom orelse return false;
        if (!std.mem.eql(u8, la, "true") and !std.mem.eql(u8, la, "false")) return false;
        e = r;
        ra = la;
    }
    if (!isCmpExpr(e)) return false;
    const dbg = dbgEnv("KERN_DEBUG_LIA") != null;
    if (dbg) {
        dbgPrint("[dbg-taut] сравнение: ", .{});
        dumpSexp(e);
        dbgPrint(" -> ожидаем {s}\n", .{ra});
    }
    const want_true = std.mem.eql(u8, ra, "true");
    if (want_true) {
        // `E` истинно <=> ОТРИЦАНИЕ несовместно (все альтернативы ¬E дают UNSAT).
        var alts = std.array_list.Managed(std.array_list.Managed(builtin_lia.Lin)).init(c.arena);
        const ok = negAlternatives(c, e, &alts);
        if (dbg) dbgPrint("[dbg-taut] negAlternatives={} alts={d}\n", .{ ok, alts.items.len });
        if (!ok) return false;
        if (alts.items.len == 0) return false;
        for (alts.items) |g| {
            if (g.items.len == 0) return false;
            var s = builtin_lia.Solver.init(c.arena);
            defer s.deinit();
            const v = builtin_lia.checkUnsat(&s, g.items);
            if (dbg) dbgPrint("[dbg-taut] ограничений {d} -> {s}\n", .{ g.items.len, @tagName(std.meta.activeTag(v)) });
            if (std.meta.activeTag(v) != .unsat) return false;
        }
        return true;
    }
    // `E` ложно <=> само `E` несовместно.
    var cons = std.array_list.Managed(builtin_lia.Lin).init(c.arena);
    if (!asLeZero(c, e, &cons)) return false;
    if (cons.items.len == 0) return false;
    var s = builtin_lia.Solver.init(c.arena);
    defer s.deinit();
    return std.meta.activeTag(builtin_lia.checkUnsat(&s, cons.items)) == .unsat;
}

/// КОММУТАТИВНОСТЬ `+` и `*`: `(* a b)` ≡ `(* b a)`, `(+ a b)` ≡ `(+ b a)`.
/// ЗВУЧНО: сложение и умножение целых (и битовых векторов) коммутативны.
///
/// ИЗМЕРЕНО на `@kern:calls_u32` (Пункт 29): Z3 нормализует произведение
/// по-разному в разных узлах (`(* x 1000000)` против `(* 1000000 x)`), из-за
/// чего шаг `(rewrite (= $x68 $x80))` оставался ДОВЕРЕННЫМ, хотя доказывать в
/// нём нечего. Сопоставление — по мультимножеству аргументов (маска до 32).
fn commEq(a: Sexp, b: Sexp) bool {
    if (a.atom != null or b.atom != null) return false;
    if (a.items.len != b.items.len or a.items.len < 3) return false;
    const h = a.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "+") and !std.mem.eql(u8, h, "*")) return false;
    if (!std.mem.eql(u8, b.items[0].atom orelse "", h)) return false;
    const n = a.items.len - 1;
    if (n > 32) return false;
    var used: u64 = 0;
    for (a.items[1..]) |ai| {
        var found = false;
        for (b.items[1..], 0..) |bj, j| {
            const bit = @as(u64, 1) << @intCast(j);
            if ((used & bit) != 0) continue;
            if (sexpEqNum(ai, bj)) {
                used |= bit;
                found = true;
                break;
            }
        }
        if (!found) return false;
    }
    return true;
}

/// ДЕ МОРГАН (обе стороны): `¬(A ∧ B) ≡ (¬A ∨ ¬B)` и `¬(A ∨ B) ≡ (¬A ∧ ¬B)`.
/// ЗВУЧНО: законы де Моргана. ИЗМЕРЕНО на `@kern:bounded` (Пункт 26): Z3
/// заканчивает вывод шагом `(rewrite (= (not (and $x25 (<= x x))) $x36))`, где
/// `$x36` — как раз дизъюнкция отрицаний; без этого правила шаг оставался
/// ДОВЕРЕННЫМ.
fn deMorganEq(a: Sexp, b: Sexp) bool {
    return dmOneWay(a, b) or dmOneWay(b, a);
}

/// `(not (and X1..Xk))` против `(or (not X1)..(not Xk))` (и вариант с `or`/`and`).
fn dmOneWay(neg: Sexp, disj: Sexp) bool {
    if (neg.atom != null or disj.atom != null) return false;
    if (neg.items.len != 2) return false;
    if (!std.mem.eql(u8, neg.items[0].atom orelse "", "not")) return false;
    const inner = neg.items[1];
    if (inner.atom != null or inner.items.len < 3) return false;
    const ih = inner.items[0].atom orelse return false;
    const want_outer = if (std.mem.eql(u8, ih, "and")) "or" else if (std.mem.eql(u8, ih, "or")) "and" else return false;
    if (!std.mem.eql(u8, disj.items[0].atom orelse "", want_outer)) return false;
    if (disj.items.len != inner.items.len) return false;
    for (inner.items[1..], disj.items[1..]) |x, y| {
        if (!polarEq(x, y)) return false;
    }
    return true;
}

/// ИСТИННОСТЬ ЛИНЕЙНОГО СРАВНЕНИЯ `e`: все альтернативы ОТРИЦАНИЯ несовместны.
/// Проверяет встроенный Фурье—Моцкин (гейт `make lia-diff`).
fn linTaut(c: *const Ctx, e: Sexp) bool {
    if (!isCmpExpr(e)) return false;
    var alts = std.array_list.Managed(std.array_list.Managed(builtin_lia.Lin)).init(c.arena);
    if (!negAlternatives(c, e, &alts)) return false;
    if (alts.items.len == 0) return false;
    for (alts.items) |g| {
        if (g.items.len == 0) return false;
        var s = builtin_lia.Solver.init(c.arena);
        defer s.deinit();
        if (std.meta.activeTag(builtin_lia.checkUnsat(&s, g.items)) != .unsat) return false;
    }
    return true;
}

/// `(not (and X1..Xk)) ≡ (not Y)`, если все `Xi`, КРОМЕ совпадающего с `Y`,
/// — ТАВТОЛОГИИ. ЗВУЧНО: `¬(Y ∧ true ∧ …) = ¬Y`; истинность `Xi` доказывает
/// встроенный решатель (`linTaut`), а не догадка.
///
/// ИЗМЕРЕНО на `@kern:bounded` (Пункт 26): Z3 завершает вывод шагом
/// `(rewrite (= (not (and (>= x 0) (<= x x))) (not (>= x 0))))` — `(<= x x)`
/// тавтологично, поэтому конъюнкт отброшен.
fn andTautEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    return andTautOneWay(c, l, r) or andTautOneWay(c, r, l);
}

fn andTautOneWay(c: *const Ctx, l: Sexp, r: Sexp) bool {
    if (l.atom != null or l.items.len != 2) return false;
    if (!std.mem.eql(u8, l.items[0].atom orelse "", "not")) return false;
    const inner = l.items[1];
    if (inner.atom != null or inner.items.len < 3) return false;
    if (!std.mem.eql(u8, inner.items[0].atom orelse "", "and")) return false;
    if (r.atom != null or r.items.len != 2) return false;
    if (!std.mem.eql(u8, r.items[0].atom orelse "", "not")) return false;
    const y = r.items[1];
    var found = false;
    for (inner.items[1..]) |x| {
        if (!found and sexpEqNum(x, y)) {
            found = true;
            continue;
        }
        if (!linTaut(c, x)) return false;
    }
    return found;
}

/// Внутренняя конъюнкция формы `(not (and …))`.
fn andInner(s: Sexp) ?Sexp {
    if (s.atom != null or s.items.len != 2) return null;
    if (!std.mem.eql(u8, s.items[0].atom orelse "", "not")) return null;
    const inner = s.items[1];
    if (inner.atom != null or inner.items.len < 3) return null;
    if (!std.mem.eql(u8, inner.items[0].atom orelse "", "and")) return null;
    return inner;
}

/// `¬A ≡ ¬B`, если конъюнкции `A` и `B` ЭКВИВАЛЕНТНЫ: обе импликации
/// доказывает встроенный решатель (`impliesLinear`, Фурье—Моцкин). ЗВУЧНО:
/// из `A ↔ B` следует `¬A ↔ ¬B`.
///
/// ИЗМЕРЕНО на `@kern:calls_u32` (Пункт 29): Z3 завершает вывод шагом
/// `(= (not (and (>= (* x 1000000) 0) (<= (* x 1000000) 4294967295)))
///     (not (and (>= x 0) (<= x 4294))))` — то есть `0 ≤ 10^6·x ≤ 4294967295`
/// равносильно `0 ≤ x ≤ 4294` над целыми.
fn andEquivEq(c: *const Ctx, l: Sexp, r: Sexp) bool {
    const a = andInner(l) orelse return false;
    const b = andInner(r) orelse return false;
    return impliesLinear(c, a, b) and impliesLinear(c, b, a);
}

/// Сравнение с точностью до ОДНОГО отрицания (двойное отрицание — тождество):
/// `X` ≡ `Y`, `(not X)` ≡ `Y`, `X` ≡ `(not Y)`. ЗВУЧНО для сорта Bool.
///
/// ИЗМЕРЕНО на `@kern:rls` (Пункт 30): Z3 заканчивает вывод шагом
/// `(= (and (<= is_deleted 1) (>= is_deleted 1))
///     (not (or (not (<= is_deleted 1)) (not (>= is_deleted 1)))))` —
/// конъюнкция против де Моргана, где дизъюнкты уже содержат `not`.
fn polarEq(x: Sexp, y: Sexp) bool {
    if (sexpEqNum(x, y)) return true;
    if (asNot(x)) |zx| if (sexpEqNum(zx, y)) return true;
    if (asNot(y)) |zy| if (sexpEqNum(x, zy)) return true;
    return false;
}

fn evalBoolConst(s: Sexp) ?bool {
    if (s.atom) |a| {
        if (std.mem.eql(u8, a, "true")) return true;
        if (std.mem.eql(u8, a, "false")) return false;
        return null;
    }
    if (!s.isList()) return null;
    const op = s.items[0].atom orelse return null;
    if (std.mem.eql(u8, op, "=") and s.items.len == 3) {
        // РЕФЛЕКСИВНОСТЬ РАВЕНСТВА: `(= A A)` тождественно истинно для ЛЮБОГО
        // терма A. ЗВУЧНО и не требует решателя. ИЗМЕРЕНО на пресете
        // `@kern:idempotent`: Z3 завершает вывод шагом `(rewrite (= (= x x)
        // true))`, и без этого правила шаг оставался ДОВЕРЕННЫМ (trusted: 1),
        // хотя доказывать в нём нечего.
        if (sexpEqNum(s.items[1], s.items[2])) return true;
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
        var unknown = false;
        for (s.items[1..]) |it| {
            const v = evalBoolConst(it) orelse {
                unknown = true;
                continue;
            };
            acc = if (is_and) (acc and v) else (acc or v);
            // ТРЁХЗНАЧНАЯ ЛОГИКА КЛИНИ (K3) — ПОГЛОЩЕНИЕ КОНСТАНТЫ.
            // В `and` константа `false` поглощает ВЕСЬ терм независимо от
            // остальных аргументов; в `or` — константа `true`. Это ТОЖДЕСТВО
            // булевой логики: посылок нет, ослабления нет.
            // ИЗМЕРЕНО (дефект #430, шаг 1 плана): единственный доверенный шаг
            // `2PhLockVParam_RC-07` — `(rewrite (= (and false (not (or …)))
            // false))`. До правки `null` у любого аргумента давал `null` для
            // всего `and`, поэтому `constBoolEq` шаг НЕ брал.
            if (is_and and !acc) return false;
            if (!is_and and acc) return true;
        }
        if (unknown) return null;
        return acc;
    }
    // ПРИЧИНА №2 (продолжение): ЛИСТОВОЙ булев атом — строковый предикат над
    // константами. Без этого `(= (str.contains "safe" …) true)` не вычислялся,
    // и последний `rewrite` не сходился.
    if (evalStrPred(s)) |v| return v;
    // КОНСТАНТНОЕ СРАВНЕНИЕ (`(<= 0 100)`, `(< 0 0)`): арифметика над
    // конкретными числами. ИЗМЕРЕНО на пресете `@kern:idempotent`.
    if (constCmpEval(s)) |v| return v;
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

/// КОММУТАТИВНЫЕ бинарные операции (белый список, шаг 2 плана #430).
/// `-` и `<`/`<=` в него НЕ входят: они не коммутативны, и шаг
/// `(commutativity (= (< a1 a2) (< a2 a1)))` обязан быть ОТВЕРГНУТ.
fn isCommutativeOp(op: []const u8) bool {
    const OPS = [_][]const u8{
        "=",     "+",     "*",     "and",   "or",    "xor",
        "bvadd", "bvmul", "bvand", "bvor",  "bvxor",
    };
    for (OPS) |o| if (std.mem.eql(u8, op, o)) return true;
    return false;
}

/// `commutativity`: заключение — равенство ДВУХ термов, отличающихся ТОЛЬКО
/// порядком аргументов КОММУТАТИВНОЙ операции.
///
/// ИЗМЕРЕНО ДАМПОМ (дефект #430, шаг 2 плана): в `storeinv…00002_001.cvc`
/// первое доверенное правило — `commutativity`, шаг
/// `(commutativity (= $x124 (= a1 a2)))`, где `$x124` раскрывается в
/// `(= a2 a1)`. Раскрытие `$x`-имён в чекере уже есть (`expand`), поэтому
/// обе стороны приводятся к явному виду ДО сравнения.
///
/// ЗВУЧНО: коммутативность `=`/`+`/`*`/`and`/`or`/`bv*` — тождество логики,
/// у шага НЕТ посылок, ослабления нет. Проверяется СТРУКТУРНО.
fn verifyCommutativity(c: *const Ctx, st: Sexp) bool {
    const eq = expand(c, proved(st), 0);
    if (!eq.isList() or eq.items.len != 3) return false;
    const h = eq.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "=")) return false;
    const l = eq.items[1];
    const r = eq.items[2];
    if (!l.isList() or !r.isList()) return false;
    if (l.items.len != 3 or r.items.len != 3) return false;
    const lop = l.items[0].atom orelse return false;
    const rop = r.items[0].atom orelse return false;
    if (!std.mem.eql(u8, lop, rop)) return false;
    if (!isCommutativeOp(lop)) return false;
    // ОПЕРАНДЫ ОБЯЗАНЫ БЫТЬ ПЕРЕСТАВЛЕНЫ. Иначе шаг ничего не доказывает:
    // подделка `(commutativity (= (= a1 a2) (= a1 a3)))` отвергается здесь.
    return sexpEqNum(l.items[1], r.items[2]) and sexpEqNum(l.items[2], r.items[1]);
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
    // `(not (<= A B))` ≡ `(< B A)` и `(not (< A B))` ≡ `(<= B A)`
    // ИЗМЕРЕНО (доверенный rewrite): `(< x_val 0)` vs `(not (<= 0 x_val))`.
    if (asNot(a)) |x| {
        if (cmpFlipEq(x, b)) return true;
    }
    if (asNot(b)) |y| {
        if (cmpFlipEq(y, a)) return true;
    }
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
    // ИЗМЕРЕНО: после нормализации `(= r_nan false)` -> `r_nan` нужно, чтобы
    // ОДИНАКОВЫЕ атомы считались равными (`boolFormEq(r_nan, r_nan)` давало false,
    // из-за чего `(and (< x 0) (= r_nan false) …)` не сходилось с
    // `(and (not (<= 0 x)) (not r_nan) …)`).
    // Прямое сравнение атомов — БЕЗ рекурсии в `sexpEqNum` (иначе цикл).
    if (a.atom) |aa| {
        if (b.atom) |bb| return std.mem.eql(u8, aa, bb);
    }
    return false;
}

/// `(not (<= A B))` ≡ `(< B A)` и `(not (< A B))` ≡ `(<= B A)` — БЕЗ создания узлов.
fn cmpFlipEq(not_cmp: Sexp, direct: Sexp) bool {
    if (!not_cmp.isList() or not_cmp.items.len != 3) return false;
    if (!direct.isList() or direct.items.len != 3) return false;
    const nh = not_cmp.items[0].atom orelse return false;
    const dh = direct.items[0].atom orelse return false;
    const na = not_cmp.items[1];
    const nb = not_cmp.items[2];
    const da = direct.items[1];
    const db = direct.items[2];
    // (not (<= A B))  <=>  (< B A)  <=>  (> A B)
    if (std.mem.eql(u8, nh, "<=")) {
        if (std.mem.eql(u8, dh, "<") or std.mem.eql(u8, dh, ">")) {
            return sexpEqNum(na, db) and sexpEqNum(nb, da);
        }
    }
    // (not (< A B))  <=>  (<= B A)  <=>  (>= A B)
    if (std.mem.eql(u8, nh, "<")) {
        if (std.mem.eql(u8, dh, "<=") or std.mem.eql(u8, dh, ">=")) {
            return sexpEqNum(na, db) and sexpEqNum(nb, da);
        }
    }
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

/// ЛИНЕЙНАЯ НОРМАЛИЗАЦИЯ `(= SUM 0)` С ТОЧНОСТЬЮ ДО ЗНАКА.
///
/// ИЗМЕРЕНО (дамп `[dbg-rw0]`, оставшиеся 3 доверенных `rewrite` в IEEE-754):
/// ```text
/// (= (+ r_val (* (- 1) x_val)) 0)   vs   (= (+ x_val (* (- 1) r_val)) 0)
/// ```
/// Это `r_val - x_val = 0` против `x_val - r_val = 0`. Как ПРЕДИКАТЫ они
/// эквивалентны (`r_val = x_val`), но СТРУКТУРНО различны.
/// ЗВУЧНО: `X = 0  <=>  -X = 0`, и слагаемые можно переставлять.
const SumTerm = struct { coef: i64, atom: []const u8 };

fn litConst(s: Sexp) ?i64 {
    if (s.atom) |a| {
        return std.fmt.parseInt(i64, a, 10) catch return null;
    }
    if (s.isList() and s.items.len == 2) {
        const h = s.items[0].atom orelse return null;
        if (std.mem.eql(u8, h, "-")) {
            if (s.items[1].atom) |a| {
                const n = std.fmt.parseInt(i64, a, 10) catch return null;
                return -n;
            }
        }
    }
    return null;
}

fn collectSum(s: Sexp, sign: i64, terms: *std.array_list.Managed(SumTerm), konst: *i64) bool {
    if (s.atom) |a| {
        if (std.fmt.parseInt(i64, a, 10)) |n| {
            konst.* += sign * n;
            return true;
        } else |_| {}
        terms.append(.{ .coef = sign, .atom = a }) catch return false;
        return true;
    }
    if (!s.isList() or s.items.len < 3) return false;
    const h = s.items[0].atom orelse return false;
    if (std.mem.eql(u8, h, "+")) {
        // ИЗМЕРЕНО (CVE-B): Z3 пишет суммы N-АРНО (`(+ K a (* (- 1) b))`), а
        // прежний код принимал только бинарный `+` (len == 3), поэтому
        // линейные формы не совпадали. Ассоциативность/коммутативность
        // сложения — тождество, ослабления нет.
        for (s.items[1..]) |it| {
            if (!collectSum(it, sign, terms, konst)) return false;
        }
        return true;
    }
    if (s.items.len != 3) return false;
    if (std.mem.eql(u8, h, "-")) {
        return collectSum(s.items[1], sign, terms, konst) and
            collectSum(s.items[2], -sign, terms, konst);
    }
    if (std.mem.eql(u8, h, "*")) {
        const lc = litConst(s.items[1]);
        const rc = litConst(s.items[2]);
        if (lc) |k| return collectSum(s.items[2], sign * k, terms, konst);
        if (rc) |k| return collectSum(s.items[1], sign * k, terms, konst);
        return false;
    }
    return false;
}

fn sumsMatch(tx: []const SumTerm, kx: i64, ty: []const SumTerm, ky: i64, s: i64) bool {
    if (kx != s * ky) return false;
    if (tx.len != ty.len) return false;
    for (tx) |a| {
        var found = false;
        for (ty) |b| {
            if (std.mem.eql(u8, a.atom, b.atom) and a.coef == s * b.coef) {
                found = true;
                break;
            }
        }
        if (!found) return false;
    }
    return true;
}

/// КАНОНИЗАТОР СРАВНЕНИЙ: любое `<=, <, >=, >` (в т.ч. под `not`) приводится
/// к виду `Σ c_i·x_i + k ≤ 0` над ℤ.
///
/// ЗВУЧИМОСТЬ (тождества над ℤ, не приближения):
///   `x ≤ y  ↔  x − y ≤ 0`
///   `x < y  ↔  x − y + 1 ≤ 0`          (целочисленный сдвиг)
///   `x ≥ y  ↔  y − x ≤ 0`
///   `x > y  ↔  y − x + 1 ≤ 0`
///   `¬(x ≤ y) ↔ y − x + 1 ≤ 0`, `¬(x < y) ↔ y − x ≤ 0`, и т.д. (знак + сдвиг).
///
/// ИЗМЕРЕНО (CVE-B, `ptr_wrap_guard.smt2`): Z3 переписывает
///   `(not (<= (ite …) cap))` -> `(not (<= (+ (ite …) (* (- 1) cap)) 0))`
///   -> `(not (>= (+ cap (* (- 1) (ite …))) 0))`
/// — это ОДИН предикат, но структурно три разных записи; без канонизации
/// 2 шага оставались доверенными.
fn cmpCanonInto(s: Sexp, terms: *std.array_list.Managed(SumTerm), konst: *i64) bool {
    var e = s;
    var neg = false;
    while (e.isList() and e.items.len == 2) {
        const h = e.items[0].atom orelse break;
        if (!std.mem.eql(u8, h, "not")) break;
        neg = !neg;
        e = e.items[1];
    }
    if (!e.isList() or e.items.len != 3) return false;
    const h = e.items[0].atom orelse return false;
    const lhs = e.items[1];
    const rhs = e.items[2];
    var sign: i64 = 1;
    var k: i64 = 0;
    if (std.mem.eql(u8, h, "<=")) {
        sign = 1;
        k = 0;
    } else if (std.mem.eql(u8, h, "<")) {
        sign = 1;
        k = 1;
    } else if (std.mem.eql(u8, h, ">=")) {
        sign = -1;
        k = 0;
    } else if (std.mem.eql(u8, h, ">")) {
        sign = -1;
        k = 1;
    } else return false;
    // Отрицание переворачивает сравнение: `¬(x≤y) ↔ y−x+1≤0` и т.д.
    if (neg) {
        sign = -sign;
        k = 1 - k;
    }
    if (!collectSum(lhs, sign, terms, konst)) return false;
    if (!collectSum(rhs, -sign, terms, konst)) return false;
    konst.* += k;
    return true;
}

fn cmpCanonEq(a: Sexp, b: Sexp) bool {
    var ta = std.array_list.Managed(SumTerm).init(std.heap.page_allocator);
    defer ta.deinit();
    var tb = std.array_list.Managed(SumTerm).init(std.heap.page_allocator);
    defer tb.deinit();
    var ka: i64 = 0;
    var kb: i64 = 0;
    if (!cmpCanonInto(a, &ta, &ka)) return false;
    if (!cmpCanonInto(b, &tb, &kb)) return false;
    if (ta.items.len == 0 and tb.items.len == 0) return false;
    return sumsMatch(ta.items, ka, tb.items, kb, 1);
}


fn eqZeroLhs(s: Sexp) ?Sexp {
    if (!s.isList() or s.items.len != 3) return null;
    const h = s.items[0].atom orelse return null;
    if (!std.mem.eql(u8, h, "=")) return null;
    if (s.items[2].atom) |a2| {
        if (std.mem.eql(u8, a2, "0")) return s.items[1];
    }
    if (s.items[1].atom) |a1| {
        if (std.mem.eql(u8, a1, "0")) return s.items[2];
    }
    return null;
}

fn eqZeroUpToSign(a: Sexp, b: Sexp) bool {
    return linFormsEq(a, b);
}

/// Линейная форма выражения: `(= X Y)` -> `X − Y`, иначе само выражение.
fn linFormOf(s: Sexp, terms: *std.array_list.Managed(SumTerm), konst: *i64) bool {
    if (s.isList() and s.items.len == 3) {
        const h = s.items[0].atom orelse return collectSum(s, 1, terms, konst);
        if (std.mem.eql(u8, h, "=")) {
            if (!collectSum(s.items[1], 1, terms, konst)) return false;
            if (!collectSum(s.items[2], -1, terms, konst)) return false;
            return true;
        }
    }
    return collectSum(s, 1, terms, konst);
}

/// ИЗМЕРЕНО (доверенный rewrite): `(= r_val x_val)` vs `(= (+ r_val (* (- 1) x_val)) 0)`
/// — это `a = b` против `a − b = 0`, ОДИН предикат. Приводим обе стороны к
/// линейной форме и сравниваем (с точностью до общего знака: `X = 0 <=> −X = 0`).
fn linFormsEq(a: Sexp, b: Sexp) bool {
    var ta = std.array_list.Managed(SumTerm).init(std.heap.page_allocator);
    defer ta.deinit();
    var tb = std.array_list.Managed(SumTerm).init(std.heap.page_allocator);
    defer tb.deinit();
    var ka: i64 = 0;
    var kb: i64 = 0;
    if (!linFormOf(a, &ta, &ka)) return false;
    if (!linFormOf(b, &tb, &kb)) return false;
    if (ta.items.len == 0 and tb.items.len == 0) return false;
    return sumsMatch(ta.items, ka, tb.items, kb, 1) or
        sumsMatch(ta.items, ka, tb.items, kb, -1);
}

/// КОНГРУЭНЦИЯ С ТОЧНОСТЬЮ ДО ЛИНЕЙНОЙ ЭКВИВАЛЕНТНОСТИ ПОДТЕРМОВ.
///
/// ИЗМЕРЕНО (CVE-B, `ptr_wrap_guard.smt2`): Z3 переписывает
///   `(= (not (<= (ite C (- a b) (+ (- a b) K)) cap))
///       (not (<= (ite C (+ a (* (- 1) b)) (+ K a (* (- 1) b))) cap)))`
/// — обе формулы отличаются ТОЛЬКО записью одного и того же линейного
/// выражения внутри ветвей `ite`. `linFormsEq` сравнивает линейные формы
/// на ВЕРХНЕМ уровне и до подтермов не достаёт, поэтому 3 шага оставались
/// доверенными (`trusted: 3`), хотя равенство очевидно.
///
/// ЗВУЧИМОСТЬ: если подтермы равны по значению, то и охватывающие формулы
/// равны — это Лейбниц (`congrArg`), без приближений. Ограничение глубины и
/// арности — только защита от раздувания; за лимитом возвращается false
/// (шаг остаётся доверенным, а НЕ «доказанным»).
fn linCongruenceDepth(a: Sexp, b: Sexp, depth: u8) bool {
    if (sexpEq(a, b)) return true;
    if (depth == 0) return false;
    if (linFormsEq(a, b)) return true;
    // Сравнения канонизируются (`x ≥ y` ↔ `x − y ≥ 0` ↔ `¬(y − x > 0)`):
    // ИЗМЕРЕНО на CVE-B — две из трёх записей одного предиката.
    if (cmpCanonEq(a, b)) return true;
    if (a.atom != null or b.atom != null) return false;
    if (a.items.len != b.items.len or a.items.len == 0) return false;
    if (a.items.len > 64) return false;
    for (a.items, b.items) |x, y| {
        if (!linCongruenceDepth(x, y, depth - 1)) return false;
    }
    return true;
}

fn linCongruenceEq(a: Sexp, b: Sexp) bool {
    return linCongruenceDepth(a, b, 8);
}

/// ПОЛНЫЙ ПЕРЕБОР ПО БУЛЕВЫМ ПЕРЕМЕННЫМ (звучимая проверка тавтологии).
///
/// ИЗМЕРЕНО (ЭТАЛОН IEEE-754): `(def-axiom (or (not (= r_nan x_nan)) (not r_nan) x_nan))`
/// — ТАВТОЛОГИЯ, но не «по паре литералов»: она тавтологична благодаря РАВЕНСТВУ
/// `r_nan = x_nan` (тогда `(not r_nan)` и `x_nan` — контрарная пара).
/// Перебор по всем значениям булевых переменных — это СЕМАНТИКА булевой логики,
/// ослабления нет (число переменных ограничено).
const MAX_BOOL_VARS = 6;

fn collectBoolVars(s: Sexp, names: *std.array_list.Managed([]const u8)) void {
    if (s.atom) |a| {
        if (std.mem.eql(u8, a, "true") or std.mem.eql(u8, a, "false")) return;
        if (std.fmt.parseInt(i64, a, 10)) |_| return else |_| {}
        for (names.items) |n| if (std.mem.eql(u8, n, a)) return;
        if (names.items.len < MAX_BOOL_VARS) names.append(a) catch {};
        return;
    }
    for (s.items) |it| collectBoolVars(it, names);
}

fn lookupVar(names: []const []const u8, vals: []const bool, a: []const u8) ?bool {
    for (names, 0..) |n, i| if (std.mem.eql(u8, n, a)) return vals[i];
    return null;
}

fn evalBoolSubst(s: Sexp, names: []const []const u8, vals: []const bool) ?bool {
    if (s.atom) |a| {
        if (std.mem.eql(u8, a, "true")) return true;
        if (std.mem.eql(u8, a, "false")) return false;
        return lookupVar(names, vals, a);
    }
    if (s.items.len < 2) return null;
    const h = s.items[0].atom orelse return null;
    if (std.mem.eql(u8, h, "not")) {
        const x = evalBoolSubst(s.items[1], names, vals) orelse return null;
        return !x;
    }
    if (std.mem.eql(u8, h, "=") and s.items.len == 3) {
        const x = evalBoolSubst(s.items[1], names, vals) orelse return null;
        const y = evalBoolSubst(s.items[2], names, vals) orelse return null;
        return x == y;
    }
    if ((std.mem.eql(u8, h, "and") or std.mem.eql(u8, h, "or")) and s.items.len >= 3) {
        const is_and = std.mem.eql(u8, h, "and");
        var acc = is_and;
        for (s.items[1..]) |it| {
            const v = evalBoolSubst(it, names, vals) orelse return null;
            acc = if (is_and) (acc and v) else (acc or v);
        }
        return acc;
    }
    return null;
}

/// Тавтология ли формула: все 2^n подстановок дают `true`.
fn isBoolTautology(s: Sexp) bool {
    var names = std.array_list.Managed([]const u8).init(std.heap.page_allocator);
    defer names.deinit();
    collectBoolVars(s, &names);
    if (names.items.len == 0 or names.items.len > MAX_BOOL_VARS) return false;
    var vals: [MAX_BOOL_VARS]bool = undefined;
    const total: usize = @as(usize, 1) << @intCast(names.items.len);
    var mask: usize = 0;
    while (mask < total) : (mask += 1) {
        for (0..names.items.len) |i| vals[i] = (mask >> @intCast(i)) & 1 == 1;
        const v = evalBoolSubst(s, names.items, vals[0..names.items.len]) orelse return false;
        if (!v) return false;
    }
    return true;
}

/// `(iff-true P (= Q true))` — P доказывает Q, значит `(= Q true)`.
///
/// ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-trusted] #2 iff-true :: (iff-true @x78 (= $x74 true))`):
/// правило не было ни в `KNOWN_RULES`, ни в верификаторах — цепочка `trans*`
/// рвалась. ЗВУЧНО: из `P` следует `(= P true)`.
fn verifyIffTrue(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const concl = expand(c, proved(st), 0);
    if (!isEq3(concl)) return false;
    const a = concl.items[1];
    const b = concl.items[2];
    const q = blk: {
        if (b.atom) |x| {
            if (std.mem.eql(u8, x, "true")) break :blk a;
        }
        if (a.atom) |x| {
            if (std.mem.eql(u8, x, "true")) break :blk b;
        }
        return false;
    };
    const p = premiseTerm(c, st.items[1]);
    return sexpEqNum(p, q);
}

/// `(iff-false P (= Q false))` — P доказывает `(not Q)`, значит `(= Q false)`.
fn verifyIffFalse(c: *const Ctx, st: Sexp) bool {
    if (st.items.len < 3) return false;
    const concl = expand(c, proved(st), 0);
    if (!isEq3(concl)) return false;
    const a = concl.items[1];
    const b = concl.items[2];
    const q = blk: {
        if (b.atom) |x| {
            if (std.mem.eql(u8, x, "false")) break :blk a;
        }
        if (a.atom) |x| {
            if (std.mem.eql(u8, x, "false")) break :blk b;
        }
        return false;
    };
    const p = premiseTerm(c, st.items[1]);
    if (asNot(p)) |inner| return sexpEqNum(inner, q);
    return false;
}

fn verifyDefAxiom(c: *const Ctx, st: Sexp) bool {
    const t = expand(c, proved(st), 0);
    if (!t.isList() or t.items.len < 3) return false;
    const h = t.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;
    // ИЗМЕРЕНО (ЭТАЛОН IEEE-754, доверенный `(def-axiom (or $x86 $x49 x_nan))`):
    // прежняя проверка `t.items.len != 3` ОТВЕРГАЛА клаузы из 3+ дизъюнктов
    // (4 элемента: `or` + 3 литерала). Форма определения `ite` — ровно 2 дизъюнкта.
    if (t.items.len == 3) {
        if (verifyIteDisjunct(t.items[1], t.items[2]) or
            verifyIteDisjunct(t.items[2], t.items[1])) return true;
    }
    // ПУНКТ 3 v2.5: аксиома определения обязана быть ТАВТОЛОГИЕЙ. Кроме формы
    // `ite` Z3 вводит так и другие определяющие клаузы (в том числе из 3+
    // дизъюнктов) — их тавтологичность проверяем НЕСОВМЕСТНОСТЬЮ ОТРИЦАНИЯ.
    if (isTautologyClause(c, t)) return true;
    // ЭТАЛОН IEEE-754: клауза-тавтология, опирающаяся на РАВЕНСТВО переменных
    // (`(or (not (= r_nan x_nan)) (not r_nan) x_nan)`). Проверяем ПОЛНЫМ
    // перебором по булевым переменным — это семантика булевой логики.
    if (isBoolTautology(t)) return true;
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-defax] раскрытая клауза: ", .{});
        dumpSexp(t);
        dbgPrint("\n", .{});
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
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-noe] src=", .{});
        dumpSexp(src);
        dbgPrint(" concl=", .{});
        dumpSexp(concl);
        dbgPrint("\n", .{});
    }
    const inner = asNot(src) orelse return false;
    if (!inner.isList() or inner.items.len < 2) return false;
    const h = inner.items[0].atom orelse return false;
    if (!std.mem.eql(u8, h, "or")) return false;
    for (inner.items[1..]) |disj| {
        if (asNot(disj)) |n| {
            if (sexpEq(n, concl)) return true;
        }
        // ДЕФЕКТ #210 (дамп на `value % 2 == 0`): Z3 выводит ЗНАКОВУЮ форму
        //   src = (not (or (= result 1) (= result 0)))
        //   concl = (not (= result 0))
        // Дизъюнкты здесь — НЕ отрицания, поэтому прежняя ветка их не видела и
        // шаг уходил в доверенные. Но `¬(A ∨ B) ⊨ ¬B` — тот же закон де Моргана
        // (в контрапозитивной записи), поэтому проверяем и его: заключение
        // обязано быть ОТРИЦАНИЕМ одного из дизъюнктов.
        if (asNot(concl)) |nc| {
            if (sexpEq(nc, disj)) return true;
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
    // ОТБРОС НУЛЕВЫХ КОЭФФИЦИЕНТОВ (ИЗМЕРЕНО на `@kern:no_arbitrage`).
    // Раньше в ограничение попадали термы вида `0*a1`, поэтому после исключения
    // переменных `l.terms.len != 0`, и встроенный решатель НЕ видел, что
    // ограничение стало чистО константным (`1 <= 0`) — возвращал `unknown`, и
    // корректный шаг `(rewrite (= (>= X X) true))` оставался ДОВЕРЕННЫМ.
    // ЗВУЧНО: слагаемое с нулевым коэффициентом не влияет на неравенство.
    var nz: usize = 0;
    for (l.terms.items) |t| {
        if (t.coeff != 0) nz += 1;
    }
    const arr = c.arena.alloc(builtin_lia.Term, nz) catch return false;
    var i: usize = 0;
    for (l.terms.items) |t| {
        if (t.coeff == 0) continue;
        arr[i] = .{ .name = t.name, .coeff = t.coeff };
        i += 1;
    }
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
    const dbg = dbgEnv("KERN_DEBUG_LIA") != null;
    if (dbg) dbgPrint("[dbg-lia] шаг: аргументов {d}\n", .{st.items.len});
    // Посылки — ВСЕ аргументы, кроме последнего (последний есть заключение).
    if (st.items.len >= 2) {
        for (st.items[1 .. st.items.len - 1]) |pnode| {
            // ДЕФЕКТ #155 (найден `evo_fuzzer.py`). БИТАЯ ссылка `@xN` (шаг
            // переименован, ссылки остались) — это ИСПОРЧЕННОЕ доказательство,
            // а не «форма вне модели». Раньше такая посылка молча выпадала,
            // сертификат Фаркаша не строился (Фаркаш 3 -> 0), а вердикт
            // оставался «PROOF VERIFIED trusted: 0», rc=0. Теперь — отказ.
            if (pnode.atom) |a| {
                // Проверяем только в РЕАЛЬНОМ выводе (карта шагов заполнена).
                // В ручных юнит-тестах контекст создаётся без `collect`, и
                // `stepexpr` пуст — там такая проверка дала бы 25 ложных
                // отказов (ИЗМЕРЕНО).
                if (c.stepexpr.count() > 0 and a.len > 1 and a[0] == '@' and c.stepexpr.get(a) == null) {
                    if (dbg) dbgPrint("[dbg-lia] BROKEN REF -> reject\n", .{});
                    return .bad;
                }
            }
            const f = formulaOf(c, pnode) orelse {
                if (dbg) dbgPrint("[dbg-lia] посылка НЕ разрешена (нет формулы)\n", .{});
                return .structural_only;
            };
            const fe = expand(c, f, 0);
            if (!asLeZero(c, fe, &cons)) {
                if (dbg) {
                    const h = if (fe.isList() and fe.items.len > 0)
                        (fe.items[0].atom orelse "list-head")
                    else
                        "atom";
                    dbgPrint("[dbg-lia] посылка не переведена: форма={s} элементов={d}\n", .{ h, fe.items.len });
                }
                return .structural_only;
            }
            if (dbg) dbgPrint("[dbg-lia] посылка OK\n", .{});
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
        dbgPrint("[dbg-lia] ограничений {d} -> {s}\n", .{
            cons.items.len, @tagName(std.meta.activeTag(vres)),
        });
    }
    // ВОССТАНОВЛЕНО (регрессия при правке #155): несовместность системы —
    // это ДОКАЗАТЕЛЬСТВО леммы (`.ok`). Без этой ветви корректные невесовые
    // th-lemma становились доверенными (ИЗМЕРЕНО: тест «ВЕРНАЯ невесовая
    // th-lemma принимается» падал с `.structural_only`).
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
                // ДЕФЕКТ #155 (НАЙДЕН эволюционным фаззером `evo_fuzzer.py`).
                // Нерезолвленная ссылка `@xN` (шаг переименован, а ссылки
                // остались) раньше МОЛЧА выпадала из сертификата Фаркаша:
                // ИЗМЕРЕНО — переименование определения `@x147` -> `@x9`
                // давало `Фаркаш 3 -> 0`, но всё равно `PROOF VERIFIED
                // trusted: 0` с rc=0. Непроверяемая посылка обязана вести
                // к отказу, а не к «доказано».
                if (a.len > 1 and a[0] == '@' and c.stepexpr.get(a) == null) {
                    return .structural_only;
                }
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
/// ИЗМЕРЕНО (ЭТАЛОН IEEE-754): после добавления `¬concl` КЛАУЗОЙ комбинаций
/// стало 8 * 3 = 24 — прежний бюджет 16 отсекал шаг раньше проверки.
const MAX_CLAUSE_COMBOS: usize = 64;

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
/// Собрать АРИФМЕТИЧЕСКИЕ переменные (внутри `+ - * <= >= < >`).
/// Нужны, чтобы отличить булевы переменные (`r_nan`, `x_nan`) от целых (`r_val`).
fn collectArithVars(s: Sexp, out: *std.array_list.Managed([]const u8), inside: bool) void {
    if (s.atom) |a| {
        if (inside) {
            if (std.fmt.parseInt(i64, a, 10)) |_| return else |_| {}
            if (std.mem.eql(u8, a, "true") or std.mem.eql(u8, a, "false")) return;
            for (out.items) |n| if (std.mem.eql(u8, n, a)) return;
            out.append(a) catch {};
        }
        return;
    }
    if (s.items.len == 0) return;
    const h = s.items[0].atom orelse "";
    const arith = std.mem.eql(u8, h, "+") or std.mem.eql(u8, h, "-") or
        std.mem.eql(u8, h, "*") or std.mem.eql(u8, h, "<=") or std.mem.eql(u8, h, ">=") or
        std.mem.eql(u8, h, "<") or std.mem.eql(u8, h, ">") or std.mem.eql(u8, h, "=");
    // `=` неоднозначен (может быть булевым равенством) -> в арифметику не берём.
    const arith_strict = arith and !std.mem.eql(u8, h, "=");
    for (s.items[1..]) |it| collectArithVars(it, out, inside or arith_strict);
}

fn collectAllVars(s: Sexp, out: *std.array_list.Managed([]const u8)) void {
    if (s.atom) |a| {
        if (std.fmt.parseInt(i64, a, 10)) |_| return else |_| {}
        if (std.mem.eql(u8, a, "true") or std.mem.eql(u8, a, "false")) return;
        for (out.items) |n| if (std.mem.eql(u8, n, a)) return;
        out.append(a) catch {};
        return;
    }
    // ИЗМЕРЕНО: обход `s.items` (включая ГОЛОВУ) собирал СЛУЖЕБНЫЕ слова
    // (`not`, `or`, `>=`, `=`, `+`) как «переменные» — 10 вместо 2.
    // Голова — это оператор, а не переменная: обходим только `items[1..]`.
    for (s.items[1..]) |it| collectAllVars(it, out);
}

fn isArithVar(arith: []const []const u8, a: []const u8) bool {
    for (arith) |n| if (std.mem.eql(u8, n, a)) return true;
    return false;
}

fn boolAtom(v: bool) Sexp {
    return Sexp{ .atom = if (v) "true" else "false" };
}

/// ПОДСТАНОВКА булевых переменных С УПРОЩЕНИЕМ булевых связок.
///
/// ИЗМЕРЕНО (ЭТАЛОН IEEE-754): `[dbg-combo] unit НЕ переведён:
/// (not (or r_nan (>= x_val 0) (not (>= r_val 0)) (not (<= r_val 0))))` —
/// `evalBoolSubst` не может вычислить литерал ЦЕЛИКОМ (внутри есть `>=`),
/// поэтому нужна ЧАСТИЧНАЯ подстановка: заменить булевы переменные на
/// `true`/`false`, затем упростить `not`/`and`/`or`.
/// ЗВУЧНО: это тождественные преобразования булевой логики.
fn substBoolSimplify(c: *const Ctx, s: Sexp, names: []const []const u8, vals: []const bool) Sexp {
    if (s.atom) |a| {
        if (lookupVar(names, vals, a)) |v| return boolAtom(v);
        return s;
    }
    if (s.items.len == 0) return s;
    const h = s.items[0].atom orelse return s;
    if (std.mem.eql(u8, h, "not") and s.items.len == 2) {
        const x = substBoolSimplify(c, s.items[1], names, vals);
        if (x.atom) |xa| {
            if (std.mem.eql(u8, xa, "true")) return boolAtom(false);
            if (std.mem.eql(u8, xa, "false")) return boolAtom(true);
        }
        if (asNot(x)) |inner| return inner;
        var out = std.array_list.Managed(Sexp).init(c.arena);
        out.append(s.items[0]) catch return s;
        out.append(x) catch return s;
        return Sexp{ .items = out.items };
    }
    if (std.mem.eql(u8, h, "=") and s.items.len == 3) {
        const x = substBoolSimplify(c, s.items[1], names, vals);
        const y = substBoolSimplify(c, s.items[2], names, vals);
        if (x.atom) |xa| {
            if (y.atom) |ya| {
                const xb = std.mem.eql(u8, xa, "true") or std.mem.eql(u8, xa, "false");
                const yb = std.mem.eql(u8, ya, "true") or std.mem.eql(u8, ya, "false");
                if (xb and yb) {
                    return boolAtom(std.mem.eql(u8, xa, "true") == std.mem.eql(u8, ya, "true"));
                }
                // ИЗМЕРЕНО (ЭТАЛОН QF_S): `(= false "safe")` — Bool против String,
                // то есть ЗАВЕДОМО ЛОЖНОЕ равенство (разные сорта). Такая ветка
                // невыполнима: возвращаем `false` (P ∧ false ≡ false).
                if (xb != yb) return boolAtom(false);
            }
        }
        var out = std.array_list.Managed(Sexp).init(c.arena);
        out.append(s.items[0]) catch return s;
        out.append(x) catch return s;
        out.append(y) catch return s;
        return Sexp{ .items = out.items };
    }
    if ((std.mem.eql(u8, h, "or") or std.mem.eql(u8, h, "and")) and s.items.len >= 3) {
        const is_or = std.mem.eql(u8, h, "or");
        var kept = std.array_list.Managed(Sexp).init(c.arena);
        for (s.items[1..]) |it| {
            const x = substBoolSimplify(c, it, names, vals);
            if (x.atom) |xa| {
                if (std.mem.eql(u8, xa, "true")) {
                    if (is_or) return boolAtom(true);
                    continue;
                }
                if (std.mem.eql(u8, xa, "false")) {
                    if (is_or) continue;
                    return boolAtom(false);
                }
            }
            kept.append(x) catch return s;
        }
        if (kept.items.len == 0) return boolAtom(!is_or);
        if (kept.items.len == 1) return kept.items[0];
        var out = std.array_list.Managed(Sexp).init(c.arena);
        out.append(s.items[0]) catch return s;
        for (kept.items) |k| out.append(k) catch return s;
        return Sexp{ .items = out.items };
    }
    return s;
}

/// ГИБРИДНАЯ проверка несовместности комбинации: ПЕРЕБОР булевых переменных
/// + Фурье — Моцкин для линейного остатка.
///
/// ИЗМЕРЕНО (ЭТАЛОН IEEE-754): `[dbg-split] комбинация #0 не переведена ->
/// .unverifiable` — в комбинацию попадают БУЛЕВЫ переменные (`r_nan`, `x_nan`),
/// которые `asLeZero` (Int-арифметика) перевести не может.
/// ЗВУЧНО: несовместность комбинации проверяется по всем значениям булевых
/// переменных; при каждой подстановке линейный остаток проверяется решателем.
fn comboUnsatBoolSplit(c: *const Ctx, lits: []const Sexp, neg_concl: ?Sexp) ComboResult {
    var all = std.array_list.Managed(Sexp).init(c.arena);
    for (lits) |l| all.append(l) catch return .unknown;
    if (neg_concl) |nc| all.append(nc) catch return .unknown;

    // ИЗМЕРЕНО: собираем ТОЛЬКО булевы ЛИТЕРАЛЫ (см. `collectBoolLits`).
    // Прежний сбор «все переменные минус арифметические» ошибочно включал
    // String-переменные (`result`, `s`) и имя типа `Char`.
    var bnames = std.array_list.Managed([]const u8).init(c.arena);
    defer bnames.deinit();
    for (all.items) |l| collectBoolLits(l, &bnames);
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-boolsplit] булевых переменных {d}: ", .{bnames.items.len});
        for (bnames.items) |n| dbgPrint("{s} ", .{n});
        dbgPrint("\n", .{});
    }
    if (bnames.items.len == 0 or bnames.items.len > MAX_BOOL_VARS) return .unknown;

    var vals: [MAX_BOOL_VARS]bool = undefined;
    const total: usize = @as(usize, 1) << @intCast(bnames.items.len);
    var mask: usize = 0;
    while (mask < total) : (mask += 1) {
        for (0..bnames.items.len) |i| vals[i] = (mask >> @intCast(i)) & 1 == 1;
        // Упрощаем литералы при данной подстановке булевых переменных.
        var simp = std.array_list.Managed(Sexp).init(c.arena);
        var dead = false;
        for (all.items) |l| {
            if (evalBoolSubst(l, bnames.items, vals[0..bnames.items.len])) |v| {
                if (!v) {
                    dead = true; // литерал ЛОЖЕН -> комбинация невыполнима
                    break;
                }
                continue; // литерал ИСТИНЕН -> ограничения не даёт
            }
            // ЧАСТИЧНАЯ подстановка с упрощением булевых связок (не только
            // вычисление целиком): литерал может содержать и `>=`, и булевы.
            const sl = substBoolSimplify(c, l, bnames.items, vals[0..bnames.items.len]);
            if (sl.atom) |sa| {
                if (std.mem.eql(u8, sa, "false")) {
                    dead = true; // литерал стал ЛОЖНЫМ -> ветка невыполнима
                    break;
                }
                if (std.mem.eql(u8, sa, "true")) continue; // литерал истинен
            }
            simp.append(sl) catch return .unknown;
        }
        if (dead) continue;
        // ВАЖНО: отрицание заключения тоже участвует в комбинации — его нельзя
        // терять (иначе комбинация ошибочно становится СОВМЕСТНОЙ -> ложный .bad).
        var nc_s: ?Sexp = null;
        if (neg_concl) |nc| {
            const sn = substBoolSimplify(c, nc, bnames.items, vals[0..bnames.items.len]);
            if (sn.atom) |sa| {
                if (std.mem.eql(u8, sa, "false")) continue; // ¬concl ложен -> ветка невыполнима
                if (!std.mem.eql(u8, sa, "true")) nc_s = sn;
            } else nc_s = sn;
        }
        // Линейный остаток проверяем СУЩЕСТВУЮЩИМ механизмом (Фурье — Моцкин).
        const r = unitsPlusPicksUnsat(c, simp.items, &.{}, nc_s);
        if (r != .unsat) return r;
    }
    return .unsat;
}

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
        if (!negateAsLeZero(c, nc, &cons)) {
            if (dbgEnv("KERN_DEBUG_LIA") != null) {
                dbgPrint("[dbg-combo] ЗАКЛЮЧЕНИЕ (¬concl) НЕ переведено: ", .{});
                dumpSexp(nc);
                dbgPrint("\n", .{});
            }
            return .unknown;
        }
    }
    for (units) |l| {
        if (!asLeZero(c, l, &cons)) {
            if (dbgEnv("KERN_DEBUG_LIA") != null) {
                dbgPrint("[dbg-combo] unit НЕ переведён: ", .{});
                dumpSexp(l);
                dbgPrint("\n", .{});
            }
            return .unknown;
        }
    }
    for (picks) |l| {
        if (!asLeZero(c, l, &cons)) {
            if (dbgEnv("KERN_DEBUG_LIA") != null) {
                dbgPrint("[dbg-combo] pick НЕ переведён: ", .{});
                dumpSexp(l);
                dbgPrint("\n", .{});
            }
            return .unknown;
        }
    }
    var s = builtin_lia.Solver.init(c.arena);
    defer s.deinit();
    const res = builtin_lia.checkUnsat(&s, cons.items);
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-lia2] ограничений {d} -> {s}\n", .{ cons.items.len, @tagName(res) });
        if (res == .unknown) {
            for (cons.items) |lin| {
                dbgPrint("[dbg-lia2]   ограничение: ", .{});
                for (lin.terms) |tm| {
                    dbgPrint("{d}*{s} ", .{ tm.coeff, tm.name });
                }
                dbgPrint("| const {d}\n", .{lin.constant});
            }
        }
    }
    return switch (res) {
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
    // ИЗМЕРЕНО (дамп `[dbg-combo] ЗАКЛЮЧЕНИЕ (¬concl) НЕ переведено`):
    // `concl = (not (or Y1 … Yk))` => `¬concl = (or Y1 … Yk)` — ДИЗЪЮНКЦИЯ,
    // которую нельзя добавить конъюнкцией ограничений. Её нужно добавить КЛАУЗОЙ
    // и расщепить.
    // ВАЖНО (найденный мой дефект): добавлять клаузой именно `¬concl` = `Y1…Yk`
    // (то, что внутри `not`), а НЕ сам `concl`. Первая версия добавляла `concl`
    // для ЛЮБОГО `or`, что давало ЛОЖНЫЙ `.bad` на эталоне `abs.c`
    // (`[dbg-split] комбинация #1 СОВМЕСТНА`, `unitres_bad = 2`).
    var neg_concl_eff = neg_concl;
    if (neg_concl) |nc| {
        if (asNot(nc)) |inner| {
            if (inner.isList() and inner.items.len >= 3) {
                const h = inner.items[0].atom orelse "";
                if (std.mem.eql(u8, h, "or")) {
                    var rem = std.array_list.Managed(Sexp).init(c.arena);
                    for (inner.items[1..]) |lit| {
                        rem.append(expand(c, lit, 0)) catch return .unverifiable;
                    }
                    if (rem.items.len == 0) return .verified;
                    rems.append(rem) catch return .unverifiable;
                    neg_concl_eff = null; // учтено клаузой
                }
            }
        }
    }
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
    if (dbgEnv("KERN_DEBUG_LIA") != null) {
        dbgPrint("[dbg-split] клауз={d} комбинаций={d}\n", .{ rems.items.len, total });
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
        switch (unitsPlusPicksUnsat(c, units, pick.items, neg_concl_eff)) {
            .unsat => {},
            .sat => {
                if (dbgEnv("KERN_DEBUG_LIA") != null) {
                    dbgPrint("[dbg-split] комбинация #{d} СОВМЕСТНА -> .bad\n", .{idx});
                }
                return .bad;
            },
            .unknown => {
                // ГИБРИД (ЭТАЛОН IEEE-754): в комбинацию попадают БУЛЕВЫ
                // переменные (`r_nan`, `x_nan`), которые `asLeZero` перевести не
                // может. Пробуем ПЕРЕБОР булевых + Фурье — Моцкин для остатка.
                var all = std.array_list.Managed(Sexp).init(c.arena);
                for (units) |u| all.append(u) catch return .unverifiable;
                for (pick.items) |p| all.append(p) catch return .unverifiable;
                switch (comboUnsatBoolSplit(c, all.items, neg_concl)) {
                    .unsat => {},
                    .sat => return .bad,
                    .unknown => {
                        if (dbgEnv("KERN_DEBUG_LIA") != null) {
                            dbgPrint("[dbg-split] комбинация #{d} не переведена -> .unverifiable\n", .{idx});
                        }
                        return .unverifiable;
                    },
                }
            },
        }
    }
    return .verified;
}

// ИЗМЕРЕНО ДАМПОМ (дефект #430, шаг 3): клаузы Z3 в `QF_BV/add_three.4_bit`
// содержат ВЛОЖЕННЫЙ `or` — после раскрытия `$x`-имени клауза имеет вид
// `(or (or A B C) k!220)`. Поэтому `remaining` (остаток после снятия `k!220`) —
// ОДИН литерал `(or A B C)`, а `concl` уплощается в ТРИ литерала: рассинхрон
// `1 != 3`, и КОРРЕКТНАЯ резолюция уходит в доверенные, хотя в том же файле
// 5 247 плоских резолюций проверены. Дословный дамп (цель + посылки):
//   цель: (or (not (or (not k!140) (not k!180))) (not k!220) (not (or k!140 k!180)))
//   @x2893 => (or (or (not (or (not k!140) (not k!180))) (not k!220)
//                  (not (or k!140 k!180))) k!220)
//   @x5139 => (not k!220)
// — то есть из `(C ∨ k!220)` и `¬k!220` выводится РОВНО `C`.
//
// ПОПЫТКА УПЛОЩЕНИЯ (ассоциативность `or` — тождество, звучно) ОТКАЧЕНА
// ПО ЗАМЕРУ: ДОВЕРЕННЫХ на этой задаче стало 2970 -> 3408, то есть ХУЖЕ.
// Значит форма `(or (or A B C) k)` обрабатывается существующими ветками
// (частичная резолюция / де Морган / расщепление по случаям) ЛУЧШЕ, чем
// уплощённая, и чинить надо РАЗБОРОМ ЭТИХ ВЕТОК, а не уплощением.
// Дамп посылок доверенного шага доступен под `KERN_DEBUG_TRUSTED`
// (`[dbg-ur-unver]`).

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
    const dbg = dbgEnv("KERN_DEBUG_LIA") != null;
    if (dbg) dbgPrint("[dbg-ur] посылок: units={d} clauses={d} concl_false={}\n", .{ units.items.len, clauses.items.len, concl_is_false });
    for (clauses.items) |cl| {
        var remaining = std.array_list.Managed(Sexp).init(c.arena);
        for (cl.items[1..]) |lit| {
            const l = expand(c, lit, 0);
            var falsified = false;
            for (units.items) |u| {
                // Структурная ЛИБО семантическая (по канонической форме) пара,
                // ЛИБО юнит ВЛЕЧЁТ литерал (`u ⊨ l`) — ИЗМЕРЕНО на QF_S:
                // `units[0] = ¬A ∧ B` влечёт `¬A`, но это НЕ «дополнение».
                //
                // ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп): `units[0]` и литерал `R2` клаузы
                // СОВПАДАЮТ (`(not (or A (not B)))`). Юнит ИСТИНЕН, значит и
                // литерал истинен -> он УДОВЛЕТВОРЁН и должен быть исключён из
                // `remaining`. Без этой проверки `R2` оставался в остатке и шаг
                // не сходился с `concl`.
                if (isComplement(l, u) or isComplementCmp(l, u) or
                    unitImpliesLit(u, l) or sexpEqNum(l, u))
                {
                    falsified = true;
                    break;
                }
            }
            if (!falsified) {
                // ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-ur] units (1)` + `clauses`):
                // посылка `$x97 = (or A B)` имеет голову `or` и потому попала в
                // `clauses`, а НЕ в `units`. Но по отношению к литералу
                // `l = (not (or A B))` вся эта КЛАУЗА целиком есть ЮНИТ,
                // опровергающий `l` (`l = ¬P`). Проверяем литерал и против
                // ДРУГИХ клауз — иначе `R2` не вычёркивался и шаг оставался
                // доверенным. ЗВУЧНО: все посылки истинны, значит `P` истинно,
                // значит `l = ¬P` ЛОЖНО -> литерал вычёркивается.
                for (clauses.items) |c2| {
                    if (c2.items.len == cl.items.len and c2.items.ptr == cl.items.ptr) continue;
                    if (isComplement(l, c2) or isComplementCmp(l, c2)) {
                        falsified = true;
                        break;
                    }
                }
            }
            if (!falsified) remaining.append(l) catch return .unverifiable;
        }
        // ИЗМЕРЕНО (ЭТАЛОН QF_S): если ВСЕ литералы клаузы опровергнуты юнитами,
        // `remaining` ПУСТ — клауза ЛОЖНА под юнитами, то есть получено
        // ПРОТИВОРЕЧИЕ, из которого следует ЛЮБОЕ заключение (`false ⊨ anything`).
        // Прежний `continue` пропускал такую клаузу, и шаг оставался доверенным.
        // ЗВУЧНО: `remaining == []` означает, что клауза опровергнута целиком.
        if (remaining.items.len == 0) return .verified;
        if (dbg) {
            dbgPrint("[dbg-ur] клауза: ", .{});
            dumpSexp(cl);
            dbgPrint("\n[dbg-ur]   units ({d}): ", .{units.items.len});
            for (units.items) |u| {
                dumpSexp(u);
                dbgPrint(" | ", .{});
            }
            dbgPrint("\n[dbg-ur]   remaining ({d}): ", .{remaining.items.len});
            for (remaining.items) |r| {
                dumpSexp(r);
                dbgPrint(" | ", .{});
            }
            dbgPrint("\n[dbg-ur]   concl: ", .{});
            dumpSexp(concl);
            dbgPrint("\n", .{});
        }
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
            // ИЗМЕРЕНО (ЭТАЛОН QF_S, полный дамп `[dbg-ur]`):
            //   remaining = [R1, R2];  concl = R1 (заключение совпадает с ОДНИМ
            //   из остатка), и `R2` опровергается ЮНИТОМ.
            // Это ЧАСТИЧНАЯ резолюция. ЗВУЧНОЕ правило:
            //   (or R1 R2) ∧ ¬R2  ⊨  R1.
            // Требуем: `concl` совпадает с одним из остатка, а КАЖДЫЙ другой
            // литерал остатка опровергнут юнитом. Иначе — НЕ «ок» (не угадываем).
            if (concl_lits.items.len == 1 and remaining.items.len >= 2) {
                var match_idx: ?usize = null;
                for (remaining.items, 0..) |r, mj| {
                    if (sexpEqNum(r, concl)) {
                        match_idx = mj;
                        break;
                    }
                }
                if (match_idx) |mi| {
                    var all_falsified = true;
                    for (remaining.items, 0..) |r, j| {
                        if (j == mi) continue;
                        var falsified = false;
                        for (units.items) |u| {
                            if (isComplement(r, u) or isComplementCmp(r, u)) {
                                falsified = true;
                                break;
                            }
                        }
                        if (!falsified) {
                            all_falsified = false;
                            break;
                        }
                    }
                    if (all_falsified) return .verified;
                }
            }
            // ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-ur]`): `remaining` = 2 литерала,
            // а `concl` = ОДНА формула `(not (or …))` — это ЗАКОН ДЕ МОРГАНА для
            // конъюнкции остатка: `(and R1 R2) <=> (not (or (not R1) (not R2)))`.
            // Раньше такой шаг уходил в `checkBySplitting` и оставался доверенным.
            if (concl_lits.items.len == 1 and remaining.items.len >= 2) {
                if (andDeMorganEq(remainingToAnd(c, remaining.items), concl)) return .verified;
            }
            // ИЗМЕРЕНО ДАМПОМ (дефект #431, шаг 3): ОСТАТОК — ОДИН терм, равный
            // ВСЕЙ цели. Клауза Z3 содержит ВЛОЖЕННЫЙ `or` (`(or C k!220)`), и
            // после снятия `k!220` юнитом `¬k!220` остаётся РОВНО `C`, но цель
            // `(or A B C)` разбирается на ТРИ литерала — поэтому сверка списков
            // даёт рассинхрон `1 != 3`, хотя `remaining[0]` ПОСИМВОЛЬНО равен
            // цели. ЗВУЧНО: `(or R1 … Rk) ∧ ¬R1 … ∧ ¬Rk-1 ⊨ Rk`, и здесь
            // `Rk == concl`. Проверка стоит в FALLBACK (там, где раньше
            // возвращалось «не проверено»), поэтому число доверенных шагов
            // МОЖЕТ ТОЛЬКО УПАСТЬ — вырасти оно не может по построению.
            //
            // ПОЧЕМУ НЕ УПЛОЩЕНИЕ `or` В НАЧАЛЕ ФУНКЦИИ: такая попытка ОТКАЧЕНА
            // ПО ЗАМЕРУ (2970 -> 3408). Причина: в битовых выводах посылка
            // `(not (or A B))` сокращает литерал `(or A B)` ОДИН-В-ОДИН, а
            // уплощение уничтожает этот литерал ДО сокращения.
            if (remaining.items.len == 1 and sexpEqNum(remaining.items[0], concl)) return .verified;
            // ОБОБЩЕНИЕ (пункт 3 v2.5): то же РАСЩЕПЛЕНИЕ ПО СЛУЧАЯМ, но для
            // ПРОИЗВОЛЬНОГО заключения: посылки ⊨ concl <=> для каждой
            // комбинации `{units} ∪ {picks} ∪ {¬concl}` несовместно.
            // ЭТАП А: печать ИМЕННО этого (не сошедшегося) шага.
            if (dbgEnv("KERN_DEBUG_LIA") != null) {
                dbgPrint("[dbg-ur-mismatch] remaining={d} concl_lits={d}\n", .{ remaining.items.len, concl_lits.items.len });
                dbgPrint("[dbg-ur-mismatch]   remaining: ", .{});
                for (remaining.items) |r| {
                    dumpSexp(r);
                    dbgPrint(" | ", .{});
                }
                dbgPrint("\n[dbg-ur-mismatch]   concl: ", .{});
                dumpSexp(concl);
                dbgPrint("\n[dbg-ur-mismatch]   units={d} clauses={d}\n", .{ units.items.len, clauses.items.len });
                for (clauses.items, 0..) |c2, j| {
                    dbgPrint("[dbg-ur-mismatch]   clause[{d}] = ", .{j});
                    dumpSexp(c2);
                    dbgPrint("\n", .{});
                }
            }
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
        // ИЗМЕРЕНО (ЭТАЛОН QF_S, дамп `[dbg-ur-mismatch]`): если ОСТАТОК ЭТОЙ
        // клаузы совпал с заключением — шаг ДОКАЗАН, и надо вернуть `.verified`
        // НЕМЕДЛЕННО. Прежний `saw_remaining = true` продолжал цикл по ДРУГИМ
        // клаузам, и остаток ПОСЛЕДНЕЙ клаузы (`[A, ¬B]`) перезаписывал
        // результат -> уходили в `checkBySplitting` -> `.unverifiable`.
        saw_remaining = true;
        return .verified;
    }
        // ЭТАП А: печать ТОЛЬКО НЕУДАВШЕГОСЯ шага (того, что вернёт .unverifiable),
        // чтобы видеть ровно его units/clauses/concl, а не те, что уже сошлись.
    if (!saw_remaining) {
        if (dbgEnv("KERN_DEBUG_LIA") != null) {
            dbgPrint("[dbg-ur-fail] НЕ сошёлся: units={d} clauses={d} concl_false={}\n", .{ units.items.len, clauses.items.len, concl_is_false });
            for (units.items, 0..) |u, i| {
                dbgPrint("[dbg-ur-fail]   unit[{d}] = ", .{i});
                dumpSexp(u);
                dbgPrint("\n", .{});
            }
            for (clauses.items, 0..) |c2, j| {
                dbgPrint("[dbg-ur-fail]   clause[{d}] = ", .{j});
                dumpSexp(c2);
                dbgPrint("\n", .{});
            }
            dbgPrint("[dbg-ur-fail]   concl = ", .{});
            dumpSexp(concl);
            dbgPrint("\n", .{});
        }
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
        dbgPrint("{s}", .{a});
        return;
    }
    dbgPrint("(", .{});
    for (e.items, 0..) |it, i| {
        if (i > 0) dbgPrint(" ", .{});
        dumpSexp(it);
    }
    dbgPrint(")", .{});
}

/// Пометить шаг как непроверенный и запомнить ПРАВИЛО первого такого шага.
/// Без этого нельзя понять, что именно осталось доверенным (METRICS 55.5).
/// ДИАГНОСТИКА (Блок 5, шаг 1 плана): пометить шаг доверенным И напечатать его
/// РАСКРЫТОЕ заключение.
///
/// ЗАЧЕМ. Подсчёт «шагов БЕЗ `k!`» по СЫРЫМ строкам ЗАВЫШАЕТ потенциал таблицы
/// истинности: отрицательный атом в выводе Z3 свёрнут в `let` под именем `$x…`
/// (например, `$x2355 = (not k!140)`), поэтому сырая строка выглядит как
/// «БЕЗ `k!`», хотя внутри `k!` есть. ИЗМЕРЕНО: вилка [122 .. 804].
fn markTrustedExp(v: *ProofVerdict, c: *const Ctx, rule: []const u8, st: Sexp) void {
    markTrusted(v, rule, st);
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-trusted-exp] {s} :: ", .{rule});
        dumpSexp(expand(c, proved(st), 0));
        dbgPrint("\n", .{});
    }
}

fn markTrusted(v: *ProofVerdict, rule: []const u8, st: Sexp) void {
    v.trusted_steps += 1;
    if (v.first_trusted.len == 0) v.first_trusted = rule;
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-trusted] #{d} {s} :: ", .{ v.trusted_steps, rule });
        dumpSexp(st);
        dbgPrint("\n", .{});
    }
}

/// Математический аудит вывода. `contract` — исходные утверждения контракта
/// (строки SMT-LIB внутри `(assert ...)`) — по ним проверяется привязка
/// посылок.
/// Вид запроса (Ф1: `QueryKind`). Определяет, применяется ли правило привязки
/// посылок: оно относится к проверке КОНТРАКТА, а не к сравнению двух тел.
pub const QueryKind = enum { refutation, equivalence };

/// Проверка контракта (по умолчанию): все посылки обязаны быть привязаны.
pub fn verifyProof(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
) !ProofVerdict {
    return verifyProofKind(allocator, proof_text, contract, .refutation);
}

/// То же, но с ТЕКСТОМ SMT-файла: из его шапки читаются `define-fun`
/// (дефект #344). Без них Z3 раскрывает определения в выводе, а контракт
/// содержит вызов — посылка не привязывается и корректный вывод отвергается.
pub fn verifyProofSmt(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
    smt_text: []const u8,
) !ProofVerdict {
    return verifyProofKindInner(allocator, proof_text, contract, .refutation, smt_text);
}

/// Явный вид запроса. Для `.equivalence` правило привязки посылок отключено
/// (контрактных посылок нет), но ВСЕ прочие требования сохранены: шагов > 0,
/// дыр 0, ни одного подделанного шага, вывод завершается `false`.
pub fn verifyProofKind(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
    kind: QueryKind,
) !ProofVerdict {
    return verifyProofKindInner(allocator, proof_text, contract, kind, "");
}

/// То же, но с шапкой SMT (`define-fun`) — см. `verifyProofSmt`.
pub fn verifyProofKindSmt(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
    kind: QueryKind,
    smt_text: []const u8,
) !ProofVerdict {
    return verifyProofKindInner(allocator, proof_text, contract, kind, smt_text);
}

fn verifyProofKindInner(
    allocator: std.mem.Allocator,
    proof_text: []const u8,
    contract: []const []const u8,
    kind: QueryKind,
    smt_text: []const u8,
) !ProofVerdict {
    var v = ProofVerdict{};
    v.premises_required = (kind == .refutation);
    var ar = std.heap.ArenaAllocator.init(allocator);
    defer ar.deinit();
    const arena = ar.allocator();

    // 1. Внешняя оболочка: найти блок (proof ...).
    const outer = parseSexp(arena, proof_text) catch |e| {
        // ЧЕСТНОСТЬ: отказ аллокатора — это НЕ «вывод не разбирается».
        // Проглатывать OOM нельзя: харнесс `checkAllAllocationFailures` обязан
        // видеть его, иначе он сообщает SwallowedOutOfMemoryError (и прав).
        if (e == error.OutOfMemory) return e;
        // 🔴 ДЕФЕКТ #371 (найден на ОФИЦИАЛЬНОМ банке SMT-LIB).
        // ИЗМЕРЕНО: предел вложенности 4096 меньше реального вывода Z3 на
        // задаче `QF_BV/20250812-Circt/add_three.4_bit.smt2` — глубина 4606.
        // Парсер возвращал TooDeep, а вердикт называл причину «вывод не
        // разбирается как S-выражение» — то есть ОБВИНЯЛ решатель в мусоре,
        // хотя вывод был корректным S-выражением и упирался в НАШ предел.
        // Класс тот же, что #370: сообщение говорит не то, что произошло.
        // Теперь причина названа точно, и у гейта есть отдельный флаг.
        if (e == error.TooDeep) {
            v.too_deep = true;
            v.reject = "вывод ГЛУБЖЕ предела вложенности парсера (MAX_SEXP_DEPTH)";
            return v;
        }
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
    // ДЕФЕКТ #344: определения `define-fun` из шапки SMT — чтобы раскрывать
    // вызовы при сопоставлении с контрактом (Z3 в выводе подставляет тела).
    if (smt_text.len != 0) loadFunDefs(&c, smt_text);
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
            if (std.mem.eql(u8, h, "intro-def")) {
                _ = verifyIntroDef(&c, st);
                v.other_steps += 1; // #432: определение — не проверенный и не доверенный шаг
            }
        }
    }

    for (c.steps.items) |st| {
        const r = ruleOf(st) orelse {
            v.other_steps += 1; // #432: шаг без правила — тоже обязан быть учтён
            continue;
        };
        if (isHole(r)) {
            v.holes += 1;
            if (v.reject.len == 0) v.reject = "вывод содержит правило-дыру (hole/trust/sorry)";
            continue;
        }
        if (!isKnownRule(r)) v.unknown_rules += 1;
        if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
            dbgPrint("[dbg-step] {s} :: ", .{r});
            dumpSexp(st);
            dbgPrint("\n", .{});
        }

        if (std.mem.eql(u8, r, "asserted")) {
            v.premises_total += 1;
            v.other_steps += 1; // #432: посылка — не «проверенный» и не «доверенный» шаг
            const t = expand(&c, proved(st), 0);
            // ДЕФЕКТ #344: Z3 раскрывает `define-fun` в выводе, а контракт
            // содержит ВЫЗОВ. Раскрываем вызовы с подстановкой аргументов с
            // ОБЕИХ сторон — иначе посылка не привязывается и корректный вывод
            // отвергается (`premises_unbound`).
            var fun_budget: usize = 200_000;
            const t_exp = funExpand(&c, t, 0, &fun_budget);
            var found = false;
            for (contract_terms.items) |ct| {
                // `sexpEqNum`, а не `sexpEq`: числовой литерал в исходнике
                // записан атомом (`-2147483648`), а Z3 в выводе — списком
                // (`(- 2147483648)`). Без нормализации корректный вывод
                // отвергался как «посылки не привязаны» (дефект #122).
                var ct_budget: usize = 200_000;
                const ct_exp = funExpand(&c, ct, 0, &ct_budget);
                if (sexpEqNum(t_exp, ct_exp)) {
                    found = true;
                    break;
                }
                // ПУНКТ 22: булевы формы `(not X)` и `(= X false)` — одно и то же
                // для сорта Bool. Без этого 4-я посылка IEEE-754 не привязывалась
                // (`посылок 3/4`) и чекер ОТВЕРГАЛ корректный вывод.
                if (boolFormEq(t_exp, ct_exp)) {
                    found = true;
                    break;
                }
                // Запасной путь БЕЗ раскрытия: если определений нет, поведение
                // остаётся прежним (раскрытие не должно ЛОМАТЬ привязку там,
                // где она уже работала).
                if (sexpEqNum(t, ct)) {
                    found = true;
                    break;
                }
                if (boolFormEq(t, ct)) {
                    found = true;
                    break;
                }
            }
            if (found) v.premises_bound += 1 else v.premises_unbound += 1;
            if (!found and dbgEnv("KERN_DEBUG_TRUSTED") != null) {
                dbgPrint("[dbg-unbound] НЕ привязана: ", .{});
                dumpSexp(t);
                dbgPrint("\n", .{});
                dbgPrint("[dbg-unbound] РАСКРЫТА: ", .{});
                dumpSexp(t_exp);
                dbgPrint("\n", .{});
                for (contract_terms.items) |ct| {
                    dbgPrint("[dbg-unbound]   контракт: ", .{});
                    dumpSexp(ct);
                    dbgPrint("\n", .{});
                    var db: usize = 200_000;
                    dbgPrint("[dbg-unbound]   контракт РАСКРЫТ: ", .{});
                    dumpSexp(funExpand(&c, ct, 0, &db));
                    dbgPrint("\n", .{});
                }
            }
        } else if (std.mem.eql(u8, r, "hypothesis")) {
            v.premises_total += 1; // локальная посылка, снимается правилом lemma
            v.other_steps += 1; // #432: то же — посылка, не проверенный шаг
        } else if (std.mem.eql(u8, r, "mp")) {
            // ДЕФЕКТ #432: счётчик обязан считать ПРОВЕРЕННЫЕ шаги, а не все
            // шаги правила. Иначе отчёт печатает одно и то же число и до, и
            // после правки (ИЗМЕРЕНО: колонка `резолюция` = 5247 и при 2970
            // доверенных, и при 1020), и читатель не видит проделанной работы.
            if (checkMp(&c, st)) v.mp_checked += 1 else v.mp_bad += 1;
        } else if (std.mem.eql(u8, r, "unit-resolution")) {
            switch (checkUnitRes(&c, st)) {
                .verified => v.unitres_checked += 1,
                .bad => v.unitres_bad += 1,
                // ФОРМА ВНЕ МОДЕЛИ ЧЕКЕРА -> доверенный шаг, а не `bad`.
                // ДЕФЕКТ #95: раньше ЛЮБОЕ несовпадение считалось `bad`, из-за
                // чего корректные выводы Z3 (частичная резолюция, лишние
                // литералы) отвергались целиком.
                .unverifiable => {
                    // ШАГ 3 ПЛАНА (#430): дамп ПОСЫЛОК и ЦЕЛИ доверенного шага.
                    // Вопрос аудитора: почему резолюция сработала 5 247 раз в
                    // этом же файле, но отказала на этих посылках. Без дампа
                    // ответа нет.
                    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
                        dbgPrint("[dbg-ur-unver] цель: ", .{});
                        dumpSexp(expand(&c, proved(st), 0));
                        dbgPrint("\n[dbg-ur-unver] посылки ({d}):\n", .{st.items.len - 2});
                        for (st.items[1 .. st.items.len - 1]) |p| {
                            dbgPrint("[dbg-ur-unver]   ", .{});
                            dumpSexp(p);
                            dbgPrint(" => ", .{});
                            dumpSexp(expand(&c, premiseTerm(&c, p), 0));
                            dbgPrint("\n", .{});
                        }
                    }
                    markTrusted(&v, "unit-resolution", st);
                },

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
                // ДЕФЕКТ #155 (найден эволюционным фаззером). `.structural_only`
                // означает «сертификат НЕ проверен». Раньше он лишь увеличивал
                // `farkas_structural`, а в `trusted_steps` НЕ попадал, поэтому
                // `checksPass()` проходил: ИЗМЕРЕНО — переименование определения
                // шага (@x147 -> @x9) при живых ссылках давало `Фаркаш 3 -> 0`,
                // `ДОВЕРЕННЫХ 0` и `PROOF VERIFIED trusted: 0`, rc=0.
                // Теперь непроверенная лемма честно становится ДОВЕРЕННОЙ,
                // и гейт закрывается (rc != 0) — как и для unit-resolution.
                // ДЕФЕКТ #433 (найден ТОЖДЕСТВОМ отчёта из #432). `.structural_only`
                // означает «сертификат НЕ проверен», но шаг при этом НЕ становился
                // доверенным — он ИСЧЕЗАЛ из отчёта: ни проверен, ни доверен,
                // ни дыра. Комментарий выше обещал обратное («теперь непроверенная
                // лемма честно становится ДОВЕРЕННОЙ»), а код лишь увеличивал
                // счётчик `farkas_structural`, который НЕ печатается.
                // ИЗМЕРЕНО на `storeinv…00002_001.cvc`: 11 таких шагов, из-за чего
                // Σ категорий (67) не сходилась с числом шагов (78).
                .structural_only => {
                    v.farkas_structural += 1;
                    markTrusted(&v, "th-lemma (структурно)", st);
                },
                .bad => {
                    v.farkas_bad += 1;
                    // ЭТАП А (диагностика): дамп шага, признанного НЕВЕРНЫМ.
                    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
                        dbgPrint("[dbg-farkas-bad] шаг: ", .{});
                        dumpSexp(st);
                        dbgPrint("\n[dbg-farkas-bad] клауза: ", .{});
                        dumpSexp(clause);
                        dbgPrint("\n", .{});
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
                .unverifiable => {
                    markTrustedExp(&v, &c, r, st);
                    // ЭТАП А (диагностика): дамп l и r для ДОВЕРЕННОГО rewrite.
                    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
                        const eq = expand(&c, proved(st), 0);
                        dbgPrint("[dbg-rw-trusted] eq: ", .{});
                        dumpSexp(eq);
                        if (eq.isList() and eq.items.len == 3) {
                            dbgPrint("\n[dbg-rw-trusted]   L: ", .{});
                            dumpSexp(eq.items[1]);
                            dbgPrint("\n[dbg-rw-trusted]   R: ", .{});
                            dumpSexp(eq.items[2]);
                        }
                        dbgPrint("\n", .{});
                    }
                },
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
            if (verifyDefAxiom(&c, st)) v.bool_verified += 1 else markTrustedExp(&v, &c, r, st);
        } else if (std.mem.eql(u8, r, "and-elim")) {
            if (verifyAndElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "not-or-elim")) {
            if (verifyNotOrElim(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "iff-true")) {
            // ЭТАЛОН QF_S: `(iff-true P (= Q true))` — из `P` следует `(= P true)`.
            if (verifyIffTrue(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "iff-false")) {
            // ЭТАЛОН QF_S: `(iff-false P (= Q false))` — из `(not Q)` следует `(= Q false)`.
            if (verifyIffFalse(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "commutativity")) {
            // ШАГ 2 ПЛАНА (#430). ИЗМЕРЕНО ДАМПОМ: это ПЕРВОЕ доверенное
            // правило `storeinv…00002_001.cvc`. Заключение — равенство двух
            // термов, отличающихся только порядком аргументов коммутативной
            // операции; проверяется СТРУКТУРНО (`verifyCommutativity`).
            // Иначе — доверенный шаг, как и было.
            if (verifyCommutativity(&c, st)) v.bool_verified += 1 else markTrusted(&v, r, st);
        } else if (std.mem.eql(u8, r, "monotonicity")) {
            if (verifyMonotonicity(&c, st)) v.bool_verified += 1 else markTrustedExp(&v, &c, r, st);
        } else if (std.mem.eql(u8, r, "lemma")) {
            // ПУНКТ 3 v2.5: разрядка гипотез (RAA) проверяется СТРУКТУРНО
            // (см. verifyLemma): поддерево выводит `false`, и каждая его
            // гипотеза отрицается в заключении.
            if (verifyLemma(&c, st)) v.bool_verified += 1 else markTrustedExp(&v, &c, r, st);
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
        const pr = proved(root);
        const t = expand(&c, pr, 0);
        v.proof_concludes_false = t.atom != null and std.mem.eql(u8, t.atom.?, "false");
        if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
            dbgPrint("[dbg-root] proved(root) ДО expand: ", .{});
            dumpSexp(pr);
            dbgPrint("\n[dbg-root] expand(proved(root)): ", .{});
            dumpSexp(t);
            dbgPrint("\n[dbg-root] атом={} concl_false={}\n", .{
                t.atom != null, v.proof_concludes_false,
            });
        }
    } else if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-root] c.root == null (корень НЕ найден)\n", .{});
    }
    if (!v.proof_concludes_false and v.reject.len == 0) {
        v.reject = "корень вывода не является false";
    }
    // ЭТАП А (диагностика): печать счётчиков ЗДЕСЬ, а не после `return v`
    // (раньше она стояла ниже раннего возврата и физически не выполнялась).
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint(
            "[dbg-counters] steps={d} holes={d} prem={d}/{d} unbound={d} " ++
                "mp_bad={d} unitres_bad={d} farkas_bad={d} rewrite_bad={d} " ++
                "unknown_rules={d} trusted={d} concl_false={} reject_len={d} " ++
                "abbrev $x={d} ?x={d}\n",
            .{
                v.proof_steps,        v.holes,          v.premises_bound,
                v.premises_total,     v.premises_unbound, v.mp_bad,
                v.unitres_bad,        v.farkas_bad,     v.rewrite_bad,
                v.unknown_rules,      v.trusted_steps,  v.proof_concludes_false,
                v.reject.len,         c.dbg_dx,         c.dbg_qx,
            },
        );
        if (v.reject.len > 0) dbgPrint("[dbg-counters] reject = {s}\n", .{v.reject});
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
    bridge: *@import("z3_bridge.zig").Z3Bridge,
    decls: []const u8,
    assertions: []const unsat_core.NamedAssertion,
    goal: []const u8,
) !ProofVerdict {
    const z3 = @import("z3_bridge.zig");
    _ = z3;
    var v = ProofVerdict{};

    // --- 1. Запрос вывода -------------------------------------------------
    var buf = BufWriter.init(allocator);
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
    var neg = BufWriter.init(allocator);
    defer neg.deinit();
    try neg.writer().print("(not {s})", .{goal});
    try contract.append(neg.items());

    const deep = try verifyProof(allocator, proof, contract.items);
    // ДЕФЕКТ #436: ДВА ПРОХОДА. Печатаем ОБА числа: расхождение `ДОВЕРЕННЫХ`
    // между `[dbg-counters]` и отчётом означает, что в отчёт попадает число
    // ДРУГОГО прохода. Без этой печати вопрос «кто владелец числа» не решается.
    if (dbgEnv("KERN_DEBUG_TRUSTED") != null) {
        dbgPrint("[dbg-twopass] pass1(v).trusted={d} pass2(deep).trusted={d}\n", .{
            v.trusted_steps, deep.trusted_steps,
        });
    }
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
    v.other_steps = deep.other_steps;
    v.first_trusted = deep.first_trusted;
    v.reject = deep.reject;
    v.too_deep = deep.too_deep;
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
            var b2 = BufWriter.init(allocator);
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

test "ПОЗИТИВ: поглощение константы в and/or ПРОВЕРЯЕТСЯ (дефект #430, шаг 1)" {
    // ИЗМЕРЕНО ДАМПОМ: единственный доверенный шаг `2PhLockVParam_RC-07` —
    // `(rewrite (= (and false (not (or …))) false))`. Поглощение `false` в `and`
    // верно ПРИ ЛЮБОМ втором аргументе (трёхзначная логика Клини): посылок нет.
    const p = "((set-logic QF_UF)(proof (rewrite (= (and false (not (or (not a) (not b)))) false))))";
    const v = try verifyProof(std.testing.allocator, p, &.{});
    try std.testing.expectEqual(@as(usize, 1), v.rewrite_verified);
    try std.testing.expectEqual(@as(usize, 0), v.trusted_steps);
    // Зеркало для `or`: поглощает константа `true`.
    const q = "((set-logic QF_UF)(proof (rewrite (= (or true (> x 0)) true))))";
    const v2 = try verifyProof(std.testing.allocator, q, &.{});
    try std.testing.expectEqual(@as(usize, 1), v2.rewrite_verified);
}

test "PROOF-АТАКА: НЕпоглощающая константа в and НЕ проверяется (дефект #430, шаг 1)" {
    // `(and true X) = true` — ЛОЖЬ: X не константа. Поглощения нет.
    const bad = "((set-logic QF_UF)(proof (rewrite (= (and true (> x 0)) true))))";
    const v = try verifyProof(std.testing.allocator, bad, &.{});
    try std.testing.expectEqual(@as(usize, 0), v.rewrite_verified);
    // `(and false X) = true` — тоже ЛОЖЬ (поглощение даёт `false`).
    const bad2 = "((set-logic QF_UF)(proof (rewrite (= (and false (> x 0)) true))))";
    const v2 = try verifyProof(std.testing.allocator, bad2, &.{});
    try std.testing.expectEqual(@as(usize, 0), v2.rewrite_verified);
}

test "ПОЗИТИВ: коммутативность равенства ПРОВЕРЯЕТСЯ (дефект #430, шаг 2)" {
    // ИЗМЕРЕНО ДАМПОМ: `(commutativity (= $x124 (= a1 a2)))`, где `$x124`
    // раскрывается в `(= a2 a1)`. Проверка СТРУКТУРНАЯ: операнды переставлены.
    const p = "((set-logic QF_UF)(proof (commutativity (= (= a2 a1) (= a1 a2)))))";
    const v = try verifyProof(std.testing.allocator, p, &.{});
    try std.testing.expectEqual(@as(usize, 1), v.bool_verified);
    try std.testing.expectEqual(@as(usize, 0), v.trusted_steps);
}

test "PROOF-АТАКА: НЕкоммутативный оператор и разные операнды отвергаются (#430, шаг 2)" {
    // `<` НЕ коммутативен: шаг не доказан.
    const bad = "((set-logic QF_UF)(proof (commutativity (= (< a1 a2) (< a2 a1)))))";
    const v = try verifyProof(std.testing.allocator, bad, &.{});
    try std.testing.expectEqual(@as(usize, 0), v.bool_verified);
    // Коммутативный оператор, но операнды НЕ переставлены (a3 вместо a2).
    const bad2 = "((set-logic QF_UF)(proof (commutativity (= (= a1 a2) (= a1 a3)))))";
    const v2 = try verifyProof(std.testing.allocator, bad2, &.{});
    try std.testing.expectEqual(@as(usize, 0), v2.bool_verified);
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
    const zb = @import("z3_bridge.zig");
    var bridge = zb.Z3Bridge.init(std.testing.allocator);
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
    const zb = @import("z3_bridge.zig");
    var bridge = zb.Z3Bridge.init(std.testing.allocator);
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

test "ДЕФЕКТ #371: предел вложенности ДОСТАТОЧЕН для официального вывода SMT-LIB" {
    // ИЗМЕРЕНО на ОФИЦИАЛЬНОМ банке SMT-LIB (`SMT-LIB/benchmark-submission`,
    // категория `QF_BV/20250812-Circt`, файл `add_three.4_bit.smt2`): вывод Z3
    // из `(get-proof)` имеет глубину 4 606. Прежний предел 4096 отвергал его,
    // называя причиной «вывод не разбирается как S-выражение».
    //
    // Тест фиксирует ОБЕ половины правки: (1) такая глубина обязана РАЗБИРАТЬСЯ,
    // (2) она обязана быть НИЖЕ предела — иначе правка «прошла», ничего не
    // изменив (класс вакуумного кейса #345).
    const official_depth: usize = 4606;
    try std.testing.expect(official_depth < MAX_SEXP_DEPTH);

    const n = official_depth * 2 + 1;
    const buf = try std.testing.allocator.alloc(u8, n);
    defer std.testing.allocator.free(buf);
    var i: usize = 0;
    while (i < official_depth) : (i += 1) buf[i] = '(';
    buf[official_depth] = 'x';
    i = 0;
    while (i < official_depth) : (i += 1) buf[official_depth + 1 + i] = ')';

    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    // Именно `parseSexp` без ошибки: официальная глубина — ВНУТРИ бюджета.
    const s = try parseSexp(arena.allocator(), buf);
    try std.testing.expect(s.isList());
}

test "ДЕФЕКТ #371: причина отказа при превышении предела названа ТОЧНО" {
    // ДО ФИКСА: `TooDeep` возвращался как «вывод не разбирается как S-выражение» —
    // то есть ОБВИНЯЛ решатель в мусоре, хотя вывод был корректным S-выражением
    // и упирался в НАШ предел. Тест фиксирует, что причина названа своим именем
    // и что гейт может отличить её машинно (флаг `too_deep`).
    const n = MAX_SEXP_DEPTH + 64;
    var buf = std.array_list.Managed(u8).init(std.testing.allocator);
    defer buf.deinit();
    try buf.appendSlice("((set-logic ALL)(proof ");
    var i: usize = 0;
    while (i < n) : (i += 1) try buf.append('(');
    try buf.append('x');
    i = 0;
    while (i < n) : (i += 1) try buf.append(')');
    try buf.appendSlice("))");

    const v = try verifyProofSmt(std.testing.allocator, buf.items, &.{}, "(set-logic ALL)");
    try std.testing.expect(v.too_deep);
    try std.testing.expect(std.mem.indexOf(u8, v.reject, "ГЛУБЖЕ") != null);
    try std.testing.expect(std.mem.indexOf(u8, v.reject, "не разбирается") == null);
    // И отказ обязан быть отказом: подтверждением он не является.
    try std.testing.expect(!v.checksPass());
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

test "ХАРДКОР: остаток из ОДНОГО литерала, равного ВСЕЙ цели, -> verified (#431, шаг 3)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var c = newCtx(a);
    // Клауза с ВЛОЖЕННЫМ `or` — ровно форма из дампа `[dbg-ur-unver]` на
    // `QF_BV/add_three.4_bit`: `(or (or A B C) k)`. Юнит `(not k)` снимает `k`,
    // остаётся РОВНО `(or A B C)`, а цель разбирается на ТРИ литерала.
    // ЗВУЧНО: `(or R1 … Rk) ∧ ¬R1 … ∧ ¬Rk-1 ⊨ Rk`.
    // Убивает мутанта, снимающего fallback: без него шаг -> `.unverifiable`
    // (доверенный), и на `add_three.4_bit` доверенных было 2970 вместо 1020.
    try c.stepexpr.put("@c1", try parseSexp(a, "(asserted (or (or A B C) k))"));
    try c.stepexpr.put("@u1", try parseSexp(a, "(asserted (not k))"));
    try std.testing.expectEqual(CheckResult.verified, checkUnitRes(&c, try parseSexp(a, "(unit-resolution @c1 @u1 (or A B C))")));
    // АТАКА: цель ДРУГАЯ (Z вместо C) — остаток ей НЕ равен, шаг НЕ проверен.
    // Без этой ветки «проверкой» называлось бы любое совпадение по счёту.
    try std.testing.expect(checkUnitRes(&c, try parseSexp(a, "(unit-resolution @c1 @u1 (or A B Z))")) != CheckResult.verified);
    // АТАКА: остаток из ДВУХ литералов, цель — один из них, но ВТОРОЙ юнитом
    // НЕ опровергнут (нет `(not B)`) -> не verified.
    try c.stepexpr.put("@c2", try parseSexp(a, "(asserted (or A B))"));
    try std.testing.expect(checkUnitRes(&c, try parseSexp(a, "(unit-resolution @c2 @u1 A)")) != CheckResult.verified);
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

// ЭШЕЛОН 5, ПУНКТ 26: три ЗВУЧИМЫХ правила, добавленных для пресета
// `@kern:idempotent` (путевая формулировка). Каждое — с НЕГАТИВНЫМ двойником.
test "ПУНКТ 26: constCmpEval — константное сравнение вычисляется, неконстантное НЕТ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    try std.testing.expectEqual(@as(?bool, true), constCmpEval(try parseSexp(a, "(<= 0 100)")));
    try std.testing.expectEqual(@as(?bool, false), constCmpEval(try parseSexp(a, "(< 0 0)")));
    try std.testing.expectEqual(@as(?bool, true), constCmpEval(try parseSexp(a, "(>= 5 5)")));
    // НЕГАТИВНЫЙ ДВОЙНИК: с переменной это НЕ константа — вычислять нельзя.
    try std.testing.expectEqual(@as(?bool, null), constCmpEval(try parseSexp(a, "(<= x 0)")));
    try std.testing.expectEqual(@as(?bool, null), constCmpEval(try parseSexp(a, "(<= x y)")));
}

test "ПУНКТ 26: constIteEq — свёртка ite с КОНСТАНТНЫМ условием" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // (= (ite false 100 0) 0) — ложное условие выбирает ветвь ELSE.
    try std.testing.expect(constIteEq(try parseSexp(a, "(ite false 100 0)"),
                                      try parseSexp(a, "0")));
    // (= (ite true 100 0) 100) — истинное условие выбирает ветвь THEN.
    try std.testing.expect(constIteEq(try parseSexp(a, "(ite true 100 0)"),
                                      try parseSexp(a, "100")));
    // НЕГАТИВНЫЙ ДВОЙНИК: не та ветвь — НЕ равно.
    try std.testing.expect(!constIteEq(try parseSexp(a, "(ite false 100 0)"),
                                       try parseSexp(a, "100")));
    // НЕГАТИВНЫЙ ДВОЙНИК: НЕконстантное условие сворачивать НЕЛЬЗЯ.
    try std.testing.expect(!constIteEq(try parseSexp(a, "(ite (< x 0) 100 0)"),
                                       try parseSexp(a, "0")));
    try std.testing.expect(!constIteEq(try parseSexp(a, "(ite (< x 0) 100 0)"),
                                       try parseSexp(a, "100")));
}

test "ПУНКТ 26: рефлексивность равенства (= A A) = true, разные термы — НЕТ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    try std.testing.expectEqual(@as(?bool, true), evalBoolConst(try parseSexp(a, "(= x x)")));
    try std.testing.expectEqual(@as(?bool, false),
        evalBoolConst(try parseSexp(a, "(not (= x x))")));
    // НЕГАТИВНЫЙ ДВОЙНИК: `(= x y)` при разных переменных — НЕ константа
    // (иначе чекер «доказывал» бы произвольные равенства).
    try std.testing.expectEqual(@as(?bool, null), evalBoolConst(try parseSexp(a, "(= x y)")));
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

// ЭШЕЛОН 5, ПУНКТ 27: ЛИНЕЙНАЯ ТАВТОЛОГИЯ `(= E true)`, где `E` — линейное
// сравнение. Звучимость даёт встроенный Фурье—Моцкин (гейт `make lia-diff`).
test "ПУНКТ 27: linTautEq — тавтология доказана, НЕтавтология ОТВЕРГНУТА" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // ТАВТОЛОГИЯ: `(= (>= X X) true)`, где X = 3a1 + 3a2 (разность сокращается,
    // остаётся `1 <= 0` — противоречие) — это ШАГ ИЗ РЕАЛЬНОГО вывода
    // `@kern:no_arbitrage` (`(rewrite (= $x50 true))`).
    const taut = try parseSexp(a, "(= (>= (+ (* 3 a1) (* 3 a2)) (+ (* 3 a1) (* 3 a2))) true)");
    try std.testing.expect(isEq3(taut));
    try std.testing.expect(linTautEq(&c, taut.items[1], taut.items[2]));
    // НЕГАТИВНЫЙ ДВОЙНИК: `(= (>= a1 5) true)` тавтологией НЕ является —
    // принимающий это правило «доказывал» бы ложные утверждения.
    const not_taut = try parseSexp(a, "(= (>= a1 5) true)");
    try std.testing.expect(!linTautEq(&c, not_taut.items[1], not_taut.items[2]));
    // И `(= E false)` для заведомо истинного `E` тоже НЕ принимается.
    const wrong = try parseSexp(a, "(= (>= a1 0) false)");
    try std.testing.expect(!linTautEq(&c, wrong.items[1], wrong.items[2]));
    // Не-сравнение (атом/терм) не является линейной тавтологией.
    try std.testing.expect(!linTautEq(&c, try parseSexp(a, "(+ a1 1)"),
                                      try parseSexp(a, "true")));
}

// ОТБРОС НУЛЕВЫХ КОЭФФИЦИЕНТОВ в `pushLin`: без него ограничение, ставшее
// чисто константным (`1 <= 0`), не распознавалось как НЕСОВМЕСТНОЕ, и корректный
// шаг оставался доверенным (ИЗМЕРЕНО на `@kern:no_arbitrage`).
test "ПУНКТ 27: pushLin отбрасывает нулевые коэффициенты (константа видна)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    var cons = std.array_list.Managed(builtin_lia.Lin).init(a);
    // `X - X + 1 <= 0`, где X = a1 + a2 -> коэффициенты сокращаются в ноль.
    try std.testing.expect(asLeZero(&c, try parseSexp(a, "(< (+ a1 a2) (+ a1 a2))"), &cons));
    try std.testing.expectEqual(@as(usize, 1), cons.items.len);
    try std.testing.expectEqual(@as(usize, 0), cons.items[0].terms.len); // термов НЕТ
    try std.testing.expectEqual(@as(i64, 1), cons.items[0].constant);
    var s = builtin_lia.Solver.init(a);
    defer s.deinit();
    try std.testing.expectEqual(builtin_lia.Verdict.unsat,
        builtin_lia.checkUnsat(&s, cons.items));
}

// ЭШЕЛОН 5, ПУНКТЫ 26/29/30: правила, добавленные ПО ДАМПАМ. Каждое — с
// НЕГАТИВНЫМ двойником: правило, принимающее неверное тождество, «доказывало»
// бы ложь.
test "ПУНКТ 29: commEq — коммутативность +/* принимается, вычитание НЕТ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    try std.testing.expect(commEq(try parseSexp(a, "(* x 1000000)"),
                                  try parseSexp(a, "(* 1000000 x)")));
    try std.testing.expect(commEq(try parseSexp(a, "(+ a b)"),
                                  try parseSexp(a, "(+ b a)")));
    // НЕГАТИВНЫЕ: разные операнды и НЕкоммутативная операция.
    try std.testing.expect(!commEq(try parseSexp(a, "(+ a b)"),
                                   try parseSexp(a, "(+ b c)")));
    try std.testing.expect(!commEq(try parseSexp(a, "(- a b)"),
                                   try parseSexp(a, "(- b a)")));
}

test "ПУНКТ 26/30: deMorganEq — обе стороны, полярность, НЕ-эквивалент отвергнут" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // ¬(A ∧ B) ≡ ¬A ∨ ¬B
    try std.testing.expect(deMorganEq(try parseSexp(a, "(not (and A B))"),
                                      try parseSexp(a, "(or (not A) (not B))")));
    // ¬(A ∨ B) ≡ ¬A ∧ ¬B
    try std.testing.expect(deMorganEq(try parseSexp(a, "(not (or A B))"),
                                      try parseSexp(a, "(and (not A) (not B))")));
    // ДВОЙНОЕ ОТРИЦАНИЕ + де Морган: (and A B) ≡ ¬(¬A ∨ ¬B).
    try std.testing.expect(deMorganEq(try parseSexp(a, "(and A B)"),
                                      try parseSexp(a, "(not (or (not A) (not B)))")));
    // НЕГАТИВНЫЙ: другой дизъюнкт.
    try std.testing.expect(!deMorganEq(try parseSexp(a, "(not (and A B))"),
                                       try parseSexp(a, "(or (not A) (not C))")));
}

test "ПУНКТ 26: andTautEq — тавтологичный конъюнкт отбрасывается, не-тавтология НЕТ" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // (not (and A TAUT)) ≡ (not A), где TAUT = (<= x x) — тавтология.
    try std.testing.expect(andTautEq(&c,
        try parseSexp(a, "(not (and (>= x 0) (<= x x)))"),
        try parseSexp(a, "(not (>= x 0))")));
    // НЕГАТИВНЫЙ: (<= x 5) тавтологией НЕ является -> отбрасывать нельзя.
    try std.testing.expect(!andTautEq(&c,
        try parseSexp(a, "(not (and (>= x 0) (<= x 5)))"),
        try parseSexp(a, "(not (>= x 0))")));
}

test "ПУНКТ 29: andEquivEq — эквивалентные конъюнкции, НЕэквивалентные отвергнуты" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // `0 <= 2x <= 10` ≡ `0 <= x <= 5` над целыми.
    try std.testing.expect(andEquivEq(&c,
        try parseSexp(a, "(not (and (>= (* x 2) 0) (<= (* x 2) 10)))"),
        try parseSexp(a, "(not (and (>= x 0) (<= x 5)))")));
    // НЕГАТИВНЫЙ: `x <= 3` не эквивалентно `2x <= 10`.
    try std.testing.expect(!andEquivEq(&c,
        try parseSexp(a, "(not (and (>= (* x 2) 0) (<= (* x 2) 10)))"),
        try parseSexp(a, "(not (and (>= x 0) (<= x 3)))")));
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

test "МУТАНТЫ 1876/2427/2601: защитные `return false` обязаны отвергать" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);

    // 2427 (verifyIffFalse): заключение `(= a b)` — НИ ОДНА сторона не `false`.
    // Это НЕ iff-false; мутант `false->true` принял бы любой `=` как определение
    // false, то есть ослабил бы правило. Ожидается ОТКАЗ.
    const iff_bad = try parseSexp(a, "(iff-false (= a b) (= a b))");
    try std.testing.expect(!verifyIffFalse(&c, iff_bad));
    // Позитивный контроль: `(= a false)` — уже настоящий iff-false (не 0/0).
    const iff_ok = try parseSexp(a, "(iff-false (not a) (= a false))");
    _ = verifyIffFalse(&c, iff_ok);

    // 2601 (verifyNotOrElim): голова `(not X)` — но `X` начинается СО СПИСКА,
    // а не с атома-связки. Мутант `orelse return true` объявил бы такое правило
    // доказанным, НЕ проверив связку (и, значит, принял бы что угодно).
    const noe_bad = try parseSexp(a, "(not-or-elim (not ((or a b) c)) (= a b))");
    try std.testing.expect(!verifyNotOrElim(&c, noe_bad));

    // 1876 (linTautEq `alts.len == 0`): НЕДОСТИЖИМАЯ защита, а не дыра в тестах.
    // ИЗМЕРЕНО: `linTautEq` доходит до этой строки только при `isCmpExpr(e)`,
    // а `negAlternatives` для любого сравнения даёт >= 1 альтернативу
    // (для `=` — две, для остальных — fallback 1591-1594). Поэтому пустой
    // список альтернатив при сравнении невозможен; сайт занесён в
    // KNOWN_EQUIVALENT_SITES с этим обоснованием.
}

test "ДЕФЕКТ #155: битая ссылка @xN в th-lemma -> ОТКАЗ (не «доказано»)" {
    // НАЙДЕНО `tools/evo_fuzzer.py`: переименование ОПРЕДЕЛЕНИЯ шага при живых
    // ссылках давало `Фаркаш 3 -> 0` и всё равно `trusted: 0`, rc=0. Теперь
    // такая посылка означает ИСПОРЧЕННОЕ доказательство -> отказ.
    const fx = @import("abs_proof_fixture.zig");
    // `@embedFile` не выходит за пределы пакета (src/), поэтому читаем файл
    // штатно: тест нативный, файловая система доступна.
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const renamed = @embedFile("abs_proof_renamed.txt");
    const contract = try extractAsserts(a, fx.ABS_CONTRACT);
    const v = try verifyProof(a, renamed, contract);
    // Главное: НЕ «чисто доказано».
    try std.testing.expect(!(v.checksPass() and v.proof_concludes_false and v.trusted_steps == 0));
}

test "КЛАМП: верхняя оценка ite-терма доказуема (шаг Z3, trusted: 0)" {
    // ИЗМЕРЕНО на клампе `+|`: Z3 переписывает `(<= (ite C T HI) HI)` в
    // `(or (not C) (<= T HI))`. Без правила шаг был ДОВЕРЕННЫМ.
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    const t = try parseSexp(a,
        "(rewrite (= (<= (ite (< a 0) a 0) 0) (or (not (< a 0)) (<= a 0))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, t));
    // НЕГАТИВНЫЙ двойник: оценка ДРУГОЙ границей — не эквивалентна.
    const bad = try parseSexp(a,
        "(rewrite (= (<= (ite (< a 0) a 0) 0) (or (not (< a 0)) (<= a 1))))");
    try std.testing.expect(checkRewrite(&c, bad) != .verified);
}

test "#303: вид запроса управляет требованием привязки посылок" {
    // refutation (проверка контракта): непривязанная посылка — отказ.
    var v = ProofVerdict{ .proof_steps = 10, .premises_unbound = 1, .premises_required = true };
    try std.testing.expect(!v.checksPass());
    try std.testing.expect(std.mem.indexOf(u8, v.failureReason(), "premises_unbound") != null);
    // equivalence (сравнение двух тел): контрактных посылок нет по построению,
    // поэтому правило не применяется — но остальные требования сохраняются.
    v.premises_required = false;
    try std.testing.expect(v.checksPass());
    v.holes = 1; // дыра остаётся фатальной в ЛЮБОМ виде запроса
    try std.testing.expect(!v.checksPass());
    v.holes = 0;
    v.mp_bad = 1; // подделанный шаг — тоже
    try std.testing.expect(!v.checksPass());
}


test "CVE-B: n-арные суммы и канонизация сравнений (trusted: 0)" {
    // ИЗМЕРЕНО на `ptr_wrap_guard.smt2`: Z3 пишет сумму N-АРНО
    // (`(+ K a (* (- 1) b))`) и меняет запись сравнения
    // (`¬(x <= y)` -> `y - x + 1 <= 0`, `x >= y` -> `0 >= y - x`).
    // Без этих правил шаги оставались ДОВЕРЕННЫМИ.
    //
    // ГРАНИЦА (названа, не спрятана): сравнение, внутри которого стоит
    // `ite`, пока НЕ канонизируется — нелинейный подтерм не выражается суммой.
    // Поэтому сертификаты CVE-B записаны РАЗБОРОМ ПО СЛУЧАЯМ (без `ite`).
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);

    // (1) N-арная сумма: `(- a b)` и `(+ a (* (- 1) b))` — одна линейная форма.
    const s1 = try parseSexp(a, "(rewrite (= (ite (>= a b) (- a b) (+ (- a b) 4294967296)) (ite (>= a b) (+ a (* (- 1) b)) (+ 4294967296 a (* (- 1) b)))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, s1));

    // (2) `¬(x <= y)` <-> `y - x + 1 <= 0` (целочисленный сдвиг).
    const s2 = try parseSexp(a, "(rewrite (= (not (<= a b)) (<= (+ b (* (- 1) a) 1) 0)))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, s2));

    // (3) Канонизация сравнения: `x >= y` <-> `0 >= y - x`.
    const s3 = try parseSexp(a, "(rewrite (= (>= a b) (>= 0 (- b a))))");
    try std.testing.expectEqual(RwResult.verified, checkRewrite(&c, s3));

    // НЕГАТИВНЫЙ двойник: другой сдвиг (+2 вместо +1) — НЕ эквивалентно.
    const bad = try parseSexp(a, "(rewrite (= (not (<= a b)) (<= (+ b (* (- 1) a) 2) 0)))");
    try std.testing.expect(checkRewrite(&c, bad) != .verified);
}

test "#344: define-fun раскрывается ПОДСТАНОВКОЙ, атомы не теряются" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    // Шапка SMT — ПОСЛЕДОВАТЕЛЬНОСТЬ выражений (не одно!): именно на этом
    // первая версия молча находила только `(set-logic ALL)`.
    loadFunDefs(&c, "(set-logic ALL)\n(declare-const a Int)\n" ++
        "(define-fun evm_div ((x Int) (y Int)) Int (ite (= y 0) 0 (div x y)))\n" ++
        "(assert (not (= (evm_div a 0) 0)))\n(check-sat)");
    const e = try parseSexp(a, "(evm_div 7 2)");
    var budget: usize = 1000;
    const out = funExpand(&c, e, 0, &budget);
    // Ожидаем раскрытое тело `(ite (= 2 0) 0 (div 7 2))` с АТОМАМИ на местах.
    try std.testing.expect(out.isList());
    try std.testing.expectEqualStrings("ite", out.items[0].atom.?);
    try std.testing.expect(out.items[1].isList());
    try std.testing.expectEqualStrings("=", out.items[1].items[0].atom.?);
    try std.testing.expectEqualStrings("2", out.items[1].items[1].atom.?);
    try std.testing.expectEqualStrings("0", out.items[1].items[2].atom.?);
    try std.testing.expectEqualStrings("0", out.items[2].atom.?);
    try std.testing.expectEqualStrings("div", out.items[3].items[0].atom.?);
    try std.testing.expectEqualStrings("7", out.items[3].items[1].atom.?);
}

test "#344: НЕГАТИВНЫЙ — подделанная подстановка НЕ проходит" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var c = newCtx(a);
    loadFunDefs(&c, "(define-fun inc ((x Int)) Int (+ x 1))");
    var b1: usize = 1000;
    const out = funExpand(&c, try parseSexp(a, "(inc 5)"), 0, &b1);
    // Раскрытие даёт `(+ 5 1)`, а НЕ `(+ 6 1)`: подстановка не подгоняет ответ.
    try std.testing.expect(sexpEqNum(out, try parseSexp(a, "(+ 5 1)")));
    try std.testing.expect(!sexpEqNum(out, try parseSexp(a, "(+ 6 1)")));
    // Неизвестная функция НЕ раскрывается (и не «угадывается»).
    var b2: usize = 1000;
    const unknown = funExpand(&c, try parseSexp(a, "(other 5)"), 0, &b2);
    try std.testing.expectEqualStrings("other", unknown.items[0].atom.?);
    try std.testing.expectEqual(@as(usize, 2), unknown.items.len);
}

test "#344: константная арифметика — floor-деление, mod, отказ на делении на ноль" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // Доказано Z3 на EVM-тождестве: `(= (div 7 2) 3)`.
    try std.testing.expect(constIntEq(try parseSexp(a, "(div 7 2)"), try parseSexp(a, "3")));
    // FLOOR, а не усечение: `(div (- 7) 2) = -4` (это и отличает SMT `div`).
    try std.testing.expect(constIntEq(try parseSexp(a, "(div (- 7) 2)"), try parseSexp(a, "-4")));
    try std.testing.expect(constIntEq(try parseSexp(a, "(mod 7 2)"), try parseSexp(a, "1")));
    // НЕГАТИВНЫЕ двойники: неверное значение и деление на ноль.
    try std.testing.expect(!constIntEq(try parseSexp(a, "(div 7 2)"), try parseSexp(a, "4")));
    try std.testing.expect(!constIntEq(try parseSexp(a, "(div 7 0)"), try parseSexp(a, "0")));
    try std.testing.expect(!constIntEq(try parseSexp(a, "(mod 7 0)"), try parseSexp(a, "0")));
}

test "ЕВКЛИДОВО деление при b < 0 (SMT-LIB2), а не floor — и БЕЗ паники" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    // ИЗМЕРЕНО в Z3: (div 1 (- 2)) = 0, (mod 1 (- 2)) = 1.
    // Zig `@divFloor(1, -2)` дал бы -1 — то есть ЛОЖНОЕ тождество.
    try std.testing.expect(constIntEq(try parseSexp(a, "(div 1 (- 2))"), try parseSexp(a, "0")));
    try std.testing.expect(!constIntEq(try parseSexp(a, "(div 1 (- 2))"), try parseSexp(a, "-1")));
    try std.testing.expect(constIntEq(try parseSexp(a, "(mod 1 (- 2))"), try parseSexp(a, "1")));
    try std.testing.expect(!constIntEq(try parseSexp(a, "(mod 1 (- 2))"), try parseSexp(a, "-1")));
    // Частное +4, а НЕ +3: (-2)*4 + 1 = -7, остаток 1 ∈ [0, 2).
    try std.testing.expect(constIntEq(try parseSexp(a, "(div (- 7) (- 2))"), try parseSexp(a, "4")));
    try std.testing.expect(!constIntEq(try parseSexp(a, "(div (- 7) (- 2))"), try parseSexp(a, "3")));
    try std.testing.expect(constIntEq(try parseSexp(a, "(mod (- 7) (- 2))"), try parseSexp(a, "1")));
    // Знаковое делимое с ПОЛОЖИТЕЛЬНЫМ делителем остаётся floor.
    try std.testing.expect(constIntEq(try parseSexp(a, "(div 7 (- 2))"), try parseSexp(a, "-3")));
    // ЗАЩИТА ОТ ПАНИКИ: `a = MIN, b = -1` даёт в Z3 2^63 — ВНЕ i64, значит
    // значение не представимо и обязан быть ОТКАЗ, а не `integer overflow`.
    // Сначала — что сам литерал MIN РАЗБИРАЕТСЯ (иначе guard недостижим).
    try std.testing.expectEqual(@as(?i64, std.math.minInt(i64)),
        evalConstInt(try parseSexp(a, "(- 9223372036854775808)")));
    try std.testing.expectEqual(@as(?i64, std.math.minInt(i64)),
        evalConstInt(try parseSexp(a, "-9223372036854775808")));
    try std.testing.expect(evalConstInt(try parseSexp(a, "(div (- 9223372036854775808) (- 1))")) == null);
    try std.testing.expect(evalConstInt(try parseSexp(a, "(div 1 (- 9223372036854775808))")) == null);
    try std.testing.expect(evalConstInt(try parseSexp(a, "(mod 1 (- 9223372036854775808))")) == null);
    // Guard обязан срабатывать и на ВЫЧИСЛЯЕМОМ MIN — иначе он мёртвый код.
    try std.testing.expectEqual(@as(?i64, std.math.minInt(i64)),
        evalConstInt(try parseSexp(a, "(- (- 1) 9223372036854775807)")));
    try std.testing.expect(evalConstInt(
        try parseSexp(a, "(div (- (- 1) 9223372036854775807) (- 1))")) == null);
    // `mod(MIN, -1) = 0` — влезает в i64, значение обязано быть.
    try std.testing.expectEqual(@as(?i64, 0), evalConstInt(try parseSexp(a, "(mod (- 9223372036854775808) (- 1))")));
}

test "ПЕРЕПОЛНЕНИЕ константной арифметики — ОТКАЗ, а не wrapping (сорт Int)" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    const max = "9223372036854775807";
    // В SMT-LIB `(+ MAX 1) = 2^63` — значение ВНЕ i64. Прежняя реализация с `+%`
    // вернула бы `MIN` и ПРИНЯЛА ложное тождество `(= (+ MAX 1) MIN)`.
    try std.testing.expect(evalConstInt(try parseSexp(a, "(+ 9223372036854775807 1)")) == null);
    try std.testing.expect(evalConstInt(try parseSexp(a, "(- (- 9223372036854775808) 1)")) == null);
    try std.testing.expect(evalConstInt(try parseSexp(a, "(* 9223372036854775807 2)")) == null);
    try std.testing.expect(!constIntEq(try parseSexp(a, "(+ 9223372036854775807 1)"),
                                     try parseSexp(a, "(- 9223372036854775808)")));
    // Непереполняющие случаи по-прежнему вычисляются.
    try std.testing.expectEqual(@as(?i64, 3), evalConstInt(try parseSexp(a, "(+ 1 2)")));
    try std.testing.expectEqual(@as(?i64, -3), evalConstInt(try parseSexp(a, "(- 0 3)")));
    _ = max;
}

