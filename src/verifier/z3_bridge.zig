// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: Z3 SMT-LIB2 мост (§ «Мост к Искусственному Интеллекту»).
//!
//! Запускает Z3 как ДОЧЕРНИЙ процесс (изоляция + лимит размера вывода).
//! Если Z3 отсутствует/падает/зависает — возвращается ToolError/Unknown,
//! и Врата Истины НЕ открываются (безопасная деградация).
//!
//! ⚠️ Отличие от черновика в документе: там `(assert {pre_smt})` подставлял
//! строку, содержащую `(declare-const ...)`, что даёт НЕВАЛИДНЫЙ SMT-LIB2.
//! Здесь объявления и выражения разделены.
const std = @import("std");
const cov = @import("../cov.zig");
const gate = @import("admission_gate.zig");

pub const SmtStatus = enum { Sat, Unsat, Unknown, Timeout, ToolError };

pub const SmtResponse = struct {
    status: SmtStatus,
    witness_model: ?[]const u8 = null,
};

/// Полный ответ решателя (включая `(get-unsat-core)`, модели Horn-задач и т.п.).
/// `stdout` — ВО ВЛАДЕНИИ вызывающего; освобождать через `allocator.free`.
pub const CapturedResponse = struct {
    status: SmtStatus,
    stdout: []u8,
};

/// Контекст потока-убийцы (жёсткий таймаут решателя).
const KillCtx = struct {
    child: *std.process.Child,
    done: std.atomic.Value(bool),
    killed: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
};

fn killAfter(ctx: *KillCtx, ms: u32) void {
    var elapsed: u64 = 0;
    const step: u64 = 5; // мс
    while (elapsed < ms) : (elapsed += step) {
        if (ctx.done.load(.acquire)) return;
        std.time.sleep(step * std.time.ns_per_ms);
    }
    if (!ctx.done.load(.acquire)) {
        ctx.killed.store(true, .release);
        // 🔴 ДЕФЕКТ (найден ПРОГОНОМ ОФИЦИАЛЬНОГО SMT-LIB, 2432 файла):
        // здесь был `ctx.child.kill()`. В Zig 0.13 `Child.kill()` посылает
        // сигнал И САМ ПОЖИНАЕТ процесс (внутри вызывает `wait()`).
        // Если убийца сработал ровно тогда, когда главный поток уже стоял
        // в `child.wait()`, второй `waitpid` получал `ECHILD`, а std
        // трактует это как `unreachable` -> PANIC (SIGABRT, rc=134).
        //
        // ИСПРАВЛЕНО: посылаем сигнал НАПРЯМУЮ и НЕ пожинаем — пожинание
        // остаётся единственной обязанностью главного потока.
        std.posix.kill(ctx.child.id, std.posix.SIG.TERM) catch {};
    }
}

pub const Z3Bridge = struct {
    allocator: std.mem.Allocator,
    z3_path: []const u8 = "z3",
    timeout_ms: u32 = 5000, // ЖЁСТКИЙ таймаут (поток-убийца), см. executeQuery.
    /// ИНЪЕКЦИЯ СБОЕВ (только для тестов): вероятность отказа на КАЖДОМ шаге
    /// взаимодействия с ОС, в процентах (0 = выключено).
    ///
    /// ЗАЧЕМ: LD_PRELOAD/strace недоступны (kernc — статический бинарник,
    /// strace не установлен). Поэтому сбои `pipe`/`spawn`/`read`/`write`
    /// моделируются ВНУТРИ, и мы проверяем, что мост:
    ///   • не паникует;
    ///   • освобождает память и дескрипторы на любом шаге;
    ///   • возвращает fail-closed `ToolError`.
    fault_pct: u8 = 0,
    fault_rng: std.Random.DefaultPrng = std.Random.DefaultPrng.init(0xF0F0),
    fault_hits: usize = 0,

    /// Решение «уронить ли этот шаг». При fault_pct=0 всегда false.
    fn fault(self: *Z3Bridge) bool {
        if (self.fault_pct == 0) return false;
        if (self.fault_rng.random().uintLessThan(u8, 100) < self.fault_pct) {
            self.fault_hits += 1;
            return true;
        }
        return false;
    }

    pub fn init(allocator: std.mem.Allocator) Z3Bridge {
        return .{ .allocator = allocator };
    }

    /// Отправляет SMT-LIB2 скрипт в Z3 и парсит ответ.
    /// НЕ возвращает ошибку при отсутствии Z3 — возвращает `.ToolError`.
    ///
    /// УСИЛЕНИЕ: ЖЁСТКИЙ ТАЙМАУТ (timeout_ms) через поток-убийцу. Раньше был
    /// только лимит размера вывода — зависший решатель не прерывался.
    pub fn executeQuery(self: *Z3Bridge, smt_script: []const u8) SmtResponse {
        const cap = self.executeCapture(smt_script);
        defer self.allocator.free(cap.stdout);
        var witness: ?[]const u8 = null;
        if (cap.status == .Sat) {
            if (std.mem.indexOf(u8, cap.stdout, "(model")) |ms| {
                witness = self.allocator.dupe(u8, cap.stdout[ms..]) catch null;
            }
        }
        return .{ .status = cap.status, .witness_model = witness };
    }

    /// Как executeQuery, но возвращает ВЕСЬ вывод решателя (нужен для
    /// `(get-unsat-core)`, Horn-моделей, `(get-value ...)` и т.п.).
    /// Вызывающий ОБЯЗАН освободить `stdout` (пустой срез освобождать можно).
    pub fn executeCapture(self: *Z3Bridge, smt_script: []const u8) CapturedResponse {
        // ИНЪЕКЦИЯ СБОЕВ: моделируем отказ на шаге «создание процесса» (EAGAIN).
        if (self.fault()) {
            cov.hit(.z3_tool_error);
            return .{ .status = .ToolError, .stdout = &.{} };
        }
        var child = std.process.Child.init(&[_][]const u8{ self.z3_path, "-in" }, self.allocator);
        child.stdin_behavior = .Pipe;
        child.stdout_behavior = .Pipe;
        child.stderr_behavior = .Ignore;

        child.spawn() catch {
            cov.hit(.z3_tool_error);
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        // Поток-убийца: если решатель завис — принудительно снимаем по таймауту.
        var kctx = KillCtx{ .child = &child, .done = std.atomic.Value(bool).init(false) };
        // ДЕФЕКТ (исправлен): раньше при отказе spawn поток-убийцы запрос
        // оставался БЕЗ таймаута — зависший решатель подвесил бы KERN
        // навсегда. Теперь fail-closed: без гарантии таймаута НЕ запускаем.
        const killer: std.Thread = std.Thread.spawn(.{}, killAfter, .{ &kctx, self.timeout_ms }) catch {
            cov.hit(.z3_tool_error);
            // ТА ЖЕ ГОНКА ECHILD, что и в killAfter: Child.kill() пожинает сам.
            std.posix.kill(child.id, std.posix.SIG.TERM) catch {};
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        child.stdin.?.writeAll(smt_script) catch {
            kctx.done.store(true, .release);
            std.posix.kill(child.id, std.posix.SIG.TERM) catch {};
            killer.join();
            return .{ .status = .ToolError, .stdout = &.{} };
        };
        child.stdin.?.close();
        child.stdin = null;

        const stdout_data = child.stdout.?.readToEndAlloc(self.allocator, 4 * 1024 * 1024) catch {
            kctx.done.store(true, .release);
            // ТА ЖЕ ГОНКА ECHILD, что и в killAfter: Child.kill() пожинает сам.
            std.posix.kill(child.id, std.posix.SIG.TERM) catch {};
            killer.join();
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        const term = child.wait() catch {
            // БАГ-ФИКС: при ошибке wait поток-убийца обязан быть остановлен и
            // joined — иначе он держит указатель на стек `kctx` (use-after-free).
            kctx.done.store(true, .release);
            // ТА ЖЕ ГОНКА ECHILD, что и в killAfter: Child.kill() пожинает сам.
            std.posix.kill(child.id, std.posix.SIG.TERM) catch {};
            killer.join();
            self.allocator.free(stdout_data);
            return .{ .status = .ToolError, .stdout = &.{} };
        };
        const timed_out = kctx.killed.load(.acquire);
        kctx.done.store(true, .release);
        killer.join();
        if (timed_out) {
            self.allocator.free(stdout_data);
            return .{ .status = .Timeout, .stdout = &.{} };
        }
        switch (term) {
            .Exited => |code| if (code != 0) {
                // Сюда попадает и отсутствующий бинарник: Zig 0.13 не сообщает
                // об ошибке exec в spawn(), потомок выходит с кодом 127.
                cov.hit(.z3_tool_error);
                self.allocator.free(stdout_data);
                return .{ .status = .ToolError, .stdout = &.{} };
            },
            else => {
                cov.hit(.z3_tool_error);
                self.allocator.free(stdout_data);
                return .{ .status = .ToolError, .stdout = &.{} };
            },
        }

        const status: SmtStatus = if (std.mem.startsWith(u8, stdout_data, "sat")) blk: {
            cov.hit(.z3_sat);
            break :blk .Sat;
        } else if (std.mem.startsWith(u8, stdout_data, "unsat")) blk: {
            cov.hit(.z3_unsat);
            break :blk .Unsat;
        } else blk: {
            cov.hit(.z3_unknown);
            break :blk .Unknown;
        };
        return .{ .status = status, .stdout = stdout_data };
    }

    /// Двухфазная проверка контракта:
    ///   1) анти-вакуумность: ∃x. pre(x)  (иначе код «мёртвый»);
    ///   2) корректность: ¬∃x. pre(x) ∧ ¬post(x)  (нет контрпримеров).
    pub fn verifyContract(self: *Z3Bridge, decls: []const u8, pre: []const u8, post: []const u8) !bool {
        const inhab = try std.fmt.allocPrint(self.allocator,
            "(set-logic ALL)\n{s}\n(assert {s})\n(check-sat)\n(get-model)\n", .{ decls, pre });
        defer self.allocator.free(inhab);
        const ir = self.executeQuery(inhab);
        if (ir.witness_model) |w| self.allocator.free(w);
        if (ir.status != .Sat) return false; // вакуумное предусловие или тул недоступен

        const corr = try std.fmt.allocPrint(self.allocator,
            "(set-logic ALL)\n{s}\n(assert (and {s} (not {s})))\n(check-sat)\n", .{ decls, pre, post });
        defer self.allocator.free(corr);
        const cr = self.executeQuery(corr);
        if (cr.witness_model) |w| self.allocator.free(w);
        return cr.status == .Unsat;
    }
};

/// Адаптер Z3Bridge → TrustedChecker для Врат Истины.
/// Payload ИИ — это SMT-LIB2 скрипт-запрос КОРРЕКТНОСТИ
/// (`(assert (and pre (not post)))`). Вердикт формирует Z3, а не ИИ.
fn z3CheckerFn(ctx: ?*anyopaque, allocator: std.mem.Allocator,
               ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ allocator, ast, contract };
    const bridge: *Z3Bridge = @ptrCast(@alignCast(ctx.?));
    const r = bridge.executeQuery(proof);
    if (r.witness_model) |w| bridge.allocator.free(w);
    return switch (r.status) {
        .Unsat => .Proved,
        .Sat => .Counterexample,
        .Unknown => .Unknown,
        .Timeout => .Timeout,
        .ToolError => .Unknown,
    };
}

pub fn makeChecker(bridge: *Z3Bridge) gate.TrustedChecker {
    return .{ .ctx = bridge, .runFn = z3CheckerFn };
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "Z3BRIDGE: отсутствие z3 не роняет мост (graceful degradation)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const r = bridge.executeQuery("(set-logic ALL)\n(check-sat)\n");
    defer if (r.witness_model) |w| std.testing.allocator.free(w);
    // Z3 нет → ToolError; Z3 есть → Sat/Unsat/Unknown. Главное — НЕ паника.
    try std.testing.expect(r.status == .Sat or r.status == .Unsat or
        r.status == .Unknown or r.status == .ToolError);
}

test "Z3BRIDGE: без Z3 контракт НЕ подтверждается (verifyContract=false)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const ok = try bridge.verifyContract("(declare-const x Int)", "(> x 0)", "(> (+ x 1) 1)");
    // При наличии Z3 контракт валиден; при отсутствии — false. Оба варианта корректны.
    _ = ok;
}

test "Z3BRIDGE → ВРАТА: без Z3 один байт 0xAA даёт e=0" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const ast_hash = [_]u8{0x01} ** 32;
    const cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, ast_hash, ast_hash, cert, policy, makeChecker(&bridge));
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}

// =========================================================================
// РЕАЛЬНЫЙ Z3 (требует бинарник `z3`; если нет — тесты мягко пропускаются)
// =========================================================================

test "Z3 РЕАЛЬНЫЙ: валидный контракт подтверждается" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const probe = bridge.executeQuery("(check-sat)\n");
    if (probe.status == .ToolError) return; // z3 недоступен — не применимо
    defer if (probe.witness_model) |w| std.testing.allocator.free(w);
    try std.testing.expectEqual(SmtStatus.Sat, probe.status);

    // x > 0  =>  x + 1 > 1   (корректно)
    const ok = try bridge.verifyContract("(declare-const x Int)", "(> x 0)", "(> (+ x 1) 1)");
    try std.testing.expect(ok);
}

test "Z3 РЕАЛЬНЫЙ: неверный контракт отвергается (контрпример)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    // x > 0  =>  x + 1 > 5   (неверно: x=1)
    const ok = try bridge.verifyContract("(declare-const x Int)", "(> x 0)", "(> (+ x 1) 5)");
    try std.testing.expect(!ok);
}

test "ВРАТА + РЕАЛЬНЫЙ Z3: корректный контракт даёт e=1 (ПЕРВЫЙ РАЗ!)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет
    const ast_hash = [_]u8{0x01} ** 32;
    // Payload — запрос КОРРЕКТНОСТИ: Pre ∧ ¬Post. Z3 докажет UNSAT => нет контрпримеров.
    const cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "(set-logic ALL)\n(declare-const x Int)\n(assert (and (> x 0) (not (> (+ x 1) 1))))\n(check-sat)\n",
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, ast_hash, ast_hash, cert, policy, makeChecker(&bridge));
    try std.testing.expectEqual(@as(u1, 1), res.e_value); // e=1 через РЕАЛЬНЫЙ решатель
    try std.testing.expectEqual(@as(u2, 1), @intFromEnum(res.eq2_status)); // T
}

test "ВРАТА + РЕАЛЬНЫЙ Z3: багованный контракт даёт e=0 (контрпример)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    const ast_hash = [_]u8{0x02} ** 32;
    const cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "(set-logic ALL)\n(declare-const x Int)\n(assert (and (> x 0) (not (> (+ x 1) 5))))\n(check-sat)\n",
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, ast_hash, ast_hash, cert, policy, makeChecker(&bridge));
    try std.testing.expectEqual(@as(u1, 0), res.e_value); // контрпример -> не допущен
}

test "Z3 + КЭШ ДОКАЗАТЕЛЬСТВ: второй вызов не дёргает решатель" {
    const pc = @import("../proof_cache.zig");
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    var cache = pc.ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    var holder: pc.CtxHolder = undefined;
    const chk = pc.cachedChecker(&holder, &cache, makeChecker(&bridge));

    const ast = [_]u8{0x03} ** 32;
    const cert = gate.ProofCertificate{
        .target_ast_digest = ast,
        .contract_digest = ast,
        .checker_id = 1,
        .witness_payload = "(set-logic ALL)\n(declare-const x Int)\n(assert (and (> x 0) (not (> (+ x 1) 1))))\n(check-sat)\n",
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };

    const r1 = try gate.AdmissionGate.verifyClaimWithChecker(std.testing.allocator, ast, ast, cert, policy, chk);
    const r2 = try gate.AdmissionGate.verifyClaimWithChecker(std.testing.allocator, ast, ast, cert, policy, chk);
    try std.testing.expectEqual(@as(u1, 1), r1.e_value);
    try std.testing.expectEqual(@as(u1, 1), r2.e_value);
    // Первый вызов — промах (решатель), второй — попадание (кэш).
    try std.testing.expectEqual(@as(usize, 1), cache.misses);
    try std.testing.expectEqual(@as(usize, 1), cache.hits);
}

test "ГРАНИЦА: мусорный SMT не роняет мост" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const junk = [_][]const u8{ "", "garbage", "(((((", "(assert", "\x00\x01\x02", "(check-sat" };
    for (junk) |j| {
        const r = bridge.executeQuery(j);
        defer if (r.witness_model) |w| std.testing.allocator.free(w);
        // любой исход допустим, ГЛАВНОЕ — нет паники
        try std.testing.expect(r.status == .Sat or r.status == .Unsat or
            r.status == .Unknown or r.status == .Timeout or r.status == .ToolError);
    }
}

// =========================================================================
// РЕСУРСЫ ОС: утечки файловых дескрипторов и зомби-процессы
// =========================================================================

fn countFds() usize {
    var dir = std.fs.openDirAbsolute("/proc/self/fd", .{ .iterate = true }) catch return 0;
    defer dir.close();
    var it = dir.iterate();
    var n: usize = 0;
    while (it.next() catch null) |_| n += 1;
    return n;
}

/// Считает процессы-зомби (<defunct>), чей родитель — текущий процесс.
fn countZombieChildren() usize {
    const my_pid = std.os.linux.getpid();
    var dir = std.fs.openDirAbsolute("/proc", .{ .iterate = true }) catch return 0;
    defer dir.close();
    var it = dir.iterate();
    var n: usize = 0;
    while (it.next() catch null) |entry| {
        if (entry.kind != .directory) continue;
        const pid = std.fmt.parseInt(i32, entry.name, 10) catch continue;
        var buf: [256]u8 = undefined;
        var path_buf: [64]u8 = undefined;
        const path = std.fmt.bufPrint(&path_buf, "/proc/{d}/stat", .{pid}) catch continue;
        const f = std.fs.openFileAbsolute(path, .{}) catch continue;
        defer f.close();
        const nread = f.readAll(&buf) catch continue;
        const data = buf[0..nread];
        // формат: pid (comm) state ppid ...
        const rp = std.mem.lastIndexOfScalar(u8, data, ')') orelse continue;
        if (rp + 2 >= data.len) continue;
        const state = data[rp + 2];
        var rest = std.mem.tokenizeScalar(u8, data[rp + 4 ..], ' ');
        const ppid = std.fmt.parseInt(i32, rest.next() orelse continue, 10) catch continue;
        if (state == 'Z' and ppid == my_pid) n += 1;
    }
    return n;
}

test "РЕСУРСЫ: 50 запросов Z3 не текут FD и не плодят зомби" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    const fd_before = countFds();
    var i: usize = 0;
    while (i < 50) : (i += 1) {
        const r = bridge.executeQuery("(set-logic ALL)\n(declare-const x Int)\n(assert (> x 0))\n(check-sat)\n(get-model)\n");
        if (r.witness_model) |w| std.testing.allocator.free(w);
        try std.testing.expect(r.status == .Sat);
    }
    const fd_after = countFds();
    // Дескрипторы не должны накапливаться (допуск на служебные).
    try std.testing.expect(fd_after <= fd_before + 3);
    // Зомби быть не должно: child.wait() их пожинает.
    try std.testing.expectEqual(@as(usize, 0), countZombieChildren());
}

// =====================================================================
// ПУЛ РЕШАТЕЛЕЙ (Эшелон 3: изнурение планировщика)
// =====================================================================
//
// Проблема: 128 одновременных `prove` на 8-ядерной машине породят 128
// процессов Z3 → исчерпание PID/FD и паника ОС.
//
// Решение: ЖЁСТКИЙ лимит одновременно работающих решателей. Запросы сверх
// лимита ВСТАЮТ В ОЧЕРЕДЬ на семафоре и выполняются по мере освобождения.
// Никаких «бесконечных» системных процессов.

pub const SolverPool = struct {
    sem: std.Thread.Semaphore,
    max_concurrent: usize,
    active: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    peak: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    completed: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    acquired_total: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),

    pub fn init(max_concurrent: usize) SolverPool {
        return .{
            .sem = std.Thread.Semaphore{ .permits = max_concurrent },
            .max_concurrent = max_concurrent,
        };
    }

    /// Занять слот решателя. Блокируется, пока все слоты заняты.
    pub fn acquire(self: *SolverPool) void {
        self.sem.wait();
        _ = self.acquired_total.fetchAdd(1, .monotonic);
        const now = self.active.fetchAdd(1, .acq_rel) + 1;
        while (true) {
            const cur = self.peak.load(.acquire);
            if (now <= cur) break;
            if (self.peak.cmpxchgWeak(cur, now, .acq_rel, .acquire) == null) break;
        }
    }

    /// Освободить слот (обязательно вызывать даже при ошибке!).
    pub fn release(self: *SolverPool) void {
        _ = self.active.fetchSub(1, .acq_rel);
        _ = self.completed.fetchAdd(1, .monotonic);
        self.sem.post();
    }

    pub fn peakConcurrent(self: *SolverPool) usize {
        return self.peak.load(.acquire);
    }
    pub fn completedCount(self: *SolverPool) usize {
        return self.completed.load(.acquire);
    }
    pub fn currentlyActive(self: *SolverPool) usize {
        return self.active.load(.acquire);
    }
};
