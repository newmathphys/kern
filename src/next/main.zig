// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN-Next: CLI-оркестратор `kernx` (§13 спецификации KERN-Next).
const std = @import("std");

/// ЕДИНЫЙ ИСТОЧНИК ВЕРСИИ. ДЕФЕКТ #97: строка версии была
/// продублирована в `--version` и в баннере `usage`, и баннер
/// отстал (печатал v1.3 при версии v2.3.0). Теперь одна константа.
pub const KERN_VERSION = "v2.8.0";
const engine = @import("engine.zig");
const parser = @import("parser.zig");
const validate = @import("validate.zig");
const exp = @import("export.zig");
const ast = @import("ast.zig");
const truth = @import("truth.zig");
const graph_dump = @import("graph_dump.zig");
const compat = @import("compat");

fn flagValue(args: []const [:0]const u8, name: []const u8) ?[]const u8 {
    for (args, 0..) |a, i| {
        if (std.mem.eql(u8, a, name) and i + 1 < args.len) return args[i + 1];
    }
    return null;
}

fn hasFlag(args: []const [:0]const u8, name: []const u8) bool {
    for (args) |a| if (std.mem.eql(u8, a, name)) return true;
    return false;
}

fn printFile(alloc: std.mem.Allocator, path: []const u8) !void {
    const data = try compat.readFileAlloc(alloc, path, 1 << 24);
    defer alloc.free(data);
    try std.Io.File.stdout().writeStreamingAll(compat.io(), data);
}

pub fn main(init: std.process.Init) !void {
    compat.setIo(init.io);
    const alloc = init.arena.allocator();

    const args = try std.process.Args.toSlice(init.minimal.args, alloc);

    if (args.len < 2) {
        printUsage();
        return;
    }
    const cmd = args[1];

    if (std.mem.eql(u8, cmd, "--version") or std.mem.eql(u8, cmd, "version")) {
        std.debug.print("{s} (Zig {s})\nCopyright (c) 2026 Vital Kalinousky\nLicense: PolyForm Noncommercial 1.0.0 / Commercial\n", .{ KERN_VERSION, @import("builtin").zig_version_string });
        return;
    }

    // Ф2: граф исходников — ЕДИНЫЙ источник для витрины (Эго-Линза, фильтры).
    // Python-сканер остаётся только сторожем паритета (`make graph-check`).
    if (std.mem.eql(u8, cmd, "graph")) {
        const root = flagValue(args, "--root") orelse "src";
        // ДЕФЕКТ #310: `--external` материализует цели `@import` за границей
        // сканирования как узлы (`"external": true`). Без флага они только
        // считаются (`edges_external`), и «0 рёбер» больше не выглядит как
        // «связей нет», когда они просто уходят за корень.
        const with_external = hasFlag(args, "--external");
        const json = graph_dump.render(alloc, root, with_external) catch |e| {
            std.debug.print("[!] graph: {s}\n", .{@errorName(e)});
            return;
        };
        try std.Io.File.stdout().writeStreamingAll(compat.io(), json);
        return;
    }

    if (std.mem.eql(u8, cmd, "build")) {
        if (args.len < 3) {
            std.debug.print("[!] build: нужен путь к .kern\n", .{});
            return;
        }
        const out_dir = flagValue(args, "--out") orelse ".kernnext";
        const scope = flagValue(args, "--scope") orelse "default";
        const force = hasFlag(args, "--force");
        // ДЕФЕКТ (исправлен): при отсутствии/недоступности файла проект падал
        // СЫРЫМ traceback'ом Zig. Теперь — понятное сообщение с причиной.
        const r = engine.build(alloc, args[2], out_dir, scope, force) catch |e| {
            std.debug.print("[!] build: не удалось обработать '{s}': {s}\n", .{ args[2], @errorName(e) });
            if (e == error.FileNotFound) {
                std.debug.print("    Проверьте путь к .kern (файл не найден или недоступен).\n", .{});
            }
            return;
        };
        if (r.skipped) {
            std.debug.print("[=] Без изменений — обработка пропущена (кэш). Используйте --force.\n", .{});
        } else {
            std.debug.print("[OK] Собрано: узлов={d}, утверждений={d}, диагностик={d} (ошибок={d})\n", .{ r.nodes, r.claims, r.diagnostics, r.errors });
            std.debug.print("     Каталог: {s}/project.kdb\n     Снапшот: {s}/project.ksnap\n     Пакет:   {s}/agent_packet.json\n     Отчёт:   {s}/report.md\n", .{ out_dir, out_dir, out_dir, out_dir });
        }
        return;
    }

    if (std.mem.eql(u8, cmd, "diff")) {
        if (args.len < 4) {
            std.debug.print("[!] diff: нужны два снапшота\n", .{});
            return;
        }
        var d = try engine.diffFiles(alloc, args[2], args[3]);
        defer d.deinit(alloc); // результат diff владеет своими строками
        std.debug.print("[DIFF] +{d} / -{d}\n", .{ d.added.len, d.removed.len });
        for (d.added) |l| std.debug.print("  + {s}\n", .{l});
        for (d.removed) |l| std.debug.print("  - {s}\n", .{l});
        return;
    }

    if (std.mem.eql(u8, cmd, "status") or std.mem.eql(u8, cmd, "report") or std.mem.eql(u8, cmd, "packet")) {
        if (args.len < 3) {
            std.debug.print("[!] {s}: нужен путь к .kern\n", .{cmd});
            return;
        }
        const src = try compat.readFileAlloc(alloc, args[2], 1 << 24);
        defer alloc.free(src);
        const res = try parser.parse(alloc, src);
        var project = res.project;
        const resolved = try truth.resolve(alloc, project);
        project.claims = resolved.claims;
        const diags = try validate.validate(alloc, project);

        if (std.mem.eql(u8, cmd, "status")) {
            std.debug.print("[STATUS] проект `{s}` v{s}\n", .{ project.name, project.version orelse "-" });
            std.debug.print("  узлов: {d}, утверждений: {d}, свидетельств: {d}, доказательств: {d}, связей: {d}\n", .{
                project.nodeCount(), project.claims.len, project.evidence.len, project.proofs.len, project.links.len,
            });
            inline for (@typeInfo(ast.Status).@"enum".field_names) |f| {
                var n: usize = 0;
                for (project.claims) |cl| if (std.mem.eql(u8, @tagName(cl.status), f)) {
                    n += 1;
                };
                if (n > 0) std.debug.print("  статус {s}: {d}\n", .{ f, n });
            }
            std.debug.print("  диагностик: {d} (ошибок: {d})\n", .{ diags.len, validate.countErrors(diags) });
            std.debug.print("  резолюция исполнений: N->T {d}, N->F {d}, N->B(конфликт) {d}\n", .{ resolved.stats.to_tested, resolved.stats.to_refuted, resolved.stats.to_conflicted });

            // --auth: проверка авторства («ключ-замок» Ed25519, вшитый в бинарник).
            if (hasFlag(args, "--auth")) {
                const owner = @import("owner");
                if (owner.verifyOwnership()) {
                    std.debug.print("\n[АВТОРСТВО] ПОДТВЕРЖДЕНО: {s}\n", .{owner.AUTHOR});
                    std.debug.print("  ключ-замок Ed25519 : ВАЛИДЕН\n", .{});
                    std.debug.print("  owner token        : {s}\n", .{owner.OWNER_TOKEN_HEX});
                } else {
                    std.debug.print("\n[АВТОРСТВО] НЕ ПОДТВЕРЖДЕНО (ключ-замок не совпал)\n", .{});
                }
            }
        } else if (std.mem.eql(u8, cmd, "report")) {
            try exp.writeReport(alloc, "report.md", project, diags);
            std.debug.print("[OK] report.md\n\n", .{});
            try printFile(alloc, "report.md");
        } else {
            const scope = flagValue(args, "--scope") orelse "default";
            try exp.writePacket(alloc, "agent_packet.json", project, diags, scope);
            std.debug.print("[OK] agent_packet.json\n\n", .{});
            try printFile(alloc, "agent_packet.json");
        }
        return;
    }

    std.debug.print("[!] Неизвестная команда: {s}\n", .{cmd});
    printUsage();
}

fn printUsage() void {
    std.debug.print(
        \\=======================================================
        \\  KERN-Next engine (kernx) {s}
        \\=======================================================
        \\Использование: kernx <команда> <файл.kern> [опции]
        \\
        \\  build <file> [--out DIR] [--scope S] [--force]  полный конвейер
        \\  diff <snapA> <snapB>                            сравнить снапшоты
        \\  status <file>                                   сводка
        \\  report <file>                                   человеческий отчёт
        \\  packet <file> [--scope S]                       agent packet
        \\  graph [--root DIR] [--json]                      граф исходников (G_src)
        \\
    , .{KERN_VERSION});
}
