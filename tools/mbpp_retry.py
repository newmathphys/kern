#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Убирает ПУСТЫЕ (ошибочные) сэмплы, чтобы генератор повторил именно их.

Генератор (tools/humaneval_api.py) пропускает уже присутствующие task_id.
Если запрос упал (rate-limit/таймаут), в файл попадает пустой completion —
он считается «готовым» и больше не повторяется. Этот скрипт удаляет такие
записи (и дубликаты), после чего повторный запуск генератора дозаполняет их.

Использование:  python3 tools/mbpp_retry.py [файл.jsonl]
"""
import json
import sys


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "samples_mbpp.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    keep, seen = [], set()
    for r in rows:
        tid = r.get("task_id")
        if not r.get("completion", "").strip():
            continue
        if tid in seen:
            continue
        seen.add(tid)
        keep.append(r)
    with open(path, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[i] оставлено {len(keep)} из {len(rows)}; "
          f"удалено пустых/дублей: {len(rows) - len(keep)}")


if __name__ == "__main__":
    main()
