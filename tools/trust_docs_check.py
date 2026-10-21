#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: документы доверия обязаны существовать и не расходиться с ключом (0K.9).

Проверяются не «файлы вообще», а конкретные обязательные разделы:
модель угроз без границ доверия бессмысленна, управление ключами без
процедуры отзыва — тоже.

Дополнительно: отпечаток ключа (`kid`), вычисленный из
`docs/keys/kern-owner.pub`, обязан присутствовать в `KEY_MANAGEMENT.md`.
Иначе документ описывает один ключ, а подписывает другой — ровно та
ошибка, из-за которой появился #251.

Запуск: python3 tools/trust_docs_check.py [--dir PATH]
Код возврата: 0 — всё на месте; 1 — нет.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = {
    "THREAT_MODEL.md": ["## 1. Активы", "## 3. Границы доверия",
                        "## 4. Что KERN НЕ защищает"],
    "KEY_MANAGEMENT.md": ["## 2. Ключи", "## 6. Отзыв",
                          "## 7. Что подпись доказывает"],
    "INCIDENT_RESPONSE.md": ["## 2. Порядок действий", "## 3. Отозванные релизы",
                             "## 5. Пост-мортем"],
}


def key_id(pub: Path) -> str:
    r = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(pub),
                        "-outform", "DER"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return ""
    return "sha256:" + hashlib.sha256(r.stdout).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверить документы доверия")
    ap.add_argument("--dir", type=Path, default=ROOT / "docs")
    ap.add_argument("--key", type=Path, default=ROOT / "docs" / "keys" / "kern-owner.pub")
    args = ap.parse_args()

    bad = 0
    for name, sections in REQUIRED.items():
        p = args.dir / name
        if not p.exists():
            print(f"  [FAIL] нет {name}")
            bad += 1
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in sections if s not in text]
        if missing:
            print(f"  [FAIL] {name}: нет разделов {missing}")
            bad += 1
        else:
            print(f"  [OK] {name}: {len(sections)} обязательных раздела")

    km = args.dir / "KEY_MANAGEMENT.md"
    kid = key_id(args.key) if args.key.exists() else ""
    if km.exists() and kid:
        if kid not in km.read_text(encoding="utf-8", errors="replace"):
            print(f"  [FAIL] KEY_MANAGEMENT.md не содержит отпечаток ключа {kid[:24]}…")
            bad += 1
        else:
            print("  [OK] отпечаток ключа в KEY_MANAGEMENT.md совпадает с файлом")

    print("\n[OK] документы доверия на месте" if not bad
          else f"\n[FAIL] расхождений: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
