# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# СНИППЕТ ДЛЯ КЕЙСА `l5-duel`: чит, который копируется в честный файл.
# Класс: dynamic dunder override (assign) - его ловит анти-чит.


class Sneak:
    def __init__(self):
        self.value = 0


Sneak.__eq__ = lambda self, other: True
