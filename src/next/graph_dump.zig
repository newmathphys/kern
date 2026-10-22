// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! `kernx graph --json` (Ф2): ЕДИНЫЙ источник графа исходников `G_src`.
//!
//! ЗАЧЕМ. Витрина (Эго-Линза, матрица фильтров) строилась Python-сканером
//! `tools/gen_showcase_graph.py`, а ядро о графе не знало. Два сканера одного
//! и того же = два расходящихся графа. Теперь граф считает ядро, а Python
//! только проверяет совпадение (`make graph-check`).
//!
//! Что считается (всё — измерения, не догадки):
//!   loc            — число строк файла;
//!   pub_fn         — число `pub fn`;
//!   tests          — число `test "`;
//!   kern           — число аннотаций `@kern:`;
//!   imports_out    — число РАЗНЫХ целей `@import("...")` внутри `src/`.
//!
//! Схема вывода совпадает с `docs/showcase-graph.json` по ключам узлов/рёбер,
//! чтобы паритет проверялся без перекодирования.

const std = @import("std");
const compat = @import("compat");

pub const Node = struct {
    id: []const u8,
    loc: usize,
    pub_fn: usize,
    tests: usize,
    kern: usize,
    imports_out: usize,
};

pub const Edge = struct { source: []const u8, target: []const u8 };

fn baseName(path: []const u8) []const u8 {
    if (std.mem.lastIndexOfScalar(u8, path, '/')) |i| return path[i + 1 ..];
    return path;
}

fn countOccurrences(haystack: []const u8, needle: []const u8) usize {
    var n: usize = 0;
    var i: usize = 0;
    while (std.mem.indexOfPos(u8, haystack, i, needle)) |p| {
        n += 1;
        i = p + needle.len;
    }
    return n;
}

fn dirName(path: []const u8) []const u8 {
    if (std.mem.lastIndexOfScalar(u8, path, '/')) |i| return path[0..i];
    return "";
}

/// Именованные модули (как в build.zig): `@import("compat")`.
fn namedModule(spec: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, spec, "compat")) return "compat.zig";
    if (std.mem.eql(u8, spec, "owner")) return "owner.zig";
    if (std.mem.eql(u8, spec, "atomic")) return "atomic_write.zig";
    return null;
}

/// `verifier` + `../core/eq2.zig` -> `core/eq2.zig`; `next` + `truth.zig` -> `next/truth.zig`.
fn resolveImport(alloc: std.mem.Allocator, base_dir: []const u8, spec: []const u8) ![]const u8 {
    if (namedModule(spec)) |rooted| return rooted;
    if (!std.mem.startsWith(u8, spec, ".")) return "";
    var parts = std.ArrayListUnmanaged([]const u8).empty;
    var it = std.mem.splitScalar(u8, base_dir, '/');
    while (it.next()) |seg| if (seg.len > 0) try parts.append(alloc, seg);
    var sit = std.mem.splitScalar(u8, spec, '/');
    while (sit.next()) |seg| {
        if (seg.len == 0 or std.mem.eql(u8, seg, ".")) continue;
        if (std.mem.eql(u8, seg, "..")) {
            if (parts.items.len > 0) _ = parts.pop();
            continue;
        }
        try parts.append(alloc, seg);
    }
    if (parts.items.len == 0) return "";
    return std.mem.join(alloc, "/", parts.items);
}

/// Собрать `(nodes, edges, external)` по каталогу `root` (обычно `src`).
///
/// ДЕФЕКТ #310: раньше цели `@import` ВНЕ сканируемого корня отбрасывались
/// молча. На `lib/std/math` это давало «64 модуля, 0 рёбер» — хотя каждый
/// модуль импортирует `../std.zig`. Отсутствие рёбер читалось как «связей нет»,
/// хотя на деле связи есть, просто они уходят за границу сканирования.
/// Теперь они возвращаются отдельным списком `external`.
pub fn collect(alloc: std.mem.Allocator, root: []const u8) !struct {
    nodes: []Node,
    edges: []Edge,
    external: []Edge,
} {
    var nodes: std.ArrayListUnmanaged(Node) = .empty;
    var edges: std.ArrayListUnmanaged(Edge) = .empty;
    var known: std.StringHashMapUnmanaged(void) = .empty;

    var dir = try compat.openDir(root, .{ .iterate = true });
    defer compat.dirClose(dir);
    var walker = try dir.walk(alloc);
    defer walker.deinit();

    // Проход 1: узлы + рёбра (цели фильтруются на проходе 2).
    while (try walker.next(compat.io())) |entry| {
        if (entry.kind != .file) continue;
        if (!std.mem.endsWith(u8, entry.path, ".zig")) continue;
        const src = dir.readFileAlloc(compat.io(), entry.path, alloc, .limited(1 << 20)) catch continue;
        // ДЕФЕКТ (найден паникой hash_map): `entry.path` — буфер walker-а,
        // он перезаписывается на следующей итерации. Ключ карты обязан
        // владеть памятью, иначе карта «теряет» уже вставленные ключи.
        // ИДЕНТИФИКАТОР — относительный путь (`core/eq2.zig`), а не basename:
        // иначе `eq2.zig` из разных каталогов склеиваются в один узел.
        const id = try alloc.dupe(u8, entry.path);
        if (known.contains(id)) continue;
        try known.put(alloc, id, {});

        var targets: std.StringHashMapUnmanaged(void) = .empty;
        const base_dir = dirName(id);
        var rest = src;
        while (std.mem.indexOf(u8, rest, "@import(\"")) |p| {
            rest = rest[p + 9 ..];
            const close = std.mem.indexOfScalar(u8, rest, '"') orelse break;
            const spec = rest[0..close];
            rest = rest[close..];
            const target = resolveImport(alloc, base_dir, spec) catch continue;
            if (target.len == 0) continue;
            // Только .zig-цели: `@import("...")` в докстроке иначе даёт
            // фантомный «импорт» в каталог и врёт в imports_out.
            if (!std.mem.endsWith(u8, target, ".zig")) continue;
            try targets.put(alloc, target, {});
        }
        try nodes.append(alloc, .{
            .id = id,
            // Как в Python-генераторе: файл, кончающийся переводом строки,
            // имеет ровно столько строк, сколько переводов (без +1).
            .loc = countOccurrences(src, "\n") +
                (if (std.mem.endsWith(u8, src, "\n")) @as(usize, 0) else @as(usize, 1)),
            .pub_fn = countOccurrences(src, "pub fn "),
            .tests = countOccurrences(src, "test \""),
            .kern = countOccurrences(src, "@kern:"),
            .imports_out = targets.count(),
        });
        var it = targets.keyIterator();
        while (it.next()) |t| {
            if (std.mem.eql(u8, t.*, id)) continue;
            try edges.append(alloc, .{ .source = id, .target = t.* });
        }
        targets.deinit(alloc);
    }

    // Проход 2: рёбра внутрь известных узлов (без дублей) + ВНЕШНИЕ цели
    // ОТДЕЛЬНЫМ списком (дефект #310: раньше они отбрасывались молча).
    var seen: std.StringHashMapUnmanaged(void) = .empty;
    var seen_ext: std.StringHashMapUnmanaged(void) = .empty;
    var kept: std.ArrayListUnmanaged(Edge) = .empty;
    var external: std.ArrayListUnmanaged(Edge) = .empty;
    const key = struct {
        fn make(a: std.mem.Allocator, from: []const u8, to: []const u8) ![]u8 {
            return std.fmt.allocPrint(a, "{s}->{s}", .{ from, to });
        }
    };
    for (edges.items) |e| {
        if (!known.contains(e.target)) {
            const ke = try key.make(alloc, e.source, e.target);
            if (seen_ext.contains(ke)) continue;
            try seen_ext.put(alloc, ke, {});
            try external.append(alloc, e);
            continue;
        }
        const k = try key.make(alloc, e.source, e.target);
        if (seen.contains(k)) continue;
        try seen.put(alloc, k, {});
        try kept.append(alloc, e);
    }
    edges.deinit(alloc);
    return .{ .nodes = try nodes.toOwnedSlice(alloc),
              .edges = try kept.toOwnedSlice(alloc),
              .external = try external.toOwnedSlice(alloc) };
}

/// Сериализовать в JSON (схема совместима с showcase-graph.json).
///
/// `include_external` (флаг `--external`) материализует цели за границей
/// сканирования как узлы с `"external": true` и добавляет их рёбра — тогда
/// граф ЗАМКНУТ и «внешних связей 0» означает «их правда нет». Без флага
/// внешние связи только СООБЩАЮТСЯ числом `edges_external` (дефект #310).
pub fn render(alloc: std.mem.Allocator, root: []const u8, include_external: bool) ![]u8 {
    const g = try collect(alloc, root);
    var parts: std.ArrayListUnmanaged([]const u8) = .empty;
    try parts.append(alloc, try std.fmt.allocPrint(alloc,
        "{{\"schema\":\"kern-graph/1\",\"source\":\"kernx graph\",\"root\":\"{s}\",\"nodes\":[", .{root}));
    for (g.nodes, 0..) |n, i| {
        if (i > 0) try parts.append(alloc, ",");
        try parts.append(alloc, try std.fmt.allocPrint(alloc,
            "{{\"id\":\"{s}\",\"loc\":{d},\"imports_out\":{d}}}",
            .{ n.id, n.loc, n.imports_out }));
    }
    if (include_external) {
        var seen_ids: std.StringHashMapUnmanaged(void) = .empty;
        for (g.nodes) |n| try seen_ids.put(alloc, n.id, {});
        for (g.external) |e| {
            if (seen_ids.contains(e.target)) continue;
            try seen_ids.put(alloc, e.target, {});
            // Запятая — ТОЛЬКО если что-то уже выведено: при нуле внутренних
            // узлов ведущая запятая давала невалидный JSON (найдено на
            // `--root lib/std/math --external`).
            if (parts.items.len > 0 and parts.items[parts.items.len - 1].len > 0 and
                parts.items[parts.items.len - 1][parts.items[parts.items.len - 1].len - 1] != '[')
            {
                try parts.append(alloc, ",");
            }
            try parts.append(alloc, try std.fmt.allocPrint(alloc,
                "{{\"id\":\"{s}\",\"loc\":0,\"imports_out\":0,\"external\":true}}",
                .{e.target}));
        }
    }
    try parts.append(alloc, "],\"edges\":[");
    for (g.edges, 0..) |e, i| {
        if (i > 0) try parts.append(alloc, ",");
        try parts.append(alloc, try std.fmt.allocPrint(alloc,
            "{{\"source\":\"{s}\",\"target\":\"{s}\",\"kind\":\"import\"}}",
            .{ e.source, e.target }));
    }
    if (include_external) {
        for (g.external, 0..) |e, i| {
            if (i > 0 or g.edges.len > 0) try parts.append(alloc, ",");
            try parts.append(alloc, try std.fmt.allocPrint(alloc,
                "{{\"source\":\"{s}\",\"target\":\"{s}\",\"kind\":\"import\",\"external\":true}}",
                .{ e.source, e.target }));
        }
    }
    try parts.append(alloc, try std.fmt.allocPrint(alloc,
        "],\"edges_external\":{d}}}\n", .{g.external.len}));

    var total: usize = 0;
    for (parts.items) |piece| total += piece.len;
    const out = try alloc.alloc(u8, total);
    var off: usize = 0;
    for (parts.items) |piece| {
        @memcpy(out[off..][0..piece.len], piece);
        off += piece.len;
    }
    return out;
}
