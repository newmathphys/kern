# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# @kern:expect-violations — ДЕМО-ФИКСТУРА: читерство НАМЕРЕННОЕ (стенд `make ai-demo`).
"""Тесты, которые «написал ИИ» вместе с модулем.

Оба теста ЗЕЛЁНЫЕ — и оба ничего не проверяют:

  * `test_transfer_smoke` — вакуумный: в нём НЕТ `assert`, упасть не может;
  * `test_transfer_negative_hidden` — чит: исключение проглочено
    (`except Exception: pass`), поэтому тест зелёный при любой дыре.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from ai_generated import transfer_with_fee  # noqa: E402


def test_transfer_smoke():
    """Вакуумный тест: ни одного assert."""
    transfer_with_fee(1000, 100)


def test_transfer_negative_hidden():
    """Чит: ошибка проглочена, поэтому тест не может упасть."""
    try:
        assert transfer_with_fee(1000, -50) < 1000
    except Exception:
        pass
