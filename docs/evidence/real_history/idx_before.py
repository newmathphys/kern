# Извлечено из boltons/mathutils.py ДО коммита 5eb6cc0 ("resolve negative Bits indices"):
# было `if k >= self.len: raise IndexError`.
def idx_ok(k: int, n: int) -> int:
    if k >= n:
        return 0
    return 1
