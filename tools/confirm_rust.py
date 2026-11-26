#!/usr/bin/env python3
"""СТУПЕНЬ ДОСТИЖИМОСТИ ДЛЯ RUST: `LAW_CANDIDATE` -> доказанный краш или отказ.

ЗАЧЕМ (измерено 2026-11-26). Rust-законы (`nan-sort`, `utf8-nth`) сопоставляют ФОРМУ
и не вызывают код, поэтому в ночном отчёте они честно называются `LAW_CANDIDATE`.
Цена этой честности — 20–30 минут чтения на каждого кандидата. У C и Python такой
ступени нет: `confirm_c` и `live_replay` физически собирают и запускают код. Здесь —
то же самое для Rust.

КАК РАБОТАЕТ. Рядом с проверяемым крейтом создаётся ПРОБНЫЙ проект:

    probe/Cargo.toml   [dependencies] target = { path = "<repo>" }
    probe/src/main.rs  <сниппет, который дёргает публичный API краевым входом>

Затем `cargo build --offline` и запуск. Код возврата 101 — это паника в Rust, то есть
тот самый краш, о котором говорил детектор. Итог — три уровня, и «не знаю» не
подменяется успехом:

    RUNTIME_CONFIRMED  паника воспроизведена (rc=101) + текст паники
    SURVIVED           собралось и отработало: находка НЕ подтверждена
    NOT_REPLAYABLE     названная причина (нет Cargo.toml, сборка без сети, нужен GPU)

ПОЧЕМУ СНИППЕТ, А НЕ АВТОГЕНЕРАЦИЯ ВЫЗОВА. Сигнатура публичной функции неизвестна, и
придумывать её значило бы выдумывать тест. Детектор даёт форму, сниппет — вызов;
без сниппета честный ответ — `NOT_REPLAYABLE :: needs_probe`, а не «наверное, баг».

ЗАПУСК: python3 tools/confirm_rust.py --selftest
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CARGO = shutil.which("cargo") or ""


def _write_probe(root: Path, target: Path, name: str, snippet: str) -> Path:
    probe = root / "probe"
    (probe / "src").mkdir(parents=True, exist_ok=True)
    (probe / "Cargo.toml").write_text(
        f'[package]\nname = "kern_probe"\nversion = "0.0.0"\nedition = "2021"\n\n'
        f'[dependencies]\n{name} = {{ path = "{target.as_posix()}" }}\n\n'
        f'[[bin]]\nname = "kern_probe"\npath = "src/main.rs"\n', encoding="utf-8")
    (probe / "src" / "main.rs").write_text(snippet, encoding="utf-8")
    return probe


def confirm_rust(target: Path, crate_name: str, snippet: str, timeout: int = 300) -> tuple:
    """Собрать пробный проект и запустить. Возвращает (уровень, подробность)."""
    if not CARGO:
        return "NOT_REPLAYABLE", "cargo отсутствует"
    if not (Path(target) / "Cargo.toml").is_file():
        return "NOT_REPLAYABLE", "нет Cargo.toml: не крейт"
    if not snippet.strip():
        return "NOT_REPLAYABLE", "needs_probe: сигнатура публичной функции неизвестна"
    with tempfile.TemporaryDirectory(prefix="kern_rust_") as td:
        probe = _write_probe(Path(td), Path(target).resolve(), crate_name, snippet)
        env = dict(os.environ, CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never")
        build = subprocess.run([CARGO, "build", "--quiet"], cwd=probe, env=env,
                               capture_output=True, text=True, timeout=timeout)
        if build.returncode != 0:
            err = (build.stderr or "").strip().splitlines()
            why = err[-1][:160] if err else "build failed"
            return "NOT_REPLAYABLE", "build_failed: " + why
        run = subprocess.run([str(probe / "target" / "debug" / "kern_probe")],
                             cwd=probe, env=env, capture_output=True, text=True,
                             timeout=timeout)
        if run.returncode == 101:
            msg = (run.stderr or "").strip().splitlines()
            pan = next((ln for ln in msg if "panicked" in ln), msg[0] if msg else "")
            return "RUNTIME_CONFIRMED", "panic rc=101 :: " + pan[:180]
        if run.returncode == 0:
            return "SURVIVED", "собралось и отработало без паники (rc=0)"
        return "RUNTIME_CONFIRMED", f"abnormal exit rc={run.returncode}"



# СНИППЕТ ДЛЯ ИЗВЕСТНОЙ ФОРМЫ. Сниппет — часть отчёта: он и есть репродьюсер.
SNIPPET_NAN_SORT = """
fn main() {
    let mut v = vec![1.0_f64, f64::NAN, 0.5];
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!("{:?}", v);
}
"""


def _selftest() -> int:
    """Механизм проверяется на КРЕЙТЕ, СОЗДАННОМ ЗДЕСЬ ЖЕ: четыре случая.
    Проверять ступень подтверждения на чужом коде нельзя — там сначала нужна
    сеть, а тест обязан быть воспроизводимым без неё."""
    bad = 0

    def ok(cond, name, detail=""):
        nonlocal bad
        if not cond:
            bad += 1
            print(f"  [FAIL] {name} {detail}")

    if not CARGO:
        print("[SKIP] cargo отсутствует — ступень подтверждения проверить нечем")
        return 0
    with tempfile.TemporaryDirectory(prefix="kern_cr_") as td:
        td = Path(td)
        crate = td / "victim"
        (crate / "src").mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            '[package]\nname = "victim"\nversion = "0.1.0"\nedition = "2021"\n',
            encoding="utf-8")
        # (1) публичный API с partial_cmp().unwrap() без гарда
        (crate / "src" / "lib.rs").write_text(
            "pub fn sort_them(v: &mut Vec<f64>) {\n"
            "    v.sort_by(|a, b| a.partial_cmp(b).unwrap());\n}\n", encoding="utf-8")
        level, detail = confirm_rust(crate, "victim", """
fn main() {
    let mut v = vec![1.0_f64, f64::NAN, 0.5];
    victim::sort_them(&mut v);
}
""")
        ok(level == "RUNTIME_CONFIRMED", "nan-sort: паника воспроизведена", detail)
        print(f"  [i] nan-sort -> {level} :: {detail[:80]}")

        # (2) тот же крейт, но гард is_finite — паники быть не должно
        (crate / "src" / "lib.rs").write_text(
            "pub fn sort_them(v: &mut Vec<f64>) {\n"
            "    v.sort_by(|a, b| if a.is_finite() && b.is_finite() {\n"
            "        a.partial_cmp(b).unwrap()\n"
            "    } else { std::cmp::Ordering::Equal });\n}\n", encoding="utf-8")
        level, detail = confirm_rust(crate, "victim", """
fn main() {
    let mut v = vec![1.0_f64, f64::NAN, 0.5];
    victim::sort_them(&mut v);
    println!("survived {}", v.len());
}
""")
        ok(level == "SURVIVED", "nan-sort с гардом: НЕ подтверждается", detail)
        print(f"  [i] гард is_finite -> {level}")

        # (3) без Cargo.toml — честный отказ, а не «наверное, баг»
        level, detail = confirm_rust(td / "notacrate", "victim", "fn main(){}")
        ok(level == "NOT_REPLAYABLE" and "Cargo.toml" in detail,
           "не крейт -> NOT_REPLAYABLE с причиной", detail)

        # (4) без сниппета — тоже отказ с названной причиной
        level, detail = confirm_rust(crate, "victim", "")
        ok(level == "NOT_REPLAYABLE" and detail.startswith("needs_probe"),
           "нет сниппета -> needs_probe", detail)
    print(f"[CONFIRM-RUST-SELFTEST] точек 4 | провалов: {bad}")
    return 0 if bad == 0 else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    print("usage: confirm_rust.py --selftest")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
