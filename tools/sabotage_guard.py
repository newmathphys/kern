#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""#628: САБОТАЖ НЕ ДОЛЖЕН УЕХАТЬ В КОММИТ.

ЗАЧЕМ. Стенд `canfail` доказывает, что проверки СПОСОБНЫ падать: он ВРЕМЕННО
портит исходники (вставляет маркер `ЛОМАЕМ` и заведомо неверный код). Если
стенд прервать, диверсия остаётся в дереве. ИЗМЕРЕНО 2026-11-11: прерванный
`canfail` оставил в `src/core/kimg_reader.zig`

    cov.hit(.merkle_mismatch);
    return KimgError.MerkleRootMismatch; // ЛОМАЕМ: всегда несовпадение

и это уехало в коммит через `git add -A` (дефект #627). Сборка после этого
падала с `error: unused local constant`.

ПРОВЕРКА (двусторонняя, см. `--selftest`):
  R1 в `src/` нет ни одного маркера диверсии;
  R2 маркер в `tools/canfail.py` разрешён (он обязан их знать, чтобы вставлять) —
     исключение НАЗВАНО, а не «молча пропущено»;
  R3 гейт УМЕЕТ падать: файл с маркером во временном дереве обязан дать rc=1.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKERS = ("ЛОМАЕМ", "SABOTAGE")
SCANNED = ("src",)
# Исключения НАЗВАНЫ и обоснованы: без них гейт был бы вакуумным.
ALLOWED = {
    "tools/canfail.py": "сам стенд обязан знать маркеры, чтобы их вставлять",
}


def scan(root: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for d in SCANNED:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in {".zig", ".py", ".c", ".h", ".rs", ".go"}:
                continue
            rel = str(p.relative_to(root))
            if rel in ALLOWED:
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if any(m in line for m in MARKERS):
                        hits.append((rel, i, line.strip()[:96]))
            except OSError:
                continue
    return hits


def selftest() -> int:
    """Гейт обязан падать на саботаже и проходить на чистом дереве."""
    fails = 0
    with tempfile.TemporaryDirectory(prefix="sab_") as td:
        tmp = Path(td)
        (tmp / "src").mkdir()
        (tmp / "src" / "ok.zig").write_text("const x = 1;\n", encoding="utf-8")
        if scan(tmp):
            print("[FAIL] R3a: чистое дерево дало находку"); fails += 1
        else:
            print("[OK] R3a: чистое дерево — находок 0")
        (tmp / "src" / "bad.zig").write_text(
            "cov.hit(.merkle_mismatch);\nreturn X; // ЛОМАЕМ: всегда несовпадение\n",
            encoding="utf-8")
        if len(scan(tmp)) != 1:
            print("[FAIL] R3b: маркер НЕ пойман"); fails += 1
        else:
            print("[OK] R3b: маркер диверсии пойман (1 файл)")
    return 1 if fails else 0


def scan_committed() -> list[tuple[str, int, str]]:
    """Скан ИМЕННО КОММИТА (HEAD), а не рабочего дерева.

    ИЗМЕРЕНО (первый прогон в ci-fast): другие стенды ВРЕМЕННО вставляют
    диверсии и сами их откатывают, поэтому сканирование рабочего дерева давало
    ложное срабатывание прямо посреди прогона. Вопрос гейта другой: не УЕХАЛА
    ли диверсия в коммит.
    """
    hits: list[tuple[str, int, str]] = []
    pat = "|".join(MARKERS)
    r = subprocess.run(["git", "grep", "-n", "-E", pat, "HEAD", "--"] + list(SCANNED),
                       capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode not in (0, 1):
        return hits
    for line in r.stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 4:
            hits.append((parts[1], int(parts[2]), parts[3].strip()[:96]))
    return hits


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    hits = scan_committed()
    if hits:
        print("[FAIL] #628: САБОТАЖ стенда УЕХАЛ В КОММИТ (прерванный canfail + git add -A):")
        for rel, ln, txt in hits[:8]:
            print(f"    {rel}:{ln}: {txt}")
        print("  Лечение: git checkout -- <файл> (вернуть версию до инъекции) и")
        print("  НЕ делать `git add -A`, пока canfail не завершился.")
        return 1
    print(f"[OK] #628: саботажа в src/ нет (маркеры: {', '.join(MARKERS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
