const std = @import("std");

// Подсистемы L0–L4
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const AdmissionGate = @import("verifier/admission_gate.zig").AdmissionGate;
const ProofCertificate = @import("verifier/admission_gate.zig").ProofCertificate;
const VerificationPolicy = @import("verifier/admission_gate.zig").VerificationPolicy;

/// CLI-оркестратор KERN.
///
/// ⚠️ ЧЕСТНО О КОМАНДАХ (см. docs/KERN34_AUDIT.md):
///   * `verify` НЕ читает образ — сертификат зашит в код. Это демонстрация
///     вызова шлюза, а не проверка файла;
///   * `ls`/`cat` — ЗАГЛУШКИ: KERNFS монтируется в attack.zig, а здесь только
///     сообщение. Причина: золотой вектор v1.2 не содержит объектов с путями,
///     поэтому роутер всё равно ничего не найдёт;
///   * `report` пишет ФИКСИРОВАННЫЙ текст и НЕ читает образ. Строку
///     «99% VERIFIED» из него убрали именно поэтому — она была фабрикацией.
pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const args = try std.process.argsAlloc(alloc);
    if (args.len < 2) {
        printUsage();
        return;
    }
    const command = args[1];

    if (std.mem.eql(u8, command, "pack")) {
        std.debug.print("[pack] Образ собирается Python-скриптом: python3 tools/golden_v1_2.py\n", .{});
        return;
    }

    if (args.len < 3) {
        std.debug.print("[!] Укажите путь к образу .kimg\n", .{});
        return;
    }
    const image_path = args[2];

    // Физика L0: zero-copy mmap
    const file = try std.fs.cwd().openFile(image_path, .{});
    defer file.close();
    const file_size = try file.getEndPos();

    const mmap_slice = try std.posix.mmap(
        null, file_size, std.posix.PROT.READ, .{ .TYPE = .SHARED }, file.handle, 0,
    );
    defer std.posix.munmap(mmap_slice);

    if (std.mem.eql(u8, command, "check-integrity")) {
        // Проверка целостности НЕ должна падать: ошибки сообщаются словами.
        if (mmap_slice.len < 128) {
            std.debug.print("[!] Образ слишком мал: {d} байт (нужно ≥ 128)\n",
                .{mmap_slice.len});
            return;
        }
        var header_bytes: [128]u8 = undefined;
        std.mem.copyForwards(u8, &header_bytes, mmap_slice[0..128]);
        const header = KimgHeader.parse(&header_bytes, file_size) catch |e| {
            std.debug.print("[!] Образ НЕВАЛИДЕН: {s}\n", .{@errorName(e)});
            return;
        };
        std.debug.print("[OK] Целостность подтверждена. Эпоха: {d}, Объектов: {d}\n",
            .{ header.version_major, header.object_count });

    } else if (std.mem.eql(u8, command, "verify")) {
        std.debug.print("[L4] Демонстрация Admission Gate (сертификат зашит, образ не читается)\n", .{});
        const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                           .allowed_checkers = 0xFFFFFFFF };
        const ast = [_]u8{0x01} ** 32;
        const cert = ProofCertificate{
            .target_ast_digest = ast,
            .contract_digest = ast,
            .checker_id = 1,
            .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
        };
        const result = try AdmissionGate.verifyClaim(ast, ast, cert, policy);
        std.debug.print("=========================================\n", .{});
        std.debug.print("Вердикт KERN-EQ2 : {s}\n", .{@tagName(result.eq2_status)});
        std.debug.print("Значение e       : {d}\n", .{result.e_value});
        std.debug.print("Статус           : {s}\n",
            .{if (result.e_value == 1) "PROVEN (Код допущен)" else "REJECTED"});
        std.debug.print("=========================================\n", .{});

    } else if (std.mem.eql(u8, command, "ls") or std.mem.eql(u8, command, "cat")) {
        std.debug.print("[L3] ЗАГЛУШКА: KERNFS монтируется программно (см. src/attack.zig).\n", .{});
        std.debug.print("[i] Причина: золотой вектор v1.2 не содержит объектов с путями — роутер ничего не найдёт.\n", .{});

    } else if (std.mem.eql(u8, command, "report")) {
        std.debug.print("[L3] Манифест НЕ читает образ: пишется фиксированный текст.\n", .{});
        const out_file = try std.fs.cwd().createFile(
            "PROJECT_CANONICAL_SPEC.kern.md", .{});
        defer out_file.close();
        try out_file.writeAll("# КАНОНИЧЕСКИЙ ПАСПОРТ KERN\n\n> Сгенерировано kernc. ОБРАЗ НЕ АНАЛИЗИРОВАЛСЯ.\n\n**Статус**: не определён (это заглушка, а не результат проверки)\n");
        std.debug.print("[OK] Файл записан (без проверки образа)\n", .{});

    } else {
        std.debug.print("[!] Неизвестная команда: {s}\n", .{command});
        printUsage();
    }
}

fn printUsage() void {
    std.debug.print(
        \\=======================================================
        \\  KERN Compiler & Formal Engine v1.2
        \\=======================================================
        \\Использование: kernc <команда> <образ.kimg>
        \\
        \\  check-integrity  L0: проверка заголовка и границ
        \\  verify           L4: демонстрация Admission Gate
        \\  ls / cat         L3: заглушка (см. src/attack.zig)
        \\  report           фиксированный манифест
        \\
    , .{});
}
