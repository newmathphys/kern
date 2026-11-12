#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: Apache-2.0
"""`gen_playground_manifest.py` — честная подпись бинарника на странице песочницы.

ЗАЧЕМ. Страница `docs/playground/` исполняет `kernc.wasm` В БРАУЗЕРЕ читателя.
Подпись «собрано из релиза vX.Y.Z» была бы ложью, если экспорт входного буфера
добавлен ПОСЛЕ тега: файл собран из HEAD, то есть из будущей версии. Поэтому
подпись = `commit` + `sha256` тех самых байт, которые лежат рядом со страницей,
и команда независимой сверки. Браузер считает sha256 сам (`crypto.subtle`) и
сравнивает с манифестом — подделать подпись, не подменив байты, нельзя.

Также копирует актуальный `zig-out/bin/kernc.wasm` в `docs/playground/`, чтобы
страница и сайт не разъезжались (та же политика, что у `docs/kernc.wasm`).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "zig-out" / "bin" / "kernc.wasm"
PLAY = ROOT / "docs" / "playground"


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — нет git: называем состояние, не молчим
        return "unknown"


def _check() -> int:
    """Проверка БЕЗ записи: байты страницы == сборка, манифест == байты."""
    dst = PLAY / "kernc.wasm"
    man = PLAY / "build.json"
    if not dst.exists() or not man.exists():
        print("[!] нет docs/playground/{kernc.wasm,build.json} — "
              "прогоните `make playground`")
        return 1
    data = dst.read_bytes()
    doc = json.loads(man.read_text(encoding="utf-8"))
    got = hashlib.sha256(data).hexdigest()
    bad = 0
    if SRC.exists() and SRC.read_bytes() != data:
        print("[FAIL] docs/playground/kernc.wasm ≠ zig-out/bin/kernc.wasm "
              "(страница исполняет НЕ ту сборку, что собрана)")
        bad = 1
    if doc.get("sha256") != got:
        print(f"[FAIL] манифест {doc.get('sha256')} ≠ фактические байты {got}")
        bad = 1
    if doc.get("bytes") != len(data):
        print(f"[FAIL] манифест {doc.get('bytes')} байт ≠ фактически {len(data)}")
        bad = 1
    if not bad:
        print(f"[OK] playground: подпись честная — {len(data)} байт, "
              f"sha256 {got[:16]}…, коммит {doc.get('commit')}")
    return bad


def main() -> int:
    if "--check" in sys.argv[1:]:
        return _check()
    if not SRC.exists():
        print(f"[!] нет {SRC.relative_to(ROOT)} — сначала `zig build wasm`")
        return 1
    PLAY.mkdir(parents=True, exist_ok=True)
    dst = PLAY / "kernc.wasm"
    shutil.copyfile(SRC, dst)
    data = dst.read_bytes()
    doc = {"commit": _commit(), "sha256": hashlib.sha256(data).hexdigest(),
           "bytes": len(data), "source": "zig build wasm (wasm32-freestanding)"}
    (PLAY / "build.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(f"[OK] playground: kernc.wasm {doc['bytes']} байт, sha256 {doc['sha256'][:16]}…, "
          f"коммит {doc['commit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
