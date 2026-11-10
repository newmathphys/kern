# Двусторонний контроль --gen-tests: НАСТОЯЩАЯ недостижимость (UNSAT)
def dead_branch(x: int) -> int:
    if x > 0 and x < 0:
        return 1
    return 0
