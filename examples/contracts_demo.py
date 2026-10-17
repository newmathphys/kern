"""Демонстрация контрактов KERN прямо в Python-коде.

Никакого SMT-LIB2: контракт — это комментарий рядом с функцией.
Проверка: python3 tools/kern_contracts.py examples/contracts_demo.py
"""


# @kern:requires amount > 0 and balance >= amount
# @kern:ensures  result == balance - amount and result < balance
def withdraw(balance: int, amount: int) -> int:
    """КОРРЕКТНАЯ функция: контракт обязан ДОКАЗАТЬСЯ."""
    return balance - amount


# @kern:requires amount > 0 and balance >= amount
# @kern:ensures  result == balance - amount and result < balance
def withdraw_buggy(balance: int, amount: int) -> int:
    """БАГ: перепутан знак — списание УВЕЛИЧИВАЕТ баланс.

    Тот же контракт, что у `withdraw`, но тело `+` вместо `-`.
    Контракт обязан НАРУШИТЬСЯ (Z3 предъявит контрпример).
    """
    return balance + amount


# @kern:requires 0 <= k and 0 <= x
# @kern:ensures  result == 3 * x
def triple(x: int, k: int) -> int:
    """Линейное умножение на литерал — тоже в подмножестве."""
    return 3 * x


# @kern:requires n >= 0
# @kern:ensures  result >= 0
def sum_to_n(n: int) -> int:
    """ВНЕ подмножества: цикл. Должна быть честно помечена SKIP."""
    total = 0
    for i in range(n):
        total = total + i
    return total


# @kern:requires True
# @kern:ensures  result <= balance
def withdraw_fixed(balance: int, amount: int) -> int:
    """ВЕТВЛЕНИЯ: два `if` с `return` -> SMT `(ite ...)`.

    СПЕЦИФИКАЦИЯ: списание НЕ МОЖЕТ увеличить баланс (`result <= balance`).
    Функция отвергает и отрицательную сумму, и сумму больше баланса ->
    обязана ДОКАЗАТЬСЯ.
    """
    if amount < 0:
        return balance
    if amount > balance:
        return balance
    return balance - amount


# @kern:requires True
# @kern:ensures  result <= balance
def withdraw_missing_neg(balance: int, amount: int) -> int:
    """БАГ: проверен только `amount > balance`, ЗАБЫТ `amount < 0`.

    При `amount = -1` функция возвращает `balance + 1`, то есть УВЕЛИЧИВАЕТ
    баланс -> обязан быть НАЙДЕН КОНТРПРИМЕР.

    ВНИМАНИЕ: первая версия контракта здесь была
    `result == balance - amount or result == balance` — и она ВЫПОЛНЯЕТСЯ
    при `amount = -1` (функция честно вычислила `balance - amount`), поэтому
    Z3 доказывал «всё хорошо» и БАГ НЕ ЛОВИЛСЯ. Контракт переписан на
    настоящую спецификацию списания.
    """
    if amount > balance:
        return balance
    return balance - amount


# @kern:requires amount > 0
# @kern:ensures  result <= balance
def withdraw_ternary(balance: int, amount: int) -> int:
    """Тернарный оператор `A if cond else B` -> SMT `ite`."""
    return balance if amount > balance else balance - amount


# @kern:requires amount >= 0
# @kern:ensures  result >= 0
def no_return_path(balance: int, amount: int) -> int:
    """БАГ: путь без `return` при `amount == 0` -> функция вернула бы None.

    Обязана быть честно отвергнута (NoReturn), а НЕ объявлена доказанной.
    """
    if amount > 0:
        return balance - amount


# @kern:requires amount > 10 and amount < 5
# @kern:ensures  result == balance - amount
def withdraw_vacuous(balance: int, amount: int) -> int:
    """ВАКУУМНЫЙ КОНТРАКТ: `requires` ПРОТИВОРЕЧИВО (пустой домен).

    Ловушка `false => anything`: обязательство `requires ∧ ¬ensures` при таком
    предусловии тривиально UNSAT, поэтому БЕЗ отдельной проверки ВЫПОЛНИМОСТИ
    самого `requires` любое тело — даже намеренно сломанное ниже — объявлялось
    бы ДОКАЗАННЫМ. Детектор обязан выдать `[VACUOUS] ... -> B4: N, e = 0`.
    """
    return balance + amount  # тело НАМЕРЕННО неверное — «доказаться» не должно
