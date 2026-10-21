"""Money in integer cents. Modelled on the standard progressive-discount /
price-plus-tax pattern (cf. TheAlgorithms/Python financial/price_plus_tax.py),
but with integer cents so the arithmetic is exact and checkable."""


# @kern:requires base >= 0 and rate >= 0 and rate <= 100
# @kern:ensures result >= 0 and result <= base
def tax_amount(base: int, rate: int) -> int:
    return base * rate // 100


# @kern:requires price >= 0 and discount_percent >= 0
# @kern:ensures result >= 0 and result <= price
def price_after_discount(price: int, discount_percent: int) -> int:
    return price - price * discount_percent // 100
