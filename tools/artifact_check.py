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


def detect_version() -> str:
    """Версия релиза, ОБЪЯВЛЕННАЯ в README (строка `releases/download/vX.Y.Z`).

    ДЕФЕКТ #94: версия была ЗАШИТА (`default="v2.2.0"`) и устарела, поэтому
    проверка сверялась с ЧУЖИМ релизом и могла показать «согласовано» или
    «расхождение» не по делу. Теперь источник — сам README.
    """
    txt = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"releases/download/(v[0-9]+[.][0-9]+[.][0-9]+)/", txt)
    if not m:
        raise SystemExit("[!] в README.md нет ссылки releases/download/vX.Y.Z")
    return m.group(1)


def unpublished_commits(version: str) -> int | None:
    """Сколько коммитов HEAD ОПЕРЕЖАЕТ тег релиза. None — определить не удалось.

    ЗАЧЕМ. Пока изменения не опубликованы, локальная сборка ФИЗИЧЕСКИ не может
    совпасть с объявленным в README хешем — это не расхождение, а ожидаемое
    состояние. Раньше проверка этого не различала и давала ложный красный.
    Если тег определить НЕ удалось — возвращаем None, и проверка остаётся
    СТРОГОЙ (fail-closed): незнание не является оправданием.
    """
    try:
        r = subprocess.run(["git", "rev-list", "--count", f"{version}..HEAD"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return None
        return int(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def newest_source_mtime() -> float:
    """Время самой свежей правки в исходниках, влияющих на бинарник."""
    newest = 0.0
    for pat in ("src/**/*.zig", "build.zig", "include/*.h"):
        for p in ROOT.glob(pat):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    return newest


def binary_is_stale() -> bool:
    """УСТАРЕЛ ли `kernc-hermetic` относительно исходников.

    ДЕФЕКТ #93: цель `artifact-check` зависела только от `build`, а `zig build`
    НЕ собирает `kernc-hermetic` (отдельный шаг). Проверялся старый бинарник,
    и цепочка «сходилась» сама с собой, хотя исходники ушли вперёд —
    ЛОЖНОЕ СРАБАТЫВАНИЕ ровно того класса, против которого построен проект.
    """
    if not LOCAL_BIN.exists():
        return False  # отсутствие обрабатывается отдельно
    return LOCAL_BIN.stat().st_mtime < newest_source_mtime()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="не скачивать asset (только README vs локальная сборка)")
    ap.add_argument("--version", default=None,
                    help="версия релиза; по умолчанию берётся из README.md")
    args = ap.parse_args()
    if args.version is None:
        args.version = detect_version()

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
    # ПРЕДОХРАНИТЕЛЬ: устаревший бинарник делает проверку бессмысленной.
    if binary_is_stale():
        print("  [!] ЛОКАЛЬНАЯ СБОРКА УСТАРЕЛА: kernc-hermetic старше исходников")
        print("      пересоберите: zig build hermetic  (иначе проверка сравнивает")
        print("      бинарник САМ С СОБОЙ и может ложно показать согласованность)")
        return 1
    ahead = unpublished_commits(args.version)
    if LOCAL_BIN.exists():
        got = sha256_file(LOCAL_BIN)
        if got == want:
            print(f"  локальная сборка: {got[:32]}...  [OK]")
        elif ahead is not None and ahead > 0:
            # ОЖИДАЕМО: исходники опережают релиз. Это НЕ провал проверки,
            # но и НЕ PASS — состояние называется прямо.
            print(f"  локальная сборка: {got[:32]}...  "
                  f"[ОПЕРЕЖАЕТ РЕЛИЗ {args.version} на {ahead} коммит(ов)]")
            print("      расхождение с README ОЖИДАЕМО: сборка включает")
            print("      неопубликованные изменения. При выпуске: обновить README")
            print("      и перезалить asset (METRICS §63.3).")
        else:
            print(f"  локальная сборка: {got[:32]}...  [РАСХОЖДЕНИЕ]")
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
    if ahead is not None and ahead > 0 and LOCAL_BIN.exists() \
            and sha256_file(LOCAL_BIN) != want:
        print("ОПУБЛИКОВАННОЕ СОСТОЯНИЕ СОГЛАСОВАНО (README == asset).")
        print(f"Сборка ОПЕРЕЖАЕТ релиз {args.version} на {ahead} коммит(ов) — "
              "это НЕ провал, но и НЕ «всё совпало»:")
        print("обновить README и перезалить asset при выпуске (METRICS §63.3).")
    else:
        print("ЦЕПОЧКА СОГЛАСОВАНА: README == сборка == asset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
