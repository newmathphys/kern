#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""diff_disasm.py — Diff-Disasm: сравнение ассемблера Debug vs ReleaseFast.

**Что проверяет.** Оптимизатор (LLVM в составе Zig) в `ReleaseFast` вправе
удалить «мёртвый» код (Dead Code Elimination). Опасность: вместе с ним может
исчезнуть **критическая проверка безопасности** (например, guard в
constant-time сравнении). Семантический зонд (`src/semantic_probe.zig`)
ловит это по ДАЙДЖЕСТУ результата; Diff-Disasm ловит это **по СТРУКТУРЕ
ассемблера** — независимым способом.

**Как.** Собираем зонд дважды (`-femit-asm`), извлекаем тела функций и
сравниваем метрики потока управления:

| Метрика | Смысл |
|:--|:--|
| инструкций | размер тела |
| условных переходов (jcc) | ветвления |
| вызовов (call) | обращения к подпрограммам |
| метки `.LBB*` | базовые блоки (форма CFG) |

**Критерии (честные):**
  1. Функция, экспортируемая в Debug, ОБЯЗАНА присутствовать и в ReleaseFast
     (иначе — DCE вырезал её: КРАСНОЕ).
  2. `kern_ct_equal` в ReleaseFast ОБЯЗАНА сохранить условные переходы
     (constant-time не должен превратиться в ветвление по данным — но и не
     должен потерять проверки). Отсутствие jcc при наличии цикла — КРАСНОЕ.
  3. Число блоков может меняться (инлайнинг/разворачивание) — это НЕ ошибка,
     печатается как информация.

Запуск: python3 tools/diff_disasm.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "src" / "binlevel_probe.zig"
FUNCS = ["kern_ct_equal", "kern_early_exit_equal"]


def emit_asm(opt: str, out_path: Path) -> bool:
    cmd = ["zig", "build-obj", str(PROBE), f"-O{opt}", "-femit-asm=" + str(out_path)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return r.returncode == 0 and out_path.exists()


def extract(text: str, name: str) -> str:
    """Тело функции из ассемблера.

    ВАЖНО: тело содержит ЛОКАЛЬНЫЕ метки (`.LBB2_1:`, `.Ltmp73:`), поэтому
    наивный поиск «до следующей метки» обрывал функцию на первой же из них
    (найдено при первом прогоне). Конец функции — метка, которая начинается
    с БУКВЫ/подчёркивания (глобальный символ), а не с точки.
    """
    m = re.search(
        rf"^{re.escape(name)}:\n(.*?)(?=\n[A-Za-z_][A-Za-z0-9_.]*:\n|\Z)",
        text, re.S | re.M)
    return m.group(1) if m else ""


def metrics(body: str) -> dict:
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    ins = [l for l in lines if not l.startswith(".") and not l.endswith(":")]
    jcc = [l for l in ins if re.match(r"^j(?!mp\b)\w+", l)]
    jmp = [l for l in ins if re.match(r"^jmp\b", l)]
    calls = [l for l in ins if l.startswith("call")]
    labels = re.findall(r"^\.LBB[\w_]*:", body, re.M)
    return {
        "инструкций": len(ins),
        "условных_переходов": len(jcc),
        "безусловных_переходов": len(jmp),
        "вызовов": len(calls),
        "базовых_блоков": len(labels),
    }


def main() -> int:
    if not PROBE.exists():
        print(f"[!] нет {PROBE}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="kern-disasm-"))
    dbg, rel = tmp / "dbg.s", tmp / "rel.s"

    if not emit_asm("Debug", dbg):
        print("[!] не удалось собрать Debug-ассемблер (нужен zig в PATH)")
        return 1
    if not emit_asm("ReleaseFast", rel):
        print("[!] не удалось собрать ReleaseFast-ассемблер")
        return 1

    dtext, rtext = dbg.read_text(errors="ignore"), rel.read_text(errors="ignore")

    print("\n=== DIFF-DISASM: Debug vs ReleaseFast ===")
    print("Цель: доказать, что оптимизатор НЕ вырезал критические проверки.\n")

    bad = 0
    for fn in FUNCS:
        dbody, rbody = extract(dtext, fn), extract(rtext, fn)
        if not dbody:
            print(f"  [—] {fn}: нет в Debug (пропуск)")
            continue
        if not rbody:
            print(f"  [КРАСНОЕ] {fn}: ЕСТЬ в Debug, ОТСУТСТВУЕТ в ReleaseFast (DCE?)")
            bad += 1
            continue
        dm, rm = metrics(dbody), metrics(rbody)
        print(f"  {fn}:")
        for k in dm:
            mark = ""
            if k == "условных_переходов" and rm[k] == 0 and dm[k] > 0:
                mark = "  <-- КРАСНОЕ: ветвления исчезли"
                bad += 1
            print(f"    {k:<22} Debug {dm[k]:>4}  ->  ReleaseFast {rm[k]:>4}{mark}")

    print(f"\n{'ВСЁ ЧИСТО: критических вырезаний не найдено' if bad == 0 else 'НАЙДЕНО ПРОБЛЕМ: ' + str(bad)}")
    print("Примечание: изменение ЧИСЛА блоков — норма (инлайнинг/разворачивание),")
    print("ошибкой считается только ПОТЕРЯ функции или ветвлений.\n")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
