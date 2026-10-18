# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 4, ПУНКТ 24: инвариант состояния (защита от двойного возврата).


# @kern:requires escrow >= 0 and amount >= 0
# @kern:state_invariant result >= 0
def refund_unsafe(state, escrow, amount):
    return escrow - amount      # БЕЗ гардов -> уходит в минус


# @kern:requires escrow >= 0 and amount >= 0
# @kern:state_invariant result >= 0
def refund_safe(state, escrow, amount):
    if state != 1:
        return escrow
    if amount > escrow:
        return escrow
    return escrow - amount
