# Контракт проекта: Биллинг

- require_all_functions_covered: true
- tests: tests/

### bank.py :: withdraw(balance, amount)
- requires: balance >= 0 and amount >= 0 and amount <= balance
- ensures: result >= 0 and result <= balance and result == balance - amount

### bank.py :: fee(amount)
- requires: amount >= 0
- ensures: result == amount // 100

### bank.py :: transfer(a, b)
- requires: a >= 0 and b >= 0 and a + b <= 1000
- ensures: result == a + b
