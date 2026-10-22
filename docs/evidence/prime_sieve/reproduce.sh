#!/usr/bin/env bash
# KERN evidence harness — defect #320.
#
# Reproduces every number quoted in the "Correction" section of
# docs/SHADOW_AUDIT_EXAMPLE.md, so the claim can be re-derived instead of believed.
#
# It compiles the VERBATIM upstream file (docs/evidence/prime_sieve/prime_sieve.c,
# TheAlgorithms/C @ master) with an injected main() and prints, for several sizes,
#   count(arr, size)                      <- what the code computes (`i <= size`)
#   "first <size> elements"               <- the exclusive reading
# so the two contract readings can be compared directly.
#
# Usage:  bash docs/evidence/prime_sieve/reproduce.sh
set -uo pipefail
cd "$(dirname "$0")"

SRC=prime_sieve.c
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

# 1. the contradiction inside the source itself
echo "=== the source's own contract, verbatim ==="
grep -n 'upto which' "$SRC"
grep -n 'array size' "$SRC"
echo

# 2. build the harness: rename upstream main, add a probing main
python3 - "$SRC" > "$OUT/harness.c" <<'PY'
import sys
s = open(sys.argv[1]).read()
s = s.replace('int main(int argc, const char *argv[])',
              'int kern_orig_main(int argc, const char *argv[])')
s += '''
int main(void) {
    int arr[1000005] = {0};
    prime(arr);
    printf("indices:  0=%d 1=%d 2=%d 3=%d 5=%d 7=%d 10=%d 11=%d 13=%d\\n",
           arr[0], arr[1], arr[2], arr[3], arr[5], arr[7], arr[10], arr[11], arr[13]);
    int sizes[] = {3, 7, 10, 11, 13, 97, 1000000};
    for (int t = 0; t < 7; t++) {
        int sz = sizes[t];
        int got = count(arr, sz);
        int excl = 0;
        for (int i = 0; i < sz; i++) if (arr[i] == 1) excl++;
        printf("count(arr,%-8d) = %-6d  first %-8d elements = %-6d  %s\\n",
               sz, got, sz, excl, got == excl ? "same" : "DIFFER");
    }
    return 0;
}
'''
sys.stdout.write(s)
PY

gcc -O0 -o "$OUT/harness" "$OUT/harness.c" || { echo "BUILD FAILED"; exit 1; }

# 3. the measurement
echo "=== measurement on the real prime array ==="
"$OUT/harness"
echo
echo "=== reading of the result ==="
echo "count(arr, 10) = 4 and the exclusive reading is also 4 -> the test value (10)"
echo "cannot distinguish the two readings, because 10 is not prime. The two readings"
echo "differ exactly when size is itself prime (3, 7, 11, 13, 97 above)."
echo "Verdict: ambiguous contract, NOT a confirmed defect."
