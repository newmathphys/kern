#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 34-Я СТАДИЯ: ВЕСЬ ПОЛНОСПЕКТРАЛЬНЫЙ КОРПУС (70/70) ПОД БРОНЁЙ.
#
# ЧТО ПРОВЕРЯЕТСЯ (одной командой, без права писать в дерево):
#   1) все 70 карточек семи блоков прогоняются по-настоящему: вердикт KERN +
#      независимый оракул (B4 из пар битов, MUS-ядро, AST-инструментация,
#      BLAKE3/Ed25519, шкала RLVR) — закон `confirmed == total`;
#   2) EN и RU витрины РЕНДЕРЯТСЯ В ПАМЯТИ и сверяются БАЙТ-В-БАЙТ с
#      закоммиченными `docs/FULL_SPECTRUM_70.{md,ru.md}`: любой дрейф -> rc=1;
#   3) файлы на диске НЕ перезаписываются (режим `--check`), поэтому гейт
#      не может «подогнать» витрину под себя.
#
# НЕВАКУУМНОСТЬ (двусторонняя, как у belnap-check):
#   * `KERN_CANFAIL_MUTATE=1` портит ОДНУ витрину в памяти -> гейт ОБЯЗАН упасть;
#   * `--selftest` запускает гейт дважды (норма -> 0, мутация текста -> != 0) и
#     краснеет, если мутация НЕ ломает проверку;
#   * кейс `full-spectrum-check` в `tools/canfail.py` правит ОЖИДАНИЕ в карточке
#     корпуса и требует красного гейта — это уже проверка чувствительности
#     к реальному расхождению данных, а не к нашему же флагу.
#
# ИЗМЕРЕНО: полный прогон 70 карточек — ~96 с (бюджет `--fast` это выдерживает).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
MUTATE=${KERN_CANFAIL_MUTATE:-0}



# ВЫБОР ИНТЕРПРЕТАТОРА (как в tools/ci.sh): голый `python3` может не иметь z3,
# а штатное окружение проекта — `.venv/bin/python`. Тихая подмена запрещена:
# если z3 нет нигде, это НАЗВАННЫЙ отказ rc=2, а не «зелёная» вакуумная проверка.
if ! "$PY" -c 'import z3' >/dev/null 2>&1; then
  if [ -x .venv/bin/python ] && .venv/bin/python -c 'import z3' >/dev/null 2>&1; then
    PY=.venv/bin/python
    echo "[i] z3 найден только в .venv — интерпретатор: $PY"
  else
    echo "[!] z3 недоступен для $PY — корпус без символической половины не проверить"
    echo "    штатно: PATH=.venv/bin:\$PATH (или PYTHON=.venv/bin/python)"
    exit 2
  fi
fi
if [ ! -x zig-out/bin/kernc ]; then
  echo "[!] нет zig-out/bin/kernc — сначала zig build (нужен для belnap/attest/prove)"
  exit 2
fi

if [ "${1:-}" = "--selftest" ]; then
  "$PY" tools/run_full_spectrum.py --check >/dev/null 2>&1; ok_rc=$?
  KERN_FS_MUTATE=text "$PY" tools/run_full_spectrum.py --check >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] full-spectrum-check --selftest: норма -> rc=0, испорченная витрина -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] full-spectrum-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc"
  echo "       испорченная витрина НЕ роняет гейт => проверка вакуумна"
  exit 1
fi
if [ "$MUTATE" = "1" ]; then
  echo "[MUTATE] KERN_CANFAIL_MUTATE=1: одна витрина портится В ПАМЯТИ — гейт обязан покраснеть"
  export KERN_FS_MUTATE=text
fi

START=$(date +%s)
"$PY" tools/run_full_spectrum.py --check
RC=$?
END=$(date +%s)
echo "[i] полный прогон 70 карточек: $((END - START)) c"
[ "$RC" -eq 0 ] && echo "[OK] full-spectrum-check: 70/70, витрины байт-в-байт, дерево не изменено"
exit "$RC"
