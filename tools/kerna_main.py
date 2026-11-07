#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kerna_main` — ОФИЦИАЛЬНАЯ ТОЧКА ВХОДА УПАКОВАННОГО `kerna` (#494).

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Спайк показал: если собрать бинарь прямо из
`kern_scan.py`, то фронтенд, который вызывает САМ СЕБЯ как экстрактор
(`PY = sys.executable`, `[PY, EXTRACTOR, "--xray", …]`), получает
`unrecognized arguments: --xray --xray-json` — и анализ молча не выполняется.
Здесь два инварианта упаковки реализованы явно:

  1. ДИСПЕТЧЕР: один бинарь обслуживает и `kerna` (паспорт), и подрежимы
     экстрактора (`--xray`, `--anti-cheat`, контракты) — переиспользование
     самого себя вместо внешнего Python;
  2. ДОКТОР: до любой работы проверяются зависимости (`z3`, `kernc`,
     `server.json`), и отсутствие — НАЗВАННЫЙ отказ rc=2, а не «находок 0».

Совместимость: в dev-режиме (`python3 tools/kerna_main.py …`) поведение то же,
что у `tools/kern_scan.py`, поэтому файл можно использовать как единую точку
входа и без упаковки.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env_resolver          # noqa: E402
import kerna_doctor          # noqa: E402

# Флаги, означающие «работает ЭКСТРАКТОР» (kern_contracts), а не сканер папки.
EXTRACTOR_FLAGS = ("--xray", "--xray-json", "--anti-cheat", "--full-scan",
                   "--emit-smt2", "--emit-pytest", "--lock-repo", "--diff-equiv",
                   "--github-annotations", "--json")
SCAN_FLAGS = ("--sample", "--timeout", "--json", "-h", "--help")


def _strip_extractor_path(args: list[str]) -> list[str]:
    """Убрать путь к `kern_contracts.py`, который фронтенд передаёт ребёнку.

    В упакованном виде `sys.executable` — это САМ бинарь, а путь к экстрактору
    ему не нужен и не существует. Иначе argparse получит лишний позиционный.
    """
    if args and str(args[0]).endswith("kern_contracts.py"):
        return args[1:]
    return args


def _is_extractor_mode(args: list[str]) -> bool:
    if not args:
        return False
    if args[0] in EXTRACTOR_FLAGS or args[0].startswith("--xray"):
        return True
    # одиночный ФАЙЛ (а не каталог) — это режим контрактов/анти-чита
    if args[0] not in SCAN_FLAGS and not args[0].startswith("-"):
        p = Path(args[0])
        return p.is_file()
    return False


# #511: `--delta` — ПОВЕДЕНЧЕСКИЙ ДИФФЕРЕНЦИАЛЬНЫЙ АУДИТ ИЗ БИНАРНИКА.
# Клиент, скачавший только архив `kerna-dist`, обязан уметь спросить «что стало
# хуже в ЭТОМ изменении?» без клонирования репозитория и без `pip install`.
# Реализация ОДНА (`tools/audit_delta.py`), бинарь лишь вызывает её тем же ABI:
# копия логики в диспетчере разошлась бы с гейтами (класс #497).
DELTA_FLAGS = ("--delta", "--delta-json")


def main(argv: list[str] | None = None) -> int:
    args = _strip_extractor_path(list(sys.argv[1:] if argv is None else argv))

    if args and args[0] in ("--doctor", "doctor"):
        rest = [] if len(args) < 2 else ["--json"] if "--json" in args else []
        rc = kerna_doctor.main(rest)
        print(f"    resource_root: {env_resolver.RESOURCE_ROOT}", file=sys.stderr)
        print(f"    host_root    : {env_resolver.HOST_ROOT}", file=sys.stderr)
        return rc

    if args and args[0] in DELTA_FLAGS:
        # Доктор обязателен и здесь: без решателя дельта врёт «изменений нет».
        rc = kerna_doctor.preflight(require_solver=True, require_kernc=False)
        if rc != 0:
            return rc
        import audit_delta          # noqa: PLC0415 — вшит в бинарь тем же путём
        rest = list(args[1:])
        if args[0] == "--delta-json":
            rest.append("--json")
        sys.argv = [sys.argv[0]] + rest
        return audit_delta.main()

    if _is_extractor_mode(args):
        # #494: ДОКТОР ОБЯЗАТЕЛЕН И ЗДЕСЬ. Без него режим `--xray` при
        # отсутствии `z3` возвращал `findings 0, unreadable 1, rc=0` — то есть
        # ровно тот тихий отказ, ради устранения которого доктор и написан
        # (измерено гейтом: R4 «ожидали rc=2, получили rc=0»).
        needs_solver = "--anti-cheat" not in args
        rc = kerna_doctor.preflight(require_solver=needs_solver,
                                    require_kernc=False)
        if rc != 0:
            return rc
        import kern_contracts
        sys.argv = [sys.argv[0]] + args
        return kern_contracts.main()

    # ПЕРЕД паспортом: без решателя «находок 0» было бы ложью (спайк, ловушка 4)
    rc = kerna_doctor.preflight(require_solver=True, require_kernc=False)
    if rc != 0:
        return rc

    import kern_scan
    sys.argv = [sys.argv[0]] + args
    return kern_scan.main()


if __name__ == "__main__":
    sys.exit(main())
