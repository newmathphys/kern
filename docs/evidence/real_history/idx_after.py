# Извлечено из boltons/mathutils.py ПОСЛЕ коммита 5eb6cc0:
# добавлена обработка отрицательных индексов (`k += self.len`).
def idx_ok(k: int, n: int) -> int:
    if k < 0:
        k = k + n
    if k < 0 or k >= n:
        return 0
    return 1
