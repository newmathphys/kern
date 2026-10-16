#!/usr/bin/env python3
"""KERN: сквозной аудит РЕЛИЗНОГО АРТЕФАКТА (защита от дефекта #82).

ЧТО ЛОВИТ. Дефект #82: бинарник `kernc-x86_64-linux-musl` в релизе отставал от
HEAD на несколько коммитов — пользователь скачивал более старый `kernc`, чем
заявлено тегом. Ни один тест этого поймать не может: тесты проверяют ЛОГИКУ,
а здесь расходится АРТЕФАКТ с объявлением.

ЧТО СВЕРЯЕТСЯ (три звена одной цепочки):

    1. README.md        — хеш, объявленный для скачивания;
    2. локальная сборка — `zig-out/bin/kernc-hermetic` (если собрана);
    3. asset в релизе   — тот файл, который реально скачает пользователь.

Любое расхождение — нарушение: значит объявление, сборка и публикация
разошлись. Проверка СЕТЕВАЯ (качает asset), но токен НЕ нужен: репозиторий
публичный, asset доступен анонимно.

Запуск:  python3 tools/artifact_check.py [--offline] [--version v2.2.0]
Код возврата: 0 — цепочка согласована, 1 — найдено расхождение.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LOCAL_BIN = ROOT / "zig-out" / "bin" / "kernc-hermetic"
ASSET_NAME = "kernc-x86_64-linux-musl"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def declared_hash(text: str) -> str | None:
    """Хеш, объявленный в README рядом с именем asset'а."""
    for line in text.splitlines():
        if ASSET_NAME in line and re.search(r"\b[0-9a-f]{64}\b", line):
            m = re.search(r"\b([0-9a-f]{64})\b", line)
            if m:
                return m.group(1)
    return None


def declared_size(text: str) -> int | None:
    m = re.search(r"binary \(([\d,]+) bytes\)", text)
    return int(m.group(1).replace(",", "")) if m else None


def fetch_asset(version: str) -> Path | None:
    url = (f"https://github.com/newmathphys/kern/releases/download/"
           f"{version}/{ASSET_NAME}")
    tmp = Path(tempfile.gettempdir()) / f"kern_asset_{version}"
    # `?cb=` обходит CDN-кеш GitHub: сразу после перезаливки он отдаёт старую
    # копию (наблюдалось при разборе #82).
    r = subprocess.run(["curl", "-fsSL", "-o", str(tmp), url + "?cb=1"],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not tmp.exists():
        print(f"  [!] не удалось скачать asset: {r.stderr.strip()[:120]}")
        return None
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="не скачивать asset (только README vs локальная сборка)")
    ap.add_argument("--version", default="v2.2.0")
    args = ap.parse_args()

    print("=" * 74)
    print("KERN: аудит релизного артефакта (README <-> сборка <-> asset)")
    print("=" * 74)

    if not README.exists():
        print("[!] нет README.md")
        return 1
    want = declared_hash(README.read_text(encoding="utf-8"))
    if want is None:
        print("[!] в README не найден объявленный sha256 для "
              f"{ASSET_NAME}")
        return 1
    size = declared_size(README.read_text(encoding="utf-8"))
    print(f"  README объявляет: {want[:32]}... "
          f"{f'({size} байт)' if size else ''}")

    problems: list[str] = []

    # --- 2. локальная сборка -------------------------------------------------
    if LOCAL_BIN.exists():
        got = sha256_file(LOCAL_BIN)
        mark = "OK" if got == want else "РАСХОЖДЕНИЕ"
        print(f"  локальная сборка: {got[:32]}...  [{mark}]")
        if got != want:
            problems.append(
                "локальная сборка не совпадает с README: пересоберите "
                "`zig build hermetic` и обновите хеш в README")
    else:
        print("  локальная сборка: нет (zig-out/bin/kernc-hermetic) — пропуск")

    # --- 3. asset в релизе ---------------------------------------------------
    if args.offline:
        print("  asset в релизе: пропуск (--offline)")
    else:
        tmp = fetch_asset(args.version)
        if tmp is None:
            problems.append("asset недоступен — проверить вручную")
        else:
            got = sha256_file(tmp)
            sz = tmp.stat().st_size
            mark = "OK" if got == want else "РАСХОЖДЕНИЕ"
            print(f"  asset {args.version}: {got[:32]}... ({sz} байт)  [{mark}]")
            if got != want:
                problems.append(
                    f"asset в релизе {args.version} НЕ совпадает с README: "
                    f"публикация отстала от объявления (дефект #82)")
            if size is not None and sz != size:
                problems.append(
                    f"размер asset {sz} != объявленного {size}")

    print("-" * 74)
    if problems:
        print("НАРУШЕНИЯ:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("ЦЕПОЧКА СОГЛАСОВАНА: README == сборка == asset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
