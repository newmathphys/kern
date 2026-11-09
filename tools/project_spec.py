#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ЗАКОН ПРОЕКТА `KERN.md`: проверить папку по одному текстовому контракту, не трогая код.

ЗАЧЕМ. Раньше контракт нужно было вписывать комментарием В КАЖДЫЙ файл проекта, а потом
помнить десяток флагов. Здесь наоборот: **один файл `KERN.md` в корне проекта** описывает
законы, а инструмент проверяет по нему папку. Исходники проекта НЕ изменяются — для
проверки делается временная копия файла, в которую подставляются строки контракта.

ЧТО ПРОВЕРЯЕТСЯ (четыре исхода, как в решётке Белнапа):
  T  закон доказан (Z3 + пруф-чекер)                     -> `[T] ДОКАЗАНО`
  F  закон опровергнут, печатается контрпример           -> `[F] НАРУШЕН`
  N  функции нет в законе / проверить не удалось         -> `[N] НЕ ОПИСАНА` (Zero-Miss)
  B  КОНФЛИКТ: тесты проекта зелёные, а закон нарушен    -> `[B] КОНФЛИКТ`

Формат `KERN.md` (минимальный, человекочитаемый):

    # Контракт проекта
    - require_all_functions_covered: true
    - tests: tests/

    ### bank.py :: withdraw(balance, amount)
    - requires: balance >= 0 and amount >= 0 and amount <= balance
    - ensures: result >= 0 and result <= balance
    - secret: secret_key          (необязательные директивы передаются как есть)

Запуск:
    python3 tools/project_spec.py ПАПКА              # проверить по KERN.md
    python3 tools/project_spec.py --init ПАПКА       # создать черновик KERN.md
Коды: 0 — все законы доказаны и все функции описаны; 1 — есть F/B/N; 2 — нет KERN.md
(названный отказ), нет инструмента или сломан формат.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
PY = sys.executable
SRC_EXT = {".py", ".c", ".h", ".cpp", ".cc", ".hpp", ".rs", ".zig", ".go", ".ts", ".tsx", ".js"}
DIRECTIVES = ("requires", "ensures", "bitvec32", "bitvec64", "array", "invariant",
              "decreases", "len", "secret", "pricing", "no_arbitrage", "rls", "float")
FN_RE = {
    ".py": re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", re.M),
    ".go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", re.M),
    ".rs": re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", re.M),
    ".zig": re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", re.M),
}
FN_RE_DEFAULT = re.compile(
    r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{?\s*$", re.M)


def inventory(root: Path) -> dict[str, list[str]]:
    """Все функции проекта: {относительный путь: [имена]}."""
    out: dict[str, list[str]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in SRC_EXT:
            continue
        if any(part in {".git", "node_modules", ".venv", "dist", "build"} for part in p.parts):
            continue
        # Тестовые файлы — не «законы проекта»: их проверяет --anti-cheat, а не KERN.md.
        if p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py":
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rx = FN_RE.get(p.suffix, FN_RE_DEFAULT)
        names = sorted(set(rx.findall(src)))
        if names:
            out[str(p.relative_to(root))] = names
    return out


def parse_spec(path: Path) -> tuple[dict, dict]:
    """Вернуть ({'rel :: fn': {директива: значение}}, {глобальные опции})."""
    laws: dict[str, dict] = {}
    opts: dict[str, str] = {}
    cur: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m_fn = re.match(r"^#{2,4}\s*(.+?)\s*::\s*([A-Za-z_]\w*)\s*(?:\(.*\))?\s*$", line)
        if m_fn:
            cur = f"{m_fn.group(1).strip()} :: {m_fn.group(2)}"
            laws.setdefault(cur, {})
            continue
        m_opt = re.match(r"^\s*[-*]\s*([a-z_]+)\s*:\s*(.+?)\s*$", line)
        if not m_opt:
            continue
        key, val = m_opt.group(1), m_opt.group(2)
        if cur is None:
            opts[key] = val
        elif key in DIRECTIVES:
            laws[cur][key] = val
    return laws, opts


def _inject(src_path: Path, fn: str, spec: dict, tmp: Path) -> Path | None:
    """Копия файла с контрактом НАД функцией (исходник проекта не меняется)."""
    try:
        text = src_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    suffix = src_path.suffix
    marker = "#" if suffix == ".py" else "//"
    block = "".join(f"{marker} @kern:{k} {v}\n" if v else f"{marker} @kern:{k}\n"
                    for k, v in spec.items())
    patterns = {
        ".py": rf"^(\s*)def\s+{re.escape(fn)}\s*\(",
        ".go": rf"^(func\s+(?:\([^)]*\)\s*)?{re.escape(fn)}\s*\()",
        ".rs": rf"^(\s*(?:pub\s+)?fn\s+{re.escape(fn)}\s*\()",
        ".zig": rf"^(\s*(?:pub\s+)?fn\s+{re.escape(fn)}\s*\()",
    }
    rx = patterns.get(suffix) or rf"^([A-Za-z_][\w\s\*]*?\b{re.escape(fn)}\s*\()"
    m = re.search(rx, text, re.M)
    if not m:
        return None
    out = text[:m.start()] + block + text[m.start():]
    dst = tmp / (src_path.stem + src_path.suffix)
    dst.write_text(out, encoding="utf-8")
    return dst


def verdict(path: Path) -> tuple[str, str]:
    """T/F/N по вердикту экстрактора + пруф-чекера."""
    # #568 (класс #513): в ЗАМОРОЖЕННОМ бинаре файла `kern_contracts.py` нет, а
    # `sys.executable` — это сам `kerna`. Диспетчер принимает одиночный файл,
    # поэтому зовём его БЕЗ пути экстрактора (он срежет аргумент сам).
    _frozen = bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))
    _cmd = ([PY, str(path)] if _frozen else [PY, str(EXTRACTOR), str(path)])
    try:
        p = subprocess.run(_cmd, capture_output=True, text=True,
                           timeout=300, errors="replace")
    except subprocess.TimeoutExpired:
        return "N", "таймаут проверки"
    out = (p.stdout or "") + (p.stderr or "")
    if "ДОКАЗАНО" in out and "нарушено 0" in out:
        m = re.search(r"\[PROOF[^\]]*\]\s*([^\n]+)", out)
        return "T", (m.group(1).strip()[:90] if m else "доказано")
    if "КОНТРАКТ НАРУШЕН" in out or re.search(r"нарушено [1-9]", out):
        m = re.search(r"\[КОНТРПРИМЕР\]\s*([^\]\n]+)", out)
        why = m.group(1).strip()[:90] if m else "нарушен"
        # ЗАМОК РЕАЛЬНОСТИ №1: живое подтверждение аварии настоящим рантаймом.
        if "[RUNTIME CONFIRMED]" in out:
            why += " | [RUNTIME CONFIRMED]"
        return "F", why
    m = re.search(r"\[SKIP\]\s*([^\n]+)", out)
    return "N", ("проверить не удалось: " + (m.group(1).strip()[:70] if m else "нет вердикта"))


def tests_green(root: Path, tests_opt: str | None) -> bool | None:
    """Зелёные ли обычные тесты проекта (нужно только для конфликта B)."""
    if not tests_opt:
        return None
    target = root / tests_opt
    if not target.exists():
        return None
    # ВАЖНО: `sys.executable` в замороженном бинаре — сам `kerna`, а не python.
    # Поэтому pytest ищем в PATH; нет -> None (B не заявляется — названный пропуск).
    import shutil as _sh
    py = _sh.which("python3") or _sh.which("python")
    if not py:
        return None
    try:
        p = subprocess.run([py, "-m", "pytest", "-q", str(target)], capture_output=True,
                           text=True, timeout=600, cwd=str(root), errors="replace")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return p.returncode == 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("[!] usage: project_spec.py [--init] ПАПКА")
        return 2
    init_mode = "--init" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print("[!] не указана папка проекта")
        return 2
    root = Path(args[0]).resolve()
    if not root.is_dir():
        print(f"[!] нет такой папки: {root}")
        return 2
    inv = inventory(root)
    spec_path = root / "KERN.md"

    if init_mode:
        if spec_path.exists():
            print(f"[!] KERN.md уже есть: {spec_path} — не перезаписываю")
            return 2
        lines = ["# Контракт проекта (черновик, создан KERN)", "",
                 "- require_all_functions_covered: true", ""]
        for rel, fns in inv.items():
            for fn in fns:
                lines += [f"### {rel} :: {fn}", "- requires: ПРИМЕР  x >= 0",
                          "- ensures: ПРИМЕР  result >= 0", ""]
        spec_path.write_text("\n".join(lines), encoding="utf-8")
        total = sum(len(v) for v in inv.values())
        print(f"[OK] черновик создан: {spec_path} — функций в проекте {total}")
        print("     замените строки ПРИМЕР на настоящие законы и запустите без --init")
        return 0

    if not spec_path.is_file():
        print(f"[!] нет закона проекта {spec_path} — создать черновик: --init {root}")
        return 2
    laws, opts = parse_spec(spec_path)
    strict = str(opts.get("require_all_functions_covered", "")).strip().lower() in ("true", "1", "yes")

    described = {k.split(" :: ")[1] for k in laws}
    missing = [(rel, fn) for rel, fns in inv.items() for fn in fns if fn not in described]

    res: dict[str, list] = {"T": [], "F": [], "N": [], "B": []}
    with tempfile.TemporaryDirectory(prefix="kern_spec_") as td:
        tmp = Path(td)
        for key, spec in laws.items():
            rel, fn = key.split(" :: ")
            src = root / rel
            if not src.is_file():
                res["N"].append((key, f"файла нет: {rel}"))
                continue
            injected = _inject(src, fn, spec, tmp)
            if injected is None:
                res["N"].append((key, f"функция не найдена в {rel}"))
                continue
            v, why = verdict(injected)
            res[v].append((key, why))

    # КОНФЛИКТ БЕЛНАПА: тесты зелёные, а закон нарушен -> B, не F.
    _tests = opts.get("tests")
    _green = tests_green(root, _tests)
    if _tests and _green is None:
        print(f"  [i] тесты проекта НЕ ЗАПУЩЕНЫ (pytest недоступен) — конфликт B не проверялся: {_tests}")
    if _green is True:
        _moved = {k for k, _w in res["F"]}
        for key, why in list(res["F"]):
            res["B"].append((key, f"тесты проекта ЗЕЛЁНЫЕ, а закон нарушен ({why})"))
        res["F"] = [(k, w) for k, w in res["F"] if k not in _moved]

    print("=" * 74)
    print(f"KERN.md: ЗАКОН ПРОЕКТА — {root}")
    print("=" * 74)
    print(f"  функций в проекте: {sum(len(v) for v in inv.values())} | "
          f"законов в KERN.md: {len(laws)} | "
          f"режим «ничего не упускать»: {'ДА' if strict else 'нет'}")
    for tag, title in (("T", "ДОКАЗАНО"), ("F", "НАРУШЕНО"),
                       ("B", "КОНФЛИКТ: тесты зелёные, закон нарушен"),
                       ("N", "НЕ ПРОВЕРЕНА")):
        for key, why in res[tag]:
            print(f"  [{tag}] {title}: {key} — {why}")
    if missing:
        for rel, fn in (missing if strict else missing[:10]):
            print(f"  [N] НЕ ОПИСАНА В KERN.md: {rel} :: {fn}")
        if not strict and len(missing) > 10:
            print(f"  ... и ещё {len(missing) - 10} (включите require_all_functions_covered)")
    print("-" * 74)
    bad = len(res["F"]) + len(res["B"]) + len(res["N"]) + (len(missing) if strict else 0)
    print(f"ИТОГ: T {len(res['T'])} | F {len(res['F'])} | B {len(res['B'])} | "
          f"N(в законе) {len(res['N'])} | не описано {len(missing)}")
    if bad == 0:
        print("ЗАКОН ПРОЕКТА ВЫПОЛНЕН: все законы доказаны, все функции описаны")
        return 0
    print("ЗАКОН ПРОЕКТА НАРУШЕН — каждая строка выше несёт причину")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
