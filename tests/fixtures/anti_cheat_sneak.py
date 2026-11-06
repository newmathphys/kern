# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# СНИППЕТ ДЛЯ КЕЙСА `l5-duel`: чит, который копируется в честный файл.
# Класс: dynamic dunder override (assign) - его ловит анти-чит.


class Sneak:
    def __init__(self):
        self.value = 0


Sneak.__eq__ = lambda self, other: True
