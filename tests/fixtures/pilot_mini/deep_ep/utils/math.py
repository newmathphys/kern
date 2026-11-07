# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# МИНИ-ПИЛОТ для can-fail кейса `pilot-gate-blind` (#505): СВОЙ код с ТОЙ ЖЕ
# семантикой, что реальная функция пилота `deep_ep/utils/math.py:22` в
# DeepSeek/DeepEP-Ascend (4dfccac4) — копия чужого файла здесь была бы
# нарушением лицензионного гейта: сторонний код живёт в `audits/`.
def ceil_div(x, y):
    return (x + y - 1) // y
