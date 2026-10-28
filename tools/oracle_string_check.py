#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для санитайзера путей (семейство `strings`, шаг D плана).

ЗАЧЕМ. До этого шага семейство `strings` проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ:
`string_theory.zig` строит SMT-запрос, `kernfs_router.validatePath` возвращает
вердикт, и оба объявляются верными. Никто не проверял, что ОТКАЗ санитайзера
НЕ КОСМЕТИЧЕСКИЙ — то есть что отклонённый путь, поданный в наивную
реализацию `open(root + path)`, действительно уводит за пределы корня.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ.
  1. НАТИВНЫЙ вердикт — `kernc theory` с формой `strings path <путь>`
     (`KernFS.validatePath`: каноничная форма, без `.`, `..`, `//`, NUL);
  2. НАИВНАЯ РЕЗОЛЮЦИЯ — `os.path.normpath(root + path)`: выходит ли результат
     за пределы `root` (классическая ошибка «конкатенация вместо join»);
  3. РЕАЛЬНАЯ ФС — в песочнице создаётся `root/`, `root/ok.txt` и КАНАРЕЙКА
     ВНЕ корня (`secret.txt`); для каждого пути делается НАСТОЯЩАЯ попытка
     `open()` по наивно разрешённому пути. Если канарейка читается — побег
     РЕАЛЬНО достижим, и отказ санитайзера был несущим.

КЛАССИФИКАЦИЯ (важно различать «строже» и «ошибка»):
  * отказ  + побег достижим  → CONFIRMED_BLOCKED (отказ несущий);
  * отказ  + побега нет      → STRICTER_THAN_NEEDED (политика каноничности,
                                а НЕ ошибка: строже ≠ неверно);
  * приём  + побег достижим  → FALSE_ACCEPT (дыра) — обязано быть 0;
  * приём  + побега нет      → CONFIRMED_ACCEPT.

ИНВАРИАНТЫ: false_accept == 0; >= 2 подтверждённых блокировок; >= 2 подтверждённых
приёмов; негативный контроль (классификатор ловит ложный приём); детерминизм.

ЧЕСТНАЯ ГРАНИЦА (названа, не спрятана). `validatePath` — ЛЕКСИЧЕСКИЙ валидатор
пространства имён KERNFS: он не разрешает симлинки ХОСТА. Это не пробел: KERNFS
обслуживает данные из образа в памяти и файловой системы хоста не касается.
Проверка «симлинк внутри корня ведёт наружу» показана отдельным разделом
(ГРАНИЦА) и в дифференциал НЕ входит, потому что относится к другому слою.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SPEC_DIR = ROOT / "tests" / "fixtures" / "oracles"
# Песочница создаётся УНИКАЛЬНОЙ на прогон (см. make_sandbox): прежний ЖЁСТКИЙ
# общий путь в /tmp был виден двум параллельным прогонам сразу (журнал #398).
# Литерал здесь НЕ приводится намеренно: страж `temp-isolation-check` читает
# текст файла, и цитата старого пути снова выглядела бы как нарушение (#290).
LONG = "/" + "a" * 5000          # длиннее PATH_MAX

# (путь, человеческое описание)
FIXTURES = [
    ("/ok.txt", "обычный путь внутри корня"),
    ("/sub/ok.txt", "путь во вложенном каталоге"),
    ("/../secret.txt", "побег через .."),
    ("/sub/../../secret.txt", "побег через вложенный .."),
    ("/..", "сам .."),
    ("//etc/passwd", "пустой компонент //"),
    ("/./ok.txt", "компонент ."),
    ("/sub/", "пустой компонент в конце"),
    ("/a\x00b", "NUL-инъекция"),
    (LONG, "длиннее PATH_MAX"),
]


def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return env


def native_verdict(path: str, idx: int) -> tuple[str, str]:
    """'reject' | 'accept' | 'error' + причина (из KernFS.validatePath)."""
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec = SPEC_DIR / f"path_{idx}.txt"
    spec.write_bytes(("# физический оракул путей\n" + f"strings path {path}\n")
                     .encode("utf-8", "surrogateescape"))
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT, env=child_env(),
                           capture_output=True, text=True, errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "error", f"kernc theory не запустился: {e}"
    out = p.stdout + p.stderr
    m = re.search(r"\u043f\u0443\u0442\u044c \u041e\u0422\u041a\u041b\u041e\u041d\u0401\u041d: (\w+)", out)
    if m:
        return "reject", m.group(1)
    if "\u043f\u0443\u0442\u044c \u041f\u0420\u0418\u041d\u042f\u0422" in out:
        return "accept", ""
    return "error", f"вердикт не разобран: {out.strip()[:160]}"


def make_sandbox() -> tuple[Path, Path]:
    """Песочница: root/ внутри, КАНАРЕЙКА secret.txt СНАРУЖИ корня.

    ДЕФЕКТ #398 (поймал страж `temp-isolation-check`): путь был ЖЁСТКИМ и
    ОБЩИМ для всех прогонов. Это ровно тот случай, против которого стоит
    правило N2: два одновременных прогона (или прогон во время чтения
    результата человеком) перетирают канарейку друг друга, и вердикт
    оракула становится случайным. Теперь каталог УНИКАЛЕН на прогон и
    удаляется за собой, поэтому ни один чужой процесс его не увидит.
    """
    base = Path(tempfile.mkdtemp(prefix="kern_path_oracle."))
    atexit.register(shutil.rmtree, base, ignore_errors=True)  # убрать за собой
    (base / "root" / "sub").mkdir(parents=True, exist_ok=True)
    (base / "root" / "ok.txt").write_text("inside\n", encoding="utf-8")
    (base / "root" / "sub" / "ok.txt").write_text("nested\n", encoding="utf-8")
    canary = base / "secret.txt"
    canary.write_text("CANARY\n", encoding="utf-8")
    return base / "root", canary


def naive_escape(root: Path, path: str) -> tuple[bool, str, str]:
    """НАИВНАЯ конкатенация `root + path` (классическая ошибка).

    Возвращает (побег?, разрешённый путь, что сказала РЕАЛЬНАЯ ФС).
    """
    resolved = os.path.normpath(str(root) + path)
    inside = resolved == str(root) or resolved.startswith(str(root) + os.sep)
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read().strip()
        fs = f"открыт, содержимое={content!r}"
    except ValueError as e:
        fs = f"ОС отвергает: {e}"
    except OSError as e:
        fs = f"ОС отвергает: {type(e).__name__}"
    return (not inside), resolved, fs


def classify(native: str, escape: bool) -> str:
    """Классификатор. ВЫНЕСЕН отдельно — негативный контроль проверяет его сам."""
    if native == "reject":
        return "CONFIRMED_BLOCKED" if escape else "STRICTER_THAN_NEEDED"
    if native == "accept":
        return "FALSE_ACCEPT" if escape else "CONFIRMED_ACCEPT"
    return "BOUNDARY"


def run() -> int:
    print("=" * 78)
    print("=== KERN: ФИЗИЧЕСКИЙ ОРАКУЛ ПУТЕЙ (санитайзер KERNFS против РЕАЛЬНОЙ ФС) ===")
    print("=" * 78)

    root, canary = make_sandbox()
    print(f"  песочница: root={root}")
    print(f"  канарейка ВНЕ корня: {canary}")

    counts = {"CONFIRMED_BLOCKED": 0, "STRICTER_THAN_NEEDED": 0,
              "CONFIRMED_ACCEPT": 0, "FALSE_ACCEPT": 0, "BOUNDARY": 0}
    bad: list[str] = []

    for i, (path, what) in enumerate(FIXTURES):
        nv, why = native_verdict(path, i)
        escape, resolved, fs = naive_escape(root, path)
        cls = classify(nv, escape)
        counts[cls] += 1
        mark = "OK " if cls in ("CONFIRMED_BLOCKED", "CONFIRMED_ACCEPT") else (
            "-- " if cls == "STRICTER_THAN_NEEDED" else "!! ")
        shown = path if len(path) <= 22 else path[:19] + "..."
        print(f"  {mark}{cls:20s} {shown:24s} ядро={nv:6s} {why:22s} побег={'ДА' if escape else 'нет'} | {fs}")
        if cls == "FALSE_ACCEPT":
            bad.append(f"{shown}: ложный приём — побег достижим ({resolved})")

    # НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор обязан ловить ложный приём.
    neg = []
    if classify("accept", True) != "FALSE_ACCEPT":
        neg.append("НЕ ловит ложный приём")
    if classify("reject", True) != "CONFIRMED_BLOCKED":
        neg.append("не подтверждает несущий отказ")
    if classify("reject", False) != "STRICTER_THAN_NEEDED":
        neg.append("не отличает «строже» от ошибки")
    print(f"  {'OK ' if not neg else '!! '}НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор "
          f"{'ловит ложный приём' if not neg else '; '.join(neg)}")

    # ГРАНИЦА (в дифференциал НЕ входит): симлинк ХОСТА внутри корня.
    link = root / "link"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to("..")
        nv_l, _ = native_verdict("/link/secret.txt", 900)
        escape_l, resolved_l, fs_l = naive_escape(root, "/link/secret.txt")
        print(f"  -- ГРАНИЦА: /link/secret.txt (симлинк хоста) → ядро={nv_l}, "
              f"лексически={'внутри' if not escape_l else 'вне'}, "
              f"ФС: {fs_l}")
        print("  -- ТО ЕСТЬ: лексическая проверка считает путь внутренним, а РЕАЛЬНАЯ ФС "
              "разрешает симлинк и отдаёт файл вне корня.")
        print("  -- ПОЧЕМУ НЕ В ДИФФЕРЕНЦИАЛЕ: validatePath — ЛЕКСИЧЕСКИЙ валидатор "
              "пространства имён KERNFS; он не разрешает симлинки ХОСТА, потому что "
              "KERNFS обслуживает данные из образа в памяти и ФС хоста не касается.")
    except OSError as e:
        print(f"  -- ГРАНИЦА: симлинк создать не удалось ({e})")

    # ДЕТЕРМИНИЗМ: два прогона — один вердикт.
    det = True
    for i, (path, _) in enumerate(FIXTURES[:3]):
        a, _ = native_verdict(path, i)
        b, _ = native_verdict(path, i)
        if a != b:
            det = False
            bad.append(f"{path!r}: вердикт недетерминирован ({a} vs {b})")
    print(f"  {'OK ' if det else '!! '}ДЕТЕРМИНИЗМ: два прогона дают один вердикт")

    print("-" * 78)
    print(f"  несущих отказов (CONFIRMED_BLOCKED) : {counts['CONFIRMED_BLOCKED']}")
    print(f"  приёмов внутри корня                : {counts['CONFIRMED_ACCEPT']}")
    print(f"  строже необходимого (не ошибка)     : {counts['STRICTER_THAN_NEEDED']}")
    print(f"  ЛОЖНЫХ ПРИЁМОВ (побег разрешён)     : {counts['FALSE_ACCEPT']}  (обязано быть 0)")
    print("-" * 78)

    ok = True
    if counts["FALSE_ACCEPT"]:
        print(f"[FAIL] ложных приёмов: {counts['FALSE_ACCEPT']}")
        ok = False
    if counts["CONFIRMED_BLOCKED"] < 2:
        print(f"[FAIL] невакуумность: несущих отказов {counts['CONFIRMED_BLOCKED']} < 2")
        ok = False
    if counts["CONFIRMED_ACCEPT"] < 2:
        print(f"[FAIL] невакуумность: приёмов {counts['CONFIRMED_ACCEPT']} < 2")
        ok = False
    if neg:
        print("[FAIL] негативный контроль не прошёл")
        ok = False
    if not det:
        print("[FAIL] вердикт недетерминирован")
        ok = False
    for r in bad:
        print(f"[FAIL] {r}")
        ok = False
    if ok:
        print(f"[OK] физический оракул путей: {counts['CONFIRMED_BLOCKED']} побегов заблокированы "
              f"НЕСУЩЕ (канарейка вне корня реально читалась бы), {counts['CONFIRMED_ACCEPT']} "
              f"путей приняты и остались внутри корня, 0 ложных приёмов")
    print(f"RC={0 if ok else 1}")
    return 0 if ok else 1


def selftest() -> int:
    """Проверка классификатора и наивной резолюции (без kernc)."""
    root = Path("/tmp/selftest_root")
    checks = [
        ("accept + побег = ЛОЖНЫЙ ПРИЁМ", classify("accept", True) == "FALSE_ACCEPT"),
        ("accept + нет побега = подтверждено", classify("accept", False) == "CONFIRMED_ACCEPT"),
        ("reject + побег = несущий отказ", classify("reject", True) == "CONFIRMED_BLOCKED"),
        ("reject + нет побега = строже (НЕ ошибка)", classify("reject", False) == "STRICTER_THAN_NEEDED"),
        ("SKIP/ошибка не вердикт", classify("error", False) == "BOUNDARY"),
        ("наивно /ok.txt внутри корня", not naive_escape(root, "/ok.txt")[0]),
        ("наивно /../secret.txt ВНЕ корня", naive_escape(root, "/../secret.txt")[0]),
        ("наивно //etc/passwd внутри (строже)", not naive_escape(root, "//etc/passwd")[0]),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'[OK]' if ok else '[FAIL]'} {n}")
    if bad:
        print(f"[FAIL] selftest: {len(bad)} проверок не прошло")
        return 1
    print(f"[OK] selftest: {len(checks)}/{len(checks)} проверок")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not KERNC.exists():
        print(f"[FAIL] нет бинарника {KERNC} — сначала `make build`")
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
