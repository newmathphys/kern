// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ЛОГИЧЕСКИЙ СТРЕСС-СЬЮТ Z3-моста (без моделей, чистая логика).
//!
//! Проверяет: парадоксы (UNSAT-ядро), overflow (QF_BV), нелинейную
//! арифметику (NIA), мёртвые ветки, Alive2-пары оптимизаций.
//! Запуск: PATH=".venv/bin:$PATH" zig run src/smt_stress.zig -O ReleaseFast
const std = @import("std");
const compat = @import("compat");
const z3b = @import("verifier/z3_bridge.zig");

const Kind = enum { proved, refuted, vacuous, unknown };

const Case = struct {
    name: []const u8,
    decls: []const u8,
    pre: []const u8,
    post: []const u8,
    expect: Kind,
};

const CASES = [_]Case{
    // --- ПАРАДОКС: предусловие невыполнимо -> ВАКУУМ (не доказательство) ---
    .{ .name = "Парадокс: pre = (x>5 ∧ x<2)", .expect = .vacuous,
       .decls = "(declare-const x Int)", .pre = "(and (> x 5) (< x 2))", .post = "(= x 0)" },
    // --- OVERFLOW: 32-бит, x+1 > x ложно при x=MAX ---
    .{ .name = "Overflow: x+1 > x (i32)", .expect = .refuted,
       .decls = "(declare-const x (_ BitVec 32))",
       .pre = "true", .post = "(bvugt (bvadd x #x00000001) x)" },
    // --- OVERFLOW (математика без границ): x+1 > x истинно ---
    .{ .name = "Int (без границ): x+1 > x", .expect = .proved,
       .decls = "(declare-const x Int)", .pre = "true", .post = "(> (+ x 1) x)" },
    // --- НЕЛИНЕЙНАЯ (NIA): x*x >= 0 ---
    .{ .name = "NIA: x*x >= 0", .expect = .proved,
       .decls = "(declare-const x Int)", .pre = "true", .post = "(>= (* x x) 0)" },
    // --- Alive2: x*8 == x<<3 (u32) ---
    .{ .name = "Alive2: x*8 == x<<3 (u32)", .expect = .proved,
       .decls = "(declare-const x (_ BitVec 32))",
       .pre = "true", .post = "(= (bvmul x #x00000008) (bvshl x #x00000003))" },
    // --- Alive2 (ложная): x/2 == x>>1 для ЗНАКОВЫХ -> контрпример x=-1 ---
    .{ .name = "Alive2(ложная): x/2 == x>>1 знаковое", .expect = .refuted,
       .decls = "(declare-const x (_ BitVec 32))",
       .pre = "true", .post = "(= (bvsdiv x #x00000002) (bvashr x #x00000001))" },
    // --- МЁРТВАЯ ВЕТКА: x*x < 0 недостижимо -> pre вакуумно ---
    .{ .name = "Мёртвая ветка: pre = (x*x < 0)", .expect = .vacuous,
       .decls = "(declare-const x Int)", .pre = "(< (* x x) 0)", .post = "false" },
    // --- КОРРЕКТНЫЙ контракт ---
    .{ .name = "Контракт: x>0 => x+1>1", .expect = .proved,
       .decls = "(declare-const x Int)", .pre = "(> x 0)", .post = "(> (+ x 1) 1)" },
    // --- НЕВЕРНЫЙ контракт ---
    .{ .name = "Контракт(ложный): x>0 => x+1>5", .expect = .refuted,
       .decls = "(declare-const x Int)", .pre = "(> x 0)", .post = "(> (+ x 1) 5)" },
    // --- СВЕРХШИРОКИЙ BitVec(1024): нет тихого усечения до u64 ---
    .{ .name = "BitVec(1024): x*2 == x<<1 (нет усечения)", .expect = .proved,
       .decls = "(declare-const x (_ BitVec 1024))",
       .pre = "true", .post = "(= (bvmul x (_ bv2 1024)) (bvshl x (_ bv1 1024)))" },
    // --- BitVec(1024): коммутативность сложения (ширина не теряется) ---
    .{ .name = "BitVec(1024): x+1 == 1+x", .expect = .proved,
       .decls = "(declare-const x (_ BitVec 1024))",
       .pre = "true", .post = "(= (bvadd x (_ bv1 1024)) (bvadd (_ bv1 1024) x))" },
    // --- BitVec(1024): ложное утверждение -> контрпример (старшие биты учитываются) ---
    .{ .name = "BitVec(1024): x+1 == x (ЛОЖНО)", .expect = .refuted,
       .decls = "(declare-const x (_ BitVec 1024))",
       .pre = "true", .post = "(= (bvadd x (_ bv1 1024)) x)" },
    // --- FLOAT (QF_FP): SMT-LIB `=` — НЕ IEEE-равенство! Для IEEE нужен `fp.eq`.
    // (эти ожидания ИСПРАВЛЕНЫ по факту ответов Z3 — он был прав, я ошибался)
    .{ .name = "FP: `=` рефлексивно даже для NaN (SMT-семантика)", .expect = .proved,
       .decls = "(declare-const x Float32)",
       .pre = "true", .post = "(= x x)" },
    .{ .name = "FP: fp.eq(x,x) ЛОЖНО для NaN (IEEE)", .expect = .refuted,
       .decls = "(declare-const x Float32)",
       .pre = "true", .post = "(fp.eq x x)" },
    .{ .name = "FP: fp.eq(-0.0, +0.0) ИСТИННО (IEEE)", .expect = .proved,
       .decls = "",
       .pre = "true", .post = "(fp.eq (_ -zero 8 24) (_ +zero 8 24))" },
    .{ .name = "FP: `=` различает -0.0 и +0.0 (битовые шаблоны)", .expect = .refuted,
       .decls = "",
       .pre = "true", .post = "(= (_ -zero 8 24) (_ +zero 8 24))" },
    .{ .name = "FP: x + 0.0 == x ЛОЖНО (контрпример -0.0)", .expect = .refuted,
       .decls = "(declare-const x Float32)",
       .pre = "true", .post = "(= (fp.add RNE x (_ +zero 8 24)) x)" },
    // --- ДЕЛЕНИЕ НА НОЛЬ: SMT-LIB определяет его; транслятор НЕ должен падать ---
    .{ .name = "Деление на ноль: (= (div x 0) x) — SMT определён", .expect = .refuted,
       .decls = "(declare-const x Int)",
       .pre = "true", .post = "(= (div x 0) x)" },
};

pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует setIo() до первого вызова.
    compat.setIo(init.io);
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    var bridge = z3b.Z3Bridge.init(alloc);

    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) {
        std.debug.print("[!] z3 недоступен: добавьте .venv/bin в PATH\n", .{});
        return;
    }

    std.debug.print("🔬 ЛОГИЧЕСКИЙ СТРЕСС Z3-моста ({} кейсов)\n\n", .{CASES.len});
    var ok_n: usize = 0;
    var timer = compat.Timer.start();

    std.debug.print("{s:<40} | {s:<9} | {s:<9} | {s}\n", .{ "Кейс", "получено", "ожидалось", "" });
    std.debug.print("{s:-<40}-+-{s:-<9}-+-{s:-<9}-+-{s:-<8}\n", .{ "", "", "", "" });

    for (CASES) |c| {
        const proved = try bridge.verifyContract(c.decls, c.pre, c.post);
        // Различаем «вакуум» (pre невыполним) и «контрпример»:
        const kind: Kind = blk: {
            if (proved) break :blk .proved;
            const inhab = bridge.executeQuery(try std.fmt.allocPrint(alloc, "(set-logic ALL)\n{s}\n(assert {s})\n(check-sat)\n", .{ c.decls, c.pre }));
            if (inhab.witness_model) |w| alloc.free(w);
            if (inhab.status != .Sat) break :blk .vacuous;
            break :blk .refuted;
        };
        const match = (kind == c.expect);
        if (match) ok_n += 1;
        std.debug.print("{s:<40} | {s:<9} | {s:<9} | {s}\n", .{
            c.name, @tagName(kind), @tagName(c.expect),
            if (match) "✅" else "❌",
        });
    }
    const ns = timer.read();
    std.debug.print("\n=== ИТОГ: {d}/{d} совпало за {d:.1} мс ===\n", .{ ok_n, CASES.len, @as(f64, @floatFromInt(ns)) / 1e6 });
}
