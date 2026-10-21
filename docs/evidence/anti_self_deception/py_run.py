import sys; sys.path.insert(0, "/tmp/kern-anti-self-deception")
from py_abs_bad import absolute
r = absolute(-1)
assert r >= 0 and (r == -1 or r == 1), f"ensures violated: absolute(-1)={r}"
print("NO VIOLATION")