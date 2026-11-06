# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ЭШЕЛОН 6, ПУНКТ 34: неинтерференция (2-Safety самокомпозиция).
# Ожидания: check_pin_leaky -> SECRET LEAK; constant_time_op -> PROVEN NON-INTERFERENT.


# @kern:secret(pin)
def check_pin_leaky(pin, guess):
    return pin == guess      # публичный выход зависит от секрета


# @kern:secret(pin)
def constant_time_op(pin, public_x):
    return public_x + 1      # выход НЕ зависит от секрета
