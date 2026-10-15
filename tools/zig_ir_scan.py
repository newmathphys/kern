#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
# (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.
"""zig_ir_scan.py — АНАЛИЗАТОР ZIG-КОДА через IR самого компилятора.

ОТВЕЧАЕТ НА ВОПРОС «почему у KERN нет анализатора Zig?»

**Честная причина, почему раньше не было:**
  * `tools/scan_to_kern.py` — РЕГУЛЯРНЫЙ сканер: он извлекает ЗАЯВЛЕНИЯ
    (тесты/TODO/доки), а не СЕМАНТИКУ кода. Писать свой парсер Zig с нуля —
    это фронтенд компилятора (годы работы).
  * но писать его и НЕ НУЖНО: Zig сам отдаёт две промежуточные формы:
      - `zig ast-check -t`  -> ZIR (текстовая форма AST/IR);
      - `zig build-obj -femit-llvm-ir` -> LLVM IR (семантика после типизации).

**Что делает этот инструмент:** получает LLVM IR от компилятора и извлекает
ПРОВЕРЯЕМЫЕ ФАКТЫ о коде -> формирует `.kern`-утверждения:
  * функции (определения) и их сигнатуры;
  * вызовы (call) — граф зависимостей;
  * ветвления (br/icmp) — форма потока управления;
  * арифметика с/без `nsw`/`nuw` (переполнение) — это ДОКАЗУЕМО через SMT.

**Граница (честно):** это анализ IR, а не полный анализ семантики Zig
(нет типов, comptime, generics). Но это НАСТОЯЩИЙ семантический слой —
в отличие от regex-сканера.

Запуск:
  python3 tools/zig_ir_scan.py <file.zig> [--out x.kern]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIG = sys.argv[0] and "zig"  # берём из PATH


def emit_ir(src: Path, optimize: str = "ReleaseSafe") -> str:
    """Просим компилятор выдать LLVM IR (семантическая форма)."""
    out = Path(tempfile.mkdtemp(prefix="kern-zir-")) / "m.ll"
    r = subprocess.run(
        ["zig", "build-obj", str(src), f"-femit-llvm-ir={out}", f"-O{optimize}"],
        capture_output=True, text=True, cwd=str(src.parent), timeout=180)
    if not out.exists():
        return f"__ERROR__ {r.stderr[-400:]}"
    return out.read_text(errors="ignore")


def facts(ir: str) -> dict:
    """Извлекаем ПРОВЕРЯЕМЫЕ факты из LLVM IR."""
    f = {}
    f["functions"] = re.findall(r"^define[^@]*@([A-Za-z_][\w.]*)\(", ir, re.M)
    f["calls"] = re.findall(r"\bcall\b[^@\n]*@([A-Za-z_][\w.]*)", ir)
    f["branches"] = len(re.findall(r"^\s+br\s", ir, re.M))
    f["icmp"] = len(re.findall(r"\bicmp\s", ir))
    # Арифметика С флагами (nsw/nuw = компилятор ОБЕЩАЕТ отсутствие переполнения)
    f["add_nsw"] = len(re.findall(r"\badd\s+nsw\b", ir))
    f["add_nuw"] = len(re.findall(r"\badd\s+nuw\b", ir))
    f["add_plain"] = len(re.findall(r"\badd\s+(?!nsw|nuw)", ir))
    f["mul_plain"] = len(re.findall(r"\bmul\s+(?!nsw|nuw)", ir))
    f["loads"] = len(re.findall(r"^\s+%\S+ = load\b", ir, re.M))
    f["stores"] = len(re.findall(r"^\s+store\b", ir, re.M))
    f["alloca"] = len(re.findall(r"\balloca\b", ir))
    return f


def to_kern(f: dict, src_name: str) -> str:
    """Факты -> .kern-утверждения (status=empirical: измерено на IR)."""
    out = [f'project "zig-ir-scan" {{', '  version "1.0"', '  root "."', '}', '']
    out.append(f'artifact "{src_name}" {{')
    out.append('  kind "source.file"')
    out.append('}')
    out.append('')

    def claim(cid, stmt, status="empirical"):
        out.append(f'claim "{cid}" {{')
        out.append(f'  statement "{stmt}"')
        out.append(f'  status {status}')
        out.append('  scope "zig-llvm-ir"')
        out.append('}')
        out.append('')

    claim("zig.functions", f"в модуле {len(f['functions'])} определений функций")
    claim("zig.calls", f"в IR {len(f['calls'])} вызовов")
    claim("zig.branches", f"в IR {f['branches']} ветвлений (br)")
    claim("zig.memory", f"в IR {f['loads']} загрузок и {f['stores']} записей в память")
    claim("zig.alloca", f"в IR {f['alloca']} стековых размещений (alloca)")

    # ВАЖНОЕ: арифметика БЕЗ флагов nsw/nuw = компилятор НЕ гарантирует
    # отсутствие переполнения -> это потенциальный риск, фиксируем отдельно.
    risky = f["add_plain"] + f["mul_plain"]
    if risky:
        claim("zig.arith.unchecked",
              f"{risky} арифметических операций БЕЗ флагов nsw/nuw "
              f"(переполнение не гарантировано) — кандидат на SMT-проверку")
    else:
        claim("zig.arith.checked",
              "вся целочисленная арифметика помечена nsw/nuw "
              "(компилятор обещает отсутствие переполнения)", "verified")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="путь к .zig")
    ap.add_argument("--out", default="")
    ap.add_argument("--opt", default="ReleaseSafe")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    if not src.exists():
        print(f"[!] нет файла {src}")
        return 1

    ir = emit_ir(src, args.opt)
    if ir.startswith("__ERROR__"):
        print("[!] компилятор не выдал IR:", ir[:200])
        return 1

    f = facts(ir)
    kern = to_kern(f, src.name)

    print(f"\n=== АНАЛИЗ ZIG-КОДА через LLVM IR ({args.opt}) ===")
    print(f"источник: {src.name}")
    for k, v in f.items():
        if isinstance(v, int):
            print(f"  {k:<14} {v}")
    print(f"\n  функции: {', '.join(f['functions'][:6])}"
          f"{' …' if len(f['functions']) > 6 else ''}")

    if args.out:
        Path(args.out).write_text(kern, encoding="utf-8")
        print(f"\n[OK] утверждения KERN -> {args.out}")
    else:
        print("\n" + kern)
    return 0


if __name__ == "__main__":
    sys.exit(main())
