// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: РЕГРЕССИЯ §6b — чтение РЕАЛЬНОГО OS-ПАЙПА (не файла!).
//!
//! ПОВОД (дефект §6b миграции 0.17). Первая версия `compat.fileReadToEndAlloc`
//! использовала позиционное чтение (`pread`) и не обрабатывала `EndOfStream`:
//!   * `pread` на пайпе возвращает `ESPIPE` — а stdout решателя Z3 это ПАЙП,
//!     поэтому `kernc prove` сообщал «z3 недоступен» при живом Z3;
//!   * `readStreaming` при закрытии пайпа возвращает `error.EndOfStream`, а НЕ
//!     `0` (как `readToEndAlloc` в 0.13) — без обработки чтение обрывалось.
//!
//! ПОЧЕМУ ТЕСТ ИМЕННО НА ПАЙПЕ: на обычном файле `pread` РАБОТАЕТ, поэтому
//! регрессия осталась бы незамеченной до первого запуска решателя. Пайп делает
//! ошибку невозможной: он не seekable по определению.
//!
//! ИНВАРИАНТЫ:
//!   I1  чтение не падает с `error.Unseekable` / `ESPIPE`;
//!   I2  `error.EndOfStream` (закрытие писателя) = конец потока;
//!   I3  возвращаются ВСЕ байты, включая объём > буфера пайпа Linux (64 КБ).

const std = @import("std");
const builtin = @import("builtin");
const compat = @import("compat");

/// Объём НЕ кратен странице (4096) и БОЛЬШЕ буфера пайпа Linux (64 КБ),
/// чтобы чтение гарантированно прошло несколько чанков.
const PAYLOAD_LEN: usize = 131_073;

fn makePipe() ?[2]std.posix.fd_t {
    if (builtin.os.tag != .linux) return null;
    var fds: [2]std.posix.fd_t = undefined;
    const rc = std.os.linux.pipe(&fds);
    if (rc != 0) return null;
    return fds;
}

/// Поток-писатель: пишет данные чанками и закрывает свой конец пайпа.
/// Чанки по 4 КБ, потому что буфер пайпа (64 КБ) меньше полезной нагрузки.
const Writer = struct {
    file: std.Io.File,
    data: []const u8,
    written: *std.atomic.Value(usize),
    failed: *std.atomic.Value(bool),

    fn run(self: @This()) void {
        var off: usize = 0;
        while (off < self.data.len) {
            const n = @min(self.data.len - off, 4096);
            compat.fileWriteAll(self.file, self.data[off .. off + n]) catch {
                self.failed.store(true, .release);
                break;
            };
            off += n;
        }
        self.written.store(off, .release);
        compat.fileClose(self.file);
    }
};

test "REG-017-6B: fileReadToEndAlloc на РЕАЛЬНОМ пайпе — не seekable, EndOfStream, без потери хвоста" {
    const fds = makePipe() orelse return error.SkipZigTest;
    const allocator = std.testing.allocator;

    const read_file = std.Io.File{ .handle = fds[0], .flags = .{ .nonblocking = false } };
    const write_file = std.Io.File{ .handle = fds[1], .flags = .{ .nonblocking = false } };
    defer compat.fileClose(read_file);

    // Детерминированная нагрузка (не кратна 4096 и > 64 КБ буфера пайпа).
    const expected = try allocator.alloc(u8, PAYLOAD_LEN);
    defer allocator.free(expected);
    for (expected, 0..) |*b, i| b.* = @truncate((i *% 31 +% 17) & 0xFF);

    var written = std.atomic.Value(usize).init(0);
    var failed = std.atomic.Value(bool).init(false);

    const t = try std.Thread.spawn(.{}, Writer.run, .{Writer{
        .file = write_file,
        .data = expected,
        .written = &written,
        .failed = &failed,
    }});

    // ЧИТАЕМ, ПОКА ПИСАТЕЛЬ РАБОТАЕТ: ровно сценарий Z3 (мост читает stdout
    // ДО `wait()` — иначе возможна взаимная блокировка).
    const actual = compat.fileReadToEndAlloc(read_file, allocator, 8 * 1024 * 1024) catch |e| {
        t.join();
        std.debug.print("  [ПРОВАЛ] чтение пайпа вернуло ошибку: {s}\n", .{@errorName(e)});
        return e;
    };
    defer allocator.free(actual);

    t.join();

    // I1: пайп не seekable — но ошибки нет (иначе не дошли бы сюда).
    try std.testing.expect(!failed.load(.acquire));
    // I3: длина совпадает побайтово (нет потери хвоста на границе чанков).
    try std.testing.expectEqual(PAYLOAD_LEN, actual.len);
    try std.testing.expectEqualSlices(u8, expected, actual);

    std.debug.print(
        "  [OK] пайп: записано {d} Б, прочитано {d} Б, побайтово совпало (чанков по 64 КБ: {d})\n",
        .{ written.load(.acquire), actual.len, (actual.len + 65535) / 65536 },
    );
}

test "REG-017-6B: пустой пайп (немедленный EOF) — пустой срез, НЕ ошибка" {
    const fds = makePipe() orelse return error.SkipZigTest;
    const allocator = std.testing.allocator;

    const read_file = std.Io.File{ .handle = fds[0], .flags = .{ .nonblocking = false } };
    const write_file = std.Io.File{ .handle = fds[1], .flags = .{ .nonblocking = false } };
    defer compat.fileClose(read_file);

    // Закрываем писателя, НЕ записав ни байта: читатель обязан получить
    // `error.EndOfStream` и вернуть пустой срез, а не ошибку.
    compat.fileClose(write_file);

    const actual = try compat.fileReadToEndAlloc(read_file, allocator, 1024);
    defer allocator.free(actual);
    try std.testing.expectEqual(@as(usize, 0), actual.len);
}

test "REG-017-6B: превышение лимита на пайпе — error.StreamTooLong, не паника" {
    const fds = makePipe() orelse return error.SkipZigTest;
    const allocator = std.testing.allocator;

    const read_file = std.Io.File{ .handle = fds[0], .flags = .{ .nonblocking = false } };
    const write_file = std.Io.File{ .handle = fds[1], .flags = .{ .nonblocking = false } };
    defer compat.fileClose(read_file);

    const data = try allocator.alloc(u8, 32 * 1024);
    defer allocator.free(data);
    @memset(data, 0xAB);

    var written = std.atomic.Value(usize).init(0);
    var failed = std.atomic.Value(bool).init(false);
    const t = try std.Thread.spawn(.{}, Writer.run, .{Writer{
        .file = write_file,
        .data = data,
        .written = &written,
        .failed = &failed,
    }});

    // Лимит 1 КБ при нагрузке 32 КБ -> аккуратный отказ.
    const r = compat.fileReadToEndAlloc(read_file, allocator, 1024);
    t.join();

    try std.testing.expectError(error.StreamTooLong, r);
}

