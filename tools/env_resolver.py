#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`env_resolver` — ЕДИНЫЙ ИСТОЧНИК ПУТЕЙ для dev и для упакованного `kerna` (#494).

ЗАЧЕМ. Упаковка в onefile расщепляет понятие «где я нахожусь» НАДВОЕ, и это
ИЗМЕРЕНО на спайке (`~/.cache/kern/kerna-spike`, 4 ловушки):

  1. `ROOT = Path(__file__).parent.parent` в frozen превращался в `/tmp`:
     экстрактор не найден -> `rc=2`, находок 0;
  2. `KERN_VERSION = _kern_version()` читает `server.json` НА ИМПОРТЕ ->
     `ImportError`, бинарь не стартует;
  3. путь к `kernc` считался ОТДЕЛЬНО (мимо ROOT) -> `/tmp/zig-out/bin/kernc`
     -> живой replay падал -> находки МОЛЧА становились нулём;
  4. без `z3` рядом: `findings 0`, `unreadable 1`, `rc=0`, stderr ПУСТ.

ПОЭТОМУ КОРНЕЙ ДВА, и путать их нельзя:
  * RESOURCE_ROOT — ВНУТРИ упаковки (`sys._MEIPASS` у PyInstaller): там данные,
    вшитые `--add-data` (`server.json`, лицензии, шаблоны);
  * HOST_ROOT — РЯДОМ С БИНАРНИКОМ (или корень репозитория в dev): там `kernc`,
    `z3`, `.venv`, проверяемая кодовая база.

ОБА УПАКОВЩИКА. `sys.frozen` выставляет ТОЛЬКО PyInstaller; Nuitka кладёт
`__compiled__` (измерено: на Nuitka-бинаре диспетчер подкоманд не включился
именно из-за этого). Проверяются оба признака — иначе вторая ловушка вернётся
при смене упаковщика.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "is_frozen", "get_resource_root", "get_host_root", "RESOURCE_ROOT",
    "HOST_ROOT", "resource_path", "host_path", "describe",
]


def is_frozen() -> bool:
    """Упаковано ли (PyInstaller ИЛИ Nuitka)."""
    if getattr(sys, "frozen", False):
        return True
    # Nuitka: sys.frozen НЕ выставляется, признак — `__compiled__`
    return hasattr(sys, "__compiled__") or "__compiled__" in globals()


def _env_path(*names: str) -> Path | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return Path(v).expanduser().resolve()
    return None


def get_resource_root() -> Path:
    """Где ВШИТЫЕ данные (внутри упаковки, иначе — корень репозитория)."""
    env = _env_path("KERN_RESOURCE_ROOT")
    if env is not None:
        return env
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    if is_frozen():                     # Nuitka onefile распаковывает рядом с __file__
        return Path(__file__).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_host_root() -> Path:
    """Где БИНАРНИК (или корень репозитория при dev-запуске)."""
    env = _env_path("KERN_HOST_ROOT", "KERN_ROOT")
    if env is not None:
        return env
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


RESOURCE_ROOT = get_resource_root()
HOST_ROOT = get_host_root()


def resource_path(name: str) -> Path:
    """Путь к ВШИТОМУ файлу; если упаковка его не содержит — fallback в HOST.

    Fallback намеренный: dev-режим и «клиент распаковал архив целиком» должны
    работать одинаково, но порядок фиксирован — сначала упаковка.
    """
    p = RESOURCE_ROOT / name
    if p.exists():
        return p
    return HOST_ROOT / name


def host_path(*parts: str) -> Path:
    """Путь ОТНОСИТЕЛЬНО БИНАРНИКА (kernc, z3, .venv, проверяемый код)."""
    return HOST_ROOT.joinpath(*parts)


def describe() -> dict:
    """Диагностика: что именно видит процесс (для `kerna doctor` и отчётов)."""
    return {
        "frozen": is_frozen(),
        "packager": ("pyinstaller" if getattr(sys, "_MEIPASS", None)
                     else ("nuitka" if is_frozen() else "source")),
        "resource_root": str(RESOURCE_ROOT),
        "host_root": str(HOST_ROOT),
        "server_json": str(resource_path("server.json")),
        "kernc": str(host_path("zig-out", "bin", "kernc")),
        "executable": sys.executable,
    }
