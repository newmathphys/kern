#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор эталонного образа KIMG v1.3 (согласованная Фаза 1 + Фаза 3).

ЧТО ИСПРАВЛЯЕТ (см. docs/archive/KERN34_AUDIT.md, «Фаза 1 и Фаза 3 несовместимы»):
  * добавлен ПУЛ СТРОК (в v1.2 его не было — роутер не мог найти ни пути);
  * добавлены объекты С ПУТЯМИ: source (0x0002) и claim (0x0005);
  * `payload_offset` и `logical_path_offset` — ОТНОСИТЕЛЬНЫ data_payload_offset
    (ровно как в спецификации KIMG: «Смещение данных (от data_payload_offset)»
    и «Индекс имени файла в пуле строк»). В v1.2 первый объект имел
    logical_path_offset = 0xFFFFFFFF, поэтому роутер не находил ничего.

РАСКЛАДКА ФАЙЛА
  [0 .. 128)            заголовок (128 байт)
  [128 .. D)            таблица объектов (N * 96 байт)
  [D .. D + pool)       пул строк (NUL-терминированные)
  [D + pool .. EOF)     полезные нагрузки объектов
  где D = data_payload_offset. Оба смещения объектов отсчитываются от D.

Хэш-схема (единая для Python и Zig):
  leaf_i = SHA256(0x00 || "KIMG-ENTRY-LEAF-V1\\0" || entry_bytes_i)
  root   = SHA256(0x00 || "KIMG-MERKLE-ROOT-V1\\0" || leaf_0 || ... || leaf_{n-1})
"""

import hashlib
from pathlib import Path
import os
import struct

# Заголовок (96 байт) + чексумма (32 байта) = 128
HEADER_FMT = "<8s H H I I I Q Q Q Q Q 32s"
# Дескриптор объекта — ровно 96 байт
OBJ_FMT = "<32s Q Q Q I H B B I I 24s"

LEAF_DOMAIN = b"\x00KIMG-ENTRY-LEAF-V1\x00"
ROOT_DOMAIN = b"\x00KIMG-MERKLE-ROOT-V1\x00"


# ===========================================================================
#  ХЕШ: ИСТОЧНИК — ЯДРО (0 внешних pip-зависимостей)
# ===========================================================================
# ЗАМЕЧАНИЕ РЕВЬЮ (принято): в стандартном `hashlib` BLAKE3 НЕТ (только
# blake2b/blake2s), поэтому `hashlib.new("blake3")` упал бы с ValueError.
# Прежняя версия брала сторонний pip-пакет `blake3` — то есть Python и Zig
# считали хеш РАЗНЫМИ библиотеками (риск расхождения).
#
# ТЕПЕРЬ: приоритет — вызов `kern_hash` из `libkern.so` через ctypes. Это
# ГАРАНТИРУЕТ, что Python и Zig используют ОДИН И ТОТ ЖЕ код ядра.
# Порядок: C-ABI ядра -> pip blake3 -> SHA-256 (hash_algo = 2).
#
# hash_algo из спецификации §5.3: 1 = BLAKE3-256, 2 = SHA2-256.
HASH_ALGO = 2  # переопределяется ниже, если доступен BLAKE3

ROOT = Path(__file__).resolve().parent.parent
_kern_lib = None
_lib_candidates = [
    ROOT / "zig-out" / "lib" / "libkern.so",
    ROOT / "libkern.so",
]
for _p in _lib_candidates:
    if _p.exists():
        try:
            import ctypes as _ct
            _kern_lib = _ct.CDLL(str(_p))
            _kern_lib.kern_hash.restype = _ct.c_int
            _kern_lib.kern_hash.argtypes = [_ct.c_uint, _ct.c_char_p,
                                            _ct.c_ulong, _ct.c_char_p]
            _buf = _ct.create_string_buffer(32)
            if _kern_lib.kern_hash(1, b"", 0, _buf) == 0:
                HASH_ALGO = 1
                break
            _kern_lib = None
        except (OSError, AttributeError):
            _kern_lib = None

try:
    import blake3 as _blake3  # pip install blake3 (запасной путь)
    _HAS_BLAKE3 = True
except ImportError:
    _HAS_BLAKE3 = False
if _kern_lib is None and _HAS_BLAKE3:
    HASH_ALGO = 1


def content_hash(data: bytes) -> bytes:
    """Хэш содержимого тем же алгоритмом, что и ядро KERN.

    Приоритет источников:
      1) `kern_hash` из libkern.so (ctypes) — ОДИН код с Zig, 0 зависимостей;
      2) pip-пакет `blake3` — если библиотеки нет;
      3) SHA-256 (`hash_algo = 2`) — если BLAKE3 недоступен вовсе.

    Измерено (`make bench-hash`): BLAKE3 быстрее SHA-256 в среднем в 5.79x
    (до 8.92x на блоках 64 КБ) — см. docs/evidence/hash_bench.log.
    """
    if _kern_lib is not None:
        buf = _ct.create_string_buffer(32)
        if _kern_lib.kern_hash(HASH_ALGO, data, len(data), buf) == 0:
            return buf.raw[:32]
    if _HAS_BLAKE3:
        return _blake3.blake3(data).digest()
    return hashlib.sha256(data).digest()


def leaf_hash(entry_bytes: bytes) -> bytes:
    assert len(entry_bytes) == 96, len(entry_bytes)
    return content_hash(LEAF_DOMAIN + entry_bytes)


def root_hash(entry_bytes_list) -> bytes:
    h = ROOT_DOMAIN
    for e in entry_bytes_list:
        h += leaf_hash(e)
    return content_hash(h)


def build_golden_v1_3(out_path: str = "tests/fixtures/valid_v1_3.kimg") -> dict:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # --- 1. Пул строк (обе строки NUL-терминированы) ---
    s_source = b"src/main.zig\x00"
    s_claim = b"L0_AlignmentInvariant.kern\x00"
    string_pool = s_source + s_claim
    off_source = 0
    off_claim = len(s_source)

    # --- 2. Полезные нагрузки (смещения ОТНОСИТЕЛЬНЫ data_payload_offset) ---
    file_content = b"pub fn main() void {}\n"
    contract = b'{"pre":"true","post":"true"}'

    payload_base = len(string_pool)                 # первый байт после пула строк
    off_file = payload_base
    off_contract = payload_base + len(file_content)
    payload_region = string_pool + file_content + contract

    # --- 3. Таблица объектов ---
    obj_source = struct.pack(
        OBJ_FMT,
        content_hash(file_content),   # digest
        off_file,                     # payload_offset (отн. data_payload_offset)
        len(file_content),            # uncompressed_size
        len(file_content),            # compressed_size
        0x0002,                       # type_id = Source
        0x0002,                       # flags: бит 1 = HAS_LOGICAL_PATH
        0,                            # compression_codec = None
        0,                            # scope_depth = 0
        off_source,                   # logical_path_offset (в пул строк)
        1,                            # schema_version
        b"\x00" * 24,                 # reserved (CONF-15: строго нули)
    )
    obj_claim = struct.pack(
        OBJ_FMT,
        content_hash(contract),       # digest
        off_contract,                 # payload_offset
        len(contract),                # uncompressed_size
        len(contract),                # compressed_size
        0x0005,                       # type_id = Claim
        0x0006,                       # flags: бит 1 = HAS_LOGICAL_PATH, биты 2-3 = статус (01=T)
        0,
        0,
        off_claim,                    # logical_path_offset = id утверждения
        1,
        b"\x00" * 24,
    )
    assert len(obj_source) == 96 and len(obj_claim) == 96

    entry_bytes = [obj_source, obj_claim]
    obj_table = obj_source + obj_claim

    # --- 4. Заголовок ---
    obj_table_offset = 128
    obj_table_size = len(obj_table)
    data_payload_offset = obj_table_offset + obj_table_size

    root_digest = root_hash(entry_bytes)

    header_head = struct.pack(
        HEADER_FMT,
        b"KIMG\r\n\x1a\n",            # magic
        1,                            # major_version
        3,                            # minor_version (v1.3)
        128,                          # header_size
        0,                            # flags
        HASH_ALGO,                    # hash_algo: 1=BLAKE3, 2=SHA-256
        4096,                         # block_size
        obj_table_offset,
        obj_table_size,
        2,                            # object_count
        data_payload_offset,
        root_digest,
    )
    assert len(header_head) == 96, len(header_head)
    header = header_head + content_hash(header_head)
    assert len(header) == 128

    with open(out_path, "wb") as f:
        f.write(header)
        f.write(obj_table)
        f.write(payload_region)

    total = len(header) + len(obj_table) + len(payload_region)
    print(f"[OK] Golden Vector v1.3: {out_path} ({total} байт)")
    print(f"     объекты: source(0x0002) + claim(0x0005), пул строк {len(string_pool)} б")
    print(f"     root_digest: {root_digest.hex()[:16]}...")
    return {"path": out_path, "size": total, "root_digest": root_digest.hex()}


if __name__ == "__main__":
    build_golden_v1_3()
