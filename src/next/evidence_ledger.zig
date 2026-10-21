// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! ЖУРНАЛ СВИДЕТЕЛЬСТВ (Фаза 2): `add` / `retract` / `epoch`.
//!
//! ЗАЧЕМ. Решётка Белнапа монотонна: `⊔` только добавляет информацию, обратной
//! операции у неё НЕТ. Поэтому «отозвать ошибочное свидетельство» нельзя
//! выразить через `joinK` — можно только ПЕРЕСЧИТАТЬ состояние по активному
//! набору вкладов. Этот файл и есть такой пересчёт.
//!
//! ИНВАРИАНТЫ (проверяются тестами):
//!   1. `add` идемпотентен: повторный id не меняет состояние и epoch;
//!   2. `retract` удаляет вклад и ПОЛНОСТЬЮ пересчитывает `(p, n)`;
//!   3. `retract` неизвестного id — no-op (не ошибка, но и не изменение);
//!   4. состояние не зависит от порядка добавления;
//!   5. `epoch` увеличивается только при реальном изменении и только ПОСЛЕ
//!      пересчёта (читатель видит согласованный снимок).

const std = @import("std");

/// Знак вклада: свидетельство «за» или «против».
pub const Sign = enum { positive, negative };

/// Состояние Белнапа, пересчитанное из активного набора вкладов.
pub const State = struct {
    p: bool = false,
    n: bool = false,

    /// `B` только при наличии ОБОИХ свидетельств — это и есть изоляция
    /// противоречия: оно не «затирается» последним вкладом.
    pub fn symbol(self: State) []const u8 {
        if (self.p and self.n) return "B";
        if (self.p) return "T";
        if (self.n) return "F";
        return "N";
    }

    /// Допуск: только чистое `T`. `B` — конфликт, `N` — нет свидетельств.
    pub fn e(self: State) u1 {
        return if (self.p and !self.n) 1 else 0;
    }

    pub fn eq(self: State, other: State) bool {
        return self.p == other.p and self.n == other.n;
    }
};

pub const Ledger = struct {
    allocator: std.mem.Allocator,
    entries: std.StringHashMapUnmanaged(Sign) = .empty,
    epoch: u64 = 0,
    snapshot: State = .{},

    pub fn init(allocator: std.mem.Allocator) Ledger {
        return .{ .allocator = allocator };
    }

    pub fn deinit(self: *Ledger) void {
        var it = self.entries.keyIterator();
        while (it.next()) |k| self.allocator.free(k.*);
        self.entries.deinit(self.allocator);
    }

    /// Добавить вклад. `false` — такой id уже учтён (идемпотентность повторов).
    pub fn add(self: *Ledger, id: []const u8, sign: Sign) !bool {
        if (self.entries.contains(id)) return false;
        const key = try self.allocator.dupe(u8, id);
        errdefer self.allocator.free(key);
        try self.entries.put(self.allocator, key, sign);
        self.recompute();
        return true;
    }

    /// Отозвать вклад. `false` — id неизвестен (no-op, не ошибка).
    pub fn retract(self: *Ledger, id: []const u8) bool {
        const kv = self.entries.fetchRemove(id) orelse return false;
        self.allocator.free(kv.key);
        self.recompute();
        return true;
    }

    /// Пересчёт `(p, n)` по АКТИВНОМУ набору и атомарная публикация.
    pub fn recompute(self: *Ledger) void {
        var s = State{};
        var it = self.entries.valueIterator();
        while (it.next()) |v| switch (v.*) {
            .positive => s.p = true,
            .negative => s.n = true,
        };
        self.snapshot = s;
        self.epoch += 1;
    }

    pub fn state(self: *const Ledger) State {
        return self.snapshot;
    }

    pub fn count(self: *const Ledger) usize {
        return self.entries.count();
    }
};

test "LEDGER: одно свидетельство за -> T, допуск e=1" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    try std.testing.expect(try l.add("test-1", .positive));
    try std.testing.expectEqualStrings("T", l.state().symbol());
    try std.testing.expectEqual(@as(u1, 1), l.state().e());
    try std.testing.expectEqual(@as(u64, 1), l.epoch);
}

test "LEDGER: T + F = B, и противоречие не затирается" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    _ = try l.add("test-1", .positive);
    _ = try l.add("test-2", .negative);
    try std.testing.expectEqualStrings("B", l.state().symbol());
    try std.testing.expectEqual(@as(u1, 0), l.state().e());
    _ = try l.add("test-3", .positive);
    try std.testing.expectEqualStrings("B", l.state().symbol());
}

test "LEDGER: retract(F) снимает конфликт -> T (пересчёт, не вычитание)" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    _ = try l.add("test-1", .positive);
    _ = try l.add("test-2", .negative);
    try std.testing.expect(l.retract("test-2"));
    try std.testing.expectEqualStrings("T", l.state().symbol());
    try std.testing.expectEqual(@as(u1, 1), l.state().e());
}

test "LEDGER: повторный add идемпотентен (epoch не растёт)" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    try std.testing.expect(try l.add("a", .positive));
    const ep = l.epoch;
    try std.testing.expect(!try l.add("a", .positive));
    try std.testing.expectEqual(ep, l.epoch);
    try std.testing.expectEqual(@as(usize, 1), l.count());
}

test "LEDGER: retract неизвестного id — no-op, не ошибка" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    _ = try l.add("a", .positive);
    const ep = l.epoch;
    try std.testing.expect(!l.retract("nope"));
    try std.testing.expectEqual(ep, l.epoch);
    try std.testing.expectEqualStrings("T", l.state().symbol());
}

test "LEDGER: состояние не зависит от порядка добавления" {
    var a = Ledger.init(std.testing.allocator);
    defer a.deinit();
    var b = Ledger.init(std.testing.allocator);
    defer b.deinit();
    _ = try a.add("x", .positive);
    _ = try a.add("y", .negative);
    _ = try b.add("y", .negative);
    _ = try b.add("x", .positive);
    try std.testing.expect(a.state().eq(b.state()));
    try std.testing.expectEqual(a.epoch, b.epoch);
}

test "LEDGER: retract всех вкладов возвращает N (а не F)" {
    var l = Ledger.init(std.testing.allocator);
    defer l.deinit();
    _ = try l.add("a", .negative);
    try std.testing.expectEqualStrings("F", l.state().symbol());
    _ = l.retract("a");
    try std.testing.expectEqualStrings("N", l.state().symbol());
    try std.testing.expectEqual(@as(u1, 0), l.state().e());
}
