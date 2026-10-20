#!/usr/bin/env bash
# trace-check — приёмка Ступени 2 (`tools/trace_explorer.py`).
#
# Почему мини-датасет, а не настоящий QuixBugs: цель гейта должна быть
# воспроизводимой БЕЗ сети. Структура каталогов повторяет QuixBugs
# (`python_programs/` + `correct_python_programs/`), поэтому проверяется
# ровно тот путь, которым движок ходит на настоящем датасете.
#
# Проверяется ДВА утверждения и одно опровержение:
#   1) расхождение в значениях ловится (bug: `n - 1` против `n`);
#   2) идентичные версии НЕ дают ложного расхождения (same);
#   3) негативный контроль: если сравнение сломать, цель ОБЯЗАНА покраснеть.
#      Иначе цель вакуумна (класс #130/#131/#132).
set -u
cd "$(dirname "$0")/.."

MINI=$(mktemp -d /tmp/kern-trace-XXXXXX) || exit 1
BROKEN=$(mktemp /tmp/kern-trace-broken-XXXXXX.py) || exit 1
cleanup() { rm -rf "$MINI" "$BROKEN"; }
trap cleanup EXIT INT TERM

mkdir -p "$MINI/python_programs" "$MINI/correct_python_programs"

cat > "$MINI/python_programs/bug.py" <<'PY'
def bug(n):
    return n - 1
PY
cat > "$MINI/correct_python_programs/bug.py" <<'PY'
def bug(n):
    return n
PY
for d in python_programs correct_python_programs; do
    cat > "$MINI/$d/same.py" <<'PY'
def same(n):
    return n + 1
PY
done

check() {   # check <лог> -> 0, если оба утверждения выполнены
    local log="$1" ok=0
    grep -qE '^bug +DIVERGED'  "$log" || { echo "  [!!] не поймано расхождение в bug"; ok=1; }
    grep -qE '^same +EXPLORED' "$log" || { echo "  [!!] ложное расхождение на идентичных версиях"; ok=1; }
    return $ok
}

echo "=== 1) штатный режим ==="
python3 tools/trace_explorer.py "$MINI" > /tmp/kern-trace-ok.log 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "  [!!] движок завершился rc=$rc"; tail -5 /tmp/kern-trace-ok.log; exit 1
fi
grep -E '^bug |^same ' /tmp/kern-trace-ok.log
check /tmp/kern-trace-ok.log || { echo "  [!!] штатный прогон не выполнил утверждений"; exit 1; }
echo "  [OK] баг пойман живым вызовом, ложного расхождения нет"

echo "=== 2) негативный контроль: ломаем сравнение ==="
# Копия движка с отключённым сравнением значений: расхождение больше не
# находится -> утверждение (1) обязано нарушиться. Если не нарушится,
# цель бесполезна (вакуумна).
sed 's/if nb != nc:/if False:  # ДИВЕРСИЯ/' tools/trace_explorer.py > "$BROKEN"
python3 "$BROKEN" "$MINI" > /tmp/kern-trace-broken.log 2>&1
brc=$?
if [ $brc -ne 0 ]; then
    echo "  [!] сломанный движок упал (rc=$brc) — это тоже отказ, засчитываю"
elif check /tmp/kern-trace-broken.log; then
    echo "  [!!] СЛОМАННОЕ сравнение всё равно «поймало» баг -> цель вакуумна"
    exit 1
else
    echo "  [OK] поломка замечена: цель способна упасть"
fi

rm -f /tmp/kern-trace-ok.log /tmp/kern-trace-broken.log
echo "[OK] trace-check: 2 утверждения + негативный контроль"
