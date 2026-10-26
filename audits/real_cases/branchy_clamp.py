"""Анатомия одной функции, РЕЖИМ 6: нужны ВЕТВИ.

`--gen-tests` и `--concolic` работают по ветвям: у функции без ветвей они
честно возвращают 0 («тест был бы вакуумным»). Поэтому режим 6 берёт
ВЕТВЯЩУЮСЯ линейную функцию: ИЗМЕРЕНО `--gen-tests` 2 теста и `--concolic`
4/4 покрытых ветвей, 0 мёртвых.
"""

# @kern:requires lo <= hi
# @kern:ensures result >= lo and result <= hi
def clamp(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v
