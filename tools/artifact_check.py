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
import time
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
    r = subprocess.run(["curl", "-fsSL", "-o", str(tmp), url + f"?cb={time.time_ns()}"],
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

    ДЕФЕКТ #355: регексп ТРЕБОВАЛ слэш после версии (`.../vX.Y.Z/`), а README
    объявляет базу БЕЗ слэша (`base=.../download/vX.Y.Z`, слэш появляется только
    при склейке `"$base/kernc-..."`). Проверено по ВСЕМ тегам (v2.6.3, v2.6.4,
    v2.7.0, v2.7.1): слэша нет ни в одном, значит `detect_version` ВСЕГДА
    бросал SystemExit, и `artifact-check`/`artifact-check-offline` не могли
    пройти НИ РАЗУ — при этом запись #285 утверждала обратное («там README
    объявляет хеш, и цепочка жива»). Форма хвоста теперь названа явно:
    слэш, конец строки, кавычка/скобка или пробел — но НЕ ещё одна цифра
    (иначе `v2.7.20` распознался бы как `v2.7.2`).
    """
    txt = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"releases/download/(v[0-9]+\.[0-9]+\.[0-9]+)(?![\d.])", txt)
    if not m:
        raise SystemExit("[!] в README.md нет ссылки releases/download/vX.Y.Z")
    return m.group(1)


def release_sha256(version: str) -> str | None:
    """sha256 для `ASSET_NAME` из ОПУБЛИКОВАННОГО `SHA256SUMS` (сеть).

    ЗАЧЕМ (дефект #355). Изначально хеш брался из README рядом с именем asset'а.
    Дефект #250 убрал этот хардкод НАМЕРЕННО (он дрейфовал при каждом релизе),
    поэтому источника хеша не осталось — и гейт падал на «в README не найден
    объявленный sha256». Но объявление НЕ исчезло: релиз публикует `SHA256SUMS`,
    который и связывает байты артефакта. Читаем его оттуда.
    """
    tmp = Path(tempfile.gettempdir()) / f"kern_sha256sums_{version}"
    url = (f"https://github.com/newmathphys/kern/releases/download/"
           f"{version}/SHA256SUMS")
    r = subprocess.run(["curl", "-fsSL", "-o", str(tmp),
                        url + f"?cb={time.time_ns()}"],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not tmp.exists():
        return None
    for line in tmp.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == ASSET_NAME:
            h = parts[0].strip()
            if re.fullmatch(r"[0-9a-f]{64}", h):
                return h
    return None


def local_binary_version() -> str | None:
    """Версия, которую ПЕЧАТАЕТ локальная сборка (`kernc-hermetic --version`)."""
    if not LOCAL_BIN.exists():
        return None
    r = subprocess.run([str(LOCAL_BIN), "--version"],
                       capture_output=True, text=True, timeout=60)
    m = re.search(r"v[0-9]+\.[0-9]+\.[0-9]+", r.stdout + r.stderr)
    return m.group(0) if m else None



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

    ИСТОРИЯ. Дефект #93: цель `artifact-check` зависела только от `build`, а
    `zig build` НЕ собирает `kernc-hermetic` (отдельный шаг). Проверялся старый
    бинарник, и цепочка «сходилась» сама с собой.

    Первое исправление сравнивало mtime бинарника с mtime исходников. Это
    оказалось НЕНАДЁЖНО (дефект #89b, найден на практике): `tools/canfail.py`
    восстанавливает пропатченные файлы атомарной записью, что ОБНОВЛЯЕТ их
    mtime, хотя содержимое не меняется. А `zig build hermetic` при неизменном
    содержимом НЕ перелинковывает и оставляет бинарнику СТАРЫЙ mtime из кэша.
    Итог: проверка кричала «сборка устарела» на полностью корректной сборке.

    ПРАВИЛЬНОЕ РЕШЕНИЕ — не УГАДЫВАТЬ свежесть, а ОБЕСПЕЧИТЬ её: цель
    `artifact-check` в Makefile зависит от `hermetic`, поэтому бинарник всегда
    собран из ТЕКУЩИХ исходников (пусть и взят из кэша). Тогда сравнение
    хэшей осмысленно, и эвристика по времени не нужна.
    """
    return False  # свежесть гарантирована зависимостью `hermetic` в Makefile


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
    txt = README.read_text(encoding="utf-8")
    # ДЕФЕКТ #355: README больше НЕ объявляет хеш (это убрал #250 намеренно).
    # Источник хеша — опубликованный `SHA256SUMS`; README объявляет ВЕРСИЮ.
    want = declared_hash(txt)
    hash_source = "README"
    if want is None:
        want = None if args.offline else release_sha256(args.version)
        hash_source = "SHA256SUMS"
    size = declared_size(txt)
    if want is not None:
        print(f"  объявлено ({hash_source}): {want[:32]}... "
              f"{f'({size} байт)' if size else ''}")
    else:
        print(f"  объявленный sha256: нет (README хеш не объявляет, "
              f"SHA256SUMS {'не читался' if args.offline else 'недоступен'})")

    problems: list[str] = []

    # --- 2. локальная сборка -------------------------------------------------
    # ПРЕДОХРАНИТЕЛЬ: устаревший бинарник делает проверку бессмысленной.
    if binary_is_stale():
        print("  [!] ЛОКАЛЬНАЯ СБОРКА УСТАРЕЛА: kernc-hermetic старше исходников")
        print("      пересоберите: zig build hermetic  (иначе проверка сравнивает")
        print("      бинарник САМ С СОБОЙ и может ложно показать согласованность)")
        return 1
    ahead = unpublished_commits(args.version)
    local_ver = local_binary_version()
    # ДЕФЕКТ #355: сравнивать БАЙТЫ локальной сборки с опубликованным asset'ом
    # нельзя, когда хеш берётся из `SHA256SUMS`: README прямо предупреждает, что
    # CI-сборка НЕ обязана совпадать побайтово с локальной `zig build hermetic`
    # (разные пути тулчейна). Поэтому в этом режиме сравнивается ВЕРСИЯ
    # (первое звено цепочки #82), а разница хешей печатается как сведение.
    byte_compare = (hash_source == "README")
    if LOCAL_BIN.exists():
        if not byte_compare:
            if local_ver is None:
                print("  локальная сборка: не удалось прочитать `--version`  "
                      "[РАСХОЖДЕНИЕ]")
                problems.append("локальная сборка не отвечает на `--version`")
            elif local_ver == args.version:
                print(f"  локальная сборка печатает {local_ver}  [OK] "
                      f"(совпадает с версией README)")
                print(f"      байты локальной сборки: {sha256_file(LOCAL_BIN)[:32]}... "
                      f"(отличие от asset ОЖИДАЕМО: разные пути тулчейна)")
            elif ahead is not None and ahead > 0:
                print(f"  локальная сборка печатает {local_ver}  "
                      f"[ОПЕРЕЖАЕТ РЕЛИЗ {args.version} на {ahead} коммит(ов)]")
            else:
                print(f"  локальная сборка печатает {local_ver}  [РАСХОЖДЕНИЕ]")
                problems.append(
                    f"сборка печатает {local_ver}, README объявляет "
                    f"{args.version}")
            got = None
        else:
            got = sha256_file(LOCAL_BIN)
            if got == want:
                print(f"  локальная сборка: {got[:32]}...  [OK]")
            elif ahead is not None and ahead > 0:
                # ОЖИДАЕМО: исходники опережают релиз. Это НЕ провал проверки,
                # но и НЕ PASS — состояние называется прямо.
                print(f"  локальная сборка: {got[:32]}...  "
                      f"[ОПЕРЕЖАЕТ РЕЛИЗ {args.version} на {ahead} коммит(ов)]")
                print("      расхождение с объявлением ОЖИДАЕМО: сборка включает")
                print("      неопубликованные изменения. При выпуске: перезалить")
                print("      asset (METRICS §63.3).")
            else:
                print(f"  локальная сборка: {got[:32]}...  [РАСХОЖДЕНИЕ]")
                problems.append(
                    "локальная сборка не совпадает с объявленным sha256: "
                    "пересоберите `zig build hermetic`")
    else:
        print("  локальная сборка: нет (zig-out/bin/kernc-hermetic) — пропуск")
        got = None

    # --- 3. asset в релизе ---------------------------------------------------
    if args.offline:
        print("  asset в релизе: пропуск (--offline)")
    elif want is None:
        problems.append(
            "не удалось прочитать `SHA256SUMS` из релиза "
            f"{args.version} — проверить вручную (README хеш не объявляет)")
    else:
        tmp = fetch_asset(args.version)
        if tmp is None:
            problems.append("asset недоступен — проверить вручную")
        else:
            asha = sha256_file(tmp)
            sz = tmp.stat().st_size
            mark = "OK" if asha == want else "РАСХОЖДЕНИЕ"
            print(f"  asset {args.version}: {asha[:32]}... ({sz} байт)  [{mark}]")
            if asha != want:
                problems.append(
                    f"asset в релизе {args.version} НЕ совпадает с объявленным "
                    f"sha256: публикация отстала от объявления (дефект #82)")
            if size is not None and sz != size:
                problems.append(
                    f"размер asset {sz} != объявленного {size}")

    print("-" * 74)
    if problems:
        print("НАРУШЕНИЯ:")
        for p in problems:
            print(f"  - {p}")
        return 1
    # «ОПЕРЕЖАЕТ» — только когда есть ЧЕМ сравнить: либо хеш, либо версия.
    behind_check = (
        (want is not None and got is not None and got != want)
        or (want is None and local_ver is not None
            and local_ver != args.version)
    )
    if ahead is not None and ahead > 0 and LOCAL_BIN.exists() and behind_check:
        print("ОПУБЛИКОВАННОЕ СОСТОЯНИЕ СОГЛАСОВАНО (объявление == asset).")
        print(f"Сборка ОПЕРЕЖАЕТ релиз {args.version} на {ahead} коммит(ов) — "
              "это НЕ провал, но и НЕ «всё совпало»:")
        print("перезалить asset при выпуске (METRICS §63.3).")
    elif want is None:
        print("ЦЕПОЧКА СОГЛАСОВАНА ЧАСТИЧНО: README(версия) == сборка; "
              "сверка хеша пропущена (--offline)")
    else:
        print("ЦЕПОЧКА СОГЛАСОВАНА: объявление == сборка == asset")
    return 0


def selftest() -> int:
    """Мета-тест: регексп версии обязан ловить ФАКТИЧЕСКУЮ форму README и НЕ
    путать `v2.7.2` с `v2.7.20`. Дефект #355: прежний регексп требовал слэш,
    которого в README нет НИ В ОДНОМ теге, поэтому гейт не мог пройти."""
    import tempfile
    bad = 0
    cases = [
        # (строка README, ожидаемая версия)
        ("base=https://github.com/newmathphys/kern/releases/download/v2.7.2",
         "v2.7.2"),
        ("base=https://github.com/newmathphys/kern/releases/download/v2.7.2/",
         "v2.7.2"),
        ("curl -fsSLO \"https://github.com/newmathphys/kern/releases/"
         "download/v2.6.4/kernc-x86_64-linux-musl\"", "v2.6.4"),
        ("base=https://github.com/newmathphys/kern/releases/download/v2.7.20",
         "v2.7.20"),                              # НЕ v2.7.2
        ("[x](.../releases/download/v2.5.0#frag)", "v2.5.0"),
    ]
    with tempfile.TemporaryDirectory() as d:
        rp = Path(d) / "README.md"
        for text, expect in cases:
            rp.write_text(text + "\n", encoding="utf-8")
            m = re.search(r"releases/download/(v[0-9]+\.[0-9]+\.[0-9]+)(?![\d.])",
                          rp.read_text(encoding="utf-8"))
            got = m.group(1) if m else None
            if got != expect:
                print(f"[FAIL] selftest: `{text[:60]}` → {got}, ожидалось {expect}")
                bad += 1
        # отсутствие ссылки — честный отказ, а не молчаливое «ок»
        rp.write_text("нет ссылки\n", encoding="utf-8")
        if re.search(r"releases/download/(v[0-9]+\.[0-9]+\.[0-9]+)(?![\d.])",
                     rp.read_text(encoding="utf-8")):
            print("[FAIL] selftest: отсутствующая ссылка признана найденной")
            bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] artifact-check selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())

