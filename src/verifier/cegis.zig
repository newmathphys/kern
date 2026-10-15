// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: CEGIS — СИНТЕЗ ПРОГРАММ ПО СПЕЦИФИКАЦИИ (вектор 4 / SyGuS).
//!
//! KERN перестаёт быть только судьёй и становится СОЗДАТЕЛЕМ кода.
//! Парадигма Counterexample-Guided Inductive Synthesis:
//!
//!   1. Кандидат берётся из грамматики (пространство поиска);
//!   2. Z3 проверяет `¬∃x. cand(x) ≠ spec(x)`;
//!   3. `unsat` → кандидат ЭКВИВАЛЕНТЕН спецификации на ВСЕЙ области → НАЙДЕН;
//!      `sat`  → Z3 выдаёт КОНТРПРИМЕР (конкретный x), кандидат отбраковывается;
//!   4. цикл повторяется для следующего кандидата.
//!
//! Ключевое: финальный вердикт даёт МАТЕМАТИКА (Z3), а не тесты. Найденное
//! выражение доказано эквивалентным для всех 2^32 входов, а не для выборки.
//!
//! Где применяем: замена наивного кода оптимизированным (Hacker's Delight),
//! автопочинка (Program Repair), генерация тела функции по постусловию.
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const Outcome = struct {
    found: bool,
    expr: []u8, // во владении вызывающего (пустая строка, если не найдено)
    tried: usize,
    counterexamples: usize,

    pub fn deinit(self: *Outcome, allocator: std.mem.Allocator) void {
        allocator.free(self.expr);
    }
};

pub const CegisEngine = struct {
    allocator: std.mem.Allocator,
    bridge: *z3.Z3Bridge,

    pub fn init(allocator: std.mem.Allocator, bridge: *z3.Z3Bridge) CegisEngine {
        return .{ .allocator = allocator, .bridge = bridge };
    }

    /// Проверка эквивалентности кандидата и спецификации на ВСЕЙ области.
    /// `unsat` = эквивалентны (доказано); `sat` = есть контрпример.
    pub fn verifyEquivalence(
        self: *CegisEngine,
        decls: []const u8,
        cand: []const u8,
        spec: []const u8,
    ) z3.SmtStatus {
        const q = std.fmt.allocPrint(self.allocator,
            \\(set-logic QF_BV)
            \\{s}
            \\(assert (not (= {s} {s})))
            \\(check-sat)
            \\
        , .{ decls, cand, spec }) catch return .ToolError;
        defer self.allocator.free(q);
        return self.bridge.executeQuery(q).status;
    }

    /// Обобщённый синтез: перебор грамматики с Z3-верификацией каждого
    /// кандидата. Контрпример от Z3 подтверждает отбраковку (CEGIS-стиль).
    pub fn synthesize(
        self: *CegisEngine,
        decls: []const u8,
        spec: []const u8,
        grammar: []const []const u8,
    ) !Outcome {
        var tried: usize = 0;
        var cex: usize = 0;
        for (grammar) |cand| {
            tried += 1;
            const st = self.verifyEquivalence(decls, cand, spec);
            switch (st) {
                .Unsat => return .{
                    .found = true,
                    .expr = try self.allocator.dupe(u8, cand),
                    .tried = tried,
                    .counterexamples = cex,
                },
                .Sat => cex += 1, // контрпример: кандидат отбракован
                else => {},
            }
        }
        return .{
            .found = false,
            .expr = try self.allocator.dupe(u8, ""),
            .tried = tried,
            .counterexamples = cex,
        };
    }

    /// Частный, но самый показательный случай: синтез сдвига.
    /// Найти k ∈ [0,31], такое что `x << k == x * mul` для ВСЕХ x : u32.
    /// Спецификация `x * 8` — это оптимизация `x << 3` (Hacker's Delight).
    pub fn synthesizeShiftMul(self: *CegisEngine, mul: u64) !Outcome {
        var buf: [32][]u8 = undefined;
        var made: usize = 0;
        defer for (buf[0..made]) |s| self.allocator.free(s);

        var spec_buf: [64]u8 = undefined;
        const spec = try std.fmt.bufPrint(&spec_buf, "(bvmul x (_ bv{d} 32))", .{mul});

        var k: usize = 0;
        while (k < 32) : (k += 1) {
            buf[made] = try std.fmt.allocPrint(self.allocator, "(bvshl x (_ bv{d} 32))", .{k});
            made += 1;
        }
        return self.synthesize("(declare-const x (_ BitVec 32))", spec, buf[0..made]);
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "CEGIS (РЕАЛЬНЫЙ Z3): x*8 ≡ x<<3 доказано на ВСЕЙ области (unsat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = CegisEngine.init(std.testing.allocator, &bridge);
    const st = eng.verifyEquivalence(
        "(declare-const x (_ BitVec 32))",
        "(bvshl x (_ bv3 32))",
        "(bvmul x (_ bv8 32))",
    );
    try std.testing.expectEqual(z3.SmtStatus.Unsat, st);
}

test "CEGIS (РЕАЛЬНЫЙ Z3): x*8 ≢ x<<2 — контрпример найден (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = CegisEngine.init(std.testing.allocator, &bridge);
    const st = eng.verifyEquivalence(
        "(declare-const x (_ BitVec 32))",
        "(bvshl x (_ bv2 32))",
        "(bvmul x (_ bv8 32))",
    );
    try std.testing.expectEqual(z3.SmtStatus.Sat, st);
}

test "CEGIS (РЕАЛЬНЫЙ Z3): СИНТЕЗ x*8 → найдено (bvshl x 3)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = CegisEngine.init(std.testing.allocator, &bridge);
    var out = try eng.synthesizeShiftMul(8);
    defer out.deinit(std.testing.allocator);
    try std.testing.expect(out.found);
    try std.testing.expectEqualStrings("(bvshl x (_ bv3 32))", out.expr);
    // K=0,1,2 отбракованы контрпримерами; K=3 доказан.
    try std.testing.expectEqual(@as(usize, 4), out.tried);
    try std.testing.expectEqual(@as(usize, 3), out.counterexamples);
}

test "CEGIS (РЕАЛЬНЫЙ Z3): СИНТЕЗ x*16 → найдено (bvshl x 4)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = CegisEngine.init(std.testing.allocator, &bridge);
    var out = try eng.synthesizeShiftMul(16);
    defer out.deinit(std.testing.allocator);
    try std.testing.expect(out.found);
    try std.testing.expectEqualStrings("(bvshl x (_ bv4 32))", out.expr);
}

test "CEGIS (РЕАЛЬНЫЙ Z3): x*3 невыразим сдвигом → НЕ найдено (честный отказ)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = CegisEngine.init(std.testing.allocator, &bridge);
    var out = try eng.synthesizeShiftMul(3);
    defer out.deinit(std.testing.allocator);
    // 3 не степень двойки => сдвиг невозможен. KERN честно сообщает «не найдено».
    try std.testing.expect(!out.found);
    try std.testing.expectEqual(@as(usize, 32), out.tried);
}
