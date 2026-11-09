#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""АВТОМАТИЧЕСКИЙ МИНИМИЗАТОР ЛОЖНЫХ СРАБАТЫВАНИЙ (поиск минимального репро).

ЗАЧЕМ. Каждый FP (как `#570` на cJSON) отнимал вечер ручных бисекций: удали строку,
перезапусти, посмотри. Здесь то же самое делает машина: жадно удаляет по одному
оператору и оставляет удаление, только если FP ВОСПРОИЗВОДИТСЯ. В конце остаётся
минимальный набор строк, без которого находка исчезает.

ЧЕСТНОСТЬ (двусторонний контроль встроен):
  * удаление принимается ТОЛЬКО если искомая находка всё ещё есть (иначе это не
    минимизация, а «сломал и обрадовался»);
  * в конце результат ОБЯЗАН воспроизводиться — иначе скрипт возвращает 1;
  * печатается, сколько прогонов сделано и сколько строк было/стало.

Запуск:
    python3 tools/minimize_fp.py ФАЙЛ --marker "DEAD BRANCH" [--out min.c] [--timeout 120]
Коды: 0 — минимальный репро воспроизводится; 1 — не удалось (FP не воспроизвёлся на
входном файле или результат нестабилен); 2 — нет инструмента/файла.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = sorted((ROOT / "dist-release").glob("kerna-dist-v*/kerna"))
KERNA = APP[-1] if APP else ROOT / "dist" / "kerna"


def has_marker(path: Path, marker: str, timeout: int) -> bool:
    """Воспроизводится ли находка на этом файле (единственный судья — сам апплаенс)."""
    try:
        p = subprocess.run([str(KERNA), "--xray", str(path)], capture_output=True,
                           text=True, timeout=timeout, errors="replace",
                           cwd=str(path.parent))
    except subprocess.TimeoutExpired:
        return False
    return marker in ((p.stdout or "") + (p.stderr or ""))


def minimize(lines: list[str], marker: str, workdir: Path, timeout: int) -> tuple[list[str], int]:
    """Жадно удалять строки, пока находка воспроизводится. Вернуть (строки, прогоны)."""
    cur = list(lines)
    probe = workdir / "probe.c"
    runs = 0

    def ok(cand: list[str]) -> bool:
        nonlocal runs
        probe.write_text("".join(cand), encoding="utf-8")
        runs += 1
        return has_marker(probe, marker, timeout)

    if not ok(cur):
        return lines, runs          # вход не воспроизводит находку — минимизировать нечего

    changed = True
    while changed:
        changed = False
        for i in range(len(cur) - 1, -1, -1):
            cand = cur[:i] + cur[i + 1:]
            if not "".join(cand).strip():
                continue
            if ok(cand):
                cur = cand
                changed = True
    return cur, runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--marker", required=True, help='напр. "DEAD BRANCH" или "CRASH PATH"')
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()

    src = Path(a.file)
    if not src.is_file():
        print(f"[!] нет файла: {src}")
        return 2
    if not KERNA.is_file():
        print(f"[!] нет апплаенса: {KERNA} (соберите: make kerna-dist)")
        return 2

    lines = src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    with tempfile.TemporaryDirectory(prefix="kern_min_") as td:
        work = Path(td)
        # окружение: заголовки ищутся относительно файла, поэтому копируем каталог файла
        cur, runs = minimize(lines, a.marker, work, a.timeout)
        body = "".join(cur)
        out = Path(a.out) if a.out else src.with_suffix(".min" + src.suffix)
        out.write_text(body, encoding="utf-8")

        ok_final = has_marker(out, a.marker, a.timeout)
        print(f"── минимизация {src.name} по маркеру «{a.marker}»")
        print(f"   прогонов апплаенса: {runs}")
        print(f"   строк было {len(lines)} -> стало {len(cur)}")
        print(f"   результат: {out}")
        if not ok_final:
            print("[FAIL] минимальный файл НЕ воспроизводит находку — минимизация не засчитана")
            return 1
        print("[OK] минимальный репро воспроизводится (двусторонний контроль пройден)")
        print("--- начало минимального файла ---")
        for ln in body.splitlines()[:40]:
            print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
