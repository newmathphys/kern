"""ЧЕСТНЫЙ БЛИЗНЕЦ к ловушке 3: ПОЛНЫЙ гард, а не точечный костыль.

Обязан быть `[PASS] ДОКАЗАНО`: настоящая защита, а не подгонка под контрпример.
"""

# @kern:requires x >= -10
# @kern:ensures result >= 0
def norm_ok(x: int) -> int:
    if x < 0:
        return 0
    return x
