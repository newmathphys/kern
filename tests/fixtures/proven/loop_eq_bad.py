def gcd(a: int, b: int) -> int:
    while b != 0:
        r = a % b
        a = b
        b = r + 1
    return abs(a)
