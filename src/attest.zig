// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: АТТЕСТАЦИЯ ВЕРДИКТА (Remote Attestation, software-часть).
//!
//! Когда KERN выдаёт вердикт `e=1`, клиент в сети должен убедиться, что его
//! сгенерировало НЕИЗМЕНЁННОЕ ядро. Подписываем (хэш контракта || Merkle-корень
//! || вердикт) ключом Ed25519 — как это делает TPM/Nitro/SGX (аппаратный корень).
//! Аппаратный анклав здесь не эмулируется, но крипто-конвейер — настоящий.
const std = @import("std");
const Ed25519 = std.crypto.sign.Ed25519;

pub const Verdict = enum { proved, refuted, unknown };

pub const Certificate = struct {
    contract_digest: [32]u8,
    merkle_root: [32]u8,
    verdict: Verdict,
    signature: [64]u8,
};

/// То, что подписывается (каноническое представление).
fn payload(contract_digest: [32]u8, merkle_root: [32]u8, v: Verdict) [65]u8 {
    var buf: [65]u8 = undefined;
    @memcpy(buf[0..32], &contract_digest);
    @memcpy(buf[32..64], &merkle_root);
    buf[64] = @intFromEnum(v);
    return buf;
}

pub fn attest(kp: Ed25519.KeyPair, contract_digest: [32]u8, merkle_root: [32]u8, v: Verdict) !Certificate {
    const sig = try kp.sign(&payload(contract_digest, merkle_root, v), null);
    return .{ .contract_digest = contract_digest, .merkle_root = merkle_root, .verdict = v, .signature = sig.toBytes() };
}

/// Проверка сертификата по публичному ключу (доверенный корень).
pub fn verify(pk: Ed25519.PublicKey, cert: Certificate) bool {
    const sig = Ed25519.Signature.fromBytes(cert.signature);
    sig.verify(&payload(cert.contract_digest, cert.merkle_root, cert.verdict), pk) catch return false;
    return true;
}

// =========================================================================
// СЕРИАЛИЗАЦИЯ (для `kernc attest sign/verify` на файлах .kimg)
// =========================================================================
//
// Раскладка (136 байт, little-endian, фиксированная):
//   0   .. 4    magic "KATT"
//   4   .. 5    version = 1
//   5   .. 6    verdict (0=proved,1=refuted,2=unknown)
//   6   .. 8    reserved (нули)
//   8   .. 40   contract_digest
//   40  .. 72   merkle_root
//   72  .. 136  signature
pub const CERT_SIZE: usize = 136;
pub const CERT_MAGIC = "KATT";

pub fn toBytes(cert: Certificate) [CERT_SIZE]u8 {
    var b: [CERT_SIZE]u8 = @as([CERT_SIZE]u8, @splat(0));
    @memcpy(b[0..4], CERT_MAGIC);
    b[4] = 1;
    b[5] = @intFromEnum(cert.verdict);
    @memcpy(b[8..40], &cert.contract_digest);
    @memcpy(b[40..72], &cert.merkle_root);
    @memcpy(b[72..136], &cert.signature);
    return b;
}

pub fn fromBytes(b: *const [CERT_SIZE]u8) !Certificate {
    if (!std.mem.eql(u8, b[0..4], CERT_MAGIC)) return error.BadCertMagic;
    if (b[4] != 1) return error.BadCertVersion;
    const v: Verdict = switch (b[5]) {
        0 => .proved,
        1 => .refuted,
        2 => .unknown,
        else => return error.BadCertVerdict,
    };
    var cert: Certificate = undefined;
    @memcpy(&cert.contract_digest, b[8..40]);
    @memcpy(&cert.merkle_root, b[40..72]);
    @memcpy(&cert.signature, b[72..136]);
    cert.verdict = v;
    return cert;
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "АТТЕСТАЦИЯ: валидный сертификат проверяется" {
    const seed = @as([32]u8, @splat(7));
    const kp = try Ed25519.KeyPair.generateDeterministic(seed);
    const cd = @as([32]u8, @splat(1));
    const mr = @as([32]u8, @splat(2));
    const cert = try attest(kp, cd, mr, .proved);
    try std.testing.expect(verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: подмена вердикта отвергается" {
    const kp = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(7)));
    const cd = @as([32]u8, @splat(1));
    const mr = @as([32]u8, @splat(2));
    var cert = try attest(kp, cd, mr, .refuted);
    cert.verdict = .proved; // злоумышленник правит вердикт
    try std.testing.expect(!verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: подмена Merkle-корня отвергается" {
    const kp = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(7)));
    var cert = try attest(kp, @as([32]u8, @splat(1)), @as([32]u8, @splat(2)), .proved);
    cert.merkle_root[0] ^= 0xFF;
    try std.testing.expect(!verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: чужой ключ не подтверждает подпись" {
    const kp = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(7)));
    const other = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(9)));
    const cert = try attest(kp, @as([32]u8, @splat(1)), @as([32]u8, @splat(2)), .proved);
    try std.testing.expect(!verify(other.public_key, cert));
}

test "АТТЕСТАЦИЯ: сериализация сертификата (round-trip) — 136 байт" {
    const kp = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(5)));
    const cert = try attest(kp, @as([32]u8, @splat(0xAA)), @as([32]u8, @splat(0xBB)), .proved);
    const bytes = toBytes(cert);
    try std.testing.expectEqual(@as(usize, CERT_SIZE), bytes.len);
    try std.testing.expectEqualStrings("KATT", bytes[0..4]);

    const back = try fromBytes(&bytes);
    try std.testing.expectEqual(Verdict.proved, back.verdict);
    try std.testing.expectEqualSlices(u8, &cert.contract_digest, &back.contract_digest);
    try std.testing.expectEqualSlices(u8, &cert.signature, &back.signature);
    // Подпись остаётся валидной после round-trip.
    try std.testing.expect(verify(kp.public_key, back));
}

test "АТТЕСТАЦИЯ: битый сертификат отвергается (magic/версия)" {
    const kp = try Ed25519.KeyPair.generateDeterministic(@as([32]u8, @splat(5)));
    const cert = try attest(kp, @as([32]u8, @splat(1)), @as([32]u8, @splat(2)), .proved);
    var bytes = toBytes(cert);
    bytes[0] = 'X';
    try std.testing.expectError(error.BadCertMagic, fromBytes(&bytes));
    bytes = toBytes(cert);
    bytes[4] = 99;
    try std.testing.expectError(error.BadCertVersion, fromBytes(&bytes));
}
