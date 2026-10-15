#!/usr/bin/env python3
"""Проверка геометрии SVG-баннера: ни одна подпись не выходит за свою панель.

ЗАЧЕМ. SVG рендерится без предупреждений: если строка шире контейнера, она
просто «уезжает» в соседнюю панель или за край холста. XML при этом остаётся
валидным, поэтому `xml.etree.ElementTree` такую ошибку не видит — визуальный
дефект проходит все проверки и попадает на главную страницу репозитория.

Это ровно класс «молчаливо сломанных проверок», против которого построен KERN:
формально всё зелено, фактически баннер испорчен.

ЧТО ДЕЛАЕТ. Оценивает ширину строки как (число символов x коэффициент шрифта),
вычисляет правую границу каждой подписи и сверяет её с границей панели, внутри
которой подпись находится. Дополнительно проверяет:
  * XML-валидность файла;
  * канонический namespace W3C (иначе браузер не отрисует SVG вообще);
  * ровно один корневой элемент (дубликат закрывающего тега ломает документ).

Запуск:  python3 tools/svg_check.py [путь]
Код возврата: 0 — геометрия корректна, 1 — найдены нарушения.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "docs" / "kern-architecture.svg"

# Коэффициент ширины символа для моноширинного шрифта.
CW_RATIO = 0.6
# Дополнительный трекинг у заголовков (.hdr имеет letter-spacing).
EXTRA = {"hdr": 0.5}

# Панели холста: (x0, x1, y0, y1, имя). Текст обязан помещаться в свою панель.
PANELS = [
    (32, 247, 104, 256, "Belnap"),
    (275, 600, 104, 256, "L0-L5"),
    (628, 928, 104, 256, "Baseline"),
]
# Вложенные боксы внутри панелей (приоритетнее панели).
INNER = [
    (291, 584, 136, 194, "box1"),
    (291, 584, 202, 252, "box2"),
]

TEXT_RE = re.compile(r'<text x="(\d+)" y="(\d+)" class="(\w+)">([^<]*)</text>')
FONT_RE = re.compile(r"\.(\w+)\s*\{[^}]*?font:\s*\d+\s+(\d+(?:\.\d+)?)px")


def font_sizes(svg: str) -> dict[str, float]:
    return {cls: float(px) for cls, px in FONT_RE.findall(svg)}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"[!] файл не найден: {path}")
        return 1
    svg = path.read_text(encoding="utf-8")

    problems: list[str] = []

    # 1. XML-валидность и единственный корень.
    try:
        ET.parse(path)
    except ET.ParseError as e:
        problems.append(f"XML невалиден: {e}")
    opens, closes = svg.count("<svg"), svg.count("</svg>")
    if opens != 1 or closes != 1:
        problems.append(f"корневых элементов <svg>: {opens}, </svg>: {closes} (нужен ровно 1)")

    # 2. Namespace: сокращённый домен браузеры не распознают -> пустой прямоугольник.
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        problems.append('namespace не канонический (нужен xmlns="http://www.w3.org/2000/svg")')

    # 3. Геометрия подписей.
    sizes = font_sizes(svg)
    m = re.search(r'<rect width="(\d+)"', svg)
    canvas_w = int(m.group(1)) if m else 960

    checked = 0
    for tm in TEXT_RE.finditer(svg):
        x, y, cls, txt = int(tm.group(1)), int(tm.group(2)), tm.group(3), tm.group(4)
        if cls not in sizes:  # .title/.node — центрированные, вне панелей
            continue
        cw = sizes[cls] * CW_RATIO + EXTRA.get(cls, 0.0)
        end = x + len(txt) * cw
        checked += 1

        limit = canvas_w
        scope = "canvas"
        for a, b, c, d, name in INNER:
            if a <= x <= b and c <= y <= d:
                limit, scope = b, name
                break
        else:
            for a, b, c, d, name in PANELS:
                if a <= x <= b and c <= y <= d:
                    limit, scope = b, name
                    break
        if end > limit - 4:
            problems.append(
                f"текст выходит за [{scope}]: x={x} конец~{end:.0f} > {limit} :: {txt!r}"
            )

    print(f"SVG: {path.name} · подписей проверено: {checked}")
    if problems:
        print("НАРУШЕНИЯ:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("ГЕОМЕТРИЯ КОРРЕКТНА: все подписи внутри своих панелей")
    return 0


if __name__ == "__main__":
    sys.exit(main())
