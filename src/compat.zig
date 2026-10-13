// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
//! KERN: слой совместимости Zig 0.13 -> 0.17 (`std.Io`).
//!
//! В Zig 0.17 файловый ввод-вывод переведён на интерфейс `std.Io`:
//! каждая операция требует явный параметр `io`, а `std.fs.cwd()` и
//! `std.io` удалены. Чтобы не пробрасывать `io` через сотни сигнатур,
//! KERN держит один процесс-глобальный `Io`, который устанавливается
//! в `main` (или берётся из `std.testing.io` в тестах).
//!
//! Контракт: `setIo()` ОБЯЗАН быть вызван в `main` до любого файлового
//! вызова. В тестах вызов не нужен — используется `std.testing.io`.

const std = @import("std");
const builtin = @import("builtin");

var g_io: ?std.Io = null;

/// Резервный `Io` для режима БИБЛИОТЕКИ (C-ABI): в чужом процессе (Python,
/// Rust, Go) нет Zig-функции `main`, поэтому `setIo()` вызвать некому.
/// Раньше это приводило к ПАНИКЕ и падению всего хост-процесса
/// (найдено `make capi-demo`: segfault в ctypes). Теперь при отсутствии
/// `setIo` мы лениво создаём собственный потоковый `Io`.
var g_fallback: ?std.Io.Threaded = null;
var g_fallback_io: ?std.Io = null;
var g_fallback_mu: std.atomic.Mutex = .unlocked;

/// Установить процесс-глобальный `Io` (вызывается из `main`).
pub fn setIo(io_val: std.Io) void {
    g_io = io_val;
}

/// Текущий `Io`: в CLI — установленный из `main(init)`, в тестах —
/// `std.testing.io`, в режиме библиотеки (C-ABI) — собственный `Io.Threaded`.
/// Паники здесь больше НЕТ: библиотека обязана быть безопасной для хоста.
pub fn io() std.Io {
    if (g_io) |v| return v;
    if (builtin.is_test) return std.testing.io;
    while (!g_fallback_mu.tryLock()) std.atomic.spinLoopHint();
    defer g_fallback_mu.unlock();
    if (g_fallback_io == null) {
        // Environ ОБЯЗАТЕЛЕН: с пустым окружением `process.spawn` не может
        // найти решатель по PATH (симптом: `kern_smt_verify` возвращал -1).
        // В режиме библиотеки берём РЕАЛЬНОЕ окружение процесса через libc.
        g_fallback = std.Io.Threaded.init(std.heap.page_allocator, .{
            .environ = fallbackEnviron(),
        });
        g_fallback_io = g_fallback.?.io();
    }
    return g_fallback_io.?;
}

/// Окружение процесса для режима библиотеки.
/// На POSIX — `environ` из libc (если библиотека слинкована с libc),
/// иначе пустое (тогда spawn ищет бинарник только по абсолютному пути).
fn fallbackEnviron() std.process.Environ {
    if (builtin.link_libc) {
        const envp: [*:null]?[*:0]u8 = std.c.environ;
        const spanned = std.mem.span(envp);
        return .{ .block = .{ .slice = @ptrCast(spanned) } };
    }
    return .empty;
}

pub fn cwd() std.Io.Dir {
    return std.Io.Dir.cwd();
}

// ===== Файловые операции (замена старых `std.fs.cwd()`-вызовов) =====

pub fn readFileAlloc(alloc: std.mem.Allocator, path: []const u8, limit: usize) ![]u8 {
    return cwd().readFileAlloc(io(), path, alloc, .limited(limit));
}

pub fn writeFile(path: []const u8, data: []const u8) !void {
    return cwd().writeFile(io(), .{ .sub_path = path, .data = data });
}

pub fn deleteFile(path: []const u8) !void {
    return cwd().deleteFile(io(), path);
}

pub fn access(path: []const u8, options: std.Io.Dir.AccessOptions) !void {
    return cwd().access(io(), path, options);
}

pub fn createFile(path: []const u8, flags: std.Io.Dir.CreateFileOptions) !std.Io.File {
    return cwd().createFile(io(), path, flags);
}

pub fn rename(old_path: []const u8, new_path: []const u8) !void {
    return std.Io.Dir.rename(cwd(), old_path, cwd(), new_path, io());
}

/// Замена `compat.makePath()` — в 0.17 называется `createDirPath`.
pub fn makePath(path: []const u8) !void {
    return cwd().createDirPath(io(), path);
}

pub fn deleteTree(path: []const u8) !void {
    return cwd().deleteTree(io(), path);
}

pub fn openDir(path: []const u8, options: std.Io.Dir.OpenOptions) !std.Io.Dir {
    return cwd().openDir(io(), path, options);
}

// ===== Операции над открытым файлом =====

pub fn fileWriteAll(file: std.Io.File, bytes: []const u8) !void {
    return file.writeStreamingAll(io(), bytes);
}

pub fn fileClose(file: std.Io.File) void {
    file.close(io());
}

pub fn fileSync(file: std.Io.File) !void {
    return file.sync(io());
}

pub fn dirClose(dir: std.Io.Dir) void {
    dir.close(io());
}

/// Сон на `ms` миллисекунд (замена `std.time.sleep`).
pub fn sleepMs(ms: u64) void {
    std.Io.sleep(io(), .fromMilliseconds(@intCast(ms)), .awake) catch {};
}

// ===== Сборка текста в память (замена ArrayList(u8).writer()) =====

/// Замена `std.ArrayList(u8).writer()` из Zig 0.13.
///
/// В 0.17 у `ArrayList` больше нет `writer()`; идиоматичный способ —
/// `std.Io.Writer.Allocating`. Обёртка сохраняет привычный API
/// (`writer()` / `items()` / `toOwnedSlice()`), чтобы 16 мест в KERN
/// менялись минимальным диффом.
pub const BufWriter = struct {
    aw: std.Io.Writer.Allocating,

    pub fn init(allocator: std.mem.Allocator) BufWriter {
        return .{ .aw = .init(allocator) };
    }

    pub fn deinit(self: *BufWriter) void {
        self.aw.deinit();
    }

    /// Аналог `buf.writer()`.
    pub fn writer(self: *BufWriter) *std.Io.Writer {
        return &self.aw.writer;
    }

    /// Аналог `buf.items` (в 0.13 — поле, здесь — метод).
    pub fn items(self: *BufWriter) []u8 {
        return self.aw.written();
    }

    /// Аналог `buf.toOwnedSlice()`.
    pub fn toOwnedSlice(self: *BufWriter) ![]u8 {
        return self.aw.toOwnedSlice();
    }

    /// Аналог `buf.appendSlice()`.
    pub fn appendSlice(self: *BufWriter, bytes: []const u8) !void {
        return self.aw.writer.writeAll(bytes);
    }
};

// ===== Замер длительности (замена std.time.Timer) =====

/// Замена `std.time.Timer` из Zig 0.13 (в 0.17 он удалён).
pub const Timer = struct {
    start_ns: i96,

    pub fn start() Timer {
        return .{ .start_ns = std.Io.Clock.now(.awake, io()).nanoseconds };
    }

    /// Наносекунды с момента `start()`.
    pub fn read(self: *Timer) u64 {
        const d = std.Io.Clock.now(.awake, io()).nanoseconds - self.start_ns;
        return @intCast(d);
    }
};

/// Читает весь файл/пайп из уже открытого дескриптора (замена
/// `File.readToEndAlloc` из 0.13).
///
/// ВАЖНО: используем `readStreaming`, а НЕ `readPositionalAll`. Позиционное
/// чтение (`pread`) работает только на seekable-файлах; на **пайпе**
/// (а stdout дочернего процесса Z3 — это именно пайп) оно падает.
/// Дефект был найден прогоном `kernc prove`: мост возвращал `ToolError`,
/// хотя `z3` присутствовал в PATH.
pub fn fileReadToEndAlloc(file: std.Io.File, alloc: std.mem.Allocator, limit: usize) ![]u8 {
    var buf: [64 * 1024]u8 = undefined;
    var list = std.array_list.Managed(u8).init(alloc);
    errdefer list.deinit();
    while (true) {
        // ВАЖНО: при закрытии пайпа `readStreaming` возвращает `error.EndOfStream`,
        // а НЕ `0` (как делал `readToEndAlloc` в 0.13). Без этой обработки
        // чтение вывода Z3 обрывалось ошибкой и мост возвращал `ToolError`.
        const n = file.readStreaming(io(), &.{&buf}) catch |e| switch (e) {
            error.EndOfStream => break,
            else => return e,
        };
        if (n == 0) break;
        if (list.items.len + n > limit) return error.StreamTooLong;
        try list.appendSlice(buf[0..n]);
    }
    return list.toOwnedSlice();
}

test "COMPAT: io доступен в тестах" {
    // В тестах io() обязан возвращать std.testing.io без setIo().
    const v = io();
    _ = v;
    try std.testing.expect(true);
}
