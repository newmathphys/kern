#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: предохранитель от ВНЕШНЕЙ правки файлов во время длинного прогона.

ЗАЧЕМ (дефект #88). Харнесс `tools/canfail.py` и мутатор `tools/mutate_zig.py`
НАМЕРЕННО меняют исходники и восстанавливают их. Но если файл правит
КТО-ТО ЕЩЁ (человек, IDE, параллельный агент) во время 40-минутного сбора
свидетельств, то:
  * свидетельства, снятые в этот момент, ЛОЖНЫ (тесты читают пропатченный код);
  * прогон падает в конце с невнятным RC=1 и утаскивает соседние логи.
Именно это произошло на практике: я правил `tools/canfail.py`, пока шёл
`make evidence` — и прогон завершился «ХАРНЕСС ОСТАВИЛ ИЗМЕНЕНИЯ В ДЕРЕВЕ».

КАК РАБОТАЕТ.
  --snapshot FILE : сохранить sha256 всех FAULTABLE-файлов (состояние на старте)
  --verify   FILE : сверить текущее состояние со снимком; перечислить
                    расхождения и вернуть 1, если они есть.

ВЫЗЫВАЕТСЯ ИЗ `tools/collect_evidence.sh`: снимок — на старте, сверка —
ПОСЛЕ КАЖДОГО ШАГА (пока очередной шаг вернул управление, все FAULTABLE-файлы
обязаны побайтово совпадать со стартовым снимком).

Список FAULTABLE читается из `tools/canfail.py` — ЕДИНЫЙ источник, чтобы
наборы не разъезжались.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANFAIL = ROOT / "tools" / "canfail.py"


# Каталоги ГЕНЕРИРУЕМЫХ артефактов и свидетельств. Их файлы входят в FAULTABLE
# (кейсы намеренно их портят), НО прогон пишет и пересобирает их ПО НАЗНАЧЕНИЮ.
# Поэтому в снимок предохранителя они НЕ входят: он защищает ВХОДЫ
# (исходники, инструменты, README), а не продукты прогона.
#
# 🔴 ДЕФЕКТ #173a (найден полным прогоном 123 целей): в снимке оставались
#    `zig-out/bin/kernc` и `kernc-hermetic`. `canfail` в самом конце делает
#    «пересборка артефактов из восстановленных исходников» — и ЛЮБОЙ честный
#    полный прогон гарантированно объявлялся «НЕДЕЙСТВИТЕЛЬНЫМ». Предохранитель
#    ложно обвинял сам харнесс.
OUTPUT_DIRS = ("docs/evidence/", "zig-out/")


def faultable() -> list[str]:
    """Список FAULTABLE из canfail.py (без импорта модуля — он с main()).

    Из него ИСКЛЮЧАЮТСЯ генерируемые свидетельства (см. OUTPUT_DIR).
    """
    src = CANFAIL.read_text(encoding="utf-8")
    m = re.search(r"^FAULTABLE\s*=\s*(\[[^\]]*\])", src, re.M | re.S)
    if not m:
        raise SystemExit("[!] не найден FAULTABLE в tools/canfail.py")
    items = list(ast.literal_eval(m.group(1)))
    return [x for x in items if not x.startswith(OUTPUT_DIRS)]


def git_dirty(rels: list[str]) -> list[str]:
    """FAULTABLE-файлы, отличающиеся от HEAD (грязное дерево НА СТАРТЕ).

    🔴 ДЕФЕКТ #173c: если базис снят на грязном дереве, «эталоном» становится
    ПРОПАТЧЕННОЕ состояние — и сверка в конце честно сообщает «файлы изменены»,
    хотя виноват снимок, а не прогон. Поэтому стартовать на грязных входах
    запрещено: пусть лучше откажет сразу, чем соврёт в конце.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--", *rels],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    return [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(out: Path, force: bool = False) -> int:
    # 🔴 ДЕФЕКТ #173b: снимок перезаписывался ВО ВРЕМЯ прогона (повторный вызов
    # из соседнего шага/сессии), и «эталоном» становилось ПРОПАТЧЕННОЕ
    # состояние. Теперь базис пишется ОДИН раз; перезапись — только явным
    # --force (осознанное решение оператора).
    if out.is_file() and not force:
        print(f"[guard] снимок уже существует: {out}")
        print("        НЕ перезаписываю: базис мог быть снят посреди прогона.")
        print("        Новый базис — только явно: --snapshot <file> --force")
        return 2
    rels = faultable()
    dirty = git_dirty(rels)
    if dirty:
        print("[guard] 🔴 дерево ГРЯЗНОЕ на старте — базис недостоверен:")
        for rel in dirty:
            print(f"        - {rel}")
        print("        Закоммитьте/откатите правки и повторите: иначе прогон")
        print("        снимет свидетельства при пропатченных исходниках.")
        return 3
    state: dict[str, str] = {}
    missing: list[str] = []
    for rel in rels:
        p = ROOT / rel
        if p.is_file():
            state[rel] = sha256_file(p)
        else:
            missing.append(rel)
    out.write_text(json.dumps({"files": state, "missing": missing},
                              indent=1, sort_keys=True), encoding="utf-8")
    print(f"[guard] снимок FAULTABLE: файлов {len(state)}, "
          f"отсутствуют {len(missing)} -> {out}")
    return 0


def verify(snap: Path) -> int:
    if not snap.is_file():
        print(f"[!] нет снимка {snap} — сначала --snapshot")
        return 2
    data = json.loads(snap.read_text(encoding="utf-8"))
    old: dict[str, str] = data.get("files", {})
    changed: list[tuple[str, str, str]] = []
    for rel, was in old.items():
        p = ROOT / rel
        if not p.is_file():
            changed.append((rel, "удалён", was[:12]))
            continue
        now = sha256_file(p)
        if now != was:
            changed.append((rel, "изменён", f"{was[:12]} -> {now[:12]}"))
    if changed:
        print("[guard] 🔴 ФАЙЛЫ ИЗМЕНЕНЫ ВО ВРЕМЯ ПРОГОНА (внешняя правка):")
        for rel, what, detail in changed:
            print(f"        - {rel}: {what} ({detail})")
        print("        Прогон НЕДЕЙСТВИТЕЛЕН: свидетельства могли быть сняты")
        print("        при пропатченных исходниках. Не правьте файлы во время")
        print("        `make evidence` / `make canfail`.")
        return 1
    print(f"[guard] FAULTABLE без изменений ({len(old)} файлов) — прогон чист")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    if len(args) != 2 or args[0] not in ("--snapshot", "--verify"):
        print(__doc__)
        return 2
    path = Path(args[1])
    if args[0] == "--snapshot":
        return snapshot(path, force)
    return verify(path)


if __name__ == "__main__":
    sys.exit(main())
