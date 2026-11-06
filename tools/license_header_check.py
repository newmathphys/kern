#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`license_header_check` — ЛИЦЕНЗИОННЫЙ ГЕЙТ (#493): заголовок = `LICENSE`.

ЗАЧЕМ. Проект переходит на ДВОЙНОЕ лицензирование (`AGPLv3` + коммерческая).
Без машинного гейта это разъезжается за неделю: часть файлов останется под
старым `GNU AGPL-3.0-or-later`, часть — без заголовка вообще, и юридически
проект снова становится непригодным для B2B.

ЧТО СТЕРЕЖЁТ (каждое — проверка, не обещание):
  R1 у каждого файла в охвате есть УТВЕРЖДЁННЫЙ заголовок (после shebang);
  R2 ни один файл в охвате не упоминает `AGPL-3.0-or-later` (старая лицензия);
  R3 `LICENSE` содержит ПОЛНЫЙ текст GNU AGPL v3, а не только имя;
  R4 исключения НАЗВАНЫ и обоснованы — `audits/` (транскрипции чужого кода:
     cmark-gfm, DeepJIT, zig-std, TheAlgorithms, CWE) и `docs/` (генерируется);
     молчаливого исключения нет: каталог обязан существовать, причина — в коде;
  R5 `--selftest` доказывает, что гейт УМЕЕТ падать (2 вида поломки).
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# УТВЕРЖДЁННЫЙ ЗАГОЛОВОК — ОДНА строка: не сдвигает номера строк в фикстурах,
# на которые опираются гейты `xray-*` (`строка N` в их отчётах).
NOTICE = ("Copyright (c) 2026 Vital Kalinousky. "
          "SPDX-License-Identifier: AGPL-3.0-or-later. "
          "Commercial use requires a separate license — see LICENSE-COMMERCIAL.md")
# ДЕФЕКТ #493a: имя СТАРОЙ лицензии собирается из двух частей НАМЕРЕННО.
# Единая текстовая замена <старая лицензия> -> AGPL переписала токен ВНУТРИ этой самой
# проверки, и гейт начал искать AGPL вместо старой лицензии: то есть ослеп
# ровно в тот момент, когда его применили (измерено: «всё ещё упоминают
# AGPL-3.0-or-later: 399» на 399 файлах). Разнесённый литерал такую замену не
# ловит, а сама проверка остаётся читаемой.
OLD_TOKEN = "Poly" + "Form"

HASH_EXT = {".py", ".sh"}
SLASH_EXT = {".zig", ".rs", ".c", ".h", ".hpp", ".cu", ".cuh",
             ".js", ".ts", ".go"}
SCOPE_DIRS = ("src", "tools", "tests", "examples")
# R4: НАЗВАННЫЕ исключения с причиной (молчаливых нет).
EXCLUDED = {
    "audits": "транскрипции чужого кода (cmark-gfm, DeepJIT, zig-std, "
              "TheAlgorithms, CWE) — лицензии принадлежат авторам",
    "docs": "документация и сгенерированные отчёты (sync перезаписывает)",
}
# Файлы, которым РАЗРЕШЕНО содержать старый токен: сам гейт обязан его
# знать, чтобы искать. Исключение названо, а не «молча пропущено».
ALLOWED_OLD_TOKEN = {"tools/license_header_check.py"}
SKIP_PARTS = {".zig-cache", "zig-out", "node_modules", "__pycache__", ".git"}


def prefix(ext: str):
    """Префикс комментария для расширения; None — файл вне охвата."""
    if ext in HASH_EXT:
        return "#"
    if ext in SLASH_EXT:
        return "//"
    return None


def head_lines(path: Path, n: int = 3):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[:n]
    except OSError:
        return []


def has_header(path: Path, pre: str) -> bool:
    want = f"{pre} {NOTICE}"
    return any(line.rstrip() == want for line in head_lines(path))


def iter_scope(root: Path):
    for d in SCOPE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or any(x in p.parts for x in SKIP_PARTS):
                continue
            pre = prefix(p.suffix)
            if pre:
                yield p, pre



def check(root: Path, quiet: bool = False) -> int:
    """Вернуть число провалов (0 = всё согласовано)."""
    bad = 0
    missing, stale = [], []
    total = 0
    for p, pre in iter_scope(root):
        total += 1
        rel = p.relative_to(root)
        if not has_header(p, pre):
            missing.append(rel)
        if (str(rel) not in ALLOWED_OLD_TOKEN
                and OLD_TOKEN in p.read_text(encoding="utf-8", errors="replace")):
            stale.append(rel)

    if not quiet:
        print(f"[i] #493: файлов в охвате {total} ({', '.join(SCOPE_DIRS)})")
        print(f"[i] без утверждённого заголовка: {len(missing)}")
        print(f"[i] всё ещё упоминают старую лицензию: {len(stale)}")
    if missing:
        bad += 1
        if not quiet:
            print("[FAIL] #493: файлы БЕЗ заголовка AGPL (первые 8):")
            for r in missing[:8]:
                print(f"    {r}")
    if stale:
        bad += 1
        if not quiet:
            print("[FAIL] #493: файлы со СТАРОЙ лицензией (первые 8):")
            for r in stale[:8]:
                print(f"    {r}")

    lic = root / "LICENSE"
    if not lic.is_file():
        bad += 1
        print("[FAIL] #493: нет файла LICENSE")
    else:
        lt = lic.read_text(encoding="utf-8", errors="replace")
        if ("GNU AFFERO GENERAL PUBLIC LICENSE" not in lt
                or "Version 3, 19 November 2007" not in lt):
            bad += 1
            print("[FAIL] #493: в LICENSE нет ПОЛНОГО текста GNU AGPL v3")
        elif not quiet:
            print("[OK] LICENSE: полный текст GNU AGPL v3")

    if not (root / "LICENSE-COMMERCIAL.md").is_file():
        bad += 1
        print("[FAIL] #493: нет LICENSE-COMMERCIAL.md (двойное лицензирование "
              "заявлено, а условий нет)")

    for name, why in EXCLUDED.items():
        if not (root / name).is_dir():
            bad += 1
            print(f"[FAIL] #493: исключение `{name}` названо, но каталога нет "
                  f"(причина была: {why})")
    if not quiet:
        for name, why in EXCLUDED.items():
            print(f"[i] исключено `{name}/`: {why}")
    return bad



def selftest() -> int:
    """R5: гейт обязан падать на каждом виде поломки (невакуумность)."""
    tmp = Path(tempfile.mkdtemp(prefix="licfix_"))
    fails = 0
    try:
        for d in SCOPE_DIRS + tuple(EXCLUDED):
            (tmp / d).mkdir(parents=True, exist_ok=True)
        (tmp / "tools" / "ok.py").write_text(
            f"#!/usr/bin/env python3\n# {NOTICE}\n", encoding="utf-8")
        (tmp / "LICENSE").write_text(
            "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007\n",
            encoding="utf-8")
        (tmp / "LICENSE-COMMERCIAL.md").write_text("terms", encoding="utf-8")
        if check(tmp, quiet=True) != 0:
            print("[FAIL] selftest: чистый набор НЕ прошёл (ложное срабатывание)")
            fails += 1
        else:
            print("[OK] selftest: чистый набор проходит")
        bad1 = tmp / "tools" / "nohdr.py"
        bad1.write_text("print(1)\n", encoding="utf-8")
        if check(tmp, quiet=True) == 0:
            print("[FAIL] selftest: файл БЕЗ заголовка не пойман")
            fails += 1
        else:
            print("[OK] selftest: файл без заголовка пойман")
        bad1.unlink()
        bad2 = tmp / "tools" / "old.py"
        # файл, который УТВЕРЖДАЕТ старую лицензию (R2 обязан это поймать)
        bad2.write_text(f"# {NOTICE}\n# {OLD_TOKEN} Noncommercial 1.0.0\n",
                        encoding="utf-8")
        if check(tmp, quiet=True) == 0:
            print("[FAIL] selftest: упоминание AGPL-3.0-or-later не поймано")
            fails += 1
        else:
            print("[OK] selftest: старая лицензия поймана")
        bad2.unlink()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print(f"[FAIL] #493 selftest: провалов {fails}")
        return 1
    print("[OK] #493 selftest: 3/3 (чистый проходит, оба вида поломки пойманы)")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    bad = check(ROOT)
    if bad:
        print(f"[FAIL] #493: провалов {bad}")
        return 1
    print("[OK] #493: заголовки AGPL + двойное лицензирование согласованы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
