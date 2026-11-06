#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kerna_doctor` — ПРЕДСТАРТОВАЯ ПРОВЕРКА ЗАВИСИМОСТЕЙ (#494).

ЗАЧЕМ. На спайке измерено: без `z3` рядом упакованный бинарь печатал
`findings 0`, `unreadable 1`, **rc=0** и ПУСТОЙ stderr. То есть пропажа
решателя выглядела как «файл не читается», а не как поломка дистрибутива —
класс `#407` (молчаливый SKIP без Z3), только на уровне поставки.

ПРАВИЛО. Отсутствие зависимости — это НАЗВАННЫЙ отказ с кодом 2 и громким
stderr, а не нулевые находки. «Нет находок» и «нет решателя» обязаны
отличаться для любого потребителя, включая CI и B2B-клиента.

ЕДИНЫЙ ИСТОЧНИК (`#353`): путь к решателю берётся из `z3bin.find_z3`, путь к
`kernc` — из `env_resolver.host_path`, а не вычисляется здесь заново.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import env_resolver

REQUIRED_ERRORS = 2          # код «дистрибутив неполон» (не 1: тот занят «находки»)


def _find_solver() -> tuple[str | None, str]:
    """Найти решатель ЧЕРЕЗ `z3bin` (одно место правды). Возвращает (путь, как искали)."""
    try:
        import z3bin
        p = z3bin.find_z3()
        return (str(p) if p else None), "$Z3 → .venv/bin/z3 → PATH"
    except Exception as exc:                                  # noqa: BLE001
        return None, f"z3bin недоступен: {type(exc).__name__}: {exc}"


def publish_solver_path() -> str | None:
    """Опубликовать найденный решатель в `PATH` (наследуется детьми).

    ДЕФЕКТ #494a (найден гейтом `kerna-check`, R3): две половины продукта искали
    решатель ПО-РАЗНОМУ. Python-часть — через `z3bin.find_z3()` (`$Z3` →
    `.venv/bin/z3` → `PATH`), а `kernc` (Zig) вызывает буквально `"z3"`, то есть
    ищет ТОЛЬКО в `PATH`. В изолированном дистрибутиве это давало абсурд:
    доктор говорит «зависимости на месте», а врата Белнапа (`_xray_solver_gate`)
    отвечают `z3 недоступен` -> `N(0,0)` -> находок 0.

    Лечение без правки Zig: найденный путь публикуется в `PATH` ДО запуска
    детей, поэтому обе половины видят один и тот же решатель.
    """
    solver, _how = _find_solver()
    if not solver:
        return None
    d = str(Path(solver).resolve().parent)
    cur = os.environ.get("PATH", "")
    if d not in cur.split(os.pathsep):
        os.environ["PATH"] = d + (os.pathsep + cur if cur else "")
    return solver


def check(require_solver: bool = True, require_kernc: bool = False) -> list[str]:
    """Список НАЗВАННЫХ недостающих зависимостей (пусто = всё на месте)."""
    missing: list[str] = []

    if require_solver:
        solver, how = _find_solver()
        if not solver:
            missing.append(
                f"решатель z3 НЕ найден (искали: {how}). Без него анализ не даёт "
                f"контрпримеров — «находок 0» было бы ЛОЖЬЮ, а не результатом")

    if require_kernc:
        kernc = env_resolver.host_path("zig-out", "bin", "kernc")
        if not Path(kernc).is_file():
            missing.append(
                f"kernc НЕ найден: {kernc} (нужен для подтверждения контрпримеров "
                f"живым вызовом, #206)")

    sj = env_resolver.resource_path("server.json")
    if not Path(sj).is_file():
        missing.append(f"server.json НЕ найден: {sj} (нужен для версии; "
                       f"молчаливый откат был бы дефектом #222)")

    return missing


def report(missing: list[str], stream=sys.stderr) -> int:
    """Громкий НАЗВАННЫЙ отказ; rc=0 только когда всё на месте."""
    if not missing:
        print("[OK] kerna doctor: зависимости на месте "
              f"(пакет: {env_resolver.describe()['packager']})", file=stream)
        return 0
    print("[!] KERNA DOCTOR: ДИСТРИБУТИВ НЕПОЛОН — запуск остановлен:", file=stream)
    for m in missing:
        print(f"    - {m}", file=stream)
    print("    Разместите рядом с бинарником: server.json, zig-out/bin/kernc, "
          ".venv/bin/z3 (см. docs/LIMITS.md).", file=stream)
    return REQUIRED_ERRORS


def preflight(require_solver: bool = True, require_kernc: bool = False,
              quiet_when_ok: bool = True) -> int:
    """Вызывается ПЕРЕД работой. 0 — можно работать, 2 — зависимость отсутствует."""
    if require_solver:
        publish_solver_path()   # #494a: одна находка решателя -> один PATH для детей
    missing = check(require_solver=require_solver, require_kernc=require_kernc)
    if not missing and quiet_when_ok:
        return 0
    return report(missing)


def main(argv: list[str]) -> int:
    import json
    if "--json" in argv:
        doc = env_resolver.describe()
        doc["missing"] = check()
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0 if not doc["missing"] else REQUIRED_ERRORS
    return report(check())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
