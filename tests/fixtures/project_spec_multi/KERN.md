# Закон проекта: многоязычный стенд (C + Python)

- require_all_functions_covered: true

### ring.c :: array_write_hit
- array: buf
- requires: idx >= 0
- ensures: result == val

### money.py :: withdraw(balance, amount)
- requires: balance >= 0 and amount >= 0 and amount <= balance
- ensures: result >= 0 and result <= balance and result == balance - amount
