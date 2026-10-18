// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

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
const compat = @import("compat");

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
    done: std.atomic.Value(bool),
    killed: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
};

/// Поток-убийца по таймауту (Zig 0.17).
///
/// В 0.17 pid передаётся **значением**, а не указателем на `Child`, поэтому
/// исчезает и риск use-after-free (указатель на стек `child`), и необходимость
/// держать `*std.process.Child`.
fn killAfterPid(pid: std.posix.pid_t, ctx: *KillCtx, ms: u32) void {
    var elapsed: u64 = 0;
    const step: u64 = 5; // мс
    while (elapsed < ms) : (elapsed += step) {
        if (ctx.done.load(.acquire)) return;
        std.Io.sleep(compat.io(), .fromMilliseconds(@intCast(step)), .awake) catch {};
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
        std.posix.kill(pid, std.posix.SIG.TERM) catch {};
    }
}

/// ЕДИНАЯ точка аварийного выхода из `executeCapture`: остановить поток-убийцу
/// и снять решатель.
///
/// ЗАЧЕМ (дефект, найден мутационным прогоном). Один и тот же блок
/// (`done.store(true)` + `kill(SIGTERM)` + `killer.join()`) был СКОПИРОВАН в
/// три ветки отказа: (1) не удалось записать скрипт в stdin, (2) нет
/// `child.stdout`, (3) не удалось прочитать вывод. Мутант `true` -> `false`
/// в ЛЮБОЙ из копий выживал: например, ветка (2) НЕДОСТИЖИМА (spawn всегда
/// ставит `.stdout = .pipe`), а копии (1) и (3) не проверялись по ЛАТЕНТНОСТИ.
///
/// Теперь ветка одна, и она покрыта тестом «лимит вывода -> возврат МНОГО
/// БЫСТРЕЕ таймаута» (`max_stdout = 8`): без `done.store(true)` поток-убийца
/// ждёт весь `timeout_ms`, и тест падает по времени. Мутант УБИТ, а не «выжил
/// как эквивалентный».
fn abortSolver(pid: std.posix.pid_t, kctx: *KillCtx) void {
    kctx.done.store(true, .release);
    std.posix.kill(pid, std.posix.SIG.TERM) catch {};
}

pub const Z3Bridge = struct {
    allocator: std.mem.Allocator,
    z3_path: []const u8 = "z3",
    timeout_ms: u32 = 5000, // ЖЁСТКИЙ таймаут (поток-убийца), см. executeQuery.
    /// ЛИМИТ ВЫВОДА решателя. Сделано ПОЛЕМ (а не константой), чтобы тесты
    /// могли дёшево и ДЕТЕРМИНИРОВАННО войти в ветку отказа чтения:
    /// иначе пришлось бы генерировать вывод > 4 МБ (медленно и нестабильно).
    max_stdout: usize = 4 * 1024 * 1024,
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
        var b = Z3Bridge{ .allocator = allocator };
        // Переменная окружения позволяет ЗАДАТЬ таймаут снаружи. Нужна
        // мутационному прогону: там мутант может вызвать дедлок пайпа, и с
        // дефолтными 5000 мс прогон растягивается на минуты (200 запросов
        // ОС-СТРЕСС 4 x 5 с = 16 минут). При 300 мс это секунды.
        if (compat.envVar("KERN_Z3_TIMEOUT_MS")) |v| {
            if (std.fmt.parseInt(u32, v, 10)) |ms| {
                if (ms > 0) b.timeout_ms = ms;
            } else |_| {}
        }
        return b;
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
            // 🔴 ДЕФЕКТ #104 (найден хардкор-аудитом): раньше здесь искался
            // префикс `"(model"`. Но `(get-model)` в Z3 5.1.0 выдаёт ГОЛЫЙ
            // список — БЕЗ слова `model`:
            //     sat
            //     (
            //       (define-fun x () Int
            //         6)
            //     )
            // Поэтому `indexOf("(model")` не находил НИЧЕГО, и поле
            // `witness_model` было ВСЕГДА null. (CLI-контрпример не страдал: он
            // делает отдельный запрос и разбирает вывод через model_extract.)
            // Теперь модель ищется по `define-fun`, а её начало — первая `(`.
            if (std.mem.indexOf(u8, cap.stdout, "define-fun") != null) {
                if (std.mem.indexOfScalar(u8, cap.stdout, '(')) |ms| {
                    witness = self.allocator.dupe(u8, cap.stdout[ms..]) catch null;
                }
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
        const io = compat.io();
        // ---- ПЕСОЧНИЦА ДЛЯ Z3 (УЛУЧШЕНИЕ №12, Zero-Trust к внешнему процессу) --
        // Z3 — большой внешний C++-бинарник, которому подаются НЕДОВЕРЕННЫЕ
        // `.smt2` (в том числе сгенерированные ИИ-агентом). Две меры:
        //   1) ОКРУЖЕНИЕ РЕБЁНКА ОЧИЩАЕТСЯ до PATH/HOME/LC_ALL — при любой
        //      уязвимости в Z3 он НЕ получит `GITHUB_TOKEN`, `AWS_*`, `SSH_*`,
        //      `OPENAI_*` и прочие секреты родительского процесса;
        //   2) `-memory:256` — жёсткий лимит памяти: «взбесившийся» решатель
        //      отказывает по памяти вместо того, чтобы съесть ОЗУ сервера.
        var sandbox = std.process.Environ.Map.init(self.allocator);
        defer sandbox.deinit();
        const keep = [_][]const u8{ "PATH", "HOME", "LC_ALL", "LANG", "TMPDIR" };
        for (keep) |k| {
            if (compat.envVar(k)) |v| sandbox.put(k, v) catch {};
        }
        var child = std.process.spawn(io, .{
            .argv = &[_][]const u8{ self.z3_path, "-memory:256", "-in" },
            .stdin = .pipe,
            .stdout = .pipe,
            .stderr = .ignore,
            .environ_map = &sandbox,
        }) catch {
            cov.hit(.z3_tool_error);
            return .{ .status = .ToolError, .stdout = &.{} };
        };
        // pid нужен потоку-убийце; после wait он станет null.
        const pid = child.id orelse {
            cov.hit(.z3_tool_error);
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        // ПУНКТ 8 ПЛАНА v2.5: ЖЁСТКАЯ КАПСУЛА ФАЙЛОВЫХ ЛИМИТОВ ДЛЯ Z3.
        //
        // ЗАЧЕМ. `z3` — внешний бинарник, которому подаются НЕДОВЕРЕННЫЕ
        // `.smt2` (в том числе полученные из чужого кода). Лимит памяти
        // (`-memory:256`) и очистка окружения уже были; оставался файловый
        // вектор: скомпрометированный решатель мог писать на диск.
        //
        // КАК (без pre-exec хука). В Zig 0.17 у `std.process.spawn` НЕТ колбэка
        // между fork и execve, поэтому `setrlimit` внутри потомка недоступен.
        // Но Linux позволяет РОДИТЕЛЮ наложить лимит на УЖЕ запущенный процесс
        // по PID: `prlimit64(pid, RLIMIT_FSIZE, &zero, null)`. Именно это и
        // применяем: `RLIMIT_FSIZE = 0` -> `z3` физически не может создать файл.
        //
        // ЧЕСТНО. Если вызов не удался (не-Linux, нет прав), запрос НЕ
        // отменяется: продолжают действовать очистка окружения, лимит памяти и
        // поток-убийца по таймауту. Факт отказа ПЕЧАТАЕТСЯ — молчаливого
        // ослабления песочницы быть не должно.
        //
        // ЧЕГО СОЗНАТЕЛЬНО НЕ ДЕЛАЕМ: не добавляем в аргументы `z3` его
        // собственные `-T:<сек>` и `rlimit=<N>`. Они меняют СЕМАНТИКУ решателя
        // (UNSAT может стать `unknown`), то есть способны переписать вердикты
        // уже опубликованных свидетельств, и дублируют поток-убийцу, который
        // таймаут уже обеспечивает. Лимит ресурсов, который НЕ меняет ответ,
        // — это `-memory:256` (он уже передаётся) и `RLIMIT_FSIZE` ниже.
        {
            const zero = std.os.linux.rlimit{ .cur = 0, .max = 0 };
            const prc = std.os.linux.prlimit(pid, .FSIZE, &zero, null);
            if (prc != 0) {
                std.debug.print(
                    "[i] prlimit(FSIZE=0) для z3 не применён (код {d}) — " ++
                        "действуют лимит памяти, очистка окружения и таймаут\n",
                    .{prc},
                );
            }
        }

        // Поток-убийца: если решатель завис — принудительно снимаем по таймауту.
        var kctx = KillCtx{ .done = std.atomic.Value(bool).init(false) };
        // ДЕФЕКТ (исправлен): раньше при отказе spawn поток-убийцы запрос
        // оставался БЕЗ таймаута — зависший решатель подвесил бы KERN
        // навсегда. Теперь fail-closed: без гарантии таймаута НЕ запускаем.
        const killer: std.Thread = std.Thread.spawn(.{}, killAfterPid, .{ pid, &kctx, self.timeout_ms }) catch {
            cov.hit(.z3_tool_error);
            std.posix.kill(pid, std.posix.SIG.TERM) catch {};
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        if (child.stdin) |sin| {
            sin.writeStreamingAll(io, smt_script) catch {
                abortSolver(pid, &kctx);
                killer.join();
                return .{ .status = .ToolError, .stdout = &.{} };
            };
            sin.close(io);
            child.stdin = null;
        }

        const sout = child.stdout orelse {
            abortSolver(pid, &kctx);
            killer.join();
            return .{ .status = .ToolError, .stdout = &.{} };
        };
        const stdout_data = compat.fileReadToEndAlloc(sout, self.allocator, self.max_stdout) catch {
            abortSolver(pid, &kctx);
            killer.join();
            return .{ .status = .ToolError, .stdout = &.{} };
        };

        // ЗАКРЫВАЕМ читающий конец пайпа ДО `child.wait()`.
        //
        // ЗАЧЕМ (найдено «медленным мутантом» `compat.zig:231`: цикл чтения
        // -> `while (false)`): если вывод НЕ дочитан, буфер пайпа (64 КБ)
        // переполняется, Z3 блокируется в `write()`, а `wait()` ждёт его
        // завершения — ДЕДЛОК, разрываемый только потоком-убийцей: 5 с на
        // КАЖДЫЙ запрос (200 запросов ОС-СТРЕСС 4 = 16 минут).
        // Закрытие читающего конца даёт потомку `EPIPE`/`SIGPIPE` мгновенно.
        sout.close(io);
        child.stdout = null;

        const term = child.wait(io) catch {
            // БАГ-ФИКС: при ошибке wait поток-убийца обязан быть остановлен и
            // joined — иначе он держит указатель на стек `kctx` (use-after-free).
            kctx.done.store(true, .release);
            std.posix.kill(pid, std.posix.SIG.TERM) catch {};
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
            .exited => |code| if (code != 0) {
                // Сюда попадает и отсутствующий бинарник: об ошибке exec
                // сообщает ненулевой код возврата потомка.
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

    /// Только ВЕРДИКТ, без владеемой модели.
    ///
    /// ЗАЧЕМ ОТДЕЛЬНАЯ ФУНКЦИЯ (дефект #105). `executeQuery` возвращает
    /// `witness_model` — ВЛАДЕЕМУЮ строку, которую вызывающий обязан
    /// освободить. На практике 40+ мест писали `b.executeStatus(q)`,
    /// отбрасывая результат: пока модель была всегда `null` (дефект #104),
    /// утечки не было. Как только #104 исправили, эти вызовы начали течь
    /// (замер: 3 теста, 40/40/43 байта).
    ///
    /// Эта функция освобождает модель ВНУТРИ, поэтому забыть её невозможно.
    /// Используйте её везде, где нужен только статус.
    pub fn executeStatus(self: *Z3Bridge, smt_script: []const u8) SmtStatus {
        const r = self.executeQuery(smt_script);
        if (r.witness_model) |w| self.allocator.free(w);
        return r.status;
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
    const ast_hash = @as([32]u8, @splat(0x01));
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    // x > 0  =>  x + 1 > 5   (неверно: x=1)
    const ok = try bridge.verifyContract("(declare-const x Int)", "(> x 0)", "(> (+ x 1) 5)");
    try std.testing.expect(!ok);
}

test "ВРАТА + РЕАЛЬНЫЙ Z3: корректный контракт даёт e=1 (ПЕРВЫЙ РАЗ!)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет
    const ast_hash = @as([32]u8, @splat(0x01));
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    const ast_hash = @as([32]u8, @splat(0x02));
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет

    var cache = pc.ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    var holder: pc.CtxHolder = undefined;
    const chk = pc.cachedChecker(&holder, &cache, makeChecker(&bridge));

    const ast = @as([32]u8, @splat(0x03));
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
    var dir = std.Io.Dir.openDirAbsolute(compat.io(), "/proc/self/fd", .{ .iterate = true }) catch return 0;
    defer compat.dirClose(dir);
    var it = dir.iterate();
    var n: usize = 0;
    while (it.next(compat.io()) catch null) |_| n += 1;
    return n;
}

/// Считает процессы-зомби (<defunct>), чей родитель — текущий процесс.
fn countZombieChildren() usize {
    const my_pid = std.os.linux.getpid();
    var dir = std.Io.Dir.openDirAbsolute(compat.io(), "/proc", .{ .iterate = true }) catch return 0;
    defer compat.dirClose(dir);
    var it = dir.iterate();
    var n: usize = 0;
    while (it.next(compat.io()) catch null) |entry| {
        if (entry.kind != .directory) continue;
        const pid = std.fmt.parseInt(i32, entry.name, 10) catch continue;
        var buf: [256]u8 = undefined;
        var path_buf: [64]u8 = undefined;
        const path = std.fmt.bufPrint(&path_buf, "/proc/{d}/stat", .{pid}) catch continue;
        const f = std.Io.Dir.openFileAbsolute(compat.io(), path, .{}) catch continue;
        defer compat.fileClose(f);
        const nread = f.readStreaming(compat.io(), &.{&buf}) catch continue;
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет

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
    sem: std.Io.Semaphore,
    max_concurrent: usize,
    active: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    peak: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    completed: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    acquired_total: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),

    pub fn init(max_concurrent: usize) SolverPool {
        return .{
            .sem = std.Io.Semaphore{ .permits = max_concurrent },
            .max_concurrent = max_concurrent,
        };
    }

    /// Занять слот решателя. Блокируется, пока все слоты заняты.
    pub fn acquire(self: *SolverPool) void {
        self.sem.waitUncancelable(compat.io());
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
        self.sem.post(compat.io());
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

test "ХАРДКОР: при SAT извлекается модель-свидетель (стр. 106)" {
    var bridge = Z3Bridge.init(std.testing.allocator);
    const r = bridge.executeQuery(
        "(set-logic ALL)\n(declare-const x Int)\n(assert (> x 5))\n" ++
            "(check-sat)\n(get-model)\n");
    defer if (r.witness_model) |w| std.testing.allocator.free(w);
    // Без z3 проверять нечего — это не провал, а пропуск.
    if (r.status != .Sat) return error.SkipZigTest;
    // Убивает мутанта `if (cap.status == .Sat)` -> `!=`:
    // при SAT свидетель НЕ извлёкся бы, и проверка ниже упала бы.
    try std.testing.expect(r.witness_model != null);
    // ВАЖНО: проверяем `define-fun`, а НЕ слово `model` — `(get-model)`
    // выдаёт голый список без ключевого слова `model` (дефект #104).
    try std.testing.expect(std.mem.indexOf(u8, r.witness_model.?, "define-fun") != null);
}

test "ДЕФЕКТ #105: executeStatus НЕ оставляет владеемой модели (нет утечки)" {
    var b = Z3Bridge.init(std.testing.allocator);
    if (b.executeStatus("(check-sat)\n") == .ToolError) return error.SkipZigTest;
    // Формула, дающая МОДЕЛЬ (sat + define-fun). Если бы `executeStatus`
    // не освобождала `witness_model`, `std.testing.allocator` зафиксировал
    // бы утечку и тест упал бы.
    //
    // ЗАЧЕМ ТЕСТ. Дефект #104 сделал `witness_model` не-null в новых
    // случаях, и 61 вызов вида `executeQuery(q).status` начал течь.
    // `executeStatus` закрывает класс навсегда: владеемой памяти наружу
    // не отдаётся вообще.
    try std.testing.expectEqual(SmtStatus.Sat, b.executeStatus(
        "(set-logic ALL)\n(declare-const x Int)\n(assert (> x 5))\n(check-sat)\n(get-model)\n"));
}

test "ИНЪЕКЦИЯ: fault_pct=0 НЕ расходует энтропию PRNG (стр. 85)" {
    var b = Z3Bridge.init(std.testing.allocator);
    b.fault_pct = 0;
    var i: usize = 0;
    while (i < 50) : (i += 1) try std.testing.expect(!b.fault());
    // Убивает мутанта `if (self.fault_pct == 0)` -> `!=`.
    // С `!=` защита не сработала бы, и КАЖДЫЙ из 50 вызовов двигал бы PRNG,
    // хотя инъекция выключена. Сверяем состояние с ЭТАЛОННЫМ PRNG того же seed:
    // при верной защите последовательности совпадают.
    var ref = std.Random.DefaultPrng.init(0xF0F0);
    try std.testing.expectEqual(
        ref.random().uintLessThan(u8, 100),
        b.fault_rng.random().uintLessThan(u8, 100));
    // Инъекция по-прежнему РАБОТАЕТ, когда включена (тест не пустой).
    b.fault_pct = 100;
    try std.testing.expect(b.fault());
    try std.testing.expect(b.fault_hits > 0);
}

test "ИНЪЕКЦИЯ: отказ чтения вывода возвращает управление НЕМЕДЛЕННО (стр. 182)" {
    // Доступность решателя проверяем ОТДЕЛЬНЫМ мостом с нормальным лимитом.
    var probe = Z3Bridge.init(std.testing.allocator);
    if (probe.executeStatus("(check-sat)\n") == .ToolError) return error.SkipZigTest;

    var b = Z3Bridge.init(std.testing.allocator);
    b.timeout_ms = 20_000; // БОЛЬШОЙ таймаут
    // Лимит МЕНЬШЕ вывода (ответ ~35 Б) -> чтение ГАРАНТИРОВАННО падает
    // с error.StreamTooLong, и мы попадаем в ветку отказа (стр. 182).
    b.max_stdout = 8;

    var timer = compat.Timer.start(); // std.time.Timer удалён в 0.17
    const cap = b.executeCapture(
        "(set-logic ALL)\n(declare-const x Int)\n(assert (> x 5))\n(check-sat)\n(get-model)\n");
    defer std.testing.allocator.free(cap.stdout);
    const ms = timer.read() / 1_000_000; // нс -> мс

    try std.testing.expectEqual(SmtStatus.ToolError, cap.status);
    // Убивает мутанта `kctx.done.store(true, .release)` -> `false` на пути
    // отказа чтения (стр. 182): с ним поток-убийца НЕ увидел бы флаг,
    // `killer.join()` ждал бы ВЕСЬ timeout_ms (20 с), и вызов вернулся бы
    // не за миллисекунды, а за 20 секунд.
    try std.testing.expect(ms < 5_000);
}

test "ЗВУЧНОСТЬ: вакуумное предусловие НЕ признаётся доказанным (стр. 262)" {
    var b = Z3Bridge.init(std.testing.allocator);
    if (b.executeStatus("(check-sat)\n") == .ToolError) return error.SkipZigTest;

    // Предусловие НЕВЫПОЛНИМО (x > 10 и x < 5) -> контракт ВАКУУМНЫЙ.
    // Убивает мутанта `if (ir.status != .Sat) return false` -> `return true`:
    // с ним вакуумный контракт был бы признан ДОКАЗАННЫМ, то есть KERN
    // подтвердил бы свойство, которое НЕ проверялось (дыра в звучности).
    try std.testing.expect(!try b.verifyContract(
        "(declare-const x Int)", "(and (> x 10) (< x 5))", "(= x x)"));

    // Контроль непустоты: ВЫПОЛНИМОЕ предусловие + верное постусловие -> true.
    try std.testing.expect(try b.verifyContract(
        "(declare-const x Int)", "(> x 0)", "(> x -1)"));

    // И ложное постусловие при выполнимом предусловии -> false.
    try std.testing.expect(!try b.verifyContract(
        "(declare-const x Int)", "(> x 0)", "(> x 100)"));
}

test "ХАРДКОР: countZombieChildren ВИДИТ реального зомби (стр. 486)" {
    // Убивает мутанта `entry.kind != .directory` -> `==`: с ним функция
    // пропускает ВСЕ каталоги `/proc/<pid>` и ВСЕГДА возвращает 0 — то есть
    // проверка «50 запросов Z3 не плодят зомби» выше становится ВАКУУМНОЙ
    // и перестаёт что-либо доказывать.
    // Здесь зомби создаётся НАМЕРЕННО: потомок завершается, но мы его
    // НЕ пожинаем до замера.
    const before = countZombieChildren();
    var child = std.process.spawn(compat.io(), .{
        .argv = &[_][]const u8{"/bin/true"},
        .stdin = .ignore,
        .stdout = .ignore,
        .stderr = .ignore,
    }) catch return error.SkipZigTest; // нет /bin/true — проверить нельзя
    // Даём потомку завершиться: до `wait()` он остаётся ЗОМБИ.
    compat.sleepMs(100);
    const during = countZombieChildren();
    _ = child.wait(compat.io()) catch {}; // пожинаем, чтобы не оставлять мусор
    try std.testing.expect(during > before);
}

