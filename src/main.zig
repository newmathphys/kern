// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

const std = @import("std");

/// ЕДИНЫЙ ИСТОЧНИК ВЕРСИИ. ДЕФЕКТ #97: строка версии была
/// продублирована в `--version` и в баннере `usage`, и баннер
/// отстал (печатал v1.3 при версии v2.3.0). Теперь одна константа.
pub const KERN_VERSION = "v2.7.3";

// Подсистемы L0-L5
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const KernFsError = @import("core/kernfs_router.zig").KernFsError;
const Eq2 = @import("core/eq2.zig").Eq2;
const Builder = @import("core/kimg_writer.zig").Builder;
const KernX = @import("runtime/kern_x.zig").KernX;
const cli_kimg = @import("cli_kimg.zig");
const AdmissionGate = @import("verifier/admission_gate.zig").AdmissionGate;
const ProofCertificate = @import("verifier/admission_gate.zig").ProofCertificate;
const VerificationPolicy = @import("verifier/admission_gate.zig").VerificationPolicy;
const TrustedChecker = @import("verifier/admission_gate.zig").TrustedChecker;
const proof_check = @import("verifier/proof_check.zig");
const model_extract = @import("verifier/model_extract.zig");
const codec = @import("core/codec.zig");
const z3b = @import("verifier/z3_bridge.zig");
const unsat_core = @import("verifier/unsat_core.zig");
const builtin_lia = @import("verifier/builtin_lia.zig");
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
/// Аварийное завершение CLI с НЕНУЛЕВЫМ кодом возврата.
///
/// ДЕФЕКТ #32 (найден can-fail харнессом): команды печатали `[!] ...`
/// и делали `return` — то есть процесс завершался с кодом 0. Автоматика
/// (CI, скрипты, `&&`) считала проваленную проверку УСПЕШНОЙ.
/// Найдено так: порча байта в эталонном образе -> `check-integrity`
/// печатал `MerkleRootMismatch`, но `echo $?` давал 0.
pub fn fail(comptime fmt: []const u8, args: anytype) noreturn {
    std.debug.print(fmt, args);
    std.process.exit(2);
}

/// Есть ли БУЛЕВ флаг (без значения) в аргументах.
///
/// ЗАЧЕМ ОТДЕЛЬНО от `flagValue`: тот требует значение ПОСЛЕ флага
/// (`-o out.kimg`). Для флага без значения (`--deflate` последним аргументом)
/// `flagValue` вернул бы null, и флаг молча НЕ СРАБОТАЛ БЫ — именно это
/// произошло при первом прогоне `kernc build --deflate`.
fn hasFlag(args: []const [:0]const u8, name: []const u8) bool {
    for (args) |a| if (std.mem.eql(u8, a, name)) return true;
    return false;
}

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

// ===========================================================================
//  ВЫВОД ДАННЫХ (дефект CLI: данные уходили в stderr)
// ===========================================================================
//
// 🔴 ДЕФЕКТ (найден тест C-ABI/CLIом C-ABI/CLI): `kernc cat`/`ls` печатали
// ДАННЫЕ через `std.debug.print`, который пишет в **stderr**. Следствия для
// автоматизации:
//   * `kernc cat img /raw/f > out.txt` давал ПУСТОЙ файл;
//   * `kernc cat img /raw/f | grep x` не видел ничего.
// В терминале это незаметно (оба потока видны) — классическая «молчаливо
// сломанная проверка» в конвейере.
//
// ПРАВИЛО: ДАННЫЕ команды -> stdout; ДИАГНОСТИКА -> stderr; ОТКАЗ -> fail().
// (Механизм ненулевого кода возврата уже есть — `fail()` ниже, дефект #32.)

/// Вывод ДАННЫХ (результат команды) в stdout.
fn emit(data: []const u8) void {
    std.Io.File.stdout().writeStreamingAll(compat.io(), data) catch {};
}

/// Форматированный вывод ДАННЫХ в stdout.
fn emitFmt(comptime fmt: []const u8, args: anytype) void {
    const s = std.fmt.allocPrint(std.heap.page_allocator, fmt, args) catch return;
    defer std.heap.page_allocator.free(s);
    emit(s);
}


/// Записать контракт в writer, ВЫРЕЗАЯ `(exit)`.
///
/// ЗАЧЕМ: если в `.smt2` есть `(exit)`, решатель завершится сразу после него,
/// и добавленные нами `(check-sat)` / `(get-model)` не выполнятся — контрпример
/// получить не удастся. Вырезаем `(exit)` и его возможные пробелы.
fn writeWithoutExit(w: anytype, smt: []const u8) !void {
    var i: usize = 0;
    while (i < smt.len) {
        if (std.mem.startsWith(u8, smt[i..], "(exit)")) {
            i += "(exit)".len;
            continue;
        }
        try w.writeByte(smt[i]);
        i += 1;
    }
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
    if (std.mem.eql(u8, command, "pack-dir")) {
        // Вариант A: упаковать КАТАЛОГ (например, клон чужого репозитория)
        // в один образ .kimg. `build` умеет только манифест `.kern`; без этой
        // команды «упакуй репозиторий» упиралось в #299.
        if (args.len < 3) {
            std.debug.print("[!] pack-dir: нужен путь к КАТАЛОГУ\n", .{});
            std.debug.print("    использование: kernc pack-dir <dir> [-o out.kimg] [--deflate]\n", .{});
            std.process.exit(2);
        }
        const root = args[2];
        const out = flagValue(args, "-o") orelse "repo.kimg";

        var dir = compat.openDir(root, .{ .iterate = true }) catch |err| {
            std.debug.print("[!] pack-dir: не открыть каталог {s}: {s}\n", .{ root, @errorName(err) });
            std.process.exit(2);
        };
        var walker = dir.walk(alloc) catch |err| {
            std.debug.print("[!] pack-dir: обход {s} не удался: {s}\n", .{ root, @errorName(err) });
            std.process.exit(2);
        };
        defer walker.deinit();

        var b = Builder.init(alloc);
        defer b.deinit();
        if (hasFlag(args, "--deflate") or hasFlag(args, "--compress")) b.compress = .deflate;

        var n_files: usize = 0;
        var n_skipped: usize = 0;
        var n_bytes: usize = 0;
        while (try walker.next(compat.io())) |entry| {
            if (entry.kind != .file) continue;
            const rel = try alloc.dupe(u8, entry.path);
            // `.git` — служебные данные VCS, в образ не идут (это не «тихая
            // потеря»: счётчик и итог печатаются ниже).
            if (std.mem.eql(u8, rel, ".git") or std.mem.startsWith(u8, rel, ".git/")) continue;
            // ДЕФЕКТ (найден первым же прогоном на zig-clap): `entry.path`
            // относителен ОТКРЫТОГО каталога, а `readFileAlloc` работает от
            // cwd — 15 из 20 файлов молча «пропускались». Склеиваем корень.
            const full = try std.fmt.allocPrint(alloc, "{s}/{s}", .{ root, rel });
            const content = compat.readFileAlloc(alloc, full, 1 << 20) catch {
                n_skipped += 1;
                continue;
            };
            try b.addSource(rel, content);
            n_files += 1;
            n_bytes += content.len;
        }
        if (n_files == 0) {
            std.debug.print("[!] pack-dir: в {s} не найдено ни одного файла\n", .{root});
            std.process.exit(2);
        }
        b.write(out) catch |err| {
            std.debug.print("[!] pack-dir: запись {s} не удалась: {s}\n", .{ out, @errorName(err) });
            std.process.exit(2);
        };
        std.debug.print("[OK] pack-dir: {d} файлов, {d} байт -> {s}\n", .{ n_files, n_bytes, out });
        if (n_skipped > 0) {
            std.debug.print("     пропущено (нет доступа или > 1 МБ): {d}\n", .{n_skipped});
        }
        std.debug.print("     проверка: kernc fsck {s} | kernc inspect {s}\n", .{ out, out });
        return;
    }

    if (std.mem.eql(u8, command, "build")) {
        if (args.len < 3) {
            std.debug.print("[!] build: нужен путь к ФАЙЛУ манифеста .kern\n", .{});
            // ДЕФЕКТ #299: раньше здесь стоял `return` (exit 0), и скрипт не мог
            // отличить ошибку использования от успешной сборки.
            std.process.exit(2);
        }
        // ДЕФЕКТ #299: `kernc build <каталог>` валился стек-трейсом Zig
        // (`error: IsDir` из std.Io.File.readStreaming) вместо диагноза.
        const source = compat.readFileAlloc(alloc, args[2], 1 << 24) catch |err| {
            if (err == error.IsDir) {
                std.debug.print("[!] build: «{s}» — это КАТАЛОГ, а нужен ФАЙЛ манифеста .kern\n", .{args[2]});
                std.debug.print("    Упаковка дерева появится как `kernc pack-dir`; сейчас см. docs/KIMG.md\n", .{});
            } else {
                std.debug.print("[!] build: не удалось прочитать {s}: {s}\n", .{ args[2], @errorName(err) });
            }
            std.process.exit(2);
        };
        const res = try kparser.parse(alloc, source);
        var project = res.project;
        // РЕЗОЛЮЦИЯ: машинные свидетельства исполнения -> статус (Белнап-аккумулятор).
        const resolved = try truth.resolve(alloc, project);
        project.claims = resolved.claims;
        const out = flagValue(args, "-o") orelse "release.kimg";

        var b = Builder.init(alloc);
        defer b.deinit();
        // СЖАТИЕ (флаг `--deflate`): пейлоады объектов пакуются кодеком 0x02.
        // Дайджест считается по ОРИГИНАЛЬНОМУ содержимому (спецификация §5.3) —
        // целостность не ослабляется, меняется только размер на диске.
        const want_deflate = hasFlag(args, "--deflate") or hasFlag(args, "--compress");
        if (want_deflate) {
            b.compress = .deflate;
            std.debug.print("[i] сжатие включено: кодек deflate (0x02)\n", .{});
        }
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
        // Отчёт: сколько объектов РЕАЛЬНО сжалось и насколько. Без этого
        // `--deflate` выглядел бы включённым, даже когда выигрыша нет
        // (`codec.compress` возвращает null, если сжатие не уменьшило объект).
        std.debug.print("[OK] Образ собран: {s} ({d} объектов)\n", .{ out, b.specs.items.len });
        if (b.compress != .raw) {
            var n_comp: usize = 0;
            var raw_total: usize = 0;
            var stored_total: usize = 0;
            for (b.specs.items) |sp| {
                raw_total += sp.content.len;
                var used: usize = sp.content.len;
                if (codec.compress(alloc, b.compress, sp.content) catch null) |buf| {
                    alloc.free(buf);
                    used = buf.len;
                    n_comp += 1;
                }
                stored_total += used;
            }
            std.debug.print("[i] сжато объектов: {d} из {d} | пейлоад {d} -> {d} байт\n", .{
                n_comp, b.specs.items.len, raw_total, stored_total,
            });
        }
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
        if (bridge.executeStatus("(check-sat)\n") == .ToolError) {
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
        // 🔴 ДЕФЕКТ #373 (найден гейтом `smtlib-proof-check` на ОФИЦИАЛЬНОМ
        // банке SMT-LIB). Здесь стоял лимит чтения `1 << 20` (1 МБ), а
        // официальная задача `QF_LIA/20231117-c_inference` весит 1 636 928 и
        // 1 682 698 байт. `readFileAlloc` падал, `catch continue` МОЛЧА
        // пропускал файл, и счётчик `файлов всего` показывал 0 — то есть
        // каталог с двумя задачами выглядел ПУСТЫМ. Отчёт говорил не то, что
        // произошло (класс #370/#371/#372), а «проверено 0» называло вакуум,
        // не называя ПРИЧИНУ.
        var unreadable: usize = 0;
        const READ_LIMIT: usize = 1 << 26; // 64 МБ: с запасом на официальные файлы

        while (try walker.next(compat.io())) |entry| {
            if (entry.kind != .file) continue;
            if (!std.mem.endsWith(u8, entry.path, ".smt2")) continue;
            const content = dir.readFileAlloc(compat.io(), entry.path, alloc, .limited(READ_LIMIT)) catch {
                // ДЕФЕКТ #373: НЕ пропускаем молча. Файл в каталоге ЕСТЬ, и
                // счётчик обязан это показать, иначе «файлов всего 0» — ложь.
                total += 1;
                unreadable += 1;
                continue;
            };
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

            // ДЕФЕКТ #105: раньше здесь брался `resp.status`, а владеемая
            // модель (`witness_model`) НЕ освобождалась. `executeStatus`
            // освобождает её внутри — утечка невозможна по построению.
            const status = bridge.executeStatus(content);
            const got: []const u8 = switch (status) {
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
        // ДЕФЕКТ #373: строка названа ЯВНО. Без неё «файлов всего 0» на
        // непустом каталоге неотличимо от пустого каталога.
        std.debug.print("не прочитано:        {d}\n", .{unreadable});
        std.debug.print("ЛОЖНЫХ СРАБАТЫВАНИЙ: {d} (ожидалось unsat, получено sat)\n", .{false_pos});
        return;
    }

    if (std.mem.eql(u8, command, "prove")) {
        // ДЕФЕКТ #304 (найден сразу после #303): путь к файлу брался как args[2],
        // поэтому `prove --query-kind equivalence file.smt2` пытался прочитать
        // ФЛАГ как файл. Теперь позиционный аргумент ищется честно: пропускаем
        // флаги и значение `--query-kind`.
        var smt_path: ?[]const u8 = null;
        var ai: usize = 2;
        while (ai < args.len) : (ai += 1) {
            const a = args[ai];
            if (std.mem.eql(u8, a, "--query-kind")) {
                ai += 1;
                continue;
            }
            if (a.len > 0 and a[0] == '-') continue;
            smt_path = a;
            break;
        }
        const smt_file = smt_path orelse {
            std.debug.print("[!] prove: нужен путь к .smt2 (SMT-LIB2)\n", .{});
            std.debug.print("    использование: kernc prove [--query-kind refutation|equivalence] <file.smt2>\n", .{});
            std.process.exit(2);
        };
        const smt = compat.readFileAlloc(alloc, smt_file, 1 << 20) catch |err| {
            std.debug.print("[!] prove: не удалось прочитать {s}: {s}\n", .{ smt_file, @errorName(err) });
            std.process.exit(2);
        };
        // ДЕФЕКТ #303: вид запроса определяет, применяется ли правило привязки
        // посылок. `refutation` (по умолчанию) — проверка контракта; для
        // `equivalence` контрактных посылок нет, и правило невыполнимо.
        const query_kind: proof_check.QueryKind = blk: {
            const v = flagValue(args, "--query-kind") orelse break :blk .refutation;
            break :blk if (std.mem.eql(u8, v, "equivalence")) .equivalence else .refutation;
        };
        var bridge = z3b.Z3Bridge.init(alloc);
        if (bridge.executeStatus("(check-sat)\n") == .ToolError) {
            fail("[!] z3 недоступен. Добавьте .venv/bin в PATH (uv pip install z3-solver).\n", .{});
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
        // ---- НЕЗАВИСИМАЯ ПЕРЕПРОВЕРКА ВЫВОДА Z3 (пруф-чекер) ----------
        // Не верим `unsat` на слово: разбираем DAG вывода и перепроверяем
        // дыры, привязку посылок, mp, резолюцию, Фаркаша и rewrite.
        {
            var q = compat.BufWriter.init(alloc);
            defer q.deinit();
            const wq = q.writer();
            try wq.writeAll("(set-option :produce-proofs true)\n");
            // 🔴 ДЕФЕКТ #371, причина (A) — найдена на ОФИЦИАЛЬНОМ банке SMT-LIB.
            // ИЗМЕРЕНО: КАЖДЫЙ официальный файл SMT-LIB заканчивается `(exit)`.
            // Старый код писал файл ДОСЛОВНО, поэтому Z3 получал `(exit)` РАНЬШЕ
            // нашего `(get-proof)`, завершался — и вывод не запрашивался вовсе.
            // Пруф-чекер получал пустую строку и отвергал вывод с текстом «не
            // разбирается как S-выражение», то есть обвинял решатель в мусоре.
            // Модельный запрос ниже `(exit)` вырезает с самого начала
            // (`writeWithoutExit`) — здесь правило обязано быть ТЕМ ЖЕ, иначе
            // официальная задача не проверяется вовсе.
            try writeWithoutExit(wq, smt);
            try wq.writeAll("\n(check-sat)\n(get-proof)\n");
            const cap = bridge.executeCapture(q.items());
            defer alloc.free(cap.stdout);
            if (cap.status == .Unsat) {
                // Файл .smt2 может содержать СВОЙ `(check-sat)` — тогда ответов
                // несколько, и первый newline не отделяет вывод. Берём блок
                // вывода после ПОСЛЕДНЕГО `unsat`.
                const up = std.mem.lastIndexOf(u8, cap.stdout, "unsat") orelse 0;
                const st = std.mem.indexOfScalarPos(u8, cap.stdout, up, '(') orelse cap.stdout.len;
                const proof = cap.stdout[st..];
                var ar = std.heap.ArenaAllocator.init(alloc);
                defer ar.deinit();
                const ta = ar.allocator();
                const contract = try proof_check.extractAsserts(ta, smt);
                const pv = try proof_check.verifyProofKindSmt(ta, proof, contract, query_kind, smt);
                std.debug.print("  [i] вид запроса: {s} | привязка посылок обязательна: {s}\n", .{
                    @tagName(query_kind), if (pv.premises_required) "да" else "нет",
                });
                // Печатаем РАЗБИВКУ проверенного: без неё нельзя понять, какие
                // именно шаги остались доверенными (вопрос из METRICS 55.5).
                std.debug.print("  [ПРУФ-ЧЕКЕР] шагов {d} | посылок {d}/{d} | mp {d} | резолюция {d} | Фаркаш {d} | rewrite(лин.) {d} | eq(refl/symm/trans) {d} | bool(and-elim/not-or-elim/mono) {d} | ДОВЕРЕННЫХ {d} | дыр {d}\n", .{
                    pv.proof_steps, pv.premises_bound, pv.premises_total, pv.mp_checked,
                    pv.unitres_checked, pv.farkas_checked, pv.rewrite_verified,
                    pv.eq_verified, pv.bool_verified, pv.trusted_steps, pv.holes,
                });
                if (pv.trusted_steps > 0) {
                    std.debug.print("  [i] первое непроверенное правило: {s} ({d} шт.)\n", .{ pv.first_trusted, pv.trusted_steps });
                }
                if (pv.checksPass() and pv.proof_concludes_false and pv.trusted_steps == 0) {
                    std.debug.print("  [PROOF VERIFIED] steps: {d} | premises bound: {d}/{d} | mp: {d} | rewrite (linear): {d} | farkas: {d} | trusted: {d} | holes: {d}\n", .{
                        pv.proof_steps, pv.premises_bound, pv.premises_total, pv.mp_checked,
                        pv.rewrite_verified, pv.farkas_checked, pv.trusted_steps, pv.holes,
                    });
                } else if (pv.checksPass() and pv.proof_concludes_false) {
                    // 🔴 ДЕФЕКТ #372 (найден гейтом `smtlib-proof-check` на
                    // ОФИЦИАЛЬНОМ банке SMT-LIB). Здесь печаталось
                    // `[PROOF VERIFIED]` при `ДОВЕРЕННЫХ > 0` — метка
                    // «ПОДТВЕРЖДЕНО» стояла на выводе, часть шагов которого
                    // проверена НЕ БЫЛА. ИЗМЕРЕНО на официальных задачах
                    // `QF_BV/20250812-Circt` и `QF_AX/storeinv`: метка выходила
                    // при 5 и 2 970 доверенных шагах. Путь `check-proof` это
                    // правило соблюдал (`trusted_steps == 0`), путь `prove` —
                    // нет: одна и та же проверка называлась по-разному.
                    // Класс тот же, что #370/#371: сообщение говорит не то,
                    // что произошло.
                    std.debug.print("  [PROOF PARTIAL] steps: {d} | premises bound: {d}/{d} | mp: {d} | rewrite (linear): {d} | farkas: {d} | НЕ ПОДТВЕРЖДЕНО: доверенных шагов {d} | holes: {d}\n", .{
                        pv.proof_steps, pv.premises_bound, pv.premises_total, pv.mp_checked,
                        pv.rewrite_verified, pv.farkas_checked, pv.trusted_steps, pv.holes,
                    });
                } else {
                    std.debug.print("  [!] причина: {s}\n", .{pv.failureReason()});
                    fail("[!] ПРУФ-ЧЕКЕР ОТВЕРГ вывод решателя\n", .{});
                }
            }
        }
        // ---- КОНТРПРИМЕР Z3: при `sat` показываем КОНКРЕТНЫЕ значения ------
        // ЗАЧЕМ. Без этого при опровергнутом контракте пользователь и ИИ-агент
        // видят только «НЕ доказано» — но не видят, КАКИЕ входы сломали
        // контракт. Вердикт `F` без контрпримера нельзя использовать.
        //
        // ЛОВУШКА (учтена): запрашивать `(get-model)` при `unsat` НЕЛЬЗЯ —
        // Z3 ответит `(error "model is not available")`. Поэтому запрос идёт
        // ОТДЕЛЬНО и только когда вердикт не «доказано».
        if (r.e_value != 1) {
            var qm = compat.BufWriter.init(alloc);
            defer qm.deinit();
            const wm = qm.writer();
            try wm.writeAll("(set-option :produce-models true)\n");
            // `(exit)` в исходном контракте оборвал бы вывод до `(get-model)`.
            try writeWithoutExit(wm, smt);
            try wm.writeAll("\n(check-sat)\n(get-model)\n");
            const cm = bridge.executeCapture(qm.items());
            defer alloc.free(cm.stdout);
            if (cm.status == .Sat) {
                // ВАЖНО (измерено): Z3 5.1.0 печатает модель БЕЗ обёртки
                // `(model ...)` — сразу `(` и `define-fun`. Поиск по строке
                // "(model" не находил ничего, и контрпример молча получался
                // «пустым». Берём всё после ПОСЛЕДНЕГО `sat`: контракт может
                // содержать СВОЙ `(check-sat)`, и тогда ответов несколько.
                const sp = std.mem.lastIndexOf(u8, cm.stdout, "sat") orelse 0;
                const after = cm.stdout[@min(sp + 3, cm.stdout.len)..];
                var ar2 = std.heap.ArenaAllocator.init(alloc);
                defer ar2.deinit();
                const bindings = model_extract.extract(ar2.allocator(), after) catch &.{};
                if (bindings.len > 0) {
                    // ПУНКТ 2 ПЛАНА v2.5: НЕЗАВИСИМАЯ ПРОВЕРКА SAT-МОДЕЛИ.
                    // Для `UNSAT` мы не верим решателю (proof_check.zig); для
                    // `SAT` тоже не должны: подставляем значения из (get-model)
                    // обратно в `(assert ...)` контракта и вычисляем их в Zig.
                    // Если ассерт ЛОЖЕН — модель фальшивая (ошибка решателя или
                    // НАШЕЙ трансляции), и предъявлять её как контрпример нельзя.
                    var model_ok = true;
                    switch (model_extract.verifyModelAgainstSmt(smt, bindings)) {
                        .ok => |n| std.debug.print(
                            "  [MODEL VERIFIED] все ассерты контракта истинны на модели ({d})\n",
                            .{n},
                        ),
                        .unsupported => |why| std.debug.print(
                            "  [i] проверка модели НЕ выполнена: {s}\n",
                            .{why},
                        ),
                        .spurious => |bad| {
                            model_ok = false;
                            std.debug.print(
                                "  [!] SPURIOUS MODEL: ассерт #{d} ЛОЖЕН на этой модели\n",
                                .{bad.index},
                            );
                            std.debug.print("      ассерт: {s}\n", .{bad.term});
                        },
                    }
                    if (model_ok) {
                        std.debug.print("  [КОНТРПРИМЕР] ", .{});
                        for (bindings, 0..) |b, k| {
                            if (k > 0) std.debug.print(", ", .{});
                            std.debug.print("{s} = {s}", .{ b.name, b.value });
                        }
                        std.debug.print("\n  [COUNTEREXAMPLE] ", .{});
                        for (bindings, 0..) |b, k| {
                            if (k > 0) std.debug.print(", ", .{});
                            std.debug.print("{s} = {s}", .{ b.name, b.value });
                        }
                        std.debug.print("\n", .{});
                    } else {
                        std.debug.print(
                            "  [i] контрпример НЕ предъявляется: он не проходит независимую проверку.\n",
                            .{},
                        );
                    }
                } else {
                    std.debug.print("  [КОНТРПРИМЕР] модель пуста (контракт нарушен, значений нет)\n", .{});
                }
            }
        }
        // ДЕФЕКТ #40 (найден can-fail): CLI печатал «НЕ доказано», но
        // завершался с кодом 0 — `make prove` оставался ЗЕЛЁНЫМ при провале
        // доказательства. Теперь не-доказательство -> exit(2).
        if (r.e_value != 1) {
            fail("[!] КОНТРАКТ НЕ ДОКАЗАН — проверка ПРОВАЛЕНА\n", .{});
        }
        return;
    }

    // ---- audit: контур «математического интеллекта» (SMT-теории) ----
    // САМОСТОЯТЕЛЬНАЯ ПРОВЕРКА ГОТОВОГО ДОКАЗАТЕЛЬСТВА: `kernc check-proof
    // <smt2> <proof>`. Нужна, чтобы пруф-чекер был применим БЕЗ решателя —
    // в частности для адверсариального фаззинга (Испытание А: 30 подделок
    // реального вывода). Код возврата: 0 — вывод ПОДТВЕРЖДЁН (checksPass и
    // вывод `false`), 1 — отвергнут. Любая подделка обязана дать 1.
    if (std.mem.eql(u8, command, "check-proof")) {
        if (args.len < 4) {
            std.debug.print("[!] check-proof: нужны <smt2> и <proof>\n", .{});
            return;
        }
        const smt = try compat.readFileAlloc(alloc, args[2], 1 << 20);
        const proof = try compat.readFileAlloc(alloc, args[3], 1 << 20);
        var ar = std.heap.ArenaAllocator.init(alloc);
        defer ar.deinit();
        const ta = ar.allocator();
        const contract = try proof_check.extractAsserts(ta, smt);
        const pv = try proof_check.verifyProofSmt(ta, proof, contract, smt);
        std.debug.print("  [ПРУФ-ЧЕКЕР] шагов {d} | посылок {d}/{d} | mp {d} | резолюция {d} | Фаркаш {d} | rewrite(лин.) {d} | ДОВЕРЕННЫХ {d} | дыр {d}\n", .{
            pv.proof_steps, pv.premises_bound, pv.premises_total, pv.mp_checked,
            pv.unitres_checked, pv.farkas_checked, pv.rewrite_verified,
            pv.trusted_steps, pv.holes,
        });
        // СТРОГО: «подтверждено» = checksPass И вывод `false` И trusted == 0.
        // Именно это требование проверяет адверсариальный фаззер: любая
        // подделка обязана сломать хотя бы одно из трёх условий.
        if (pv.checksPass() and pv.proof_concludes_false and pv.trusted_steps == 0) {
            std.debug.print("  [PROOF VERIFIED] trusted: {d} | holes: {d}\n", .{ pv.trusted_steps, pv.holes });
        } else {
            std.debug.print("  [!] ОТВЕРГНУТО: {s}\n", .{pv.failureReason()});
            std.process.exit(1);
        }
        return;
    }

    if (std.mem.eql(u8, command, "audit")) {
        var bridge = z3b.Z3Bridge.init(alloc);
        bridge.timeout_ms = 10000;
        if (bridge.executeStatus("(check-sat)\n") == .ToolError) {
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
            const st = bridge.executeStatus(q);
            std.debug.print("[2] ARRAYS (аксиомы Маккарти): независимость ячеек при i≠j — {s}\n", .{if (st == .Unsat) "ДОКАЗАНО" else @tagName(st)});
            const q2 = try eng.buildGuardedSafeQuery("i", 16);
            defer alloc.free(q2);
            const st2 = bridge.executeStatus(q2);
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
            const st = bridge.executeStatus(q);
            std.debug.print("[4] STRINGS (QF_S): '..' проходит при вырезании '/' — {s}\n", .{if (st == .Sat) "УЯЗВИМОСТЬ (контрпример есть)" else @tagName(st)});
            const q2 = try eng.buildZeroByteQuery();
            defer alloc.free(q2);
            const st2 = bridge.executeStatus(q2);
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

    if (std.mem.eql(u8, command, "lia")) {
        // ПУНКТ 1 ПЛАНА v2.5: ВСТРОЕННЫЙ РЕШАТЕЛЬ БЕЗ Z3.
        //   kernc lia <file>   — решить конъюнкцию линейных ограничений.
        // Формат строки: `LE c1:name1 c2:name2 ... k`
        //   означает `c1*name1 + c2*name2 + ... + k <= 0`.
        // Печатает ровно один из трёх вердиктов: UNSAT / SAT <точка> / UNKNOWN <причина>.
        if (args.len < 3) {
            std.debug.print("[!] lia: нужен путь к файлу ограничений\n", .{});
            return;
        }
        const ltext = compat.readFileAlloc(alloc, args[2], 1 << 20) catch {
            std.debug.print("[!] lia: не читается {s}\n", .{args[2]});
            return;
        };
        var lar = std.heap.ArenaAllocator.init(alloc);
        defer lar.deinit();
        const la = lar.allocator();
        var lins: std.ArrayListUnmanaged(builtin_lia.Lin) = .empty;
        var it_lines = std.mem.splitScalar(u8, ltext, '\n');
        while (it_lines.next()) |raw| {
            const line = std.mem.trim(u8, raw, " \t\r");
            if (line.len == 0 or line[0] == '#') continue;
            var toks = std.mem.tokenizeAny(u8, line, " \t");
            const kw = toks.next() orelse continue;
            if (!std.mem.eql(u8, kw, "LE")) {
                std.debug.print("[!] lia: поддерживается только `LE` (получено {s})\n", .{kw});
                return;
            }
            var terms: std.ArrayListUnmanaged(builtin_lia.Term) = .empty;
            var constant: i64 = 0;
            var last_is_const = false;
            while (toks.next()) |tk| {
                last_is_const = true;
                if (std.mem.indexOfScalar(u8, tk, ':')) |cpos| {
                    const cs = tk[0..cpos];
                    const nm = tk[cpos + 1 ..];
                    const cf = std.fmt.parseInt(i64, cs, 10) catch {
                        std.debug.print("[!] lia: плохой коэффициент `{s}`\n", .{cs});
                        return;
                    };
                    terms.append(la, .{ .name = la.dupe(u8, nm) catch return, .coeff = cf }) catch return;
                    last_is_const = false;
                } else {
                    constant = std.fmt.parseInt(i64, tk, 10) catch {
                        std.debug.print("[!] lia: плохая константа `{s}`\n", .{tk});
                        return;
                    };
                }
            }
            if (!last_is_const) {
                std.debug.print("[!] lia: строка без константы: {s}\n", .{line});
                return;
            }
            lins.append(la, .{ .terms = terms.items, .constant = constant }) catch return;
        }
        var lsolver = builtin_lia.Solver.init(alloc);
        defer lsolver.deinit();
        switch (builtin_lia.checkUnsat(&lsolver, lins.items)) {
            .unsat => std.debug.print("UNSAT\n", .{}),
            .unknown => |why| std.debug.print("UNKNOWN {s}\n", .{why}),
            .sat => |pt| {
                std.debug.print("SAT", .{});
                for (pt) |b| std.debug.print(" {s}={d}", .{ b.name, b.value });
                std.debug.print("\n", .{});
            },
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
            const kp = try Ed25519.KeyPair.generateDeterministic(seed_raw[0..32].*);
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
            const bind_ok = std.crypto.timing_safe.eql([32]u8, cert.contract_digest, digest) and
                std.crypto.timing_safe.eql([32]u8, cert.merkle_root, h.root_digest);
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
        std.debug.print("{s} (Zig {s})\n", .{ KERN_VERSION, @import("builtin").zig_version_string });
        std.debug.print("Copyright (c) {s} {s}. All rights reserved.\n", .{ owner.YEAR, owner.AUTHOR });
        std.debug.print("License: PolyForm Noncommercial 1.0.0 / Commercial\n", .{});
        std.debug.print("Owner token: {s}\n", .{owner.OWNER_TOKEN_HEX});
        std.debug.print("Ownership key-lock: {s}\n", .{if (owner.verifyOwnership()) "VALID" else "NOT confirmed"});
        return;
    }

    if (std.mem.eql(u8, command, "pack")) {
        std.debug.print("[pack] Образ собирается командой: kernc build <file.kern> -o out.kimg\n", .{});
        return;
    }

    // ЭШЕЛОН 8, ПУНКТ 40В: `kernc grep <pattern> <image.kimg>` (livegrep-стиль).
    // ИЗМЕРЕНО/ПРИНЦИП: поиск НЕ выполняется по недоверенному образу — сначала
    // заголовок + Merkle-корень (rc=2 при порче), затем обход объектов с
    // распаковкой (`decompressObject` сверяет дайджест по содержимому).
    // rc=0 — есть совпадения, rc=1 — нет, rc=2 — образ повреждён.
    if (std.mem.eql(u8, command, "grep")) {
        if (args.len < 4) fail("[!] Использование: kernc grep <pattern> <image.kimg>\n", .{});
        const pattern = args[2];
        const img_path = args[3];
        if (pattern.len == 0) fail("[!] Пустой шаблон\n", .{});
        const img = compat.readFileAlloc(alloc, img_path, 1 << 28) catch |e| {
            fail("[!] чтение образа: {s}\n", .{@errorName(e)});
        };
        defer alloc.free(img);
        if (img.len < 128) fail("[!] образ слишком мал: {d} байт\n", .{img.len});
        var hb: [128]u8 = undefined;
        @memcpy(&hb, img[0..128]);
        const h = KimgHeader.parse(&hb, img.len) catch |e| {
            fail("[!] образ НЕВАЛИДЕН: {s}\n", .{@errorName(e)});
        };
        // ПОИСК ЗАБЛОКИРОВАН при несовпадении корня: иначе выдача по
        // повреждённому образу вводила бы в заблуждение (rc=2 по условию).
        KimgHeader.verifyMerkleRoot(img, h) catch |e| {
            fail("[!] Merkle-корень НЕ совпал ({s}) — поиск заблокирован\n", .{@errorName(e)});
        };
        var fs = KernFS.mountFromBytes(alloc, img) catch |e| {
            fail("[!] монтирование: {s}\n", .{@errorName(e)});
        };
        defer fs.deinit();
        var hits: usize = 0;
        for (fs.objects) |obj| {
            const nm = fs.objectPath(obj);
            if (std.mem.indexOf(u8, nm, pattern) != null) {
                hits += 1;
                std.debug.print("{s}:0: [имя объекта]\n", .{nm});
            }
            var owned: ?[]u8 = null;
            defer if (owned) |o| alloc.free(o);
            const body: []const u8 = blk: {
                if (obj.compression_codec != 0) {
                    owned = fs.decompressObject(alloc, obj) catch break :blk "";
                    break :blk owned.?;
                }
                break :blk fs.objectPayloadRaw(obj) catch break :blk "";
            };
            var it = std.mem.splitScalar(u8, body, '\n');
            var ln: usize = 0;
            while (it.next()) |line| {
                ln += 1;
                if (std.mem.indexOf(u8, line, pattern) != null) {
                    hits += 1;
                    std.debug.print("{s}:{d}: {s}\n", .{ nm, ln, line });
                }
            }
        }
        std.debug.print("[grep] `{s}`: совпадений {d} (объектов {d})\n", .{ pattern, hits, fs.objects.len });
        if (hits == 0) std.process.exit(1);
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
            fail("[!] Образ слишком мал: {d} байт\n", .{data.len});
        }
        var hb: [128]u8 = undefined;
        @memcpy(&hb, data[0..128]);
        const h = KimgHeader.parse(&hb, data.len) catch |e| {
            fail("[!] Образ НЕВАЛИДЕН: {s}\n", .{@errorName(e)});
        };
        KimgHeader.verifyMerkleRoot(data, h) catch |e| {
            fail("[!] Merkle-корень НЕ совпал: {s}\n", .{@errorName(e)});
        };
        std.debug.print("[OK] Целостность: заголовок + Merkle-корень совпали. Эпоха: {d}.{d}, объектов: {d}\n", .{ h.version_major, h.version_minor, h.object_count });

        // ГЛУБОКАЯ ПРОВЕРКА ДАННЫХ (Эшелон 2, пункт 12 — Data Poisoning / Bit-Rot
        // Guard). ИЗМЕРЕНО хаос-тестом `tools/bitrot_chaos_check.py`: Merkle-корень
        // считается по ХРАНИМЫМ в заголовке дайджестам, поэтому порча САМИХ
        // ДАННЫХ (bit-rot, torn write, подмена чанка) им НЕ ловилась — 11 из 20
        // инъекций проходили незамеченными. Здесь пересчитываем дайджест КАЖДОГО
        // объекта по его байтам: для несжатых — прямая сверка, для сжатых —
        // сверка ПОСЛЕ распаковки (именно её видит потребитель).
        {
            var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
                fail("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            };
            defer fs.deinit();
            var verified: usize = 0;
            for (fs.objects, 0..) |obj, oi| {
                // ДЕФЕКТ #127 (НАЙДЕН хаос-тестом `tools/bitrot_chaos_check.py`).
                // ИМЯ объекта хранится в области данных, но НЕ покрыто ни
                // дайджестом объекта (тот считается по СОДЕРЖИМОМУ), ни
                // Merkle-корнем (тот считается по ДАЙДЖЕСТАМ). ИЗМЕРЕНО: инверсия
                // одного бита в имени (`abs_kern_ab?Broken.smt2`) проходила
                // проверку молча, а объект становился НЕДОСТУПЕН по пути.
                // МИТИГАЦИЯ (не полное исправление): имя обязано состоять из
                // ПЕЧАТАЕМЫХ ASCII. Полное исправление — включать область имён в
                // Merkle-корень (изменение формата, отдельная задача).
                const nm = fs.objectPath(obj);
                if (nm.len == 0) fail("[!] ОБЪЕКТ {d}: ПУСТОЕ имя\n", .{oi});
                for (nm) |ch| {
                    if (ch < 0x20 or ch > 0x7E) {
                        fail("[!] ОБЪЕКТ {d}: ИМЯ ПОВРЕЖДЕНО (непечатаемый байт 0x{X:0>2}) — bit-rot в области имён\n", .{ oi, ch });
                    }
                }
                if (obj.compression_codec == 0) {
                    _ = fs.objectPayload(obj) catch |e| {
                        fail("[!] ОБЪЕКТ {d} ПОВРЕЖДЁН (bit-rot / подмена): {s}\n", .{ oi, @errorName(e) });
                    };
                } else {
                    const buf = fs.decompressObject(alloc, obj) catch |e| {
                        fail("[!] ОБЪЕКТ {d} ПОВРЕЖДЁН (сжатый): {s}\n", .{ oi, @errorName(e) });
                    };
                    alloc.free(buf);
                }
                verified += 1;
            }
            std.debug.print("[OK] ДАННЫЕ: дайджест пересчитан для всех объектов ({d}) — bit-rot не пройдёт\n", .{verified});
        }

    } else if (std.mem.eql(u8, command, "ls")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            fail("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
        };
        defer fs.deinit();
        // ДАННЫЕ команды -> stdout (иначе `kernc ls img > f` даёт пустой файл).
        emitFmt("[L3] Объектов в образе: {d}\n", .{fs.objects.len});
        for (fs.objects) |obj| {
            emitFmt("  type=0x{X:0>4} size={d} path=`{s}`\n", .{ obj.type_id, obj.uncompressed_size, fs.objectPath(obj) });
        }

    } else if (std.mem.eql(u8, command, "cat")) {
        if (args.len < 4) {
            fail("[!] cat: нужен путь, напр. /raw/src/main.zig\n", .{});
        }
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            fail("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
        };
        defer fs.deinit();
        const node = fs.read(args[3]) catch |e| {
            // ПРОЗРАЧНАЯ РАСПАКОВКА: сжатый объект нельзя отдать zero-copy
            // срезом (распаковка требует буфера), поэтому `payloadSlice`
            // возвращает `CompressedNeedsDecompress`. Для пользователя это
            // НЕ должно быть ошибкой: `kernc cat` распаковывает сам.
            if (e == KernFsError.CompressedNeedsDecompress) {
                const want = if (std.mem.startsWith(u8, args[3], "/raw/"))
                    args[3][5..]
                else
                    args[3];
                for (fs.objects) |obj| {
                    if (!std.mem.eql(u8, fs.objectPath(obj), want)) continue;
                    const out_buf = fs.decompressObject(alloc, obj) catch |e2| {
                        fail("[!] распаковка не удалась: {s}\n", .{@errorName(e2)});
                    };
                    defer alloc.free(out_buf);
                    emit(out_buf);
                    return;
                }
                fail("[!] сжатый объект не найден по пути: {s}\n", .{args[3]});
            }
            fail("[!] {s}: {s}\n", .{ args[3], @errorName(e) });
        };
        // СОДЕРЖИМОЕ -> stdout. Это данные, а не диагностика.
        switch (node) {
            .raw_slice => |s| emit(s),
            .virtual_view => |s| emit(s),
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
        // РАСХОЖДЕНИЕ С ЗАЯВЛЕННЫМ СТАТУСОМ (Дефект: `refuted > 0 -> rc=1`
        // ломало `make audits`, где опровергнутые МУТАЦИИ — часть замысла
        // корпуса). Честный критерий тревоги: вердикт решателя ПРОТИВОРЕЧИТ
        // объявленному статусу заявления:
        //   * объявлено `proven`, а формула опровергнута  -> ТРЕВОГА;
        //   * объявлено `refuted`, а формула доказана      -> ТРЕВОГА;
        //   * статус не объявлен (N)                       -> вердикт
        //     информационный, тревоги нет (иначе нельзя было бы проверить
        //     образ с намеренно ложными утверждениями).
        var mismatch: usize = 0;
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

            // ДЕФЕКТ #119: `/raw/` отдаёт ZERO-COPY срез, а для СЖАТОГО объекта
            // (codec 0x02) это сжатые байты — контракт «не находился», и Врата
            // молча деградировали в e=0 на ЛЮБОМ образе с `--deflate`. Поэтому
            // объект ищется напрямую, а при сжатии распаковывается
            // (`decompressObject` сверяет дайджест по распакованному содержимому).
            var owned_payload: ?[]u8 = null;
            defer if (owned_payload) |o| alloc.free(o);
            const payload: []const u8 = blk: {
                for (fs.objects) |co| {
                    if (co.type_id != 0x0002) continue;
                    const cp = fs.objectPath(co);
                    if (!std.mem.eql(u8, cp, contract_path)) continue;
                    if (co.compression_codec != 0) {
                        owned_payload = fs.decompressObject(alloc, co) catch break :blk "";
                        break :blk owned_payload.?;
                    }
                    break :blk fs.objectPayload(co) catch break :blk "";
                }
                break :blk "";
            };
            if (payload.len == 0) {
                std.debug.print("    контракт `{s}` НЕ найден в образе -> e=0 (N)\n", .{contract_path});
                no_contract += 1;
                continue;
            }

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

            // =============================================================
            // ЭШЕЛОН 2, ПУНКТ 9 — PROOF-CARRYING .kimg.
            //
            // Если рядом с контрактом в ТОМ ЖЕ образе лежит его сертификат
            // `<stem>.proof` (текст вывода Z3), проверяем сертификат НАШИМ
            // пруф-чекером — БЕЗ решателя (внешний z3 не вызывается вообще).
            //
            // Сертификат ЕСТЬ, но не сходится (`checksPass` ложно / вывод не
            // `false` / есть доверенные шаги) -> ЖЁСТКИЙ ОТКАЗ: подделка
            // обязана закрывать Врата, а не откатываться молча к Z3.
            // =============================================================
            {
                const stem = if (std.mem.endsWith(u8, contract_path, ".smt2"))
                    contract_path[0 .. contract_path.len - 5]
                else
                    contract_path;
                const cert_path = std.fmt.allocPrint(alloc, "{s}.proof", .{stem}) catch null;
                if (cert_path) |cpath| {
                    defer alloc.free(cpath);
                    var owned_cert: ?[]u8 = null;
                    defer if (owned_cert) |o| alloc.free(o);
                    const cert: []const u8 = blk: {
                        for (fs.objects) |co| {
                            if (co.type_id != 0x0002) continue;
                            if (!std.mem.eql(u8, fs.objectPath(co), cpath)) continue;
                            if (co.compression_codec != 0) {
                                owned_cert = fs.decompressObject(alloc, co) catch break :blk "";
                                break :blk owned_cert.?;
                            }
                            break :blk fs.objectPayload(co) catch break :blk "";
                        }
                        break :blk "";
                    };
                    if (cert.len != 0) {
                        var car = std.heap.ArenaAllocator.init(alloc);
                        defer car.deinit();
                        const ca = car.allocator();
                        const contract_terms = proof_check.extractAsserts(ca, payload) catch &.{};
                        const pv = proof_check.verifyProof(ca, cert, contract_terms) catch null;
                        if (pv) |v| {
                            if (v.checksPass() and v.proof_concludes_false and v.trusted_steps == 0) {
                                proven += 1;
                                std.debug.print("    {s}: [PCC VERIFIED] proof ok ({d} steps) -> e=1 (T)\n", .{ contract_path, v.proof_steps });
                                continue;
                            }
                            refuted += 1;
                            // ПОДДЕЛАННЫЙ СЕРТИФИКАТ — тревога ВСЕГДА, независимо
                            // от объявленного статуса: доказательство заявлено,
                            // но не проходит пруф-чекер.
                            mismatch += 1;
                            std.debug.print("    {s}: [PCC REJECTED] forged proof -> e=0 (F)\n", .{contract_path});
                            continue;
                        }
                    }
                }
            }

            // ДЕФЕКТ #105: только вердикт -> `executeStatus` (без владеемой модели).
            const status = bridge.executeStatus(payload);
            switch (status) {
                .Unsat => {
                    // (assert ...) невыполнимо => утверждение ДОКАЗАНО.
                    proven += 1;
                    // Объявлено `refuted` (bits == 2), а доказано -> РАСХОЖДЕНИЕ.
                    if (bits == 2) mismatch += 1;
                    std.debug.print("    контракт `{s}`: UNSAT -> e=1 (T) ДОКАЗАНО\n", .{contract_path});
                },
                .Sat => {
                    refuted += 1;
                    // Объявлено `proven`/`verified` (bits == 1), а опровергнуто ->
                    // РАСХОЖДЕНИЕ (заявление не подтвердилось).
                    if (bits == 1) mismatch += 1;
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
        std.debug.print("[i] ИТОГ: доказано {d}, контрпримеров {d}, без контракта {d}, РАСХОЖДЕНИЙ С ЗАЯВЛЕННЫМ СТАТУСОМ {d}\n", .{ proven, refuted, no_contract, mismatch });
        std.debug.print("[i] e=1 выставляется ТОЛЬКО по вердикту решателя. Заявления без\n", .{});
        std.debug.print("    привязанного контракта остаются e=0 — это и есть честный статус.\n", .{});
        // ЭШЕЛОН 2, ПУНКТ 9 (+ исправление критерия): тревога — НЕ «есть
        // опровергнутые», а РАСХОЖДЕНИЕ вердикта с ОБЪЯВЛЕННЫМ статусом
        // (или подделанный сертификат). Иначе образ, в котором опровергнутые
        // утверждения — часть замысла (золотой корпус аудитов с мутациями),
        // нельзя было бы проверить вовсе.
        if (mismatch > 0) std.process.exit(1);

    // Ф3.2: CLI над готовым парсером KIMG. Нужен внешнему конформансу
    // (Фаза 5, раздел 10), который умеет работать только с файлами и командами.
    } else if (std.mem.eql(u8, command, "fsck")) {
        if (args.len < 3) {
            std.debug.print("[!] fsck: нужен путь к .kimg\n", .{});
            std.process.exit(2);
        }
        std.process.exit(cli_kimg.fsck(alloc, args[2]));

    } else if (std.mem.eql(u8, command, "inspect")) {
        if (args.len < 3) {
            std.debug.print("[!] inspect: нужен путь к .kimg\n", .{});
            std.process.exit(2);
        }
        std.process.exit(cli_kimg.inspect(alloc, args[2]));

    } else if (std.mem.eql(u8, command, "diff")) {
        if (args.len < 4) {
            std.debug.print("[!] diff: нужны два .kimg\n", .{});
            std.process.exit(2);
        }
        std.process.exit(cli_kimg.diff(alloc, args[2], args[3]));

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
            // Ф3: бюджет — указатели на локальные счётчики. `host_calls_max = 0`
            // означает «VM не имеет права обращаться к хосту вообще».
            var vm_fuel: u32 = fuel;
            var vm_arena: usize = 0;
            var vm_out: usize = 0;
            var vm_depth: u32 = 0;
            var vm_calls: u32 = 0;
            var vm = KernX.initWithBudget(.{
                .fuel = &vm_fuel, .arena = &vm_arena, .arena_max = 1 << 20,
                .output = &vm_out, .output_max = 1 << 20,
                .depth = &vm_depth, .depth_max = 64,
                .host_calls = &vm_calls, .host_calls_max = 0,
            });
            std.debug.print("[KERN-X] байткод `{s}` ({d} б), топливо {d}\n", .{ fs.objectPath(obj), code.len, fuel });
            vm.execute(code) catch |e| {
                std.debug.print("  РЕЗУЛЬТАТ: {s} (остаток топлива {d})\n", .{ @errorName(e), vm_fuel });
                return;
            };
            std.debug.print("  РЕЗУЛЬТАТ: HALT OK (остаток топлива {d})\n", .{vm_fuel});
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
        var buf = compat.BufWriter.init(alloc);
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
        try compat.fileWriteAll(f, buf.items());
        std.debug.print("[OK] agent_packet.json (из образа)\n", .{});

    } else if (std.mem.eql(u8, command, "report")) {
        var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
            std.debug.print("[!] монтирование не удалось: {s}\n", .{@errorName(e)});
            return;
        };
        defer fs.deinit();
        const out_file = try compat.createFile("PROJECT_CANONICAL_SPEC.kern.md", .{});
        defer compat.fileClose(out_file);
        var buf = compat.BufWriter.init(alloc);
        defer buf.deinit();
        const w = buf.writer();
        try w.print("# КАНОНИЧЕСКИЙ ПАСПОРТ KERN\n\n> Сгенерировано kernc ИЗ ОБРАЗА `{s}` ({d} байт).\n\n**Объектов:** {d}\n\n", .{ image_path, data.len, fs.objects.len });
        for (fs.objects) |obj| {
            try w.print("- `type=0x{X:0>4}` size={d} path=`{s}`\n", .{ obj.type_id, obj.uncompressed_size, fs.objectPath(obj) });
        }
        try compat.fileWriteAll(out_file, buf.items());
        std.debug.print("[OK] Отчёт записан ИЗ ОБРАЗА: PROJECT_CANONICAL_SPEC.kern.md\n", .{});

    } else {
        std.debug.print("[!] Неизвестная команда: {s}\n", .{command});
        printUsage();
    }
}

fn printUsage() void {
    std.debug.print(
        \\=======================================================
        \\  KERN Compiler & Formal Engine {s}
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
    , .{KERN_VERSION});
}
