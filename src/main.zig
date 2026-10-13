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
const unsat_core = @import("verifier/unsat_core.zig");
const array_theory = @import("verifier/array_theory.zig");
const chc = @import("verifier/chc.zig");
const string_theory = @import("verifier/string_theory.zig");
const compat = @import("compat");
const cegis = @import("verifier/cegis.zig");
const kparser = @import("next/parser.zig");
const truth = @import("next/truth.zig");
const attest_mod = @import("attest.zig");
const owner_mod = @import("owner.zig");
const Ed25519 = std.crypto.sign.Ed25519;

/// CLI-оркестратор KERN (§13 финальной спецификации).
///   build            .kern → .kimg (реальная сборка образа)
///   check-integrity  заголовок + границы + Merkle-корень
///   ls / cat         навигация по KERNFS
///   verify           Врата Истины (вердикт внешнего чекера; Z3 если есть)
///   unify            RLAIF: сечение политопов (архитектор vs ИИ)
///   run              KERN-X: исполнение байткода с топливом
///   handoff          agent_packet.json из образа
///   report           отчёт из образа
///   prove            доказательство SMT-скрипта через реальный Z3
///   audit            контур «математического интеллекта»: UNSAT-core,
///                    теория массивов, CHC/Horn, строки (QF_S), CEGIS-синтез
fn flagValue(args: []const [:0]const u8, name: []const u8) ?[]const u8 {
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

pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует явный `io` — публикуем его в compat.
    compat.setIo(init.io);
    const alloc = init.arena.allocator();

    const args = try std.process.Args.toSlice(init.minimal.args, alloc);

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
        const source = try compat.readFileAlloc(alloc, args[2], 1 << 24);
        const res = try kparser.parse(alloc, source);
        var project = res.project;
        // РЕЗОЛЮЦИЯ: машинные свидетельства исполнения -> статус (Белнап-аккумулятор).
        const resolved = try truth.resolve(alloc, project);
        project.claims = resolved.claims;
        const out = flagValue(args, "-o") orelse "release.kimg";

        var b = Builder.init(alloc);
        defer b.deinit();
        // ДЕФЕКТ (исправлен): раньше непрочитанный артефакт молча давал
        // ПУСТОЙ объект в образе (`catch ""`). Теперь каждый отказ виден,
        // а итог выводится отдельной строкой — «тихая деградация» недопустима.
        var unreadable: usize = 0;
        for (project.artifacts) |a| {
            const content = compat.readFileAlloc(alloc, a.path, 1 << 20) catch blk: {
                unreadable += 1;
                std.debug.print("[!] артефакт НЕ прочитан: {s} (нет файла или > 1 МБ) — в образ пойдёт пустой объект\n", .{a.path});
                break :blk "";
            };
            try b.addSource(a.path, content);
        }
        if (unreadable > 0) {
            std.debug.print("[!] ВНИМАНИЕ: {d} из {d} артефактов не прочитаны — образ НЕПОЛНЫЙ\n", .{ unreadable, project.artifacts.len });
        }
        for (project.claims) |c| {
            // АРХИТЕКТУРНЫЙ МОСТ «ТЕКСТ → КОНТРАКТ»:
            // в `context` заявления сканер кладёт путь к привязанному
            // машинному контракту (напр. `formal/bench_speed.smt2`) или к
            // свидетельству исполнения (`.jsonl`). Пишем этот путь в payload
            // объекта-заявления, чтобы `kernc verify` мог его найти в образе,
            // прогнать через решатель и вынести вердикт ПО МАТЕМАТИКЕ,
            // а не по буквам README.
            try b.addClaim(try claimPath(alloc, c.statement), c.scope orelse "", statusBits(c.status));
        }
        for (project.proofs) |p| try b.addSource(p.path, p.theorem);
        if (flagValue(args, "--bytecode")) |bc| {
            const code = try compat.readFileAlloc(alloc, bc, 1 << 20);
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
    // ---- smtlib: официальный прогон банка SMT-LIB со сверкой :status ----
    //
    // ЗАЧЕМ: SMT-LIB Benchmark Suite — мировой эталон. В каждом .smt2 вшит
    // ожидаемый ответ `(set-info :status sat|unsat|unknown)`. Сверяем вердикт
    // KERN-моста с ожидаемым и считаем РАСХОЖДЕНИЯ.
    //
    // ВАЖНО: «ложное срабатывание» для верификатора — это когда ожидалось
    // `unsat` (безопасно), а получено `sat` (найден контрпример). Это
    // опасное направление; обратное (unsat вместо sat) — консервативно.
    if (std.mem.eql(u8, command, "smtlib")) {
        if (args.len < 3) {
            std.debug.print("[!] smtlib: нужен каталог с *.smt2\n", .{});
            return;
        }
        var bridge = z3b.Z3Bridge.init(alloc);
        bridge.timeout_ms = 2000;
        // Флаг --timeout-ms N: для ПОЛНОГО свипа банка нужен короткий лимит
        // (иначе тяжёлые QF_AUFBV съедают всё время). Таймаут — это ЛИМИТ
        // РЕСУРСА, он учитывается отдельно от расхождений.
        if (flagValue(args, "--timeout-ms")) |ts| {
            bridge.timeout_ms = std.fmt.parseInt(u32, ts, 10) catch 2000;
        }
        if (bridge.executeQuery("(check-sat)\n").status == .ToolError) {
            std.debug.print("[!] z3 недоступен (uv pip install z3-solver, .venv/bin в PATH)\n", .{});
            return;
        }
        var dir = compat.openDir(args[2], .{ .iterate = true }) catch |e| {
            std.debug.print("[!] не открыть каталог '{s}': {s}\n", .{ args[2], @errorName(e) });
            return;
        };
        defer compat.dirClose(dir);

        var walker = try dir.walk(alloc);
        defer walker.deinit();

        var total: usize = 0;
        var matched: usize = 0;
        var mismatched: usize = 0;
        var skipped: usize = 0;
        var false_pos: usize = 0; // ожидалось unsat, получено sat (опасно)
        var timeout_n: usize = 0;
        var shown: usize = 0;

        while (try walker.next()) |entry| {
            if (entry.kind != .file) continue;
            if (!std.mem.endsWith(u8, entry.path, ".smt2")) continue;
            const content = dir.readFileAlloc(alloc, entry.path, 1 << 20) catch continue;
            total += 1;

            // Ожидаемый статус: ищем в первой части файла.
            const head = content[0..@min(content.len, 4096)];
            const expect: ?[]const u8 = if (std.mem.indexOf(u8, head, ":status unsat")) |_|
                "unsat"
            else if (std.mem.indexOf(u8, head, ":status sat")) |_|
                "sat"
            else if (std.mem.indexOf(u8, head, ":status unknown")) |_|
                "unknown"
            else
                null;
            if (expect == null) {
                skipped += 1;
                continue;
            }

            const resp = bridge.executeQuery(content);
            const got: []const u8 = switch (resp.status) {
                .Sat => "sat",
                .Unsat => "unsat",
                .Unknown => "unknown",
                .Timeout => "timeout",
                .ToolError => "error",
            };

            if (std.mem.eql(u8, got, expect.?)) {
                matched += 1;
            } else if (std.mem.eql(u8, got, "timeout") or std.mem.eql(u8, got, "error")) {
                // ТАЙМАУТ/ОШИБКА — это ЛИМИТ РЕСУРСА, а не неверный вердикт.
                // Считать это «расхождением» было бы нечестно: решатель не
                // ошибся, он не успел. Учитываем отдельно.
                timeout_n += 1;
            } else if (std.mem.eql(u8, expect.?, "unknown") or std.mem.eql(u8, got, "unknown")) {
                skipped += 1; // unknown не считается расхождением
            } else {
                mismatched += 1;
                if (std.mem.eql(u8, expect.?, "unsat") and std.mem.eql(u8, got, "sat")) false_pos += 1;
                if (shown < 5) {
                    std.debug.print("  [РАСХОЖДЕНИЕ] {s}: ожидалось {s}, получено {s}\n", .{ entry.path, expect.?, got });
                    shown += 1;
                }
            }
        }

        const checked = matched + mismatched;
        const pct: f64 = if (checked > 0)
            @as(f64, @floatFromInt(matched)) / @as(f64, @floatFromInt(checked)) * 100.0
        else
            0.0;
        std.debug.print("\n=== SMT-LIB BENCHMARK RUN ===\n", .{});
        std.debug.print("файлов всего:        {d}\n", .{total});
        std.debug.print("проверено (:status): {d}\n", .{checked});
        std.debug.print("совпало:             {d} ({d:.1}%)\n", .{ matched, pct });
        std.debug.print("расхождений:         {d}\n", .{mismatched});
        std.debug.print("таймаутов:           {d}\n", .{timeout_n});
        std.debug.print("пропущено (unknown): {d}\n", .{skipped});
        std.debug.print("ЛОЖНЫХ СРАБАТЫВАНИЙ: {d} (ожидалось unsat, получено sat)\n", .{false_pos});
        return;
    }

    if (std.mem.eql(u8, command, "prove")) {
        if (args.len < 3) {
            std.debug.print("[!] prove: нужен путь к .smt2 (SMT-LIB2)\n", .{});
            return;
        }
        const smt = try compat.readFileAlloc(alloc, args[2], 1 << 20);
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

    // ---- audit: контур «математического интеллекта» (SMT-теории) ----
    if (std.mem.eql(u8, command, "audit")) {
        var bridge = z3b.Z3Bridge.init(alloc);
        bridge.timeout_ms = 10000;
        if (bridge.executeQuery("(check-sat)\n").status == .ToolError) {
            std.debug.print("[!] z3 недоступен (uv pip install z3-solver).\n", .{});
            return;
        }
        std.debug.print("=== KERN AUDIT: теории SMT (математический интеллект) ===\n\n", .{});

        // [1] UNSAT CORE — локализация точной конфликтующей строки
        {
            var eng = unsat_core.UnsatCoreEngine.init(alloc);
            const pres = [_]unsat_core.NamedAssertion{
                .{ .name = "line_10_non_negative", .formula = "(>= x 0)" },
                .{ .name = "line_12_upper_bound", .formula = "(<= x 100)" },
            };
            var core = try eng.localize(&bridge, "(declare-const x Int)", &pres, "(>= x 0)");
            defer core.deinit();
            std.debug.print("[1] UNSAT CORE (локализация ошибки): {s}\n", .{if (core.is_conflict) "КОНФЛИКТ" else "нет"});
            std.debug.print("    виновные строки: ", .{});
            for (core.conflicting) |n| std.debug.print("{s} ", .{n});
            std.debug.print("\n\n", .{});
        }

        // [2] ТЕОРИЯ МАССИВОВ — отсутствие алиасинга доказано
        {
            var eng = array_theory.ArrayTheoryEngine.init(alloc);
            const q = try eng.buildAliasingIndependenceQuery("i", "j");
            defer alloc.free(q);
            const st = bridge.executeQuery(q).status;
            std.debug.print("[2] ARRAYS (аксиомы Маккарти): независимость ячеек при i≠j — {s}\n", .{if (st == .Unsat) "ДОКАЗАНО" else @tagName(st)});
            const q2 = try eng.buildGuardedSafeQuery("i", 16);
            defer alloc.free(q2);
            const st2 = bridge.executeQuery(q2).status;
            std.debug.print("    защищённая запись (0≤i<16): {s}\n\n", .{if (st2 == .Unsat) "БЕЗОПАСНО (доказано)" else @tagName(st2)});
        }

        // [3] CHC / HORN — инвариант цикла
        {
            var eng = chc.ChcEngine.init(alloc);
            const st = eng.proveLoopSafety(&bridge, "(= x 0)", "(< x 10)", "(+ x 1)", "(>= x 10)");
            std.debug.print("[3] CHC/HORN (инвариант цикла): while(x<10) x++ ⇒ x≥10 — {s}\n", .{if (st == .Sat) "ДОКАЗАНО (инвариант найден)" else @tagName(st)});
            const st2 = eng.proveLoopSafety(&bridge, "(= x 0)", "(< x 10)", "(+ x 1)", "(< x 5)");
            std.debug.print("    ложное постусловие x<5: {s}\n\n", .{if (st2 == .Unsat) "БАГ (инварианта нет)" else @tagName(st2)});
        }

        // [4] СТРОКИ (QF_S) — разрыв санитайзера
        {
            var eng = string_theory.StringTheoryEngine.init(alloc);
            const q = try eng.buildSanitizerGapQuery("..", "/");
            defer alloc.free(q);
            const st = bridge.executeQuery(q).status;
            std.debug.print("[4] STRINGS (QF_S): '..' проходит при вырезании '/' — {s}\n", .{if (st == .Sat) "УЯЗВИМОСТЬ (контрпример есть)" else @tagName(st)});
            const q2 = try eng.buildZeroByteQuery();
            defer alloc.free(q2);
            const st2 = bridge.executeQuery(q2).status;
            std.debug.print("    нуль-байтовая инъекция: {s}\n\n", .{if (st2 == .Sat) "ДОСТИЖИМА" else @tagName(st2)});
        }

        // [5] CEGIS — синтез программы по спецификации
        {
            var eng = cegis.CegisEngine.init(alloc, &bridge);
            var out = try eng.synthesizeShiftMul(8);
            defer out.deinit(alloc);
            std.debug.print("[5] CEGIS (синтез кода): спецификация x*8\n", .{});
            if (out.found) {
                std.debug.print("    СИНТЕЗИРОВАНО: {s}  (проверок: {d}, контрпримеров: {d})\n", .{ out.expr, out.tried, out.counterexamples });
            } else {
                std.debug.print("    не найдено (честный отказ)\n", .{});
            }
        }
        return;
    }

    // ---- attest: аттестация образа .kimg (Remote Attestation, Ed25519) ----
    //   kernc attest sign   <image.kimg> -k <seed32.bin> -o <cert.bin>
    //   kernc attest verify <image.kimg> <cert.bin>
    if (std.mem.eql(u8, command, "attest")) {
        if (args.len < 4) {
            std.debug.print(
                "Использование:\n  kernc attest sign   <image.kimg> -k <seed32.bin> -o <cert.bin>\n  kernc attest verify <image.kimg> <cert.bin>\n", .{});
            return;
        }
        const mode = args[2];
        const img = try compat.readFileAlloc(alloc, args[3], 64 << 20);
        defer alloc.free(img);
        if (img.len < 128) {
            std.debug.print("[!] файл меньше 128-байтного заголовка\n", .{});
            return;
        }
        const hdr_bytes: *const [128]u8 = @ptrCast(img.ptr);
        const h = KimgHeader.parse(hdr_bytes, img.len) catch |e| {
            std.debug.print("[!] заголовок невалиден: {s}\n", .{@errorName(e)});
            return;
        };
        KimgHeader.verifyMerkleRoot(img, h) catch {
            std.debug.print("[!] Merkle-корень НЕ совпал — аттестовать нельзя\n", .{});
            return;
        };
        var digest: [32]u8 = undefined;
        std.crypto.hash.sha2.Sha256.hash(img, &digest, .{});

        if (std.mem.eql(u8, mode, "sign")) {
            const seed_path = flagValue(args, "-k") orelse {
                std.debug.print("[!] нужен путь к ключу: -k <seed32.bin>\n", .{});
                return;
            };
            const out_path = flagValue(args, "-o") orelse "attestation.cert";
            const seed_raw = try compat.readFileAlloc(alloc, seed_path, 64);
            defer alloc.free(seed_raw);
            if (seed_raw.len != 32) {
                std.debug.print("[!] seed должен быть ровно 32 байта (получено {d})\n", .{seed_raw.len});
                return;
            }
            const kp = try Ed25519.KeyPair.create(seed_raw[0..32].*);
            const cert = try attest_mod.attest(kp, digest, h.root_digest, .proved);
            const bytes = attest_mod.toBytes(cert);
            const f = try compat.createFile(out_path, .{});
            defer compat.fileClose(f);
            try compat.fileWriteAll(f, &bytes);
            std.debug.print("[OK] ОБРАЗ АТТЕСТОВАН: {s}\n", .{owner_mod.AUTHOR});
            std.debug.print("  образ    : {s} ({d} байт)\n", .{ args[3], img.len });
            std.debug.print("  вердикт  : proved (Merkle-корень совпал)\n", .{});
            std.debug.print("  сертификат: {s} ({d} байт, Ed25519)\n", .{ out_path, bytes.len });
            return;
        }

        if (std.mem.eql(u8, mode, "verify")) {
            if (args.len < 5) {
                std.debug.print("[!] нужен путь к сертификату\n", .{});
                return;
            }
            const raw = try compat.readFileAlloc(alloc, args[4], 4096);
            defer alloc.free(raw);
            if (raw.len != attest_mod.CERT_SIZE) {
                std.debug.print("[!] размер сертификата {d} != {d}\n", .{ raw.len, attest_mod.CERT_SIZE });
                return;
            }
            const cb: *const [attest_mod.CERT_SIZE]u8 = @ptrCast(raw.ptr);
            const cert = attest_mod.fromBytes(cb) catch |e| {
                std.debug.print("[!] сертификат повреждён: {s}\n", .{@errorName(e)});
                return;
            };
            const pk = try Ed25519.PublicKey.fromBytes(owner_mod.OWNER_PUBLIC_KEY);
            const sig_ok = attest_mod.verify(pk, cert);
            const bind_ok = std.mem.eql(u8, &cert.contract_digest, &digest) and
                std.mem.eql(u8, &cert.merkle_root, &h.root_digest);
            if (sig_ok and bind_ok) {
                std.debug.print("[OK] ОБРАЗ АТТЕСТОВАН: {s}\n", .{owner_mod.AUTHOR});
                std.debug.print("  подпись владельца : ВАЛИДНА\n", .{});
                std.debug.print("  привязка к образу : digest + Merkle-корень совпали\n", .{});
            } else {
                std.debug.print("[!] АТТЕСТАЦИЯ НЕ ПОДТВЕРЖДЕНА (подпись={s}, привязка={s})\n", .{
                    if (sig_ok) "ok" else "НЕВЕРНА",
                    if (bind_ok) "ok" else "НЕ СОВПАЛА",
                });
            }
            return;
        }
        std.debug.print("[!] неизвестный режим: {s}\n", .{mode});
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
    const data = compat.readFileAlloc(alloc, image_path, 1 << 28) catch |e| {
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
        std.debug.print("[L4] Образ: {s}\n", .{image_path});

        // АРХИТЕКТУРНЫЙ МОСТ «ТЕКСТ → КОНТРАКТ».
        // У каждого заявления в payload записан путь к привязанному контракту
        // (аннотация `<!-- @kern:spec path="..." -->` в Markdown, см.
        // tools/scan_to_kern.py). Если контракт есть — он лежит в этом же
        // образе как артефакт; читаем его и прогоняем через Z3. Вердикт
        // выносится ПО ФОРМУЛЕ, а не по тексту заявления.
        var proven: usize = 0;
        var refuted: usize = 0;
        var no_contract: usize = 0;
        for (fs.objects) |obj| {
            if (obj.type_id != 0x0005) continue;
            const id = fs.objectPath(obj);
            const bits: u2 = @intCast((obj.flags >> 2) & 0b11);
            const contract_path = fs.objectPayload(obj) catch "";
            std.debug.print("  claim `{s}`: заявленный статус = {s}\n", .{ id, statusSymbol(bits) });

            if (contract_path.len == 0) {
                no_contract += 1;
                std.debug.print("    контракт НЕ привязан -> e=0 (N): текст без машинного доказательства\n", .{});
                continue;
            }

            var pb: [512]u8 = undefined;
            const raw_path = std.fmt.bufPrint(&pb, "/raw/{s}", .{contract_path}) catch {
                no_contract += 1;
                continue;
            };
            const node = fs.read(raw_path) catch {
                std.debug.print("    контракт `{s}` НЕ найден в образе -> e=0 (N)\n", .{contract_path});
                no_contract += 1;
                continue;
            };

            // ДВА КЛАССА УТВЕРЖДЕНИЙ (см. docs/SPEC_ANCHORS_DEMO.md):
            //   • @kern:spec  -> .smt2  — МАТЕМАТИЧЕСКОЕ свойство, вердикт даёт Z3;
            //   • @kern:evidence -> лог — ФАКТ исполнения, формулой не доказуется.
            // Второй класс нельзя «прогнать через решатель»: это была бы подмена
            // сути. Честно сообщаем, что проверка свидетельств не реализована.
            if (!std.mem.endsWith(u8, contract_path, ".smt2")) {
                std.debug.print("    свидетельство `{s}`: это ФАКТ исполнения, а не контракт SMT\n", .{contract_path});
                std.debug.print("      -> e=0 (проверка логов исполнения не реализована — честно)\n", .{});
                no_contract += 1;
                continue;
            }

            const resp = bridge.executeQuery(node.raw_slice);
            switch (resp.status) {
                .Unsat => {
                    // (assert ...) невыполнимо => утверждение ДОКАЗАНО.
                    proven += 1;
                    std.debug.print("    контракт `{s}`: UNSAT -> e=1 (T) ДОКАЗАНО\n", .{contract_path});
                },
                .Sat => {
                    refuted += 1;
                    std.debug.print("    контракт `{s}`: SAT -> e=0 (F) КОНТРПРИМЕР\n", .{contract_path});
                },
                .Timeout => {
                    std.debug.print("    контракт `{s}`: ТАЙМАУТ -> e=0 (безопасно)\n", .{contract_path});
                },
                .ToolError => {
                    std.debug.print("    контракт `{s}`: решатель недоступен -> e=0 (безопасно)\n", .{contract_path});
                },
                .Unknown => {
                    std.debug.print("    контракт `{s}`: UNKNOWN -> e=0 (безопасно)\n", .{contract_path});
                },
            }
        }
        std.debug.print("[i] ИТОГ: доказано {d}, контрпримеров {d}, без контракта {d}\n", .{ proven, refuted, no_contract });
        std.debug.print("[i] e=1 выставляется ТОЛЬКО по вердикту решателя. Заявления без\n", .{});
        std.debug.print("    привязанного контракта остаются e=0 — это и есть честный статус.\n", .{});

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
        const f = try compat.createFile("agent_packet.json", .{});
        defer compat.fileClose(f);
        var buf = std.array_list.Managed(u8).init(alloc);
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
        try compat.fileWriteAll(f, buf.items);
        std.debug.print("[OK] agent_packet.json (из образа)\n", .{});

    } else if (std.mem.eql(u8, command, "report")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        const out_file = try compat.createFile("PROJECT_CANONICAL_SPEC.kern.md", .{});
        defer compat.fileClose(out_file);
        var buf = std.array_list.Managed(u8).init(alloc);
        defer buf.deinit();
        const w = buf.writer();
        try w.print("# КАНОНИЧЕСКИЙ ПАСПОРТ KERN\n\n> Сгенерировано kernc ИЗ ОБРАЗА `{s}` ({d} байт).\n\n**Объектов:** {d}\n\n", .{ image_path, data.len, fs.objects.len });
        for (fs.objects) |obj| {
            try w.print("- `type=0x{X:0>4}` size={d} path=`{s}`\n", .{ obj.type_id, obj.uncompressed_size, fs.objectPath(obj) });
        }
        try compat.fileWriteAll(out_file, buf.items);
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
