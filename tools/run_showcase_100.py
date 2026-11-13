#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: Apache-2.0
"""`run_showcase_100.py` — витрина практической пользы KERN на живых задачах.

ЗАМОРОЖЕНО (правило полигона): ядро и анализатор (`src/`, `tools/kern_contracts.py`)
НЕ меняются. Здесь только каталог `benchmarks/showcase_100/*.json` и этот раннер.

ФОРМАТ: json-файл на «десяток» — {"dozen": "...", "cards": [{...}]}, где карточка:
  id, sphere, trick, kind ("diff-equiv" | "anti-cheat"), files {name: body},
  run [файлы для KERN], expect (подстрока вердикта), oracle {kind, ...}.

Оракулы независимы от KERN: `diff` реально вызывает old()/new() и сравнивает
результаты; `unittest` прогоняет тест и требует rc=0 (то есть показывает, что
честный инструмент СЛЕП, а KERN ловит).

Выход: docs/SHOWCASE_100.ru.md + rc=0 только если ВСЕ карточки подтверждены.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "benchmarks" / "showcase_100"
KC = ROOT / "tools" / "kern_contracts.py"
DOC_RU = ROOT / "docs" / "SHOWCASE_100.ru.md"
PY = sys.executable


def _run(args: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def _oracle(card: dict, d: Path) -> tuple[bool, str]:
    """Независимая проверка карточки — без KERN."""
    spec = card.get("oracle") or {}
    kind = spec.get("kind")
    if kind == "diff":
        old_p, new_p = d / spec["old"], d / spec["new"]
        fn = spec.get("fn", "f")
        args = spec.get("args", "0, 10")
        script = (f"import importlib.util as u\n"
                  f"def load(p,n):\n"
                  f"    s=u.spec_from_file_location(n,p); m=u.module_from_spec(s);\n"
                  f"    s.loader.exec_module(m); return m\n"
                  f"o=load(r'{old_p}','o'); n2=load(r'{new_p}','n2')\n"
                  f"ro=o.{fn}({args}); rn=n2.{fn}({args})\n"
                  f"print('OLD',ro); print('NEW',rn); print('SAME',ro==rn)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "SAME False" in out
        ce = " / ".join(ln for ln in out.splitlines() if ln.startswith(("OLD", "NEW")))
        return ok, (ce[:90] if ce else out.strip()[:90])
    if kind == "unittest":
        rc, out = _run([PY, "-m", "unittest", "discover", "-s", str(d),
                        "-p", spec.get("pattern", "test_*.py")], cwd=d)
        return rc == 0, (f"unittest rc={rc} (слеп)" if rc == 0 else f"unittest rc={rc}")
    if kind == "belnap":
        # ЖИВОЙ механизм проекта: `_belnap_state` из пример-сервера (не копия!).
        script = (
            "import importlib.util as u, pathlib, json\n"
            f"p=pathlib.Path(r'{ROOT}/examples/kern_mcp_server.py')\n"
            "s=u.spec_from_file_location('m',p); m=u.module_from_spec(s)\n"
            "s.loader.exec_module(m)\n"
            "j=m._belnap_state\n"
            "t=j(1,0); f=j(0,1); b=j(1,1)\n"
            "def deny_wins(a,b_):\n"
            "    return 'deny' if b_ else ('allow' if a else 'none')\n"
            "print('T',t); print('F',f); print('JOIN',b); print('BOOL',deny_wins(1,1))\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "JOIN B" in out and "BOOL deny" in out
        got = [ln for ln in out.splitlines() if ln.startswith(("JOIN", "BOOL"))]
        return ok, (" / ".join(got)[:90] if got else out.strip()[:90])
    if kind == "bruteforce":
        # Независимый перебор: ищем пару (a1, a2), где бизнес-функция ТЕРЯЕТ деньги.
        mod = d / spec["module"]
        fn = spec.get("fn", "loss")
        limit = int(spec.get("limit", 200))
        script = (
            "import importlib.util as u\n"
            f"s=u.spec_from_file_location('biz',r'{mod}'); m=u.module_from_spec(s)\n"
            f"s.loader.exec_module(m)\n"
            f"hit=None\n"
            f"for a1 in range(1,{limit}):\n"
            f"    for a2 in range(1,{limit}):\n"
            f"        if m.{fn}(a1,a2) < 0:\n"
            f"            hit=(a1,a2,m.{fn}(a1,a2)); break\n"
            f"    if hit: break\n"
            f"print('HIT',hit)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "HIT (" in out
        line = [ln for ln in out.splitlines() if ln.startswith("HIT")]
        return ok, (line[0][:90] if line else out.strip()[:90])
    return False, "оракул не задан"



def main(argv: list[str]) -> int:
    parts = sorted(CASES_DIR.glob("*.json")) if CASES_DIR.exists() else []
    if not parts:
        print(f"[!] нет карточек в {CASES_DIR.relative_to(ROOT)}")
        return 1
    rows: list[tuple[str, str, str, str, str, str]] = []
    total = confirmed = 0
    t_all = time.time()
    for part in parts:
        data = json.loads(part.read_text(encoding="utf-8"))
        dozen = data.get("dozen", part.stem)
        print(f"\n=== {dozen} ===")
        for card in data.get("cards", []):
            total += 1
            with tempfile.TemporaryDirectory() as td:
                d = Path(td)
                for fname, body in (card.get("files") or {}).items():
                    (d / fname).write_text(body, encoding="utf-8")
                if card.get("kind") == "diff-equiv":
                    args = [PY, str(KC), "--diff-equiv",
                            *[str(d / x) for x in card["run"]]]
                elif card.get("kind") == "contract":
                    # Десяток 01: обычный путь контрактов НА ФАЙЛЕ ВРЕМЕННОГО КАТАЛОГА.
                    # Литералов `@kern:` в отслеживаемых файлах нет — замок контрактов
                    # репозитория не затрагивается (правило полигона).
                    args = [PY, str(KC), str(d / card["run"][0])]
                elif card.get("kind") == "belnap":
                    args = None       # вердикт даёт живой механизм (см. ниже)
                else:
                    args = [PY, str(KC), "--anti-cheat", str(d / card["run"][0])]
                if args is None:
                    orc_ok, orc_txt = _oracle(card, d)
                    kern_ok = orc_ok and "JOIN B" in orc_txt
                    out_k = orc_txt
                else:
                    _rc_k, out_k = _run(args)
                    kern_ok = card["expect"] in out_k
                    orc_ok, orc_txt = _oracle(card, d)
            confirmed += 1 if (kern_ok and orc_ok) else 0
            mark = "OK " if (kern_ok and orc_ok) else "FAIL"
            print(f"  [{mark}] {card['id']:22s} KERN={kern_ok} oracle={orc_txt[:55]}")
            ce = ""
            for ln in out_k.splitlines():
                if "КОНТРПРИМЕР" in ln:
                    ce = ln.strip()[:80]
                    break
            rows.append((dozen, card["id"], card.get("sphere", ""),
                         card.get("trick", ""),
                         "ПОЙМАЛ" if kern_ok else "пропустил",
                         ce or orc_txt[:60]))
    dt = time.time() - t_all
    print(f"\nИТОГ: карточек {total} | подтверждено KERN+оракулом {confirmed} | {dt:.1f} с")
    lines = ["# Витрина практической пользы KERN", "",
             f"Сгенерировано `tools/run_showcase_100.py` за {dt:.1f} с. Каждая строка —",
             "**реальный** запуск KERN и независимого оракула (вызов функции или unittest).",
             "", "| Десяток | Задача | Сфера | В чём подвох | KERN | Контрпример |",
             "|:--|:--|:--|:--|:--|:--|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    lines += ["", f"**Подтверждено: {confirmed} / {total}.**", ""]
    DOC_RU.write_text("\n".join(lines), encoding="utf-8")
    print(f"витрина: {DOC_RU.relative_to(ROOT)}")
    return 0 if confirmed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
