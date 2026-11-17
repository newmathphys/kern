# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ПУНКТ 38: ИЗМЕРЕННАЯ ГРАНИЦА ФРАГМЕНТА. Тело `x * 2` корректно, но лежит ВНЕ
# замкнутого линейного фрагмента, поэтому награда — 0.0 ABSTAIN, а НЕ ложный +1.0.
# Линейный кандидат (x + 1) проверяется отдельно и получает +1.0 (см. tools/rlvr_oracle_check.sh).
# @kern:requires x >= 0
# @kern:ensures result >= 0
def double(x):
    return x * 2
