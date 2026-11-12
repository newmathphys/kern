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
import re
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
    if not SRC.exists():
        # ДЕФЕКТ #665: раньше здесь был МОЛЧАЛИВЫЙ пропуск, и в CI (где `zig build wasm`
        # не вызывался) рассинхрон ядра и песочницы не проверялся вообще. Теперь это
        # названный ОТКАЗ: `ci.sh` собирает wasm стадией выше, значит отсутствие файла —
        # дефект конвейера, а не нормальная ситуация.
        print("[FAIL] нет zig-out/bin/kernc.wasm — сверка песочницы с ядром "
              "НЕВОЗМОЖНА (запустите `zig build wasm`)")
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
    # ИСПОЛНЕНИЕ, А НЕ ТОЛЬКО ХЕШИ: Node исполняет ТОТ ЖЕ браузерный .wasm за доли
    # секунды, поэтому песочница не может сломаться тихо. Нет node — НАЗВАННЫЙ SKIP
    # (в CI он есть), а не тихое «зелено».
    js = ROOT / "tools" / "playground_node_check.js"
    node = shutil.which("node")
    if js.exists() and node:
        p = subprocess.run([node, str(js)], capture_output=True, text=True, timeout=120)
        out = (p.stdout or "") + (p.stderr or "")
        print(out.strip().splitlines()[-1] if out.strip() else "[FAIL] node: пустой вывод")
        if p.returncode != 0:
            for line in out.splitlines():
                if "[FAIL]" in line:
                    print(line)
            bad = 1
    else:
        print("[SKIP] wasm-playground: node не найден — сценарии НЕ исполнены "
              "(в CI node есть; локально поставьте node)")
    # ДВУЯЗЫЧИЕ: наборы ключей EN и RU обязаны совпадать. Иначе на английской
    # странице вылезет непереведённая строка (или наоборот) — ровно то, что убивает
    # первое впечатление у внешней аудитории.
    js_file = PLAY / "playground.js"
    if js_file.exists():
        src = js_file.read_text(encoding="utf-8")

        def keys_of(lang: str) -> set[str]:
            m = re.search(rf"\n  {lang}: {{(.*?)\n  }}", src, re.S)
            return set(re.findall(r'"([a-z][a-z0-9.]*)":', m.group(1))) if m else set()

        en, ru = keys_of("en"), keys_of("ru")
        if not en or not ru:
            print("[FAIL] playground.js: не найдены словари i18n en/ru")
            bad = 1
        elif en != ru:
            print(f"[FAIL] i18n: ключи расходятся — только EN {sorted(en - ru)}, "
                  f"только RU {sorted(ru - en)}")
            bad = 1
        else:
            print(f"[OK] i18n: EN и RU полны и совпадают ({len(en)} ключей), "
                  f"язык по умолчанию — EN")
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
