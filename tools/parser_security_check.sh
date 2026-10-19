#!/usr/bin/env bash
# ЗАЩИТА ПАРСЕРА: Comment-in-String Injection + Type-Alias Spoofing.
set -u
PY=${PYTHON:-python3}
EX=${KERNC_EXTRACTOR:-tools/kern_contracts.py}
fail=0

# 1) Подделка контракта ВНУТРИ строкового литерала НЕ должна распознаваться.
out=$($PY - <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("kc", "tools/kern_contracts.py")
m = importlib.util.module_from_spec(spec); sys.modules["kc"] = m; spec.loader.exec_module(m)
res = m.parse_file(Path("tests/fixtures/inject_comment_in_string.py"))
print(len(res))
PY
)
if [ "$out" = "0" ]; then
  echo '  [OK] Comment-in-String: подделка в литерале НЕ считается контрактом'
else
  echo "  [FAIL] подделка распознана (функций: $out)"; fail=1
fi

# 2) НАСТОЯЩИЙ комментарий обязан распознаваться (иначе цель вакуумна).
tmp=$(mktemp /tmp/psc_XXXX.py)
printf '# @kern:ensures result >= 0\ndef f(x: int) -> int:\n    return x\n' > "$tmp"
out=$($PY - <<PY
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("kc", "tools/kern_contracts.py")
m = importlib.util.module_from_spec(spec); sys.modules["kc"] = m; spec.loader.exec_module(m)
res = m.parse_file(Path("$tmp"))
print(len(res))
PY
)
rm -f "$tmp"
if [ "$out" -ge 1 ]; then
  echo '  [OK] настоящий комментарий распознаётся (контроль не вакуумный)'
else
  echo '  [FAIL] настоящий комментарий НЕ распознан — защита сломала парсер'; fail=1
fi

# 3) Type-Alias Spoofing ловится.
sp=$(mktemp /tmp/psc_XXXX.py)
printf 'PositiveInt = int\n\ndef f(x):\n    return x\n' > "$sp"
out=$($PY "$EX" --anti-cheat "$sp" 2>&1)
rm -f "$sp"
echo "$out" | grep -q 'type-alias spoofing' \
  && echo '  [OK] Type-Alias Spoofing пойман' \
  || { echo '  [FAIL] Type-Alias Spoofing НЕ пойман'; fail=1; }

# 4) Обычный `a + b` (u32) ОБЯЗАН ловиться как переполнение...
if $PY "$EX" tests/fixtures/zig_plain_add.zig 2>&1 | grep -q 'ПЕРЕПОЛНЕНИЕ'; then
  echo '  [OK] обычный `+` на u32 -> ПЕРЕПОЛНЕНИЕ (баг пойман)'
else
  echo '  [FAIL] обычный `+` НЕ поймано переполнение'; fail=1
fi

# ...а ЯВНЫЕ `+|` (Zig) и `.saturating_add` (Rust) — НЕТ (законная семантика).
for f in tests/fixtures/zig_saturating_add.zig tests/fixtures/rust_saturating_add.rs; do
  out=$($PY "$EX" "$f" 2>&1)
  if echo "$out" | grep -q 'ПЕРЕПОЛНЕНИЕ'; then
    echo "  [FAIL] ложное ПЕРЕПОЛНЕНИЕ на $f"; fail=1
  elif echo "$out" | grep -q 'явное'; then
    echo "  [OK] $(basename "$f"): явное насыщение распознано, ложного OVERFLOW нет"
  else
    echo "  [FAIL] $f: ни распознавания, ни вердикта"; fail=1
  fi
done

[ "$fail" -eq 0 ] && { echo '[OK] parser-security-check'; exit 0; }
echo '[FAIL] parser-security-check'; exit 1
