// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

const std = @import("std");

// Подсистемы L0-L5
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const Eq2 = @import("core/eq2.zig").Eq2;
const Builder = @import("core/kimg_writer.zig").Builder;
const KernX = @import("runtime/kern_x.zig").KernX;
const AdmissionGate = @import("verifier/admission_gate.zig").AdmissionGate;
const ProofCertificate = @import("verifier/admission_gate.zig").ProofCertificate;
const VerificationPolicy = @import("verifier/admission_gate.zig").VerificationPolicy;
const TrustedChecker = @import("verifier/admission_gate.zig").TrustedChecker;
const z3b = @import("verifier/z3_bridge.zig");
const kparser = @import("next/parser.zig");
const truth = @import("next/truth.zig");

/// CLI-оркестратор KERN (§13 финальной спецификации).
///   build            .kern → .kimg (реальная сборка образа)
///   check-integrity  заголовок + границы + Merkle-корень
///   ls / cat         навигация по KERNFS
///   verify           Врата Истины (вердикт внешнего чекера; Z3 если есть)
///   unify            RLAIF: сечение политопов (архитектор vs ИИ)
///   run              KERN-X: исполнение байткода с топливом
///   handoff          agent_packet.json из образа
///   report           отчёт из образа
fn flagValue(args: []const [:0]u8, name: []const u8) ?[]const u8 {
    for (args, 0..) |a, i| {
        if (std.mem.eql(u8, a, name) and i + 1 < args.len) return args[i + 1];
    }
    return null;
}

fn statusBits(s: @import("next/ast.zig").Status) u2 {
    return switch (s) {
        .proven, .verified, .tested, .compiled => 1,
        .refuted => 2,
        .conflicted => 3,
        else => 0,
    };
}

fn statusSymbol(bits: u2) []const u8 {
    return switch (bits) {
        0 => "N",
        1 => "T",
        2 => "F",
        3 => "B",
    };
}

/// Путь утверждения для KERNFS: символ '/' — разделитель пути, поэтому
/// заменяем его на '_', чтобы утверждение было адресуемо как /claims/<id>/status.
fn claimPath(alloc: std.mem.Allocator, s: []const u8) ![]const u8 {
    const out = try alloc.alloc(u8, s.len);
    for (s, 0..) |c, i| out[i] = if (c == '/') '_' else c;
    return out;
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const args = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, args);

    if (args.len < 2) {
        printUsage();
        return;
    }
    const command = args[1];

    // ---- build: .kern → .kimg ----
    if (std.mem.eql(u8, command, "build")) {
        if (args.len < 3) {
            std.debug.print("[!] build: нужен путь к .kern\n", .{});
            return;
        }
        const source = try std.fs.cwd().readFileAlloc(alloc, args[2], 1 << 24);
        const res = try kparser.parse(alloc, source);
        var project = res.project;
        // РЕЗОЛЮЦИЯ: машинные свидетельства исполнения -> статус (Белнап-аккумулятор).
        const resolved = try truth.resolve(alloc, project);
        project.claims = resolved.claims;
        const out = flagValue(args, "-o") orelse "release.kimg";

        var b = Builder.init(alloc);
        defer b.deinit();
        for (project.artifacts) |a| {
            const content = std.fs.cwd().readFileAlloc(alloc, a.path, 1 << 20) catch "";
            try b.addSource(a.path, content);
        }
        for (project.claims) |c| {
            try b.addClaim(try claimPath(alloc, c.statement), "{}", statusBits(c.status));
        }
        for (project.proofs) |p| try b.addSource(p.path, p.theorem);
        if (flagValue(args, "--bytecode")) |bc| {
            const code = try std.fs.cwd().readFileAlloc(alloc, bc, 1 << 20);
            try b.addBytecode("program.bcx", code);
        }
        if (b.specs.items.len == 0) {
            std.debug.print("[!] В проекте нет объектов для упаковки\n", .{});
            return;
        }
        try b.write(out);
        std.debug.print("[OK] Образ собран: {s} ({d} объектов)\n", .{ out, b.specs.items.len });
        return;
    }

    // ---- unify: RLAIF (сечение политопов) ----
    if (std.mem.eql(u8, command, "unify")) {
        if (args.len < 4) {
            std.debug.print("[!] unify: нужны <human_max> <ai_min>\n", .{});
            return;
        }
        const human_max = try std.fmt.parseInt(u32, args[2], 10);
        const ai_min = try std.fmt.parseInt(u32, args[3], 10);
        const delta = ai_min -| human_max; // сатурирующее вычитание (Уравнение V)
        if (delta > 0) {
            std.debug.print("[B] КОНФЛИКТ: предложение ИИ (min={d}) превышает лимит архитектора (max={d}).\n", .{ ai_min, human_max });
            std.debug.print("    Градиент ошибки ∇error = {d} → отправить агенту на исправление.\n", .{delta});
        } else {
            std.debug.print("[T] УНИФИКАЦИЯ УСПЕШНА: пересечение непусто (ai_min={d} <= human_max={d}).\n", .{ ai_min, human_max });
        }
        return;
    }

    // ---- prove: доказательство SMT-скрипта через РЕАЛЬНЫЙ Z3 ----
    if (std.mem.eql(u8, command, "prove")) {
        if (args.len < 3) {
            std.debug.print("[!] prove: нужен путь к .smt2 (SMT-LIB2)\n", .{});
            return;
        }
        const smt = try std.fs.cwd().readFileAlloc(alloc, args[2], 1 << 20);
        var bridge = z3b.Z3Bridge.init(alloc);
        if (bridge.executeQuery("(check-sat)\n").status == .ToolError) {
            std.debug.print("[!] z3 недоступен. Добавьте .venv/bin в PATH (uv pip install z3-solver).\n", .{});
            return;
        }
        var ast: [32]u8 = undefined;
        std.crypto.hash.sha2.Sha256.hash(smt, &ast, .{});
        const cert = ProofCertificate{
            .target_ast_digest = ast,
            .contract_digest = ast,
            .checker_id = 1,
            .witness_payload = smt,
        };
        const policy = VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };
        const r = try AdmissionGate.verifyClaimWithChecker(alloc, ast, ast, cert, policy, z3b.makeChecker(&bridge));
        std.debug.print("[L4] SMT-доказательство: {s}\n", .{args[2]});
        std.debug.print("  KERN-EQ2 : {s}\n", .{r.eq2_status.symbol()});
        std.debug.print("  e        : {d}\n", .{r.e_value});
        std.debug.print("  ВЕРДИКТ  : {s}\n", .{if (r.e_value == 1) "ДОКАЗАНО (допущено)" else "НЕ доказано (контрпример/таймаут)"});
        return;
    }

    // ---- --version / version: авторство и лицензия ----
    if (std.mem.eql(u8, command, "--version") or std.mem.eql(u8, command, "version")) {
        const owner = @import("owner.zig");
        std.debug.print("KERN Compiler & Formal Engine v1.3.0 (Zig 0.13)\n", .{});
        std.debug.print("Copyright (c) {s} {s}. All rights reserved.\n", .{ owner.YEAR, owner.AUTHOR });
        std.debug.print("License: MIT (см. LICENSE)\n", .{});
        std.debug.print("Owner token: {s}\n", .{owner.OWNER_TOKEN_HEX});
        std.debug.print("Ownership key-lock: {s}\n", .{if (owner.verifyOwnership()) "ВАЛИДЕН" else "НЕ подтверждён"});
        return;
    }

    if (std.mem.eql(u8, command, "pack")) {
        std.debug.print("[pack] Образ собирается командой: kernc build <file.kern> -o out.kimg\n", .{});
        return;
    }

    if (args.len < 3) {
        std.debug.print("[!] Укажите путь к образу .kimg\n", .{});
        return;
    }
    const image_path = args[2];
    const data = std.fs.cwd().readFileAlloc(alloc, image_path, 1 << 28) catch |e| {
        std.debug.print("[!] Не удалось прочитать {s}: {s}\n", .{ image_path, @errorName(e) });
        return;
    };

    if (std.mem.eql(u8, command, "check-integrity")) {
        if (data.len < 128) {
            std.debug.print("[!] Образ слишком мал: {d} байт\n", .{data.len});
            return;
        }
        var hb: [128]u8 = undefined;
        @memcpy(&hb, data[0..128]);
        const h = KimgHeader.parse(&hb, data.len) catch |e| {
            std.debug.print("[!] Образ НЕВАЛИДЕН: {s}\n", .{@errorName(e)});
            return;
        };
        KimgHeader.verifyMerkleRoot(data, h) catch |e| {
            std.debug.print("[!] Merkle-корень НЕ совпал: {s}\n", .{@errorName(e)});
            return;
        };
        std.debug.print("[OK] Целостность: заголовок + Merkle-корень совпали. Эпоха: {d}.{d}, объектов: {d}\n", .{ h.version_major, h.version_minor, h.object_count });

    } else if (std.mem.eql(u8, command, "ls")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        std.debug.print("[L3] Объектов в образе: {d}\n", .{fs.objects.len});
        for (fs.objects) |obj| {
            std.debug.print("  type=0x{X:0>4} size={d} path=`{s}`\n", .{ obj.type_id, obj.uncompressed_size, fs.objectPath(obj) });
        }

    } else if (std.mem.eql(u8, command, "cat")) {
        if (args.len < 4) {
            std.debug.print("[!] cat: нужен путь, напр. /raw/src/main.zig\n", .{});
            return;
        }
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        const node = fs.read(args[3]) catch |e| {
            std.debug.print("[!] {s}: {s}\n", .{ args[3], @errorName(e) });
            return;
        };
        switch (node) {
            .raw_slice => |s| std.debug.print("{s}", .{s}),
            .virtual_view => |s| std.debug.print("{s}", .{s}),
        }

    } else if (std.mem.eql(u8, command, "verify")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        var bridge = z3b.Z3Bridge.init(alloc);
        const checker = z3b.makeChecker(&bridge);
        std.debug.print("[L4] Образ: {s}\n", .{image_path});
        for (fs.objects) |obj| {
            if (obj.type_id != 0x0005) continue;
            const id = fs.objectPath(obj);
            const bits: u2 = @intCast((obj.flags >> 2) & 0b11);
            std.debug.print("  claim `{s}`: ЗАЯВЛЕННЫЙ статус = {s}\n", .{ id, statusSymbol(bits) });
            const cert = ProofCertificate{
                .target_ast_digest = obj.digest,
                .contract_digest = obj.digest,
                .checker_id = 1,
                .witness_payload = "",
            };
            const policy = VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 0xFFFFFFFF };
            const r = try AdmissionGate.verifyClaimWithChecker(alloc, obj.digest, obj.digest, cert, policy, checker);
            std.debug.print("    Врата Истины (Z3-мост): e={d} ({s})\n", .{ r.e_value, r.eq2_status.symbol() });
        }
        std.debug.print("[i] Заявленный статус — это ЗАЯВЛЕНИЕ; допуск (e=1) требует внешнего решателя.\n", .{});

    } else if (std.mem.eql(u8, command, "run")) {
        const fuel_s = flagValue(args, "--fuel") orelse "1000";
        const fuel = try std.fmt.parseInt(u32, fuel_s, 10);
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        var found = false;
        for (fs.objects) |obj| {
            if (obj.type_id != 0x0007) continue;
            found = true;
            const code = try fs.objectPayload(obj);
            var vm = KernX.init(fuel);
            std.debug.print("[KERN-X] байткод `{s}` ({d} б), топливо {d}\n", .{ fs.objectPath(obj), code.len, fuel });
            vm.execute(code) catch |e| {
                std.debug.print("  РЕЗУЛЬТАТ: {s} (остаток топлива {d})\n", .{ @errorName(e), vm.fuel });
                return;
            };
            std.debug.print("  РЕЗУЛЬТАТ: HALT OK (остаток топлива {d})\n", .{vm.fuel});
        }
        if (!found) std.debug.print("[i] В образе нет байткода (type 0x0007). Соберите с --bytecode.\n", .{});

    } else if (std.mem.eql(u8, command, "handoff")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        const f = try std.fs.cwd().createFile("agent_packet.json", .{});
        defer f.close();
        var buf = std.ArrayList(u8).init(alloc);
        defer buf.deinit();
        const w = buf.writer();
        try w.writeAll("{\n  \"v\": \"1.3\",\n  \"task\": \"handoff\",\n  \"truth_rule\": \"e=1_only_after_required_verification\",\n");
        try w.writeAll("  \"proven\": [\n");
        var first = true;
        for (fs.objects) |obj| {
            if (obj.type_id != 0x0005) continue;
            const bits: u2 = @intCast((obj.flags >> 2) & 0b11);
            if (bits != 1) continue;
            if (!first) try w.writeAll(",\n");
            first = false;
            try w.print("    {{\"id\": \"{s}\", \"status\": \"T\"}}", .{fs.objectPath(obj)});
        }
        try w.writeAll("\n  ],\n  \"stats\": {\n");
        try w.print("    \"objects\": {d}\n  }}\n}}\n", .{fs.objects.len});
        try f.writeAll(buf.items);
        std.debug.print("[OK] agent_packet.json (из образа)\n", .{});

    } else if (std.mem.eql(u8, command, "report")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        const out_file = try std.fs.cwd().createFile("PROJECT_CANONICAL_SPEC.kern.md", .{});
        defer out_file.close();
        var buf = std.ArrayList(u8).init(alloc);
        defer buf.deinit();
        const w = buf.writer();
        try w.print("# КАНОНИЧЕСКИЙ ПАСПОРТ KERN\n\n> Сгенерировано kernc ИЗ ОБРАЗА `{s}` ({d} байт).\n\n**Объектов:** {d}\n\n", .{ image_path, data.len, fs.objects.len });
        for (fs.objects) |obj| {
            try w.print("- `type=0x{X:0>4}` size={d} path=`{s}`\n", .{ obj.type_id, obj.uncompressed_size, fs.objectPath(obj) });
        }
        try out_file.writeAll(buf.items);
        std.debug.print("[OK] Отчёт записан ИЗ ОБРАЗА: PROJECT_CANONICAL_SPEC.kern.md\n", .{});

    } else {
        std.debug.print("[!] Неизвестная команда: {s}\n", .{command});
        printUsage();
    }
}

fn printUsage() void {
    std.debug.print(
        \\=======================================================
        \\  KERN Compiler & Formal Engine v1.3
        \\=======================================================
        \\Использование: kernc <команда> <файл> [опции]
        \\
        \\  build <file.kern> [-o out.kimg] [--bytecode f]  сборка образа
        \\  check-integrity <file.kimg>                     L0: заголовок + Merkle
        \\  ls <file.kimg>                                  L3: объекты образа
        \\  cat <file.kimg> <путь>                          L3: полезная нагрузка
        \\  verify <file.kimg>                              L4: Врата Истины (Z3)
        \\  unify <human_max> <ai_min>                      RLAIF: сечение политопов
        \\  prove <file.smt2>                               L4: доказательство через Z3 (e=1)
        \\  run <file.kimg> [--fuel N]                      KERN-X: исполнение
        \\  handoff <file.kimg>                             agent_packet.json
        \\  report <file.kimg>                              отчёт из образа
        \\
    , .{});
}
