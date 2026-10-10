const std = @import("std");
const kimg = @import("object_entry.zig"); // 96-байтный дескриптор
const Eq2 = @import("eq2.zig").Eq2;       // KERN-EQ2 математика

pub const KernFsError = error{
    PathTraversalAttempt, // CONF-13: запрет ..
    InvalidPathFormat,    // запрет пустых компонент и .
    FileNotFound,
    AccessDenied,         // CONF-06: запрет на запись
};

/// Результат запроса к виртуальной ФС
pub const VfsNode = union(enum) {
    raw_slice: []const u8,    // Zero-Copy срез из mmap (для исходников)
    virtual_view: []const u8, // сгенерированный ответ (для статусов и отчётов)
};

pub const KernFS = struct {
    allocator: std.mem.Allocator,
    mmap_slice: []const u8,
    objects: []const kimg.ObjectEntry,
    string_pool: []const u8,

    pub fn init(allocator: std.mem.Allocator, mmap_slice: []const u8,
                objects: []const kimg.ObjectEntry, string_pool: []const u8) KernFS {
        return .{
            .allocator = allocator,
            .mmap_slice = mmap_slice,
            .objects = objects,
            .string_pool = string_pool,
        };
    }

    /// CONF-13: строгая валидация пути. Запрет path traversal.
    ///
    /// ПРОВЕРЕНО: все четыре отказа работают (нет ведущего `/`, `//`, `.`, `..`).
    pub fn validatePath(path: []const u8) !void {
        if (path.len == 0 or path[0] != '/') return KernFsError.InvalidPathFormat;

        var it = std.mem.split(u8, path, "/");
        _ = it.next(); // пропуск первого пустого токена (из-за ведущего слеша)

        while (it.next()) |component| {
            if (component.len == 0) return KernFsError.InvalidPathFormat; // //
            if (std.mem.eql(u8, component, ".")) return KernFsError.InvalidPathFormat;
            if (std.mem.eql(u8, component, "..")) return KernFsError.PathTraversalAttempt;
            if (std.mem.indexOfScalar(u8, component, 0) != null)
                return KernFsError.InvalidPathFormat; // NUL-инъекция
        }
    }

    /// Извлечение имени из пула строк. Границы проверяются (в отличие от
    /// первой версии Фазы 3, где чтение могло уйти за пул).
    fn getString(self: KernFS, offset: u32) []const u8 {
        if (offset >= self.string_pool.len) return "";
        var len: usize = 0;
        while (offset + len < self.string_pool.len and
               self.string_pool[offset + len] != 0) : (len += 1) {}
        return self.string_pool[offset .. offset + len];
    }

    /// Главный метод роутинга.
    ///
    /// 🔴 ИЗВЕСТНОЕ РАСХОЖДЕНИЕ (см. docs/KERN34_AUDIT.md): роутер ищет
    /// объекты типов 0x0002 (source) и 0x0005 (claim) С ПУТЁМ, а золотой вектор
    /// v1.2 содержит ОДИН объект типа 0x0001 без пути. Поэтому на образе v1.2
    /// ни один путь не находится. Это НЕ ошибка роутера — это несогласованность
    /// Фазы 1 и Фазы 3, которую нужно устранить в спецификации.
    pub fn read(self: *KernFS, path: []const u8) !VfsNode {
        try validatePath(path);

        // 1. Пространство исходников (/raw/...)
        if (std.mem.startsWith(u8, path, "/raw/")) {
            const target_path = path[5..];
            for (self.objects) |obj| {
                if (obj.type_id == 0x0002 and obj.logical_path_offset != 0xFFFFFFFF) {
                    const obj_path = self.getString(obj.logical_path_offset);
                    if (std.mem.eql(u8, obj_path, target_path)) {
                        // ZERO-COPY: возвращаем срез mmap напрямую
                        const start = obj.payload_offset;
                        const end = start + obj.uncompressed_size;
                        return VfsNode{ .raw_slice = self.mmap_slice[start..end] };
                    }
                }
            }
            return KernFsError.FileNotFound;
        }

        // 2. Семантическое пространство (/claims/...)
        if (std.mem.startsWith(u8, path, "/claims/")) {
            var it = std.mem.split(u8, path[8..], "/");
            const claim_id = it.next() orelse return KernFsError.FileNotFound;
            const view_type = it.next() orelse return KernFsError.FileNotFound;

            for (self.objects) |obj| {
                if (obj.type_id == 0x0005) {
                    const obj_id = self.getString(obj.logical_path_offset);
                    if (std.mem.eql(u8, obj_id, claim_id)) {
                        // Статус синтезируется НА ЛЕТУ из битовой маски
                        if (std.mem.eql(u8, view_type, "status")) {
                            const eq2_state: Eq2 = @enumFromInt(obj.flags & 0b11);
                            const status_str = switch (eq2_state) {
                                .N => "N\n",
                                .T => "T\n",
                                .F => "F\n",
                                .B => "B\n",
                            };
                            return VfsNode{ .virtual_view = status_str };
                        }
                        if (std.mem.eql(u8, view_type, "contract.json")) {
                            const start = obj.payload_offset;
                            const end = start + obj.uncompressed_size;
                            return VfsNode{ .raw_slice = self.mmap_slice[start..end] };
                        }
                    }
                }
            }
            return KernFsError.FileNotFound;
        }

        // 3. Запись запрещена (CONF-06).
        // ⚠️ Замечание аудита: возвращается FileNotFound, а не AccessDenied —
        // объявленный код AccessDenied не используется нигде.
        return KernFsError.FileNotFound;
    }
};

// ==========================================
// КОНФОРМАНС-ТЕСТЫ
// ==========================================
test "CONF-13: path traversal и валидация формата" {
    try KernFS.validatePath("/raw/src/main.zig");
    try KernFS.validatePath("/claims/123/status");

    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("raw/src")); // нет ведущего /
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw//main.zig")); // двойной слеш
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw/./main.zig")); // запрет .
    try std.testing.expectError(KernFsError.PathTraversalAttempt,
        KernFS.validatePath("/raw/../../etc/passwd")); // побег
}

test "SEC-03: NUL-инъекция и побег через /claims" {
    try std.testing.expectError(KernFsError.PathTraversalAttempt,
        KernFS.validatePath("/claims/../raw/secret.key"));
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw/file.zig\x00.md"));
}

