// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license: newmathphys@gmail.com
//! KERN: извлечение КОНТРПРИМЕРА из вывода Z3 `(get-model)`.
//!
//! ЗАЧЕМ. Когда контракт опровергнут (`sat` -> `KERN-EQ2: F`, `e = 0`),
//! пользователь и ИИ-агент видят только «НЕ доказано» — но не видят, КАКИЕ
//! значения сломали контракт. Без этого вердикт `F` бесполезен: нельзя ни
//! починить код, ни понять, что именно нарушено.
//!
//! ФОРМАТ Z3 (модель — список 0-арных определений):
//! ```text
//! sat
//! (model
//!   (define-fun balance () Int 0)
//!   (define-fun amount () Int (- 1))
//! )
//! ```
//!
//! ВАЖНО: отрицательные числа Z3 печатает как `(- N)`, поэтому `(- 1)`
//! ОБЯЗАНО превращаться в `-1`, иначе контрпример читается неверно.
//! Функции С АРГУМЕНТАМИ (`(define-fun f ((x Int)) Int ...)`) пропускаются:
//! это определения, а не значения входа.
const std = @import("std");

/// Связывание «имя = значение». Памятью владеет вызывающий (`free`).
pub const Binding = struct {
    name: []const u8,
    value: []const u8,
};

inline fn isSpace(c: u8) bool {
    return c == ' ' or c == '\t' or c == '\r' or c == '\n';
}

fn skipSpaces(text: []const u8, i: *usize) void {
    while (i.* < text.len and isSpace(text[i.*])) : (i.* += 1) {}
}

/// Пропустить сбалансированное S-выражение, начинающееся на `text[i] == '('`.
/// Возвращает false, если скобка не закрылась (усечённый ввод).
fn skipSexpr(text: []const u8, i: *usize) bool {
    if (i.* >= text.len or text[i.*] != '(') return false;
    var depth: usize = 0;
    while (i.* < text.len) : (i.* += 1) {
        if (text[i.*] == '(') {
            depth += 1;
        } else if (text[i.*] == ')') {
            depth -= 1;
            if (depth == 0) {
                i.* += 1;
                return true;
            }
        }
    }
    return false;
}

/// Отрендерить значение в читаемую форму.
/// `(- 1)` -> `-1`; `(- 42)` -> `-42`; прочее — как есть.
fn renderValue(allocator: std.mem.Allocator, raw: []const u8) ![]const u8 {
    const t = std.mem.trim(u8, raw, " \t\r\n");
    if (t.len > 4 and std.mem.startsWith(u8, t, "(- ") and t[t.len - 1] == ')') {
        const inner = std.mem.trim(u8, t[3 .. t.len - 1], " \t");
        // только одиночное число: без пробелов внутри
        if (inner.len > 0 and std.mem.indexOfScalar(u8, inner, ' ') == null) {
            return std.fmt.allocPrint(allocator, "-{s}", .{inner});
        }
    }
    return allocator.dupe(u8, t);
}

/// Разобрать вывод `(get-model)`. Возвращает список 0-арных констант.
pub fn extract(allocator: std.mem.Allocator, text: []const u8) ![]Binding {
    var out: std.ArrayListUnmanaged(Binding) = .empty;
    errdefer {
        for (out.items) |b| {
            allocator.free(b.name);
            allocator.free(b.value);
        }
        out.deinit(allocator);
    }

    var i: usize = 0;
    while (std.mem.indexOfPos(u8, text, i, "(define-fun ")) |start| {
        i = start + "(define-fun ".len;
        // 1) имя
        const name_start = i;
        while (i < text.len and !isSpace(text[i]) and text[i] != '(') : (i += 1) {}
        const name = text[name_start..i];
        if (name.len == 0) continue;
        skipSpaces(text, &i);

        // 2) список аргументов: 0-арные -> `()`
        if (i >= text.len or text[i] != '(') continue;
        const args_start = i;
        if (!skipSexpr(text, &i)) break;
        const args = std.mem.trim(u8, text[args_start + 1 .. i - 1], " \t\r\n");
        if (args.len != 0) continue; // функция с аргументами — не значение входа

        skipSpaces(text, &i);
        // 3) сорт: атом или `(_ BitVec 32)`
        if (i < text.len and text[i] == '(') {
            if (!skipSexpr(text, &i)) break;
        } else {
            while (i < text.len and !isSpace(text[i]) and text[i] != ')') : (i += 1) {}
        }
        skipSpaces(text, &i);

        // 4) значение: атом ИЛИ S-выражение `(- 1)`
        const val_start = i;
        if (i < text.len and text[i] == '(') {
            if (!skipSexpr(text, &i)) break;
        } else {
            while (i < text.len and !isSpace(text[i]) and text[i] != ')') : (i += 1) {}
        }
        if (i <= val_start) continue;
        const value = try renderValue(allocator, text[val_start..i]);
        errdefer allocator.free(value);
        const name_copy = try allocator.dupe(u8, name);
        try out.append(allocator, .{ .name = name_copy, .value = value });
    }
    return out.toOwnedSlice(allocator);
}

/// Свободить результат `extract`.
pub fn free(allocator: std.mem.Allocator, bindings: []Binding) void {
    for (bindings) |b| {
        allocator.free(b.name);
        allocator.free(b.value);
    }
    allocator.free(bindings);
}

// ===========================================================================
//  ПРОВЕРКА SAT-МОДЕЛИ ВНУТРИ ЯДРА (пункт 2 плана v2.5)
// ===========================================================================
// ЗАЧЕМ. Для `UNSAT` мы не верим решателю на слово — вывод перепроверяет
// `proof_check.zig`. Для `SAT` модель до сих пор принималась КАК НАПЕЧАТАНО.
// Если ошибётся Z3 или НАША трансляция Python->SMT, пользователю предъявят
// ФАЛЬШИВЫЙ контрпример, и он пойдёт «чинить» корректный код.
//
// ЧТО ДЕЛАЕМ. Подставляем значения из `(get-model)` обратно в `(assert ...)`
// контракта и вычисляем КАЖДЫЙ ассерт НЕЗАВИСИМЫМ вычислителем на Zig.
// Хотя бы один ложный ассерт -> модель отвергается как `SpuriousModel`.
//
// ГРАНИЦА ЧЕСТНО. Поддержан целочисленно-линейный фрагмент и булевы связки:
// `+ - * / div mod`, сравнения, `and/or/not`, `ite`. Термы с битовыми
// векторами (`#x...`, `bv*`) НЕ поддержаны: вместо догадки возвращается
// `unsupported`, и вызывающий ОБЯЗАН сообщить, что проверка модели не
// выполнена. Непроверенное не выдаётся за проверенное (fail-closed).
pub const ModelCheck = union(enum) {
    /// Все ассерты вычислены и истинны (значение — их количество).
    ok: usize,
    /// Ассерт ЛОЖЕН под этой моделью -> модель фальшивая.
    spurious: struct { index: usize, term: []const u8 },
    /// Проверить нельзя (вне фрагмента) — честный отказ, не «ок».
    unsupported: []const u8,
};

const Val = union(enum) { int: i128, boolean: bool };
const EvalError = error{ Unsupported, Malformed, OutOfRange };

fn lookupInt(bindings: []const Binding, name: []const u8) EvalError!i128 {
    for (bindings) |b| {
        if (!std.mem.eql(u8, b.name, name)) continue;
        if (b.value.len > 0 and b.value[0] == '#') return EvalError.Unsupported;
        return std.fmt.parseInt(i128, b.value, 10) catch EvalError.Unsupported;
    }
    return EvalError.Malformed; // имя не связано моделью
}

fn asInt(v: Val) EvalError!i128 {
    return switch (v) {
        .int => |n| n,
        else => EvalError.Malformed,
    };
}

fn asBool(v: Val) EvalError!bool {
    return switch (v) {
        .boolean => |b| b,
        else => EvalError.Malformed,
    };
}

fn inRange(x: i128) EvalError!i128 {
    if (x > std.math.maxInt(i64) or x < std.math.minInt(i64)) return EvalError.OutOfRange;
    return x;
}

/// Деление как в SMT-LIB для `Int`: округление ВНИЗ (пол).
fn floorDiv(a: i128, b: i128) EvalError!i128 {
    if (b == 0) return EvalError.Malformed;
    var q = @divTrunc(a, b);
    if (@rem(a, b) != 0 and ((a < 0) != (b < 0))) q -= 1;
    return q;
}

/// Остаток как в SMT-LIB `mod`: знак берётся у ДЕЛИТЕЛЯ.
fn smtMod(a: i128, b: i128) EvalError!i128 {
    if (b == 0) return EvalError.Malformed;
    const r = @rem(a, b);
    return if (r != 0 and ((r < 0) != (b < 0))) r + b else r;
}

fn skipWs(t: []const u8, i: *usize) void {
    while (i.* < t.len and isSpace(t[i.*])) : (i.* += 1) {}
}

fn readAtom(t: []const u8, i: *usize) []const u8 {
    const s = i.*;
    while (i.* < t.len and !isSpace(t[i.*]) and t[i.*] != '(' and t[i.*] != ')') : (i.* += 1) {}
    return t[s..i.*];
}

/// Вычислить терм под моделью. Рекурсивный спуск БЕЗ аллокаций: `i` указывает
/// на начало терма, после вызова — сразу за ним.
fn evalTerm(t: []const u8, i: *usize, b: []const Binding, depth: u32) EvalError!Val {
    if (depth > 64) return EvalError.Malformed;
    skipWs(t, i);
    if (i.* >= t.len) return EvalError.Malformed;

    if (t[i.*] != '(') {
        const a = readAtom(t, i);
        if (a.len == 0) return EvalError.Malformed;
        if (std.mem.eql(u8, a, "true")) return Val{ .boolean = true };
        if (std.mem.eql(u8, a, "false")) return Val{ .boolean = false };
        if (std.fmt.parseInt(i128, a, 10)) |n| {
            return Val{ .int = n };
        } else |_| {}
        if (a[0] == '#') return EvalError.Unsupported;
        return Val{ .int = try lookupInt(b, a) };
    }

    i.* += 1;
    skipWs(t, i);
    const head = readAtom(t, i);
    if (head.len == 0) return EvalError.Malformed;

    var args: [8]Val = undefined;
    var n: usize = 0;
    while (true) {
        skipWs(t, i);
        if (i.* >= t.len) return EvalError.Malformed;
        if (t[i.*] == ')') {
            i.* += 1;
            break;
        }
        if (n >= args.len) return EvalError.Unsupported;
        args[n] = try evalTerm(t, i, b, depth + 1);
        n += 1;
    }

    if (std.mem.eql(u8, head, "+")) {
        var s: i128 = 0;
        for (args[0..n]) |v| s += try asInt(v);
        return Val{ .int = try inRange(s) };
    }
    if (std.mem.eql(u8, head, "-")) {
        if (n == 0) return EvalError.Malformed;
        var s: i128 = try asInt(args[0]);
        if (n == 1) return Val{ .int = try inRange(-s) };
        for (args[1..n]) |v| s -= try asInt(v);
        return Val{ .int = try inRange(s) };
    }
    if (std.mem.eql(u8, head, "*")) {
        var s: i128 = 1;
        for (args[0..n]) |v| s *= try asInt(v);
        return Val{ .int = try inRange(s) };
    }
    if (std.mem.eql(u8, head, "/") or std.mem.eql(u8, head, "div")) {
        if (n != 2) return EvalError.Malformed;
        return Val{ .int = try inRange(try floorDiv(try asInt(args[0]), try asInt(args[1]))) };
    }
    if (std.mem.eql(u8, head, "mod")) {
        if (n != 2) return EvalError.Malformed;
        return Val{ .int = try inRange(try smtMod(try asInt(args[0]), try asInt(args[1]))) };
    }
    // ДЕФЕКТ #146: РАВЕНСТВО БУЛЕВЫХ ПОДФОРМУЛ. `(= (= p g) (= p2 g))` —
    // это сравнение ДВУХ булевых значений, а не целых. ИЗМЕРЕНО на
    // `@kern:secret` (Пункт 34): вычислитель падал на `asInt` от Bool, и
    // годный контрпример объявлялся «фальшивой моделью».
    if (std.mem.eql(u8, head, "=") and n == 2) {
        if (asInt(args[0])) |a| {
            if (asInt(args[1])) |c| return Val{ .boolean = a == c } else |_| {}
        } else |_| {}
        if (asBool(args[0])) |a| {
            if (asBool(args[1])) |c| return Val{ .boolean = a == c } else |_| {}
        } else |_| {}
        return EvalError.Unsupported;
    }
    if (std.mem.eql(u8, head, "<") or std.mem.eql(u8, head, "<=") or
        std.mem.eql(u8, head, ">") or std.mem.eql(u8, head, ">="))
    {
        if (n != 2) return EvalError.Malformed;
        const a = try asInt(args[0]);
        const c = try asInt(args[1]);
        const r = if (std.mem.eql(u8, head, "<")) a < c else if (std.mem.eql(u8, head, "<=")) a <= c else if (std.mem.eql(u8, head, ">")) a > c else a >= c;
        return Val{ .boolean = r };
    }
    if (std.mem.eql(u8, head, "and")) {
        for (args[0..n]) |v| if (!try asBool(v)) return Val{ .boolean = false };
        return Val{ .boolean = true };
    }
    if (std.mem.eql(u8, head, "or")) {
        for (args[0..n]) |v| if (try asBool(v)) return Val{ .boolean = true };
        return Val{ .boolean = false };
    }
    if (std.mem.eql(u8, head, "not")) {
        if (n != 1) return EvalError.Malformed;
        return Val{ .boolean = !(try asBool(args[0])) };
    }
    if (std.mem.eql(u8, head, "ite")) {
        if (n != 3) return EvalError.Malformed;
        return if (try asBool(args[0])) args[1] else args[2];
    }
    return EvalError.Unsupported;
}

/// ПРОВЕРИТЬ МОДЕЛЬ ПРОТИВ АССЕРТОВ КОНТРАКТА (независимо от Z3).
pub fn verifyModelAgainstSmt(smt: []const u8, bindings: []const Binding) ModelCheck {
    var i: usize = 0;
    var checked: usize = 0;
    while (std.mem.indexOfPos(u8, smt, i, "(assert")) |pos| {
        i = pos + 7;
        if (i < smt.len and !isSpace(smt[i]) and smt[i] != '(') continue;
        var j = i;
        skipWs(smt, &j);
        if (j >= smt.len or smt[j] != '(') continue;
        var k = j;
        if (!skipSexpr(smt, &k)) return .{ .unsupported = "ассерт не закрыт" };
        const term = smt[j..k];
        var p: usize = 0;
        const v = evalTerm(term, &p, bindings, 0) catch |e| switch (e) {
            EvalError.Unsupported => return .{ .unsupported = "терм вне фрагмента (BitVec/неизвестная операция)" },
            // ДЕФЕКТ #146: НЕУМЕНИЕ вычислить форму — это НЕ «фальшивая модель».
            // Раньше Malformed/Overflow объявлялись `spurious`, и настоящий
            // КОНТРПРИМЕР СКРЫВАЛСЯ (измерено на `@kern:secret`). Теперь честно
            // говорим «не проверено», а не «модель подделана».
            else => return .{ .unsupported = "форма вне вычислителя модели" },
        };
        const truth = switch (v) {
            .boolean => |x| x,
            .int => return .{ .unsupported = "ассерт не булев" },
        };
        if (!truth) return .{ .spurious = .{ .index = checked, .term = term } };
        checked += 1;
    }
    return .{ .ok = checked };
}

// ===========================================================================
//  ТЕСТЫ
// ===========================================================================

test "MODEL: положительные, отрицательные, булевы, BitVec" {
    const alloc = std.testing.allocator;
    const text =
        \\sat
        \\(model
        \\  (define-fun balance () Int 0)
        \\  (define-fun amount () Int (- 1))
        \\  (define-fun big () Int (- 42))
        \\  (define-fun flag () Bool true)
        \\  (define-fun mask () (_ BitVec 32) #x0000000f)
        \\)
    ;
    const b = try extract(alloc, text);
    defer free(alloc, b);
    try std.testing.expectEqual(@as(usize, 5), b.len);
    try std.testing.expectEqualStrings("balance", b[0].name);
    try std.testing.expectEqualStrings("0", b[0].value);
    try std.testing.expectEqualStrings("amount", b[1].name);
    // ГЛАВНОЕ: `(- 1)` -> `-1`, а не `(- 1)`.
    try std.testing.expectEqualStrings("-1", b[1].value);
    try std.testing.expectEqualStrings("-42", b[2].value);
    try std.testing.expectEqualStrings("true", b[3].value);
    try std.testing.expectEqualStrings("#x0000000f", b[4].value);
}

test "MODEL: функции С АРГУМЕНТАМИ пропускаются (это не значения входа)" {
    const alloc = std.testing.allocator;
    const text =
        \\(model
        \\  (define-fun f ((x Int)) Int (+ x 1))
        \\  (define-fun x () Int 7)
        \\)
    ;
    const b = try extract(alloc, text);
    defer free(alloc, b);
    try std.testing.expectEqual(@as(usize, 1), b.len);
    try std.testing.expectEqualStrings("x", b[0].name);
    try std.testing.expectEqualStrings("7", b[0].value);
}

test "MODEL: пустая модель -> пустой список (не паника)" {
    const alloc = std.testing.allocator;
    const b = try extract(alloc, "sat\n(model\n)\n");
    defer free(alloc, b);
    try std.testing.expectEqual(@as(usize, 0), b.len);
}

test "MODEL: мусорный ввод -> пустой список, без паники" {
    const alloc = std.testing.allocator;
    const b = try extract(alloc, "unsat\n(error \"model is not available\")\n");
    defer free(alloc, b);
    try std.testing.expectEqual(@as(usize, 0), b.len);
}

test "MODEL: усечённый ввод не роняет парсер" {
    const alloc = std.testing.allocator;
    // ВНИМАНИЕ (найдено прогоном): первая версия теста ожидала 0 связываний.
    // Это НЕВЕРНО: у `x` полностью присутствуют имя, сорт и значение — обрезаны
    // лишь внешние скобки `(model` и `(define-fun`, которые парсеру не нужны.
    // Корректное требование: НЕ падать, а извлечь только ПОЛНЫЕ связывания.
    const b = try extract(alloc, "(model (define-fun x () Int 5");
    defer free(alloc, b);
    try std.testing.expect(b.len <= 1);
    if (b.len == 1) {
        try std.testing.expectEqualStrings("x", b[0].name);
        try std.testing.expectEqualStrings("5", b[0].value);
    }
}

test "MODEL: незакрытое значение не даёт мусорного связывания" {
    const alloc = std.testing.allocator;
    // Значение — незакрытое S-выражение: `(- 1` без `)`. Связывание НЕ полное,
    // поэтому оно не должно попасть в результат.
    const b = try extract(alloc, "(model (define-fun x () Int (- 1");
    defer free(alloc, b);
    try std.testing.expectEqual(@as(usize, 0), b.len);
}

test "ХАРДКОР: define-fun БЕЗ значения пропускается (стр. 117)" {
    const alloc = std.testing.allocator;
    // После сорта значение ОТСУТСТВУЕТ (сразу закрывающая скобка).
    // Убивает мутанта `if (i <= val_start) continue` -> `<`:
    // с `<` пропуск не срабатывает, и `renderValue` получает ПУСТОЙ срез —
    // в результат попало бы связывание с пустым значением.
    const text = "sat\n(model\n  (define-fun x () Int)\n)\n";
    const got = try extract(alloc, text);
    defer free(alloc, got);
    try std.testing.expectEqual(@as(usize, 0), got.len);
}

test "ГРАНИЦА: skipSexpr на КОНЦЕ ввода не читает память (стр. 43)" {
    const text = "abc";
    // i РОВНО на границе среза.
    // Убивает мутанта `if (i.* >= text.len ...)` -> `>`: с ним проверка
    // пропускается и `text[i.*]` читает ЗА границей — в Safe-режимах это
    // паника (выход за границы среза), то есть тест падает.
    var i: usize = text.len;
    try std.testing.expect(!skipSexpr(text, &i));
    // Не-скобка тоже отвергается (граница «ниже»).
    i = 0;
    try std.testing.expect(!skipSexpr(text, &i));
    // Контроль непустоты: корректная скобка принимается.
    const ok_text = "(a b) c";
    var j: usize = 0;
    try std.testing.expect(skipSexpr(ok_text, &j));
}

test "ГРАНИЦА: extract на УСЕЧЁННОМ define-fun не читает память (стр. 95)" {
    const alloc = std.testing.allocator;
    // Имя есть, а списка аргументов НЕТ (ввод кончился).
    // Убивает мутанта `if (i >= text.len or text[i] != '(') continue;` -> `and`:
    // с `and` при `i == text.len` вычисляется `text[i]` — чтение ЗА границей
    // среза (паника в Safe-режимах).
    const got = try extract(alloc, "(define-fun x");
    defer free(alloc, got);
    try std.testing.expectEqual(@as(usize, 0), got.len);
}

// ===========================================================================
//  ПУНКТ 2 ПЛАНА v2.5: ПРОВЕРКА SAT-МОДЕЛИ ПРОТИВ АССЕРТОВ КОНТРАКТА
// ===========================================================================

test "MODEL CHECK: модель удовлетворяет всем ассертам -> ok" {
    const b = [_]Binding{
        .{ .name = "x", .value = "-1" },
        .{ .name = "y", .value = "5" },
    };
    const smt = "(set-logic ALL)\n(declare-const x Int)\n(declare-const y Int)\n" ++
        "(assert (and (>= x -10) (<= x 10)))\n" ++
        "(assert (<= (+ x y) 4))\n(check-sat)\n";
    const r = verifyModelAgainstSmt(smt, &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).ok, std.meta.activeTag(r));
    try std.testing.expectEqual(@as(usize, 2), r.ok);
}

test "MODEL CHECK: ЛОЖНЫЙ ассерт -> spurious (модель ОТВЕРГНУТА)" {
    // Значение x = 100 несовместимо с (<= x 10): значит модель фальшивая,
    // и предъявлять её пользователю как контрпример НЕЛЬЗЯ.
    const b = [_]Binding{
        .{ .name = "x", .value = "100" },
        .{ .name = "y", .value = "5" },
    };
    const smt = "(assert (and (>= x -10) (<= x 10)))\n";
    const r = verifyModelAgainstSmt(smt, &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).spurious, std.meta.activeTag(r));
}

test "MODEL CHECK: BitVec вне фрагмента -> unsupported (это НЕ «ок»)" {
    const b = [_]Binding{.{ .name = "x", .value = "#x0000000a" }};
    const smt = "(assert (= x #x0000000a))\n";
    const r = verifyModelAgainstSmt(smt, &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).unsupported, std.meta.activeTag(r));
}

test "MODEL CHECK: div/mod по правилам SMT-LIB (пол и знак делителя)" {
    const b = [_]Binding{
        .{ .name = "a", .value = "-7" },
        .{ .name = "d", .value = "2" },
    };
    // SMT-LIB для Int: div(-7,2) = -4 (округление ВНИЗ), mod(-7,2) = 1.
    const smt = "(assert (= (div a d) -4))\n(assert (= (mod a d) 1))\n";
    const r = verifyModelAgainstSmt(smt, &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).ok, std.meta.activeTag(r));
    try std.testing.expectEqual(@as(usize, 2), r.ok);
}

test "MODEL CHECK: несвязанное имя -> ассерт не подтверждён (spurious)" {
    const b = [_]Binding{.{ .name = "x", .value = "1" }};
    const smt = "(assert (<= y 10))\n"; // y в модели отсутствует
    const r = verifyModelAgainstSmt(smt, &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).spurious, std.meta.activeTag(r));
}

test "MODEL CHECK: пустой контракт -> ok с нулём проверенных" {
    const b = [_]Binding{.{ .name = "x", .value = "1" }};
    const r = verifyModelAgainstSmt("(check-sat)\n", &b);
    try std.testing.expectEqual(std.meta.Tag(ModelCheck).ok, std.meta.activeTag(r));
    try std.testing.expectEqual(@as(usize, 0), r.ok);
}


// =========================================================================
//  РУБЕЖ 4 (мутационный обстрел): тесты, УБИВАЮЩИЕ выживших мутантов.
// =========================================================================

// Убивает `model_extract.zig:66 [and->or]`: значение `(- 42 7)` содержит
// ПРОБЕЛ внутри, поэтому сворачивать его в `-42 7` НЕЛЬЗЯ (это уже не одно
// число). Мутант `or` сделал бы условие истинным и испортил значение.
test "МУТАНТ 66: renderValue НЕ сворачивает (- 42 7) — внутри пробел" {
    const got = try renderValue(std.testing.allocator, "(- 42 7)");
    defer std.testing.allocator.free(got);
    try std.testing.expectEqualStrings("(- 42 7)", got);
    // Контроль: одиночное число сворачивается штатно.
    const ok = try renderValue(std.testing.allocator, "(- 42)");
    defer std.testing.allocator.free(ok);
    try std.testing.expectEqualStrings("-42", ok);
}

// Убивает `model_extract.zig:245 [>=->>]` — проверка ДОСТИЖЕНИЯ КОНЦА входа
// (`i >= t.len`). На ОБОРВАННОМ терме обязан вернуться честный `Malformed`;
// мутант `>` пошёл бы читать `t[i]` за границей среза (panic).
test "МУТАНТ 245: обрыв входа -> Malformed (без выхода за границы)" {
    var i: usize = 0;
    try std.testing.expectError(EvalError.Malformed, evalTerm("(+ 1", &i, &.{}, 0));
    var j: usize = 0;
    try std.testing.expectError(EvalError.Malformed, evalTerm("(- 3", &j, &.{}, 0));
}

// Убивает `model_extract.zig:295 [==->!=]` — ветка `or` в вычислителе.
// Мутант `!=` пропустил бы её и вернул неверный ответ.
test "МУТАНТ 295: evalTerm(or true false) = true" {
    var i: usize = 0;
    const v = try evalTerm("(or true false)", &i, &.{}, 0);
    try std.testing.expect(v.boolean);
    var j: usize = 0;
    const w = try evalTerm("(or false false)", &j, &.{}, 0);
    try std.testing.expect(!w.boolean);
    var k: usize = 0;
    const u = try evalTerm("(or false true)", &k, &.{}, 0);
    try std.testing.expect(u.boolean);
}
// =========================================================================
//  ИСПЫТАНИЕ В (--full-file): тесты на ВСЕ выжившие сайты model_extract.zig.
//  Каждый тест проверен ПРИМЕНЕНИЕМ соответствующей мутации.
// =========================================================================

fn ev(s: []const u8) EvalError!Val {
    var i: usize = 0;
    return evalTerm(s, &i, &.{}, 0);
}

// 188 [or->and]: выход за диапазон i64 обязан ловиться (мутант `and` не ловит).
test "МУТАНТ 188: inRange ловит выход за i64" {
    try std.testing.expectError(EvalError.OutOfRange,
        inRange(@as(i128, std.math.maxInt(i64)) + 1));
    try std.testing.expectError(EvalError.OutOfRange,
        inRange(@as(i128, std.math.minInt(i64)) - 1));
    try std.testing.expectEqual(@as(i128, 0), try inRange(0));
}

// 196 [and->or]: SMT `div` округляет ВНИЗ; при нулевом остатке поправки быть НЕ
// должно (мутант `or` вычитает 1 зря).
test "МУТАНТ 196: div при нулевом остатке не поправляется" {
    try std.testing.expectEqual(@as(i128, -2), (try ev("(div (- 4) 2)")).int);
    try std.testing.expectEqual(@as(i128, -4), (try ev("(div (- 7) 2)")).int); // floor, а не trunc
}

// 204 [and->or]: SMT `mod` имеет знак ДЕЛИТЕЛЯ; при нулевом остатке результат 0
// (мутант `or` добавляет делитель к нулю).
test "МУТАНТ 204: mod при нулевом остатке равен 0" {
    try std.testing.expectEqual(@as(i128, 0), (try ev("(mod 4 (- 2))")).int);
    try std.testing.expectEqual(@as(i128, 1), (try ev("(mod (- 7) 2)")).int);
}

// 222 [>=->>]: вход обрывается сразу после оператора -> честный Malformed
// (мутант `>` читает за границей среза).
test "МУТАНТ 222: ПУСТОЙ вход -> Malformed (без чтения за границей)" {
    // Строка 222 — проверка ДО разбора: пустой текст обязан дать Malformed,
    // иначе мутант `>` читает t[0] за границей среза.
    try std.testing.expectError(EvalError.Malformed, ev(""));
    try std.testing.expectError(EvalError.Malformed, ev("   "));
}

// 250 [>=->>]: 9 аргументов не помещаются в буфер на 8 -> Unsupported
// (мутант `>` пишет args[8] за границей массива).
test "МУТАНТ 250: 9 аргументов -> Unsupported" {
    try std.testing.expectError(EvalError.Unsupported, ev("(+ 1 2 3 4 5 6 7 8 9)"));
}

// 261 [==->!=]: унарный минус без аргументов -> Malformed (мутант падает на args[0]).
test "МУТАНТ 261: (-) без аргументов -> Malformed" {
    try std.testing.expectError(EvalError.Malformed, ev("(-)"));
}

// 263 [==->!=]: унарный минус ОБЯЗАН менять знак (мутант возвращает s как есть).
test "МУТАНТ 263: унарный минус меняет знак" {
    try std.testing.expectEqual(@as(i128, -5), (try ev("(- 5)")).int);
}

// 287 [>=->>]: сравнение на ТОЧНОМ равенстве обязано быть истинным.
test "МУТАНТ 287: (>= 5 5) и (<= 5 5) истинны" {
    try std.testing.expect((try ev("(>= 5 5)")).boolean);
    try std.testing.expect((try ev("(<= 5 5)")).boolean);
    try std.testing.expect(!(try ev("(> 5 5)")).boolean);
}

// 299 [!=->==]: `(not X)` с ОДНИМ аргументом обязан вычисляться (мутант -> Malformed).
test "МУТАНТ 299: not с одним аргументом вычисляется" {
    try std.testing.expect((try ev("(not false)")).boolean);
    try std.testing.expect(!(try ev("(not true)")).boolean);
}

// 303 [!=->==]: `ite` с ТРЕМЯ аргументами обязан вычисляться (мутант -> Malformed).
test "МУТАНТ 303: ite с тремя аргументами вычисляется" {
    try std.testing.expectEqual(@as(i128, 1), (try ev("(ite true 1 2)")).int);
    try std.testing.expectEqual(@as(i128, 2), (try ev("(ite false 1 2)")).int);
}

// 318 [or->and]: `assert` в КОНЦЕ текста не должен приводить к чтению за
// границей (мутант `and` не отсекает случай `j >= len`). Проверяем через
// ПУБЛИЧНУЮ точку входа: контракт без валидного `(assert (` не проверяется.
test "МУТАНТ 318: assert в конце текста не падает" {
    const mc = verifyModelAgainstSmt("(assert   ", &.{});
    try std.testing.expect(mc == .ok);
    try std.testing.expectEqual(@as(usize, 0), mc.ok);
}

// Убивает `model_extract.zig:315 [!=->==]`: `(assert(` БЕЗ пробела после слова
// обязан разбираться. Мутант `==` считает такой assert «не тем» и пропускает
// его, поэтому проверенных ассертов становится 0 вместо 1.
test "МУТАНТ 315: assert без пробела после слова разбирается" {
    const b = [_]Binding{.{ .name = "x", .value = "0" }};
    const mc = verifyModelAgainstSmt("(assert(>= x 0))", &b);
    try std.testing.expect(mc == .ok);
    try std.testing.expectEqual(@as(usize, 1), mc.ok);
}
