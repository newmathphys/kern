#!/usr/bin/env bash
# KERN: САМОТЕСТ pre-commit-шлюза (цель `make hook-check`).
#
# ЗАЧЕМ. Хук, который ничего не блокирует, — декорация. Проверяются ОБА
# исхода: КОРРЕКТНЫЙ контракт -> коммит ПРОПУЩЕН; СЛОМАННЫЙ -> ЗАБЛОКИРОВАН.
# Работает на временном репозитории, рабочий репозиторий не трогается.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

mkdir -p "$W/tools" "$W/zig-out/bin"
cp "$ROOT/tools/kern_contracts.py" "$W/tools/"
# Реальный kernc нужен хуку (он вызывает Z3 + пруф-чекер). Симлинк, чтобы
# самотест не требовал сборки внутри временного репозитория.
if [ -x "$ROOT/zig-out/bin/kernc" ]; then
  ln -s "$ROOT/zig-out/bin/kernc" "$W/zig-out/bin/kernc"
else
  echo "[!] нет $ROOT/zig-out/bin/kernc — соберите: zig build"
  exit 2
fi
cd "$W" || exit 1
git init -q .
git config user.email kern@local
git config user.name kern
git config commit.gpgsign false
"$PY" tools/kern_contracts.py --install-hook . >/dev/null || {
  echo "  [FAIL] не удалось установить хук"; exit 1; }

echo "KERN: самотест pre-commit шлюза (временный репозиторий $W)"
echo "───────────────────────────────────────────────────────────────────────"

# --- 1. КОРРЕКТНЫЙ контракт: коммит обязан ПРОЙТИ --------------------------
cat > good.py <<'EOF'
# @kern:requires amount > 0 and balance >= amount
# @kern:ensures  result == balance - amount
def charge(balance: int, amount: int) -> int:
    return balance - amount
EOF
git add -A >/dev/null
if git commit -qm "good contract" >/dev/null 2>&1; then
  echo "  [OK]   корректный контракт: коммит ПРОПУЩЕН"
else
  echo "  [FAIL] корректный контракт: коммит ЗАБЛОКИРОВАН (ложное срабатывание)"
  exit 1
fi

# --- 2. СЛОМАННЫЙ контракт: коммит обязан быть ЗАБЛОКИРОВАН ----------------
cat > bad.py <<'EOF'
# @kern:requires amount > 0
# @kern:ensures  result <= balance
def charge(balance: int, amount: int) -> int:
    return balance + amount
EOF
git add -A >/dev/null
if git commit -qm "broken contract" >/dev/null 2>&1; then
  echo "  [FAIL] сломанный контракт: коммит ПРОШЁЛ — шлюз НЕ работает!"
  exit 1
fi
echo "  [OK]   сломанный контракт: коммит ЗАБЛОКИРОВАН"

# --- 3. ДЕЛЕНИЕ НА НОЛЬ: коммит обязан быть ЗАБЛОКИРОВАН -------------------
rm -f bad.py
cat > div.py <<'EOF'
# @kern:requires balance >= 0
# @kern:ensures  result >= 0
def share(balance: int, amount: int) -> int:
    return balance // amount
EOF
git add -A >/dev/null
if git commit -qm "div by zero" >/dev/null 2>&1; then
  echo "  [FAIL] деление на ноль: коммит ПРОШЁЛ — шлюз НЕ работает!"
  exit 1
fi
echo "  [OK]   деление на ноль: коммит ЗАБЛОКИРОВАН"

echo "───────────────────────────────────────────────────────────────────────"
echo "[OK] pre-commit шлюз проверен: блокирует сломанное, пропускает корректное"
