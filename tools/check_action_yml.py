#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Проверка `action.yml` без обязательной зависимости от PyYAML.

ЗАЧЕМ. Гейт `ecosystem-check` импортировал PyYAML внутри heredoc. В окружении
без PyYAML он печатал «No module named 'yaml'» и объявлял action.yml
невалидным — ОТСУТСТВИЕ БИБЛИОТЕКИ выдавалось за дефект файла (дефект #249).

ЧТО ПРОВЕРЯЕТ (одни и те же четыре утверждения в обоих путях):
  * `inputs.version.default` начинается с `v2.` (тег, с которого качается бинарь);
  * `inputs.mode.default` == `verify`;
  * объявлен выход `sarif-file`;
  * среди шагов есть проверка `sha256sum -c` скачанного бинаря.

Запуск:  python3 tools/check_action_yml.py [путь]
Код возврата: 0 — корректно, 1 — нарушение.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "action.yml"
Q = chr(39) + chr(34)


def parse_with_yaml(src: str):
    import yaml  # noqa: PLC0415
    d = yaml.safe_load(src)
    return (d["inputs"]["version"]["default"],
            d["inputs"]["mode"]["default"],
            list(d["outputs"]),
            any("sha256sum -c" in str(s.get("run", "")) for s in d["runs"]["steps"]),
            "yaml")


def parse_by_text(src: str):
    def field(name: str) -> str:
        pat = (r"^  " + name + r":\s*\n(?:.*\n)*?\s+default:\s*[" + Q + r"]?([^" + Q + r"\n]+)")
        m = re.search(pat, src, re.M)
        return m.group(1).strip() if m else ""
    return (field("version"), field("mode"),
            ["sarif-file"] if "sarif-file" in src else [],
            "sha256sum -c" in src, "text")


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    if not path.exists():
        print(f"[!] нет {path}")
        return 1
    src = path.read_text(encoding="utf-8")
    try:
        ver, mode, outs, sha, how = parse_with_yaml(src)
    except ImportError:
        ver, mode, outs, sha, how = parse_by_text(src)
        print("  [i] PyYAML отсутствует — action.yml проверен по тексту "
              "(те же 4 утверждения)")
    bad = 0
    if not str(ver).startswith("v2."):
        print(f"[!] inputs.version.default = {ver!r} (ожидался тег v2.x)")
        bad += 1
    if mode != "verify":
        print(f"[!] inputs.mode.default = {mode!r} (ожидалось 'verify')")
        bad += 1
    if "sarif-file" not in outs:
        print(f"[!] нет выхода sarif-file: {outs}")
        bad += 1
    if not sha:
        print("[!] в шагах нет проверки SHA256 скачанного бинаря")
        bad += 1
    if bad:
        return 1
    print(f"  [OK] action.yml ({how}): version={ver}, mode=verify, "
          f"sha256-проверка, sarif-file-выход")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
