#!/usr/bin/env bash
# ПОЛНЫЙ МУТАЦИОННЫЙ СВИП В ОТДЕЛЬНОМ WORKTREE (дефект #482).
#
# ЗАЧЕМ. Мутатор и `canfail` оба правят исходники, поэтому в ОДНОМ дереве они
# обязаны исключать друг друга (дефект #88b). Но полный свип идёт ~40 минут, и
# раньше он блокировал `canfail`, то есть ЛЮБУЮ проверку гейтов. Теперь лок
# выводится из пути дерева (`tools/mutation_lock.py`), поэтому свип в ОТДЕЛЬНОМ
# worktree не мешает основной работе: у каждого дерева свой замок.
#
# РЕЗУЛЬТАТ: `docs/evidence/mutate_full.log` (копируется из worktree) — его
# нужно ЗАКОММИТИТЬ вместе с обновлённым числом сайтов.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ZIG="${KERN_ZIG:-zig}"
Z3="${KERN_Z3_PATH:-$ROOT/.venv/bin/z3}"
TAG="$(printf '%s' "$ROOT" | sha256sum | cut -c1-8)"
WT="${KERN_MUT_WT:-$(dirname "$ROOT")/kern-mut-$TAG}"
MAX="${1:-5000}"

if [ ! -d "$WT/.git" ] && [ ! -f "$WT/.git" ]; then
  echo "[i] создаю worktree для свипа: $WT"
  git worktree add --detach "$WT" HEAD >/dev/null || { echo "[!] worktree не создан"; exit 2; }
else
  echo "[i] worktree уже есть: $WT"
  # ВАЖНО: обновляем worktree на ТЕКУЩИЙ HEAD главного дерева (объекты общие),
  # иначе свип тестирует старый снимок — и «починка» не проверяется (#482/#479).
  git -C "$WT" checkout --detach "$(git -C "$ROOT" rev-parse HEAD)" >/dev/null 2>&1 \
    || echo "[!] worktree не переключён на HEAD главного дерева — свип пойдёт по старому снимку"
fi

echo "[i] свип: --max $MAX, jobs 4, в $WT (главное дерево свободно)"
( cd "$WT" && KERN_ZIG="$ZIG" timeout 10800 python3 tools/mutate_zig.py \
    --max "$MAX" --seed 7 --jobs 4 --require-solver --z3-path "$Z3" ) \
  > "$WT/mutate_full.log" 2>&1
RC=$?
echo "[i] свип rc=$RC"
if [ -s "$WT/mutate_full.log" ]; then
  grep -E 'найдено сайтов мутации|Всего мутантов|СКОР|surviv|выжил' "$WT/mutate_full.log" | tail -6
  # ТРЕЙЛЕР (#487): лог обязан нести СВОЙ rc и разбивку способа убийства,
  # иначе машинному владельцу нечего сверять с README и facts.json.
  { cat "$WT/mutate_full.log";
    _k=$(grep -c ' -> killed' "$WT/mutate_full.log" || true);
    _c=$(grep -c 'killed (compile)' "$WT/mutate_full.log" || true);
    _t=$(grep -c 'killed (timeout)' "$WT/mutate_full.log" || true);
    _s=$(grep -c '-> survived' "$WT/mutate_full.log" || true);
    echo "";
    echo "# РАЗБИВКА СПОСОБА УБИЙСТВА (машинно разбирается \`tools/mutate_log_check.py\`):";
    echo "# test $((_k-_c-_t)) | compile $_c | timeout $_t | survived $_s";
    echo "RC=$RC"; } > "$ROOT/docs/evidence/mutate_full.log"
  echo "[i] лог скопирован в docs/evidence/mutate_full.log — ЗАКОММИТЬТЕ его"
fi
exit "$RC"
