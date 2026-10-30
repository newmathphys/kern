# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
#
# ДВУСТОРОННИЙ КОНТРОЛЬ анти-чита (дефект #426): здесь НЕТ читов, и НИ ОДНА
# находка недопустима. Каждая строка — форма, которую новое правило МОГЛО БЫ
# задеть, но не должно: иначе «починка» превратилась бы в шум.
import sys
import pytest
import unittest


class Account:
    def __init__(self):
        self.balance = 0          # (1) штатное присваивание в `__init__`

    def setup(self):
        self.balance = 100        # (2) штатное присваивание в `setUp`-подобном методе


def configure(cfg):
    cfg.timeout = 30              # (3) присваивание НЕ функции (число), не чит
    return cfg


def main():
    return 0


sys.exit(main())                  # (4) МОДУЛЬНЫЙ CLI-идиом: не «exit в тестируемом коде»


@pytest.mark.skipif(sys.platform == "win32", reason="только POSIX")  # (5) условный skip
def test_conditional():
    assert Account().balance == 0
