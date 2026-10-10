const std = @import("std");
const AdmissionGate = @import("verifier/admission_gate.zig").AdmissionGate;
const ProofCertificate = @import("verifier/admission_gate.zig").ProofCertificate;
const VerificationPolicy = @import("verifier/admission_gate.zig").VerificationPolicy;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const ObjectEntry = @import("core/object_entry.zig").ObjectEntry;
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;

/// ВОСПРОИЗВОДИМАЯ ПРОВЕРКА ДВУХ УЯЗВИМОСТЕЙ KERN.
///
/// Этот файл — не тест, а демонстрация: он показывает на живом запуске, что
///   (1) Врата Истины обходятся ОДНИМ БАЙТОМ,
///   (2) KERNFS не находит ни одного файла в золотом векторе v1.2.
///
/// Результаты зафиксированы в docs/KERN34_AUDIT.md.
pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    std.debug.print(
        "\n########## АТАКА 1: ИИ присылает ОДИН БАЙТ вместо доказательства ##########\n",
        .{});

    // ИИ не предоставил доказательства. Он положил в сертификат байт 0xAA,
    // потому что именно он в исходнике означает «Proved».
    const ast_hash = [_]u8{0x01} ** 32;
    const ai_cert = ProofCertificate{
        .target_ast_digest = ast_hash, // хеши скопированы из спецификации
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 }, // ОДИН БАЙТ
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 0xFFFFFFFF };

    const res = try AdmissionGate.verifyClaim(ast_hash, ast_hash, ai_cert, policy);
    std.debug.print("Вердикт: {s}, e={d}\n",
        .{ @tagName(res.eq2_status), res.e_value });
    if (res.e_value == 1) {
        std.debug.print(
            ">>> ИТОГ: код ДОПУЩЕН в прод БЕЗ ЕДИНОГО ДОКАЗАТЕЛЬСТВА <<<\n", .{});
    }

    std.debug.print(
        "\n########## АТАКА 2: KERNFS на золотом векторе v1.2 ##########\n", .{});

    const data = std.fs.cwd().readFileAlloc(
        alloc, "tests/fixtures/valid_v1_2.kimg", 1 << 20) catch {
        std.debug.print("[i] образа нет — соберите: python3 tools/golden_v1_2.py\n", .{});
        return;
    };
    defer alloc.free(data);

    var hb: [128]u8 = undefined;
    @memcpy(&hb, data[0..128]);
    const header = try KimgHeader.parse(&hb, data.len);
    std.debug.print("заголовок: объектов {d}, таблица на {d}, payload на {d}\n",
        .{ header.object_count, header.object_table_offset,
           header.data_payload_offset });

    const objs_ptr: [*]const u8 = data.ptr + header.object_table_offset;
    const objs: []const ObjectEntry =
        @as([*]const ObjectEntry, @ptrCast(@alignCast(objs_ptr)))[0..header.object_count];
    var fs = KernFS.init(alloc, data, objs, data[header.data_payload_offset..]);

    const probes = [_][]const u8{
        "/raw/src/core/memory.zig",
        "/claims/L0_AlignmentInvariant.kern/status",
    };
    for (probes) |p| {
        std.debug.print("  {s} -> ", .{p});
        if (fs.read(p)) |_| {
            std.debug.print("НАЙДЕНО\n", .{});
        } else |e| {
            std.debug.print("ошибка: {s}\n", .{@errorName(e)});
        }
    }
    std.debug.print(
        ">>> ИТОГ: роутер не находит ничего — Фаза 1 и Фаза 3 несовместимы <<<\n\n",
        .{});
}
