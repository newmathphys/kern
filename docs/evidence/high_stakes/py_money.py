"""Money in integer cents: the standard tax / bill-split patterns.

Modelled on TheAlgorithms/Python financial/price_plus_tax.py, but in integer
cents so the arithmetic is exact and checkable (float money is a defect class
of its own).
"""


# @kern:requires base >= 0
# @kern:ensures result >= 0 and result <= base
def tax_15_percent(base: int) -> int:
    return base * 15 // 100


# @kern:requires total >= 0 and people >= 0
# @kern:ensures result >= 0
def split_bill_unguarded(total: int, people: int) -> int:
    return total // people


# @kern:requires total >= 0 and people > 0
# @kern:ensures result >= 0
def split_bill_guarded(total: int, people: int) -> int:
    return total // people
