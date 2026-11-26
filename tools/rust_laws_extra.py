#!/usr/bin/env python3
"""ДВА ДЕТЕКТОРА RUST, КОТОРЫХ НЕ БЫЛО В АВТОМАТИКЕ: `nan-sort` и `utf8-nth`.

ЗАЧЕМ (измерено, а не предположено). План окна №38 требовал перевести ночные
шарды на три «проверенных» класса Rust. Проверка фактом показала: `law_hunter`
покрывает `eq-hash`, `eq-ord`, `ord-non-total`, но НЕ покрывает два класса,
которые дали ВЛИТЫЕ фиксы:

    $ python3 tools/law_hunter.py --rust ~/.cache/kern/repos/fvs
    … проверено 1 .rs, находок 0          <- а `nan-sort` найден там РУКАМИ

Значит «переключить шарды на проверенные классы» без этих двух детекторов
означало бы переключить их на пустоту. Оба класса детерминированы и не требуют
решателя: это чистое сопоставление формы, зато с отсевом законных случаев.

КЛАСС 1 — `nan-sort`: `partial_cmp(...).unwrap()` над вычисленным значением в
ПУБЛИЧНОЙ функции. `NaN.partial_cmp(x)` = `None` → паника в сортировке, которую
вызывает пользователь. ЗАКОННЫЕ случаи отсеиваются: `unwrap_or(Equal)`,
`total_cmp`, явная проверка `is_nan`, и типы без NaN (`Instant`, `Duration`,
`SystemTime`) — там `partial_cmp` тотален.

КЛАСС 2 — `utf8-nth`: `chars().nth(k).unwrap()` в ПУБЛИЧНОЙ функции без проверки
длины/`starts_with`/`is_char_boundary` рядом. `nth` за пределами строки даёт
`None` → паника на входе, который API не запрещает.

ЗАПУСК:  python3 tools/rust_laws_extra.py --selftest [--rs DIR]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# `partial_cmp(...)` с `.unwrap()`/`.expect(` в той же цепочке, но НЕ `unwrap_or`.
_NAN_SORT = re.compile(
    r"partial_cmp\s*\([^)]*\)\s*\.\s*(?:unwrap\s*\(\s*\)|expect\s*\()")
_NAN_OK = re.compile(r"unwrap_or|total_cmp|is_nan|NAN|is_none|is_finite")
# ДЕФЕКТ, НАЙДЕННЫЙ ЧТЕНИЕМ (iced/core/src/gradient.rs:70): гард
# `if offset.is_finite() && (0.0..=1.0).contains(&offset)` делает
# `partial_cmp` тотальным, а детектор без `is_finite` объявлял панику — ЛОЖНО.
# Такие примеры идут в калибровку (`_FINITE`), а не в отчёт.

_NO_NAN_TYPES = re.compile(r"\b(Instant|Duration|SystemTime|SystemTimeError)\b")
# `chars().nth(k).unwrap()` / `.expect(`.
_UTF8_NTH = re.compile(
    r"chars\s*\(\s*\)\s*\.\s*nth\s*\([^)]*\)\s*\.\s*(?:unwrap\s*\(\s*\)|expect\s*\()")
_UTF8_OK = re.compile(
    r"is_char_boundary|char_indices|starts_with|ends_with|\.len\s*\(\s*\)\s*[<>]="
    r"|\.get\s*\(|\.chars\s*\(\s*\)\s*\.count|chars\.count|nth_or")
_PUB_FN = re.compile(r"\bpub(?:\([^)]*\))?\s+(?:async\s+)?fn\s+([A-Za-z_]\w*)")


def _enclosing_pub_fn(src: str, pos: int) -> str:
    """Имя ближайшей функции выше `pos`, если она публичная; иначе пусто."""
    best = ""
    for m in _PUB_FN.finditer(src, 0, pos):
        best = m.group(1)
    return best


def _window(src: str, pos: int, before: int = 4, after: int = 1) -> str:
    lines = src.splitlines(keepends=True)
    idx, acc = 0, 0
    for i, ln in enumerate(lines):
        acc += len(ln)
        if acc > pos:
            idx = i
            break
    return "".join(lines[max(0, idx - before): idx + after + 1])


def nan_sort(src: str) -> list:
    out = []
    for m in _NAN_SORT.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        fn = _enclosing_pub_fn(src, m.start())
        if not fn:
            continue                      # приватный путь — не наш отчёт
        ctx = _window(src, m.start(), before=4, after=1)
        if _NAN_OK.search(m.group(0)) or _NAN_OK.search(ctx):
            continue                      # уже защищено или unwrap_or(Equal)
        if _NO_NAN_TYPES.search(ctx):
            continue                      # Instant/Duration: NaN невозможен
        out.append({"law": "nan-sort", "line": line, "symbol": fn,
                    "detail": "partial_cmp().unwrap() над float в публичной "
                              "функции: NaN даёт None → паника в сортировке"})
    return out


def utf8_nth(src: str) -> list:
    out = []
    for m in _UTF8_NTH.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        fn = _enclosing_pub_fn(src, m.start())
        if not fn:
            continue
        ctx = _window(src, m.start(), before=5, after=0)
        if _UTF8_OK.search(ctx):
            continue                      # длина/граница проверена рядом
        out.append({"law": "utf8-nth", "line": line, "symbol": fn,
                    "detail": "chars().nth(k).unwrap() без проверки длины: "
                              "k за концом строки → паника"})
    return out




def find_all(src: str) -> list:
    return nan_sort(src) + utf8_nth(src)


# КАЛИБРОВКА: формы взяты из ЖИВЫХ файлов, а не придуманы.
_FVS_PREFIX = """
use rayon::prelude::*;
pub struct FastVectorSimilarity;
impl FastVectorSimilarity {
    pub fn compute_densities(&self, x: &[f64], y: &[f64]) -> Vec<f64> {
        let mut ranks: Vec<(usize, f64)> = vec![];
        ranks.par_sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
        ranks.iter().map(|v| v.1).collect()
    }
}
"""
_FVS_FIXED = _FVS_PREFIX.replace(".unwrap()", ".unwrap_or(std::cmp::Ordering::Equal)")
_GUARDED = _FVS_PREFIX.replace(
    "a.1.partial_cmp(&b.1).unwrap()",
    "if a.1.is_nan() { std::cmp::Ordering::Equal } else { "
    "a.1.partial_cmp(&b.1).unwrap() }")
_FINITE = """
impl Gradient {
    pub fn add_stop(mut self, offset: f32) -> Self {
        if offset.is_finite() && (0.0..=1.0).contains(&offset) {
            let idx = self.stops.binary_search_by(|s| s.offset.partial_cmp(&offset).unwrap());
            let _ = idx;
        }
        self
    }
}
"""
_INSTANT = """
pub fn oldest(times: &[(u64, Instant)]) -> Instant {
    times.iter().min_by(|a, b| a.1.partial_cmp(&b.1).unwrap()).unwrap().1
}
"""
_PRIVATE = """
fn helper(v: &[f64]) -> f64 {
    v.iter().min_by(|a, b| a.partial_cmp(b).unwrap()).copied().unwrap()
}
"""
_VGER = """
impl Tree {
    pub fn nth_char(&self, text: &str, i: usize) -> char {
        let c = text.chars().nth(i).unwrap();
        c
    }
}
"""
_VGER_FIXED = _VGER.replace("let c = text.chars().nth(i).unwrap();",
                            "if !text.starts_with(\"\") || i >= text.len() { return ' '; }\n"
                            "        let c = text.chars().nth(i).unwrap();")


def _selftest() -> int:
    """Каждый детектор — ПОЛОЖИТЕЛЬНЫЙ и ОТРИЦАТЕЛЬНЫЙ случай, иначе он
    декорация (урок #475: гейт, который не умеет отказать, ничего не сторожит)."""
    bad = 0

    def ok(cond, name):
        nonlocal bad
        if not cond:
            bad += 1
            print(f"  [FAIL] {name}")

    ok(len(nan_sort(_FVS_PREFIX)) == 1, "nan-sort: форма из fvs найдена (1)")
    ok(len(nan_sort(_FVS_FIXED)) == 0, "nan-sort: unwrap_or(Equal) — не находка")
    ok(len(nan_sort(_GUARDED)) == 0, "nan-sort: гард is_finite — не находка (iced)")
    ok(len(nan_sort(_FINITE)) == 0, "nan-sort: гард is_finite — не находка (iced)")
    ok(len(nan_sort(_INSTANT)) == 0, "nan-sort: Instant/Duration отсеян")
    ok(len(nan_sort(_PRIVATE)) == 0, "nan-sort: приватная функция не отчёт")

    ok(len(utf8_nth(_VGER)) == 1, "utf8-nth: форма из vger найдена (1)")
    ok(len(utf8_nth(_VGER_FIXED)) == 0, "utf8-nth: проверка длины рядом — не находка")
    ok(len(utf8_nth(_FVS_PREFIX)) == 0, "utf8-nth: чужой класс не срабатывает")
    print(f"[RUST-LAWS-SELFTEST] точек 9 | провалов: {bad}")
    return 0 if bad == 0 else 1


def _scan_dir(root: Path) -> None:
    skip = {"examples", "example", "tests", "test", "benches", "bench"}
    files = [p for p in root.rglob("*.rs")
             if ".git" not in p.parts and not (skip & set(p.parts))]
    total = 0
    for p in files:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for it in find_all(src):
            total += 1
            print(f"{p}:{it['line']} [{it['law']}] {it['symbol']} — {it['detail'][:70]}")
    print(f"{root}: проверено {len(files)} .rs, находок {total}")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    if "--rs" in argv:
        _scan_dir(Path(argv[argv.index("--rs") + 1]))
        return 0
    print("usage: rust_laws_extra.py --selftest | --rs DIR")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
