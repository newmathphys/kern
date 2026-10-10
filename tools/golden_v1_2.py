#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор золотого вектора KIMG v1.2 (Фаза 1).

Собирает канонический образ: заголовок 128 байт + таблица объектов (96 байт
на запись) + полезная нагрузка.

⚠️ ЧЕСТНО О ГРАНИЦАХ (см. docs/KERN12_AUDIT.md):
  * функция `content_hash` НАЗВАНА blake3, но ЖЁСТКО использует SHA-256 —
    никакого `try/except` здесь нет, комментарий о «фоллбэке» описывал
    механизм, которого не существует;
  * спецификация называет алгоритм BLAKE3, Zig-ядро считает SHA-256.
    Реализация «как обещано» (через blake3) ЛОМАЕТ сквозную сверку —
    проверено. Алгоритм обязан быть зафиксирован ОДИН.
  * `payload_offset` в v1.2 ОТНОСИТЕЛЬНЫЙ (от data_payload_offset), а логика
    KERNFS Фазы 3 считает его абсолютным — это делает фазы несовместимыми;
  * пула строк в образе НЕТ, поэтому роутер не может найти ни одного пути.
"""

import hashlib
import os
import struct

# Заголовок (96 байт) + чексумма (32 байта) = 128
HEADER_FMT = "<8s H H I I I Q Q Q Q Q 32s"
# Дескриптор объекта — ровно 96 байт
OBJ_FMT = "<32s Q Q Q I H B B I I 24s"


def content_hash(data: bytes) -> bytes:
    """Хэш содержимого. ФАКТИЧЕСКИ SHA-256, несмотря на имя."""
    return hashlib.sha256(data).digest()


def build_golden_v1_2(out_path: str = "tests/fixtures/valid_v1_2.kimg") -> dict:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    payload = b'{"schema": "kern.project-manifest/1", "synthetic": true}'
    payload_digest = content_hash(payload)

    obj_entry = struct.pack(
        OBJ_FMT,
        payload_digest,      # 0-31: digest
        0,                   # 32-39: payload_offset (ОТНОСИТЕЛЬНЫЙ в v1.2)
        len(payload),        # 40-47: uncompressed_size
        len(payload),        # 48-55: compressed_size
        0x0001,              # 56-59: type_id = project.manifest
        0,                   # 60-61: flags
        0,                   # 62: compression_codec
        0,                   # 63: scope_depth
        0xFFFFFFFF,          # 64-67: logical_path_offset = ПУТИ НЕТ
        1,                   # 68-71: schema_version
        b"\x00" * 24,        # 72-95: reserved (обязаны быть нулями, CONF-15)
    )
    assert len(obj_entry) == 96, len(obj_entry)

    # Merkle Leaf по спецификации 6.4: H(0x00 || "KIMG-ENTRY-LEAF-V1\0" || 96 байт)
    root_digest = content_hash(b"\x00KIMG-ENTRY-LEAF-V1\0" + obj_entry)

    header_head = struct.pack(
        HEADER_FMT,
        b"KIMG\r\n\x1a\n", 1, 0, 128, 0, 2, 4096,
        128, 96, 1, 128 + 96,
        root_digest,
    )
    assert len(header_head) == 96, len(header_head)
    header = header_head + content_hash(header_head)
    assert len(header) == 128

    with open(out_path, "wb") as f:
        f.write(header)
        f.write(obj_entry)
        f.write(payload)

    total = len(header) + len(obj_entry) + len(payload)
    print(f"[OK] Golden Vector v1.2: {out_path} ({total} байт)")
    print(f"     root_digest: {root_digest.hex()[:16]}...")
    return {"path": out_path, "size": total,
            "root_digest": root_digest.hex()}


if __name__ == "__main__":
    build_golden_v1_2()
