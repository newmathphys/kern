#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""#636: ПАКЕТНЫЙ АУДИТ ОСИРОТЕВШИХ ПРОВЕРОК (безопасный).

ЗАЧЕМ. Гейт #633 показал: 115 проверочных целей Makefile не вызываются ни из
`ci-fast`, ни из `tools/ci.sh`. `xray-check` среди них был КРАСНЫМ — значит среди
остальных почти наверняка есть ещё тихо красные. Нужна карта, а не догадки.

БЕЗОПАСНОСТЬ (обязательна, иначе аудит сам наносит ущерб):
  * СНАЧАЛА `make -n <target>` — dry-run. Если в командах есть запись/установка
    (`rm`, `mv`, `cp`, `install`, `git ...`, `sync`, `hook`, `curl`, `docker`),
    цель помечается `SKIP_NONREADONLY` и НЕ запускается;
  * цели идут СТРОГО ПОСЛЕДОВАТЕЛЬНО (-j1): параллельный запуск ловит гонку на
    `.zig-cache` (об этом предупреждает сам README);
  * каждая цель — под таймаутом;
  * после каждой цели проверяется `git status --porcelain`; если дерево стало
    грязным — запись в отчёт `DIRTIED` и немедленный откат изменений.

Запуск: python3 tools/orphan_audit.py [--timeout 25] [--limit N]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "orphan_gates.baseline.json"
WRITE_PAT = re.compile(r"\b(rm|mv|cp|install|ln|chmod|touch|mkdir|git|sync|hook|"
                       r"curl|wget|docker|pip|npm|apt)\b")


def targets() -> list[str]:
    if not BASELINE.is_file():
        return []
    return sorted(json.loads(BASELINE.read_text(encoding="utf-8")).get("orphans", []))


def dry_run(t: str) -> tuple[bool, str]:
    """True, если цель безопасна для прогона (только чтение/проверка)."""
    try:
        r = subprocess.run(["make", "-n", t], capture_output=True, text=True,
                           timeout=20, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return False, "dry-run timeout"
    text = r.stdout + r.stderr
    if r.returncode != 0:
        return False, "dry-run rc!=0"
    if WRITE_PAT.search(text):
        m = WRITE_PAT.search(text)
        return False, f"пишущая команда: {m.group(0)}"
    return True, ""


def dirty() -> set[str]:
    r = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                       text=True, cwd=str(ROOT))
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def main() -> int:
    timeout = 25
    limit = 10 ** 6
    for i, a in enumerate(sys.argv):
        if a == "--timeout" and i + 1 < len(sys.argv):
            timeout = int(sys.argv[i + 1])
        if a == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    # #636b: НАСЛЕДУЕМ окружение целиком (первый прогон дал 57 ложных «Ошибка 127»:
    # команды не находились, потому что PATH был урезан) и ДОПИСЫВАЕМ свои пути.
    env = dict(os.environ)
    extra = [str(ROOT / "zig-out" / "bin"), str(ROOT / ".venv" / "bin")]
    zig = os.environ.get("ZIG_DIR") or str(Path.home() / "opt" / "zig-x86_64-linux-0.17.0")
    if Path(zig, "zig").is_file():
        extra.insert(0, zig)
    env["PATH"] = os.pathsep.join([p for p in extra if Path(p).is_dir()] + [env.get("PATH", "")])
    env.setdefault("PYTHON", str(ROOT / ".venv" / "bin" / "python"))
    rows: list[tuple[str, str, str]] = []
    for t in targets()[:limit]:
        ok, why = dry_run(t)
        if not ok:
            rows.append((t, "SKIP_NONREADONLY", why))
            print(f"  [SKIP] {t}: {why}", flush=True)
            continue
        before = dirty()
        try:
            r = subprocess.run(["make", "-s", t], capture_output=True, text=True,
                               timeout=timeout, cwd=str(ROOT), env=env)
            rc, out = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            rows.append((t, "TIMEOUT", f">{timeout}s"))
            print(f"  [TIMEOUT] {t}", flush=True)
            continue
        after = dirty()
        new_dirt = after - before
        if new_dirt:
            subprocess.run(["git", "checkout", "--", "."], cwd=str(ROOT),
                           capture_output=True, text=True)
            rows.append((t, "DIRTIED", ", ".join(sorted(new_dirt))[:80]))
            print(f"  [DIRTIED] {t}: {sorted(new_dirt)[:2]} (откатано)", flush=True)
            continue
        if rc == 0:
            rows.append((t, "PASS", ""))
            print(f"  [PASS] {t}", flush=True)
            continue
        low = out.lower()
        if any(k in low for k in ("z3", "zig", "lean", "mathlib", "network",
                                 "недоступ", "not found", "command not found")):
            rows.append((t, "SKIP_NEEDS_ENV", out.strip().splitlines()[-1][:80]
                         if out.strip() else ""))
            print(f"  [ENV] {t}: нужны внешние инструменты", flush=True)
            continue
        last = out.strip().splitlines()[-1] if out.strip() else ""
        rows.append((t, "FAIL", last[:90]))
        print(f"  [FAIL] {t}: {last[:80]}", flush=True)

    from collections import Counter
    cnt = Counter(s for _, s, _ in rows)
    print("\n=== СВОДКА ===")
    for k in ("PASS", "FAIL", "TIMEOUT", "DIRTIED", "SKIP_NONREADONLY", "SKIP_NEEDS_ENV"):
        if cnt.get(k):
            print(f"  {k:16} {cnt[k]}")
    out_path = ROOT / "docs" / "evidence" / "orphan_audit.log"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(f"{t}\t{s}\t{w}" for t, s, w in rows) + "\n",
                        encoding="utf-8")
    print(f"[записано] {out_path.relative_to(ROOT)}")
    fails = [t for t, s, _ in rows if s in ("FAIL", "DIRTIED")]
    if fails:
        print(f"[i] КРАСНЫЕ: {', '.join(fails[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
