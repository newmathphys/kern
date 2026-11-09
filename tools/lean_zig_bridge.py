#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""МОСТ Lean 4 <-> Zig: доказательство, что ЯДРО реализует ровно ту алгебру B₄,
которая записана и доказана в Lean (`formal/KernAllMath.lean`).

ПОЧЕМУ ЭТО НЕ «СВЕРКА НА ПРИМЕРАХ». Домен конечен: 4 значения × 4 = 16 пар для
`joinK`/`meetK` и 4 значения для `notB`/`conflate`, итого 40 входов. Таблица
считается ДВУМЯ независимыми способами:

  * `formal/KernBelnapTable.lean` — ОПРЕДЕЛЕНИЕМ Lean (не рукописью: `def joinK` …);
  * `kernx belnap-table` — РЕАЛИЗАЦИЕЙ ЯДРА (`src/core/eq2.zig`).

Если таблицы совпали на ВСЕХ входах, функции равны всюду (домен исчерпан) — это
и есть refinement для этого компонента, в отличие от «проверили 5 значений».
Законы решётки (`joinK_comm/assoc/idem`, `contradiction_isolation`, `conflate_*`)
доказаны в Lean о ТОМ ЖЕ определении, поэтому они переносятся на код.

ЧЕГО ЭТОТ ГЕЙТ НЕ ДОКАЗЫВАЕТ (названная граница, не спрятано): связь Lean с
остальным ядром — решателем LIA/Фаркашем и пруф-чекером. Там домен бесконечен,
и нужен refinement-пруф, а не исчерпание таблицы.

Коды: 0 — таблицы совпали; 1 — РАСХОЖДЕНИЕ (дефект кода); 2 — Lean недоступен
(НАЗВАННЫЙ отказ: без Lean проверять нечего, «зелёным» это не считается).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_FILE = ROOT / "formal" / "KernBelnapTable.lean"
KERNX = ROOT / "zig-out" / "bin" / "kernx"
EXPECTED_LINES = 40


def _lean() -> str | None:
    """Путь к `lean` (elan ставит его в ~/.elan/bin — там его и ищем)."""
    for cand in (shutil.which("lean"),
                 str(Path.home() / ".elan" / "bin" / "lean"),
                 str(ROOT / ".venv" / "bin" / "lean")):
        if cand and Path(cand).is_file():
            return cand
    return None


def run_lean(lean: str) -> tuple[int, str]:
    p = subprocess.run([lean, "--run", str(LEAN_FILE)], capture_output=True,
                       text=True, timeout=600, cwd=str(ROOT))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_zig() -> tuple[int, str]:
    if not KERNX.exists():
        return 2, f"нет {KERNX} (соберите: zig build)"
    p = subprocess.run([str(KERNX), "belnap-table"], capture_output=True,
                       text=True, timeout=300, cwd=str(ROOT))
    return p.returncode, p.stdout or ""


def compare(lean_out: str, zig_out: str) -> list[str]:
    """Построчное сравнение; пустой список — совпало."""
    a = [ln.strip() for ln in lean_out.splitlines() if "|" in ln]
    b = [ln.strip() for ln in zig_out.splitlines() if "|" in ln]
    problems: list[str] = []
    if len(a) != EXPECTED_LINES:
        problems.append(f"Lean дал {len(a)} строк, ожидалось {EXPECTED_LINES} "
                        f"(таблица НЕПОЛНА — сравнение было бы вакуумным)")
    if len(b) != EXPECTED_LINES:
        problems.append(f"ядро дало {len(b)} строк, ожидалось {EXPECTED_LINES}")
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            problems.append(f"строка {i}: Lean `{x}` != Zig `{y}`")
            if len(problems) > 8:
                problems.append("… (ещё есть расхождения)")
                break
    return problems


def selftest() -> int:
    """Гейт обязан ЛОВИТЬ расхождение: подделываем одну строку таблицы."""
    rc, out = run_zig()
    if rc != 0 or not out.strip():
        print(f"[!] нет таблицы ядра (rc={rc}) — самотест невозможен")
        return 2
    good = [ln for ln in out.splitlines() if "|" in ln]
    bad = list(good)
    # меняем РЕЗУЛЬТАТ одной операции: joinK|N|T|<res> -> неверный символ
    for i, ln in enumerate(bad):
        if ln.startswith("joinK|N|T|"):
            bad[i] = "joinK|N|T|F"          # по определению должно быть T
            break
    det = compare("\n".join(good), "\n".join(bad))
    if det:
        print(f"  [OK] самотест: подмена одной строки замечена — {det[0]}")
        return 0
    print("  [FAIL] самотест: подмена строки НЕ замечена — сравнение вакуумно")
    return 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    lean = _lean()
    if lean is None:
        print("[!] Lean не найден (нет `lean` ни в PATH, ни в ~/.elan/bin) — проверка "
              "моста НЕВОЗМОЖНА. Это названный отказ, а НЕ «мост в порядке».")
        return 2
    rc_l, out_l = run_lean(lean)
    if rc_l != 0:
        print(f"[!] Lean завершился с rc={rc_l}:")
        print(out_l.strip()[-600:])
        return 2
    rc_z, out_z = run_zig()
    if rc_z != 0:
        print(f"[!] ядро не отдало таблицу (rc={rc_z}): {out_z.strip()[:200]}")
        return 2
    problems = compare(out_l, out_z)
    if problems:
        print("[FAIL] МОСТ Lean<->Zig: таблица ЯДРА расходится с Lean-определением:")
        for p in problems:
            print(f"  - {p}")
        print("  Это дефект КОДА (или определения), а не «шум окружения».")
        return 1
    print(f"[OK] мост Lean<->Zig: таблица B₄ совпала на ВСЕХ {EXPECTED_LINES} входах "
          f"(joinK 16 · meetK 16 · notB 4 · conflate 4) — домен исчерпан, "
          f"функции равны, законы Lean переносятся на ядро")
    return 0


if __name__ == "__main__":
    sys.exit(main())
