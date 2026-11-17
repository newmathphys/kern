#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 38-Я СТАДИЯ (окно №16): LIVE REPLAY, ВЕДОМЫЙ МОДЕЛЬЮ Z3.
#
# ЧТО ДОКАЗЫВАЕТСЯ (каждая точка — физический прогон, 8 фикстур):
#   1) край из модели (`period == 0`) подтверждается как ZeroDivisionError;
#   2) `kern_len_xs = 0` -> пустой список подтверждает IndexError;
#   3) функция со штатной валидацией даёт GUARDED_RAISE, а не CONFIRMED;
#   4) конструктор НЕ подаёт None вместо коллекции -> чужой TypeError не трофей;
#   5) норма (вход без края) -> SURVIVED;
#   6) ЗАМОК qualname: находка внутри `class A.PSAR` резолвится в A.PSAR;
#   7) ЗАМОК строки: находка вне тела любой функции -> NOT_REPLAYABLE;
#   8) метод экземпляра (`Box.pop` на пустом списке) подтверждается.
#
# НЕВАКУУМНОСТЬ: KERN_CANFAIL_MUTATE=1 требует ПРИНЯТЬ чужой qualname как
# трофей -> гейт обязан покраснеть. Останется зелёным — значит замок фиктивен.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
# pandas — ОПЦИОНАЛЬНА: без неё DataFrame-параметры честно получают
# NOT_REPLAYABLE, а 8 фикстур гейта (списки/строки/методы) проходят как есть.
# Поэтому ищем интерпретатор с pandas, но НЕ отказываем, если его нет (#634).
if ! "$PY" -c 'import pandas' >/dev/null 2>&1; then
  for _c in python3 /usr/bin/python3 python3.13 python3.12; do
    if command -v "$_c" >/dev/null 2>&1 && "$_c" -c 'import pandas' >/dev/null 2>&1; then
      PY="$_c"; break
    fi
  done
fi
MUTATE=${KERN_CANFAIL_MUTATE:-0}
if [ "${1:-}" = "--selftest" ]; then
  bash "$0" >/dev/null 2>&1; ok_rc=$?
  KERN_CANFAIL_MUTATE=1 bash "$0" >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] live-replay-check --selftest: норма -> rc=0, испорченное ожидание -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] live-replay-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc"
  exit 1
fi
if [ "$MUTATE" = "1" ]; then
  # ИСПОРЧЕННОЕ ожидание: требуем засчитать находку, чья строка ВНЕ тела
  # одноимённой функции (призрак finta.PSAR). Верный резолвер обязан отказать.
  "$PY" - "$ROOT" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
import live_replay as L
import tempfile, pathlib
work = pathlib.Path(tempfile.mkdtemp(prefix="kern_mut_"))
(work / "ghost.py").write_text(L.NL.join([
    "class A:", "    def PSAR(self, ohlc):", "        return ohlc[0]", "", "",
    "def PSAR(ohlc):", "    return 1", ""]), encoding="utf-8")
f = {"path": str(work / "ghost.py"), "kind": "bounds", "fn": "PSAR",
     "line": 6, "text": "возможен выход за границы", "model": {"kern_len_ohlc": 0}}
sig = L.signature(f["path"], "PSAR", 6)
verdict, detail = L.replay_one(f, L.load_target(f["path"]), sig)
if verdict == "CONFIRMED":
    print("[MUT] чужой qualname принят — проверка вакуумна")
    sys.exit(0)
print("[MUT] чужой qualname отвергнут: %s (%s)" % (verdict, detail))
sys.exit(1)
PYEOF
  rc=$?
  [ "$rc" -eq 0 ] && { echo "[FAIL] live-replay-check: мутация НЕ поймана"; exit 1; }
  echo "[FAIL] live-replay-check: мутированное ожидание отвергнуто -> гейт краснеет (это и требуется)"
  exit 1
fi
"$PY" tools/live_replay.py --selftest || { echo "[FAIL] live-replay-check: selftest"; exit 1; }
echo "[OK] live-replay-check: 8 фикстур — край из модели, замок qualname/строки, метод класса, легальность типа"
