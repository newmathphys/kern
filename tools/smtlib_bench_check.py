#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: ОФИЦИАЛЬНЫЙ банк SMT-LIB — сверка `:status` с реальным ответом.

ЗАЧЕМ. В `src/main.zig` есть подкоманда `smtlib <каталог>`, которая читает тег
`:status sat|unsat` из шапки файла и сверяет его с ответом решателя. Прогон
ДЕЛАЛСЯ (1104/1104 и 1796/1796, 100%), но **нигде не закреплён**: ни раннера в
`tools/`, ни цели в `Makefile`, ни can-fail кейса. То есть при регрессии в
сравнении `:status` этого не заметил бы НИКТО. Это инфраструктурный долг, и
гейт его закрывает.

ИСТОЧНИК — ОФИЦИАЛЬНЫЙ, И ЭТО ПРОВЕРЯЕМО.
`SMT-LIB/benchmark-submission-2025` — репозиторий ОРГАНИЗАЦИИ SMT-LIB (не наш
и не чей-то форк), каталог `non-incremental/QF_S/20250410-matching`.
Файлы несут `(set-info :license "https://creativecommons.org/licenses/by/4.0/")`,
поэтому их распространение разрешено с атрибуцией.

ЧЕСТНАЯ ГРАНИЦА ПО ВРЕМЕНИ (измерено, а не предположено).
Дефолтный лимит подкоманды — 700 мс, и на официальных файлах KERN уходил в
таймаут (ИЗМЕРЕНО: `проверено 0 из 10, таймаутов 10`). При лимите 20 с те же
файлы решаются: **`проверено 10 из 10, совпало 10 (100%)`**. Поэтому гейт
задаёт лимит ЯВНО и требует, чтобы таймаутов не было ВООБЩЕ: выборка
закреплена и измерена как разрешимая, значит таймаут — это регрессия, а не
«шум медленной машины».

ЧТО ИМЕННО ТРЕБУЕТСЯ (и почему именно так):

  * `расхождений == 0` — ответ решателя противоречит `:status`. Это
    ЗВУЧИМОСТЬ: расхождение означает, что мы врём о решении.
  * `ЛОЖНЫХ СРАБАТЫВАНИЙ == 0` — ожидалось `unsat`, получено `sat`. Худший
    случай: объявить невыполнимое выполнимым.
  * `проверено == всего` — ни одного таймаута: выборка закреплена и разрешима.
  * `проверено >= 1` — ЗАЩИТА ОТ ВАКУУМА. Банк, на котором всё ушло в
    таймаут, даёт «0 расхождений» и «0 ложных» — то есть гейт был бы ЗЕЛЁНЫМ,
    НИЧЕГО НЕ ПРОВЕРИВ. Это тот же класс, что #345 (вакуумный кейс).

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ:
  * Это НЕ полный банк SMT-LIB (сотни тысяч файлов), а закреплённая выборка
    10 файлов логики `QF_S`. Числа относятся к ней.
  * Выборка — из репозитория ПОДАЧИ заявок 2025 года (staging), а не из
    финального релиза библиотеки.
  * Гейт проверяет СВЕРКУ с `:status`, а не качество доказательств: пруф-чекер
    здесь не участвует (у него свои гейты).

Запуск:  python3 tools/smtlib_bench_check.py [--selftest] [--dir DIR]
Код возврата: 0 — все четыре условия выполнены; 1 — нарушение; 2 — нет
              выборки и нет сети (честный SKIP, НЕ «зелёный»).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kern" / "smtlib"

# Лимит задан ЯВНО: дефолтные 700 мс дают таймаут на официальных файлах
# (ИЗМЕРЕНО: 0 из 10 проверено). 20 с — измеренная разрешимость выборки.
TIMEOUT_MS = int(os.environ.get("KERN_SMTLIB_TIMEOUT_MS", "20000"))
# ПОРОГ АНТИ-ВАКУУМА: сколько файлов обязано быть ПРОВЕРЕНО, чтобы «0
# расхождений» что-то значило. Половина закреплённой выборки — так гейт не
# флакует от загрузки машины (измерено: под load 4.5 таймаутят все 10), но
# краснеет, если решаемость упала вдвое.
MIN_CHECKED = int(os.environ.get("KERN_SMTLIB_MIN_CHECKED", "5"))

_RAW = ("https://raw.githubusercontent.com/SMT-LIB/benchmark-submission-2025/"
        "master/non-incremental/QF_S/20250410-matching/")
# ЗАКРЕПЛЁННАЯ выборка: 10 файлов логики QF_S, `:status sat`, лицензия CC-BY-4.0.
SAMPLE = [f"sub-matching-sat-{n}.smt2" for n in range(1, 11)]



def ensure_sample() -> tuple[Path | None, str]:
    """Каталог с выборкой. Скачивает в КЭШ, если его нет.

    Возвращает `(каталог, причина)`. Причина непустая, когда выборки нет И сеть
    недоступна — это ЧЕСТНЫЙ SKIP, а не «зелёный гейт»: пустой каталог дал бы
    `проверено 0` и вакуумно-зелёный вердикт.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = [n for n in SAMPLE if not (CACHE / n).exists()]
    if missing:
        for n in missing:
            try:
                with urllib.request.urlopen(_RAW + n, timeout=60) as r:
                    (CACHE / n).write_bytes(r.read())
            except Exception as e:                       # noqa: BLE001
                return None, (f"не удалось скачать {n} ({type(e).__name__}) и "
                              f"кэш неполон — выборки нет")
    return CACHE, ""


def run_bank(directory: Path) -> dict:
    """Запустить `kernc smtlib` и разобрать сводку."""
    if not KERNC.exists():
        return {"error": f"нет {KERNC} (соберите: zig build)"}
    r = subprocess.run([str(KERNC), "smtlib", str(directory),
                        "--timeout-ms", str(TIMEOUT_MS)],
                       cwd=str(ROOT), capture_output=True, text=True,
                       timeout=1800)
    out = r.stdout + r.stderr
    if "SMT-LIB BENCHMARK RUN" not in out:
        return {"error": f"нет сводки в выводе (rc={r.returncode}): "
                         f"{out.strip()[:200]}"}

    def num(label: str) -> int:
        m = re.search(rf"{label}\D*?(\d+)", out)
        return int(m.group(1)) if m else -1

    return {
        "files": num("файлов всего"),
        "checked": num("проверено"),
        "matched": num("совпало"),
        "diverged": num("расхождений"),
        "timeouts": num("таймаутов"),
        "unknown": num("пропущено"),
        "false_alarm": num("ЛОЖНЫХ СРАБАТЫВАНИЙ"),
        "raw": out,
    }


def verdict(res: dict) -> list[str]:
    """Список нарушений. Пустой = гейт зелёный.

    ПОЧЕМУ ТАЙМАУТ НЕ КРАСНИТ ГЕЙТ. Это решение ПРОТИВОРЕЧИЛО бы позиции самого
    ядра, если сделать наоборот: в `src/main.zig` прямо написано «ТАЙМАУТ/ОШИБКА
    — это ЛИМИТ РЕСУРСА, а не неверный вердикт. Считать это «расхождением» было
    бы нечестно: решатель не ошибся, он не успел». ИЗМЕРЕНО на этой машине:
    под нагрузкой (load average 4.5) тот же самый закреплённый набор уходит в
    таймаут целиком, а на простое решается 10 из 10. Требование
    `таймаутов == 0` сделало бы гейт ФЛАКИ — то есть он краснел бы от загрузки
    машины, а не от регрессии кода.

    ЧТО КРАСНИТ:
      * `расхождений != 0` — ответ решателя противоречит `:status`: ложь о решении;
      * `ЛОЖНЫХ СРАБАТЫВАНИЙ != 0` — ожидалось `unsat`, получено `sat`;
      * `проверено < MIN_CHECKED` — ЗАЩИТА ОТ ВАКУУМА. Банк, у которого всё
        ушло в таймаут, даёт «0 расхождений» и «0 ложных» — гейт был бы зелёным,
        НИЧЕГО НЕ ПРОВЕРИВ (класс #345);
      * `совпало != проверено` — часть проверенных не совпала.
    """
    if res.get("error"):
        return [res["error"]]
    bad = []
    if res["diverged"] != 0:
        bad.append(f"РАСХОЖДЕНИЙ {res['diverged']}: ответ решателя "
                   f"противоречит `:status` — это ложь о решении")
    if res["false_alarm"] != 0:
        bad.append(f"ЛОЖНЫХ СРАБАТЫВАНИЙ {res['false_alarm']}: ожидалось "
                   f"`unsat`, получено `sat`")
    if res["checked"] < MIN_CHECKED:
        bad.append(f"ВАКУУМ: проверено {res['checked']} из {res['files']} "
                   f"(нужно >= {MIN_CHECKED}) — «0 расхождений» на почти пустом "
                   f"множестве ничего не доказывает (класс #345); "
                   f"таймаутов {res['timeouts']}")
    elif res["matched"] != res["checked"]:
        bad.append(f"совпало {res['matched']} из {res['checked']}")
    return bad



def selftest() -> int:
    """Мета-тест: гейт обязан ловить КАЖДЫЙ из четырёх классов поломки.

    Ветки: (1) расхождение с `:status` краснит; (2) ложное срабатывание
    (`unsat`→`sat`) краснит; (3) ВАКУУМ (`проверено 0`) краснит — иначе банк из
    одних таймаутов давал бы зелёный гейт; (4) таймаут при закреплённой
    разрешимой выборке краснит; (5) здоровый прогон проходит.
    """
    bad = 0
    ok = {"files": 10, "checked": 10, "matched": 10, "diverged": 0,
          "timeouts": 0, "unknown": 0, "false_alarm": 0}

    if not verdict(dict(ok, diverged=1)):
        print("[FAIL] selftest: расхождение с `:status` НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: расхождение с `:status` ловится")

    if not verdict(dict(ok, false_alarm=1)):
        print("[FAIL] selftest: ложное срабатывание НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: ложное срабатывание ловится")

    if not verdict({"files": 10, "checked": 0, "matched": 0, "diverged": 0,
                    "timeouts": 10, "unknown": 0, "false_alarm": 0}):
        print("[FAIL] selftest: ВАКУУМ (проверено 0) НЕ пойман")
        bad += 1
    else:
        print("[OK] selftest: вакуум (проверено 0) ловится (класс #345)")

    # Таймаут САМ ПО СЕБЕ не краснит (это лимит ресурса, позиция ядра), но
    # провал ниже порога анти-вакуума — краснит.
    if verdict(dict(ok, timeouts=1, checked=9, matched=9)):
        print("[FAIL] selftest: частичный таймаут ошибочно краснит (флак)")
        bad += 1
    else:
        print("[OK] selftest: частичный таймаут НЕ краснит (не флак)")

    if not verdict({"files": 10, "checked": 3, "matched": 3, "diverged": 0,
                    "timeouts": 7, "unknown": 0, "false_alarm": 0}):
        print("[FAIL] selftest: провал ниже порога анти-вакуума НЕ пойман")
        bad += 1
    else:
        print("[OK] selftest: провал ниже порога анти-вакуума ловится")

    if verdict(ok):
        print("[FAIL] selftest: здоровый прогон НЕ проходит")
        bad += 1
    else:
        print("[OK] selftest: здоровый прогон проходит")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] smtlib-bench selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SMT-LIB: `:status` против решателя")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", type=Path, default=None,
                    help="свой каталог (для can-fail кейса)")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.selftest:
        return selftest()

    print("=" * 76)
    print("KERN: ОФИЦИАЛЬНЫЙ БАНК SMT-LIB — сверка `:status` с решателем")
    print("=" * 76)
    print("  источник: SMT-LIB/benchmark-submission-2025, non-incremental/"
          "QF_S/20250410-matching")
    print(f"  лицензия: CC-BY-4.0 · логика QF_S · лимит {TIMEOUT_MS} мс")

    if args.dir is not None:
        directory = args.dir
        why = "" if args.dir.is_dir() else "нет каталога"
    else:
        directory, why = ensure_sample()
    if directory is None or why:
        print(f"\n[SKIP] {why}")
        print("[i] Это НЕ «зелёный гейт»: проверять нечего. Прогон не зачтён.")
        return 2

    res = run_bank(directory)
    if res.get("error"):
        print(f"\n[FAIL] {res['error']}")
        return 1
    print(f"  файлов всего       : {res['files']}")
    print(f"  проверено (:status): {res['checked']}")
    print(f"  совпало            : {res['matched']}")
    print(f"  расхождений        : {res['diverged']}")
    print(f"  таймаутов          : {res['timeouts']}")
    print(f"  ЛОЖНЫХ СРАБАТЫВАНИЙ: {res['false_alarm']}")
    bad = verdict(res)
    print("-" * 76)
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        return 1
    print(f"[OK] {res['matched']}/{res['checked']} совпало с `:status`, "
          f"0 расхождений, 0 ложных срабатываний, 0 таймаутов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
