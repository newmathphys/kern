def gcd(a: int, b: int) -> int:
    while b:
        t = b
        b = a % b
        a = t
    return abs(a)
