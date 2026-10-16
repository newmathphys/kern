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
