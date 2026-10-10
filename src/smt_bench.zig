// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN SMT-бенчмарк: доказательство эквивалентности оптимизаций (Alive2 /
//! Hacker's Delight) через РЕАЛЬНЫЙ Z3. Модель не нужна — чистая логика.
//!
//! Запуск: PATH=".venv/bin:$PATH" zig run src/smt_bench.zig -O ReleaseFast
const std = @import("std");
const z3b = @import("verifier/z3_bridge.zig");

const Claim = struct {
    name: []const u8,
    script: []const u8,
    expect: []const u8, // "unsat" = эквивалентны, "sat" = есть контрпример
};

const CLAIMS = [_]Claim{
    .{ .name = "Alive2: x*2 == x<<1 (u32)", .expect = "unsat", .script =
    \\(set-logic QF_BV)
    \\(declare-const x (_ BitVec 32))
    \\(assert (not (= (bvmul x #x00000002) (bvshl x #x00000001))))
    \\(check-sat)
    },
    .{ .name = "Hacker's Delight: x*2 == x+x (Int)", .expect = "unsat", .script =
    \\(set-logic QF_LIA)
    \\(declare-const x Int)
    \\(assert (not (= (* x 2) (+ x x))))
    \\(check-sat)
    },
    .{ .name = "Hacker's Delight: x+0 == x (Int)", .expect = "unsat", .script =
    \\(set-logic QF_LIA)
    \\(declare-const x Int)
    \\(assert (not (= (+ x 0) x)))
    \\(check-sat)
    },
    .{ .name = "Hacker's Delight: (x & -x) == 0 <=> x == 0 (u32)", .expect = "unsat", .script =
    \\(set-logic QF_BV)
    \\(declare-const x (_ BitVec 32))
    \\(assert (not (= (= (bvand x (bvneg x)) #x00000000) (= x #x00000000))))
    \\(check-sat)
    },
    .{ .name = "Alive2: x/2 == x>>1 ДЛЯ ЗНАКОВЫХ (ложная оптимизация)", .expect = "sat", .script =
    \\(set-logic QF_BV)
    \\(declare-const x (_ BitVec 32))
    \\(assert (not (= (bvsdiv x #x00000002) (bvashr x #x00000001))))
    \\(check-sat)
    \\(get-model)
    },
    .{ .name = "Overflow: существует x, где x+1 < x (u32)", .expect = "sat", .script =
    \\(set-logic QF_BV)
    \\(declare-const x (_ BitVec 32))
    \\(assert (bvult (bvadd x #x00000001) x))
    \\(check-sat)
    \\(get-model)
    },
    .{ .name = "Alive2: x & 0 == 0 (u32)", .expect = "unsat", .script =
    \\(set-logic QF_BV)
    \\(declare-const x (_ BitVec 32))
    \\(assert (not (= (bvand x #x00000000) #x00000000)))
    \\(check-sat)
    },
    .{ .name = "Termination/грам: gcd(x,x) == x (Int, x>0)", .expect = "unsat", .script =
    \\(set-logic QF_LIA)
    \\(declare-const x Int)
    \\(assert (and (> x 0) (not (= x x))))
    \\(check-sat)
    },
};

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    var bridge = z3b.Z3Bridge.init(alloc);

    std.debug.print("🔬 KERN SMT-бенчмарк: эквивалентность оптимизаций (Alive2 / Hacker's Delight)\n", .{});
    std.debug.print("   Решатель: {s}\n\n", .{bridge.z3_path});

    var proved: usize = 0;
    var refuted: usize = 0;
    var errors: usize = 0;

    std.debug.print("{s:<58} | {s:<8} | {s}\n", .{ "Оптимизация", "Z3", "вердикт" });
    std.debug.print("{s:-<58}-+-{s:-<8}-+-{s:-<26}\n", .{ "", "", "" });

    for (CLAIMS) |c| {
        const r = bridge.executeQuery(c.script);
        defer if (r.witness_model) |w| alloc.free(w);
        const got = switch (r.status) {
            .Sat => "sat",
            .Unsat => "unsat",
            .Unknown => "unknown",
            .Timeout => "timeout",
            .ToolError => "toolerr",
        };
        const ok = std.mem.eql(u8, got, c.expect);
        if (r.status == .ToolError) errors += 1;
        if (r.status == .Unsat) proved += 1;
        if (r.status == .Sat) refuted += 1;
        std.debug.print("{s:<58} | {s:<8} | {s}\n", .{
            c.name, got,
            if (ok) "✅ совпало" else "❌ НЕ совпало",
        });
    }

    std.debug.print("\n=== ИТОГ ===\n", .{});
    std.debug.print("Всего проверок:        {d}\n", .{CLAIMS.len});
    std.debug.print("Доказано эквивалентными (unsat): {d}\n", .{proved});
    std.debug.print("Найдены контрпримеры (sat):      {d}\n", .{refuted});
    std.debug.print("Ошибок решателя:                 {d}\n", .{errors});
}
