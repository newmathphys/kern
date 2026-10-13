// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: БЕНЧМАРК ИНВАРИАНТОВ ЦИКЛОВ (CHC / Horn Clauses).
//!
//! Классические циклы (стиль SV-COMP `loop-lit` / TermCOMP) кодируются
//! системой Horn-ограничений и отдаются Z3 SPACER. Решатель СИНТЕЗИРУЕТ
//! индуктивный инвариант — БЕЗ разворачивания цикла.
//!
//! Соглашение (CHC-COMP): `sat` = инвариант найден (свойство ДОКАЗАНО);
//! `unsat` = инварианта нет (БАГ достижим); иначе — не справился.
//!
//! Запуск: `zig run src/chc_bench.zig -O ReleaseFast` (нужен z3 в PATH).
const std = @import("std");
const z3 = @import("verifier/z3_bridge.zig");
const chc = @import("verifier/chc.zig");

const Case = struct {
    name: []const u8,
    init: []const u8,
    guard: []const u8,
    step: []const u8,
    post: []const u8,
    expect: z3.SmtStatus,
};

const CASES = [_]Case{
    .{ .name = "sum: x:=0; while(x<10) x++      => x>=10", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 1)", .post = "(>= x 10)", .expect = .Sat },
    .{ .name = "exact: x:=0; while(x<10) x++    => x=10", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 1)", .post = "(= x 10)", .expect = .Sat },
    .{ .name = "countdown: x:=10; while(x>0) x-- => x<=0", .init = "(= x 10)", .guard = "(> x 0)", .step = "(- x 1)", .post = "(<= x 0)", .expect = .Sat },
    .{ .name = "stride2: x:=0; while(x<10) x+=2  => x>=10", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 2)", .post = "(>= x 10)", .expect = .Sat },
    .{ .name = "stride3: x:=0; while(x<10) x+=3  => x>=10", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 3)", .post = "(>= x 10)", .expect = .Sat },
    .{ .name = "doubling: x:=1; while(x<1000) x*=2 => x>=1000", .init = "(= x 1)", .guard = "(< x 1000)", .step = "(* x 2)", .post = "(>= x 1000)", .expect = .Sat },
    .{ .name = "parity: x:=0; while(x<10) x+=2     => x чётно", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 2)", .post = "(= (mod x 2) 0)", .expect = .Sat },
    .{ .name = "bound: x:=0; while(x<10) x++     => x<=10", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 1)", .post = "(<= x 10)", .expect = .Sat },
    // БАГИ: инварианта не существует — контрпример достижим.
    .{ .name = "БАГ: x:=0; while(x<10) x++      => x<5", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 1)", .post = "(< x 5)", .expect = .Unsat },
    .{ .name = "БАГ: x:=0; while(x<10) x+=2     => x=11", .init = "(= x 0)", .guard = "(< x 10)", .step = "(+ x 2)", .post = "(= x 11)", .expect = .Unsat },
    .{ .name = "БАГ: countdown x:=10; while(x>0) x-- => x=1", .init = "(= x 10)", .guard = "(> x 0)", .step = "(- x 1)", .post = "(= x 1)", .expect = .Unsat },
};

pub fn main() !void {
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    var bridge = z3.Z3Bridge.init(alloc);
    bridge.timeout_ms = 15000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) {
        std.debug.print("[!] z3 недоступен. Добавьте .venv/bin в PATH.\n", .{});
        return;
    }
    var eng = chc.ChcEngine.init(alloc);

    std.debug.print("=== KERN CHC-БЕНЧМАРК: инварианты циклов (Z3 SPACER) ===\n\n", .{});
    var pass: usize = 0;
    var total_ms: u64 = 0;
    for (CASES) |c| {
        var timer = try std.time.Timer.start();
        const st = eng.proveLoopSafety(&bridge, c.init, c.guard, c.step, c.post);
        const ms = timer.read() / std.time.ns_per_ms;
        total_ms += ms;
        const ok = st == c.expect;
        if (ok) pass += 1;
        const verdict = switch (st) {
            .Sat => "ДОКАЗАНО (инвариант найден)",
            .Unsat => "БАГ (инварианта нет)",
            .Unknown => "не справился",
            .Timeout => "таймаут",
            .ToolError => "ошибка тула",
        };
        std.debug.print("{s} {s:<52} {s:>28}  [{d} мс]\n", .{
            if (ok) "OK  " else "FAIL",
            c.name,
            verdict,
            ms,
        });
    }
    std.debug.print("\n=== ИТОГ: {d}/{d} совпало с ожиданием; суммарно {d} мс ===\n", .{ pass, CASES.len, total_ms });
}
