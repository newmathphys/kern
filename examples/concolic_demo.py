def classify(x: int, y: int) -> int:
    if x > 5:
        if y > 3:
            return 1
        return 2
    if x < -5:
        return 3
    return 0
