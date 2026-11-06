#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""МЕТА-ГЕЙТ #470: ПОТОЛОК ПАМЯТИ у подпроцессов `audits_run.py` РАБОТАЕТ.

ЗАЧЕМ. `#470` ставит RLIMIT_AS на КАЖДЫЙ подпроцесс `make audits`, потому что
`kernc prove` на `audits/rust-core/midpoint.rs` вырос до 5.4 ГБ и продолжал
расти (таймаут 300 с был, потолка памяти не было — при 6 воркерах это могло
вытеснить всю машину). Но лимит, который никто не проверяет, деградирует МОЛЧА:
достаточно потерять `preexec_fn` при рефакторинге — и защита исчезнет, а гейт
останется зелёным. Поэтому здесь три исхода проверяются НАСТОЯЩИМИ
подпроцессами (быстро, без Z3, без сети):

  A. Потолок соблюдён  : потомок просит 8x потолка -> `rc=125` + НАЗВАННАЯ причина;
  B. Смерть по сигналу : `rc<0` (SIGSEGV) -> `rc=125` + ИМЯ сигнала, а не сырое `-11`;
  C. Не-памятный сбой  : `exit 3` проходит БЕЗ изменений (нет ложного обвинения).

НЕВАКУУМНОСТЬ (`--selftest`): при `mem_cap=False` исход A обязан перестать быть
125, а исход B — вернуть сырой отрицательный `rc`. Иначе тест «зеленел» бы и
без лимита, то есть не проверял бы ничего.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Потолок задаётся ДО импорта: `AUDIT_MEM_MB` читается на уровне модуля.
CAP_MB = 128
os.environ["KERN_AUDIT_MEM_MB"] = str(CAP_MB)


def _load():
    spec = importlib.util.spec_from_file_location("audits_run", ROOT / "tools" / "audits_run.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    selftest = "--selftest" in sys.argv
    ar = _load()

    if ar.resource is None:  # pragma: no cover - не-POSIX
        print("[SKIP] resource/RLIMIT_AS недоступны на этой платформе — потолок не проверяем")
        return 0
    assert ar.AUDIT_MEM_MB == CAP_MB, f"потолок не применился: {ar.AUDIT_MEM_MB} != {CAP_MB}"

    fails = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal fails
        if not ok:
            fails += 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")

    # --- A. Потолок РЕАЛЬНО режет: 8x потолка одним куском -------------------
    rc_a, out_a = ar.run([sys.executable, "-c", f"x = bytearray({8 * CAP_MB} * 1024 * 1024)"],
                         timeout=120, mem_cap=True)
    check("A потолок соблюдён", rc_a == 125 and "ЛИМИТ ПАМЯТИ" in out_a,
          f"rc={rc_a}, причина={'ЛИМИТ ПАМЯТИ' if 'ЛИМИТ ПАМЯТИ' in out_a else out_a.strip()[:60]}")

    # --- B. Смерть по СИГНАЛУ: rc<0 -> НАЗВАННЫЙ исход -----------------------
    rc_b, out_b = ar.run(["sh", "-c", "kill -SEGV $$"], timeout=120, mem_cap=True)
    check("B смерть по сигналу", rc_b == 125 and "SIGSEGV" in out_b,
          f"rc={rc_b}, {out_b.strip()[:70]}")

    # --- C. Не-памятный сбой НЕ маскируется под OOM -------------------------
    rc_c, out_c = ar.run(["sh", "-c", "exit 3"], timeout=120, mem_cap=True)
    check("C нет ложного обвинения", rc_c == 3 and "ЛИМИТ ПАМЯТИ" not in out_c,
          f"rc={rc_c} (ожидали неизменный 3)")

    # --- НЕВАКУУМНОСТЬ: без потолка исходы ОБЯЗАНЫ измениться ----------------
    if selftest:
        rc_x, out_x = ar.run([sys.executable, "-c", f"x = bytearray({8 * CAP_MB} * 1024 * 1024)"],
                             timeout=120, mem_cap=False)
        check("A' без потолка 8x выделяется", rc_x == 0 and "ЛИМИТ ПАМЯТИ" not in out_x,
              f"rc={rc_x} (если тут 125 — тест был бы вакуумным)")
        rc_y, out_y = ar.run(["sh", "-c", "kill -SEGV $$"], timeout=120, mem_cap=False)
        check("B' без потолка сырой rc", rc_y == -11 and "SIGSEGV" not in out_y,
              f"rc={rc_y} (сырой сигнал не должен называться нашей ветвью)")

    print(f"[{'FAIL' if fails else 'OK'}] гейт #470: проверок провалено {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
