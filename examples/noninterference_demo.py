# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 6, ПУНКТ 34: неинтерференция (2-Safety самокомпозиция).
# Ожидания: check_pin_leaky -> SECRET LEAK; constant_time_op -> PROVEN NON-INTERFERENT.


# @kern:secret(pin)
def check_pin_leaky(pin, guess):
    return pin == guess      # публичный выход зависит от секрета


# @kern:secret(pin)
def constant_time_op(pin, public_x):
    return public_x + 1      # выход НЕ зависит от секрета
