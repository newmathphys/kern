// Copyright (c) 2026 mrbritneyxxx. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

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
// ТЕСТЫ
// =========================================================================

test "АТТЕСТАЦИЯ: валидный сертификат проверяется" {
    const seed = [_]u8{7} ** 32;
    const kp = try Ed25519.KeyPair.create(seed);
    const cd = [_]u8{1} ** 32;
    const mr = [_]u8{2} ** 32;
    const cert = try attest(kp, cd, mr, .proved);
    try std.testing.expect(verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: подмена вердикта отвергается" {
    const kp = try Ed25519.KeyPair.create([_]u8{7} ** 32);
    const cd = [_]u8{1} ** 32;
    const mr = [_]u8{2} ** 32;
    var cert = try attest(kp, cd, mr, .refuted);
    cert.verdict = .proved; // злоумышленник правит вердикт
    try std.testing.expect(!verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: подмена Merkle-корня отвергается" {
    const kp = try Ed25519.KeyPair.create([_]u8{7} ** 32);
    var cert = try attest(kp, [_]u8{1} ** 32, [_]u8{2} ** 32, .proved);
    cert.merkle_root[0] ^= 0xFF;
    try std.testing.expect(!verify(kp.public_key, cert));
}

test "АТТЕСТАЦИЯ: чужой ключ не подтверждает подпись" {
    const kp = try Ed25519.KeyPair.create([_]u8{7} ** 32);
    const other = try Ed25519.KeyPair.create([_]u8{9} ** 32);
    const cert = try attest(kp, [_]u8{1} ** 32, [_]u8{2} ** 32, .proved);
    try std.testing.expect(!verify(other.public_key, cert));
}
