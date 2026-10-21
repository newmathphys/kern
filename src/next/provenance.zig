// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! ТРИ ГРАФА ПРОИСХОЖДЕНИЯ (Фаза 2): `G_src`, `G_build`, `G_prov`.
//!
//! ЗАЧЕМ. Один смешанный «граф зависимостей» не отвечает на вопрос «откуда
//! это взялось». Здесь три проекции, и у каждой свои правила:
//!   `G_src`   — импорты и вызовы исходников: ЦИКЛЫ РАЗРЕШЕНЫ (модули бывают
//!               взаимными), но отрицательный рекурсивный цикл запрещён;
//!   `G_build` — артефакты и шаги сборки: ребро «шаг -> артефакт»;
//!   `G_prov`  — только добавление свидетельств (append-only), без циклов.
//!
//! Почему запрещён именно ОТРИЦАТЕЛЬНЫЙ цикл: `f` зависит от `g`, `g` — от
//! `not f` — это не «взаимная зависимость», а противоречивое определение
//! (в терминах B4 — `B`, которое нельзя разрешить). Такой граф отвергается.
//!
//! Реализация проверки — Косараju (два прохода DFS, итеративно, без рекурсии:
//! глубина стека не зависит от размера графа).

const std = @import("std");

pub const GraphKind = enum { g_src, g_build, g_prov };

/// `negated` — ребро, проходящее через отрицание (`not f`, `!x`).
pub const EdgeKind = enum { import, build, proof, negated };

pub const Edge = struct {
    from: u32,
    to: u32,
    kind: EdgeKind = .import,
};

pub const Graph = struct {
    kind: GraphKind,
    nodes: []const []const u8,
    edges: []const Edge,
};

pub const ProvenanceError = error{ NegativeRecursiveCycle, OutOfMemory };

/// Есть ли отрицательное ребро внутри сильно связной компоненты.
pub fn hasNegativeRecursiveCycle(g: Graph, allocator: std.mem.Allocator) !bool {
    const n: usize = g.nodes.len;
    if (n == 0 or g.edges.len == 0) return false;

    // CSR-представление: adj (прямой) и radj (обратный).
    var out_deg = try allocator.alloc(u32, n + 1);
    defer allocator.free(out_deg);
    var in_deg = try allocator.alloc(u32, n + 1);
    defer allocator.free(in_deg);
    @memset(out_deg, 0);
    @memset(in_deg, 0);
    for (g.edges) |e| {
        if (e.from >= n or e.to >= n) continue;
        out_deg[e.from + 1] += 1;
        in_deg[e.to + 1] += 1;
    }
    for (1..n + 1) |i| {
        out_deg[i] += out_deg[i - 1];
        in_deg[i] += in_deg[i - 1];
    }
    var adj = try allocator.alloc(u32, g.edges.len);
    defer allocator.free(adj);
    var radj = try allocator.alloc(u32, g.edges.len);
    defer allocator.free(radj);
    var of = try allocator.dupe(u32, out_deg);
    defer allocator.free(of);
    var inf = try allocator.dupe(u32, in_deg);
    defer allocator.free(inf);
    for (g.edges) |e| {
        if (e.from >= n or e.to >= n) continue;
        adj[of[e.from]] = e.to;
        of[e.from] += 1;
        radj[inf[e.to]] = e.from;
        inf[e.to] += 1;
    }

    // Проход 1: порядок выхода (post-order) по прямому графу.
    var visited = try allocator.alloc(bool, n);
    defer allocator.free(visited);
    @memset(visited, false);
    var order = std.ArrayListUnmanaged(u32).empty;
    defer order.deinit(allocator);
    var stack = try allocator.alloc(u32, n);
    defer allocator.free(stack);
    var cursor = try allocator.alloc(u32, n);
    defer allocator.free(cursor);
    @memset(cursor, 0);

    for (0..n) |start| {
        if (visited[start]) continue;
        var sp: usize = 0;
        stack[sp] = @intCast(start);
        sp += 1;
        visited[start] = true;
        cursor[start] = out_deg[start];
        while (sp > 0) {
            const v = stack[sp - 1];
            var pushed = false;
            while (cursor[v] < out_deg[v + 1]) {
                const to = adj[cursor[v]];
                cursor[v] += 1;
                if (!visited[to]) {
                    visited[to] = true;
                    cursor[to] = out_deg[to];
                    stack[sp] = to;
                    sp += 1;
                    pushed = true;
                    break;
                }
            }
            if (!pushed) {
                try order.append(allocator, v);
                sp -= 1;
            }
        }
    }

    // Проход 2: компоненты по ОБРАТНОМУ графу в обратном порядке выхода.
    const NO_COMP: u32 = 0xFFFF_FFFF;
    var comp = try allocator.alloc(u32, n);
    defer allocator.free(comp);
    @memset(comp, NO_COMP);
    var next_comp: u32 = 0;
    var i: usize = order.items.len;
    while (i > 0) {
        i -= 1;
        const root = order.items[i];
        if (comp[root] != NO_COMP) continue;
        var sp: usize = 0;
        stack[sp] = root;
        sp += 1;
        comp[root] = next_comp;
        while (sp > 0) {
            const v = stack[sp - 1];
            sp -= 1;
            var e = in_deg[v];
            while (e < in_deg[v + 1]) : (e += 1) {
                const to = radj[e];
                if (comp[to] == NO_COMP) {
                    comp[to] = next_comp;
                    stack[sp] = to;
                    sp += 1;
                }
            }
        }
        next_comp += 1;
    }

    for (g.edges) |e| {
        if (e.from >= n or e.to >= n) continue;
        if (e.kind != .negated) continue;
        // Отрицательное ребро внутри SCC: в SCC есть путь to -> from,
        // значит ребро лежит на цикле, проходящем через отрицание.
        if (comp[e.from] == comp[e.to]) return true;
    }
    return false;
}


/// Проверка графа: отрицательный рекурсивный цикл — ошибка.
pub fn check(g: Graph, allocator: std.mem.Allocator) !void {
    if (try hasNegativeRecursiveCycle(g, allocator))
        return ProvenanceError.NegativeRecursiveCycle;
}

test "G_src: положительный цикл f->g->f допустим" {
    const nodes = [_][]const u8{ "f", "g" };
    const edges = [_]Edge{
        .{ .from = 0, .to = 1 },
        .{ .from = 1, .to = 0 },
    };
    const g = Graph{ .kind = .g_src, .nodes = &nodes, .edges = &edges };
    try std.testing.expect(!try hasNegativeRecursiveCycle(g, std.testing.allocator));
    try check(g, std.testing.allocator);
}

test "G_src: ОТРИЦАТЕЛЬНЫЙ рекурсивный цикл f->g->not f отвергается" {
    const nodes = [_][]const u8{ "f", "g" };
    const edges = [_]Edge{
        .{ .from = 0, .to = 1, .kind = .import },
        .{ .from = 1, .to = 0, .kind = .negated },
    };
    const g = Graph{ .kind = .g_src, .nodes = &nodes, .edges = &edges };
    try std.testing.expect(try hasNegativeRecursiveCycle(g, std.testing.allocator));
    try std.testing.expectError(ProvenanceError.NegativeRecursiveCycle,
        check(g, std.testing.allocator));
}

test "G_src: отрицательное ребро ВНЕ цикла допустимо" {
    const nodes = [_][]const u8{ "a", "b" };
    const edges = [_]Edge{.{ .from = 0, .to = 1, .kind = .negated }};
    const g = Graph{ .kind = .g_src, .nodes = &nodes, .edges = &edges };
    try std.testing.expect(!try hasNegativeRecursiveCycle(g, std.testing.allocator));
}

test "G_src: self-loop с отрицанием отвергается (f = not f)" {
    const nodes = [_][]const u8{"f"};
    const edges = [_]Edge{.{ .from = 0, .to = 0, .kind = .negated }};
    const g = Graph{ .kind = .g_src, .nodes = &nodes, .edges = &edges };
    try std.testing.expectError(ProvenanceError.NegativeRecursiveCycle,
        check(g, std.testing.allocator));
}

test "G_src: отрицание МЕЖДУ разными SCC не является циклом" {
    const nodes = [_][]const u8{ "a", "b", "c" };
    const edges = [_]Edge{
        .{ .from = 0, .to = 1, .kind = .negated },
        .{ .from = 1, .to = 2 },
    };
    const g = Graph{ .kind = .g_src, .nodes = &nodes, .edges = &edges };
    try std.testing.expect(!try hasNegativeRecursiveCycle(g, std.testing.allocator));
}

test "G_build и G_prov проверяются теми же правилами" {
    const nodes = [_][]const u8{ "kernc", "libkern" };
    const edges = [_]Edge{
        .{ .from = 0, .to = 1, .kind = .build },
        .{ .from = 1, .to = 0, .kind = .negated },
    };
    for ([_]GraphKind{ .g_build, .g_prov }) |k| {
        const g = Graph{ .kind = k, .nodes = &nodes, .edges = &edges };
        try std.testing.expect(try hasNegativeRecursiveCycle(g, std.testing.allocator));
    }
}
