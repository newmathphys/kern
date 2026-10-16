#!/usr/bin/env bash
# ФИНАЛЬНАЯ ЦЕПОЧКА (исправленная): дождаться освобождения ЗАМКА canfail,
# затем пересобрать аттестат и перегенерировать быстрые свидетельства.
#
# ПОЧЕМУ ПО ЗАМКУ, А НЕ ПО ИМЕНИ ПРОЦЕССА (дефект #88b).
# Первая версия проверяла `pgrep -f tools/canfail.py`. Возникла гонка:
# regen_final проскочил проверку ДО того, как regen_canfail успел запустить
# canfail — и `make evidence-fast` пошёл ПАРАЛЛЕЛЬНО с мутирующим харнессом.
# Свидетельства того момента были бы ЛОЖНЫМИ (тесты читают пропатченные файлы).
# Замок flock держится всё время работы харнесса и снимается ЯДРОМ даже при
# SIGKILL — поэтому он и есть правильный индикатор занятости.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PWD/.venv/bin:$PATH"

LOCK=/tmp/kern_canfail.lock
echo "[chain] жду освобождения замка canfail..."
python3 - "$LOCK" <<'PY'
import fcntl, sys, time
path = sys.argv[1]
while True:
    try:
        f = open(path, "r+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        break
    except (BlockingIOError, FileNotFoundError):
        time.sleep(5)
PY
while pgrep -f 'tools/canfail.py' > /dev/null 2>&1; do sleep 5; done
sleep 3

echo "[chain] аттестат..."
python3 tools/slsa_provenance.py --no-build

echo "[chain] evidence-fast..."
make evidence-fast
echo "DONE" >> /tmp/final_chain.log
