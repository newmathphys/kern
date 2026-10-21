print('=== A. boltons 5eb6cc0: проверка индекса (ДО фикса и ПОСЛЕ) ===')
def before(k, n):
    if k >= n: return 0
    return 1
def after(k, n):
    if k < 0: k = k + n
    if k < 0 or k >= n: return 0
    return 1
print('before(-1, 0) =', before(-1, 0), '<- ПРИНИМАЕТ недопустимый индекс (баг)')
print('after(-1, 0)  =', after(-1, 0), '<- отвергает (фикс)')
print('before(-6, 5) =', before(-6, 5), '<- тоже принимает индекс -6 при длине 5')
print('after(-6, 5)  =', after(-6, 5))
print()
print('=== B. boltons c1c25da: off-by-one в 2 ** len_ ===')
def guard_before(val, len_):
    return 'ACCEPT' if not (val > 2 ** len_) else 'REJECT'
def guard_after(val, len_):
    return 'ACCEPT' if not (val >= 2 ** len_) else 'REJECT'
print('before(val=4, len_=2) =', guard_before(4, 2), '<- 4 не влезает в 2 бита (баг)')
print('after (val=4, len_=2) =', guard_after(4, 2), '<- фикс отвергает')
print("  реальное следствие фикса: Bits(4, 2) давал значение '100' (3 бита) при объявленной длине 2")
print()
print('=== C. QuixBugs gcd: реальный баг из датасета ===')
import sys
sys.setrecursionlimit(200)
def gcd_buggy(a, b):
    if b == 0: return a
    return gcd_buggy(a % b, b)
try:
    print('gcd_buggy(1, 2) =', gcd_buggy(1, 2))
except RecursionError:
    print('gcd_buggy(1, 2) -> RecursionError (реальный краш до фикса)')
def gcd_fixed(a, b):
    if b == 0: return a
    return gcd_fixed(b, a % b)
print('gcd_fixed(1, 2) =', gcd_fixed(1, 2))
