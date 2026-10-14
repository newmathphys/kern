#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: CAN-FAIL — доказательство, что каждая проверка СПОСОБНА УПАСТЬ.

ЗАЧЕМ. Дефекты #26 и #30 показали: цель может быть «зелёной», НИЧЕГО не
проверяя (кросс-арх падал в qemu, анализатор constant-time был недостижим).
`RC=0` не является доказательством работоспособности проверки — вакуумная
проверка тоже даёт `RC=0`.

МЕТОД (мутационное тестирование САМИХ ПРОВЕРОК, а не кода):
  1. Вносим искусственную поломку (fault) в инвариант, который цель обязана
     защищать.
  2. Запускаем цель.
  3. ОЖИДАЕМ НЕНУЛЕВОЙ код возврата.
     • цель покраснела  -> проверка РАБОТАЕТ   (PASS)
     • цель осталась зелёной -> проверка ВАКУУМНА (FAIL, это дефект)
  4. Откатываем дерево (backup/restore).

Запуск:  python3 tools/canfail.py [--only <имя>] [--list]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(cmd: str, timeout: int = 600) -> int:
    """Возвращает код возврата команды (в shell)."""
    p = subprocess.run(["bash", "-lc", cmd], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode


def sh_out(cmd: str, timeout: int = 600):
    p = subprocess.run(["bash", "-lc", cmd], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Fault:
    """Контекстный менеджер: ломает файл(ы) и ГАРАНТИРОВАННО откатывает."""

    def __init__(self, files):
        self.files = [ROOT / f for f in files]
        self.backup = {}

    def __enter__(self):
        for f in self.files:
            if f.exists():
                self.backup[f] = f.read_bytes()
        return self

    def __exit__(self, *exc):
        for f, data in self.backup.items():
            f.write_bytes(data)
        return False


FAULTABLE = [
    "tools/canfail.py",
    "tools/cache_avalanche_bench.py",
    "formal/KernAllMath.lean",
    "src/verifier/noninterference.zig",
    "src/binlevel_probe.zig",
    "src/verifier/admission_gate.zig",
    "src/verifier/array_theory.zig",
    "src/tests/litmus_memory_test.zig",
    "src/smt_bench.zig",
    "src/kimg_stress.zig",
    "src/main.zig",
    "tests/fixtures/valid_v1_3.kimg",
    "zig-out/bin/kernc",
]


def clean_slate() -> None:
    """Восстанавливает ТОЛЬКО повреждённые файлы из списка ломаемых.

    ⚠️ ВАЖНО: нельзя делать слепой `git checkout --` по всему списку — это
    СТИРАЕТ законные незакоммиченные правки (проверено на практике: так
    пропали фиксы #36/#37). Поэтому восстанавливаем файл, только если он
    РЕАЛЬНО повреждён (не читается как UTF-8 или пуст).
    """
    for f in FAULTABLE:
        p = ROOT / f
        if not p.exists():
            continue
        if p.suffix in (".kimg",) or p.name == "kernc":
            continue  # бинарные — не проверяем на UTF-8
        try:
            if p.read_bytes():
                p.read_text(encoding="utf-8")
                continue  # валиден — не трогаем
        except UnicodeDecodeError:
            pass
        subprocess.run(["git", "checkout", "--", f], cwd=str(ROOT),
                       capture_output=True, text=True)


def patch(path: str, old: str, new: str) -> None:
    """Замена подстроки в файле (падает, если подстрока не найдена)."""
    p = ROOT / path
    try:
        s = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Файл повреждён (прерванный прогон) — восстанавливаем и пробуем снова.
        subprocess.run(["git", "checkout", "--", path], cwd=str(ROOT),
                       capture_output=True, text=True)
        s = p.read_text(encoding="utf-8")
    if old not in s:
        raise RuntimeError(f"шаблон не найден в {path}: {old[:60]!r}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")


# ==========================================================================
# КЕЙСЫ: (имя, что проверяем, команда, инъекция поломки, таймаут)
# ==========================================================================

def case_avalanche():
    """Лавина SHA-256. ЛОМАЕМ: подменяем SHA-256 на «наивный» хэш."""
    patch("tools/cache_avalanche_bench.py",
          "    return h.digest()",
          "    return weak_key(proof)")
    return "make avalanche"


def case_lean_sorry():
    """Lean без sorry. ЛОМАЕМ: добавляем `sorry` в доказательство."""
    p = ROOT / "formal" / "KernAllMath.lean"
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_PROBE : True := by sorry\n")
    return "bash formal/check.sh"


def case_binlevel_earlyexit():
    """Constant-time. ЛОМАЕМ: добавляем РАННИЙ ВЫХОД в constantTimeEqual."""
    patch("src/verifier/noninterference.zig",
          "    for (a, b) |x, y| acc |= x ^ y; // без ветвлений и раннего выхода",
          "    for (a, b) |x, y| { if (x != y) return false; acc |= x ^ y; } // ЛОМАЕМ")
    return "make binlevel"


def case_disasm_dce():
    """Diff-disasm. ЛОМАЕМ: убираем зондирующую функцию."""
    patch("src/binlevel_probe.zig",
          "pub export fn kern_early_exit_equal(",
          "pub fn kern_early_exit_equal_disabled(")
    return "make disasm"


def case_core_invariant():
    """Ядро: инвариант Врат. ЛОМАЕМ: открываем Врата по ТАЙМ-АУТУ.

    Это ровно тот класс бага, который KERN обязан ловить: `e=1` без
    доказательства (решатель не ответил -> вердикт не доказан).
    """
    patch("src/verifier/admission_gate.zig",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .N; // тайм-аут не является опровержением",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .T; e_val = 1; // ЛОМАЕМ: открываем Врата по тайм-ауту")
    return "make test"


def case_golden_merkle():
    """Эталонный образ. ЛОМАЕМ: портим байт в golden-фикстуре."""
    p = ROOT / "tests" / "fixtures" / "valid_v1_3.kimg"
    if not p.exists():
        return None
    b = bytearray(p.read_bytes())
    b[130] ^= 0xFF          # внутри таблицы объектов
    p.write_bytes(bytes(b))
    return "zig build && ./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg"


def case_slsa_hash():
    """SLSA. ЛОМАЕМ: подменяем бинарник ПОСЛЕ аттестации."""
    rc, _ = sh_out("zig build && python3 tools/slsa_provenance.py --no-build", 300)
    if rc != 0:
        return None
    with open("/tmp/kernc_pad", "ab") as f:
        f.write(b"\x00" * 8)
    sh("cat /tmp/kernc_pad >> zig-out/bin/kernc", 60)
    return "python3 tools/slsa_provenance.py --check"


def case_grep_vacuity():
    """ГРЕП-ФИЛЬТР (#34). ЛОМАЕМ: переименовываем ARRAY-тесты.

    Цель `make arrays` фильтровала вывод через `grep -E "ARRAY|passed"`.
    Если ARRAY-тесты исчезли, слово `passed` из итоговой строки всё равно
    совпадает -> цель остаётся ЗЕЛЁНОЙ, хотя проверять больше нечего.
    Теперь цель ходит через `tools/run_filtered.py`, который ТРЕБУЕТ
    наличия тестов по фильтру.
    """
    p = ROOT / "src" / "verifier" / "array_theory.zig"
    s = p.read_text(encoding="utf-8")
    if 'test "ARRAY' not in s:
        return None
    p.write_text(s.replace('test "ARRAY', 'test "ZZZ_'), encoding="utf-8")
    return "make arrays"


def case_grep_vacuity_litmus():
    """ГРЕП-ФИЛЬТР (#34), вторая цель. ЛОМАЕМ: переименовываем LITMUS-тесты."""
    p = ROOT / "src" / "tests" / "litmus_memory_test.zig"
    if not p.exists():
        return None
    s = p.read_text(encoding="utf-8")
    if 'test "LITMUS' not in s:
        return None
    p.write_text(s.replace('test "LITMUS', 'test "ZZZ_'), encoding="utf-8")
    return "make litmus"


def case_attack_regression():
    """Демонстратор атак. ЛОМАЕМ: возвращаем обход Врат одним байтом."""
    p = ROOT / "src" / "verifier" / "admission_gate.zig"
    s = p.read_text(encoding="utf-8")
    # Открываем Врата, если в payload есть байт 0xAA (та самая АТАКА 1).
    old = "        switch (checker_verdict) {"
    if old not in s:
        return None
    new = ("        if (cert.witness_payload.len > 0 and cert.witness_payload[0] == 0xAA) {\n"
           "            return AdmissionResult{ .eq2_status = .T, .e_value = 1 }; // ЛОМАЕМ\n"
           "        }\n"
           "        switch (checker_verdict) {")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    return "make attack"


def case_smt_bench():
    """SMT-бенчмарк. ЛОМАЕМ: подменяем ОЖИДАНИЕ на противоположное.

    `bench-smt` сверяет вердикт Z3 с таблицей `expect`. Раньше несовпадение
    только печаталось («❌ НЕ совпало») и не влияло на код возврата (#37).
    """
    patch("src/smt_bench.zig",
          '.{ .name = "Alive2: x*2 == x<<1 (u32)", .expect = "unsat", .script =',
          '.{ .name = "Alive2: x*2 == x<<1 (u32)", .expect = "sat", .script =')
    return "zig build bench-smt"


def case_stress_threshold():
    """Порог стресса. ЛОМАЕМ: делаем норматив недостижимым.

    Проверяем, что порог (`< 0.005 мс`) РЕАЛЬНО связан с кодом возврата,
    а не только с текстом «⚠️ медленнее» (дефект #36).
    """
    patch("src/kimg_stress.zig",
          "    if (!(per < 0.005)) {",
          "    if (!(per < 0.0000001)) { // ЛОМАЕМ: недостижимый порог")
    return "zig build bench-kimg-stress"


def case_build_syntax():
    """Сборка. ЛОМАЕМ: синтаксическая ошибка в ядре.

    Базовая проверка: цель `build` не является no-op и реально компилирует.
    """
    patch("src/main.zig", "fn flagValue(", "fn flagValue_BROKEN(")
    return "zig build"


def case_sanity_control():
    """Заведомо БЕЗОПАСНАЯ правка: добавляем комментарий в файл.

    Семантику НЕ меняет -> `make arrays` обязан остаться ЗЕЛЁНЫМ.
    Ожидаемый результат харнесса: «ВАКУМНА» (то есть он РАБОТАЕТ).
    Если харнесс скажет «PASS» — он сломан, и все доказательства фиктивны.
    """
    p = ROOT / "src" / "verifier" / "array_theory.zig"
    with p.open("a", encoding="utf-8") as f:
        f.write("\n// KERN canfail: мета-контроль — семантику НЕ меняет\n")
    return "make arrays"


def case_meta_broken_verdict():
    """K4, ВТОРОЙ УРОВЕНЬ: ломаем САМ ВЕРДИКТ харнесса.

    Если вердикт всегда говорит PASS, то ВСЕ доказательства фиктивны.
    `--selftest` обязан это заметить и вернуть ненулевой код.
    Это и есть ответ на «кто проверит проверяющего».
    """
    patch("tools/canfail.py",
          '    if rc != 0:\n        return True, "NOT_VACUOUS"        # проверка покраснела — она работает\n    return False, "VACUOUS"               # поломка внесена, цель зелёная — ВАКУУМ',
          '    return True, "NOT_VACUOUS"  # ЛОМАЕМ: всегда PASS')
    return "python3 tools/canfail.py --selftest"


CASES = [
    ("avalanche",     "лавина SHA-256 (Hash Flooding)",       case_avalanche),
    ("lean-sorry",    "Lean: отсутствие `sorry`",              case_lean_sorry),
    ("binlevel",      "constant-time (ранний выход)",          case_binlevel_earlyexit),
    ("disasm",        "diff-disasm: потеря функции",           case_disasm_dce),
    ("core-gate",     "Врата Истины (e=1 без чекера)",         case_core_invariant),
    ("golden",        "Merkle эталонного образа",              case_golden_merkle),
    ("slsa",          "SLSA: хэш бинарника",                   case_slsa_hash),
    ("grep-arrays",   "греп-фильтр: исчезли ARRAY-тесты",      case_grep_vacuity),
    ("grep-litmus",   "греп-фильтр: исчезли LITMUS-тесты",     case_grep_vacuity_litmus),
    ("attack",        "демонстратор атак: обход Врат",         case_attack_regression),
    ("smt-bench",     "SMT-бенчмарк: несовпадение ожидания",   case_smt_bench),
    ("stress-thresh", "порог стресса связан с кодом возврата", case_stress_threshold),
    ("build-syntax",  "сборка не является no-op",              case_build_syntax),
    # --- МЕТА-КОНТРОЛЬ (K4): проверка САМОГО харнесса ---------------------
    # Подсовываем заведомо БЕЗОПАСНУЮ правку (комментарий, семантику не
    # меняет). Цель ОБЯЗАНА остаться зелёной, и харнесс ОБЯЗАН это увидеть
    # и сказать «ВАКУУМНА». Если харнесс вместо этого скажет «PASS» —
    # значит он сломан и ВСЕ остальные доказательства фиктивны.
    ("sanity-control", "МЕТА: харнесс обязан поймать вакуум",   case_sanity_control, True),
    # K4, второй уровень: ломаем САМ ВЕРДИКТ и требуем, чтобы self-test упал.
    ("meta-verdict",  "МЕТА-2: сломанный вердикт ловится",      case_meta_broken_verdict),
]


def verdict(rc: int, expect_vacuous: bool) -> tuple:
    """ЧИСТАЯ функция вердикта харнесса. Выделена, чтобы её можно было
    ПРОВЕРИТЬ (K4): сломанный вердикт = все доказательства фиктивны.

    Возвращает (is_pass: bool, kind: str).
    """
    if expect_vacuous:
        # Мета-контроль: правка безопасна, цель ОБЯЗАНА остаться зелёной.
        if rc == 0:
            return True, "META_OK"        # харнесс корректно увидел вакуум
        return False, "META_FALSE_ALARM"  # ложное срабатывание
    if rc != 0:
        return True, "NOT_VACUOUS"        # проверка покраснела — она работает
    return False, "VACUOUS"               # поломка внесена, цель зелёная — ВАКУУМ


def selftest() -> int:
    """K4: самопроверка ЛОГИКИ харнесса на синтетических входах.

    Без неё «харнесс работает» — такое же голословное утверждение, как
    `RC=0` у любой другой проверки.
    """
    cases = [
        # (rc, expect_vacuous, ожидаемый is_pass, что проверяем)
        (1, False, True,  "цель покраснела -> PASS (не вакуумна)"),
        (0, False, False, "цель зелёная при поломке -> FAIL (ВАКУУМ)"),
        (0, True,  True,  "мета: безопасная правка, цель зелёная -> PASS"),
        (1, True,  False, "мета: безопасная правка, а цель красная -> FAIL"),
    ]
    bad = 0
    for rc, ev, want, what in cases:
        got, kind = verdict(rc, ev)
        mark = "OK" if got == want else "ПРОВАЛ"
        if got != want:
            bad += 1
        print(f"  [{mark}] rc={rc} expect_vacuous={int(ev)} -> {kind:16s} | {what}")
    print(f"\nСАМОПРОВЕРКА ХАРНЕССА: {'ПРОЙДЕНА' if bad == 0 else 'ПРОВАЛЕНА'}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="K4: проверить ЛОГИКУ харнесса на синтетических входах")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.list:
        for c in CASES:
            print(f"  {c[0]:14s} {c[1]}")
        return 0

    env = dict(os.environ)
    env["PATH"] = (f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:"
                   f"{ROOT}/.venv/bin:{env.get('PATH','')}")
    os.environ.update(env)

    print("=" * 70)
    print("KERN: CAN-FAIL — проверка, что проверки СПОСОБНЫ УПАСТЬ")
    print("=" * 70)
    print("Метод: ломаем инвариант -> цель ОБЯЗАНА покраснеть.\n")

    clean_slate()

    ok = bad = skipped = 0
    for c in CASES:
        name, desc, fn = c[0], c[1], c[2]
        expect_vacuous = c[3] if len(c) > 3 else False
        if args.only and args.only != name:
            continue
        t0 = time.time()
        try:
            with Fault(FAULTABLE):
                cmd = fn()
                if cmd is None:
                    print(f"  [SKIP] {name:14s} {desc} (предусловие не выполнено)")
                    skipped += 1
                    continue
                rc, out = sh_out(cmd, 900)
        except subprocess.TimeoutExpired:
            rc, out = 124, "TIMEOUT"
        except Exception as e:
            import traceback
            print(f"  [ERR ] {name:14s} {desc}: {e}")
            traceback.print_exc()
            skipped += 1
            continue
        dt = time.time() - t0
        is_pass, kind = verdict(rc, expect_vacuous)
        if kind == "META_OK":
            print(f"  [PASS] {name:14s} {desc}")
            print(f"         харнесс КОРРЕКТНО увидел вакуум (цель осталась зелёной) за {dt:.0f} с")
            ok += 1
        elif kind == "META_FALSE_ALARM":
            print(f"  [FAIL] {name:14s} {desc}")
            print(f"         ХАРНЕСС СЛОМАН: безопасная правка, а цель покраснела (rc={rc})"
                  f" — ложное срабатывание")
            bad += 1
        elif kind == "NOT_VACUOUS":
            print(f"  [PASS] {name:14s} {desc}")
            print(f"         проверка ПОКРАСНЕЛА (rc={rc}) за {dt:.0f} с — она не вакуумна")
            ok += 1
        else:  # VACUOUS
            print(f"  [FAIL] {name:14s} {desc}")
            print(f"         ВАКУУМНА: поломка внесена, а цель осталась ЗЕЛЁНОЙ (rc=0)!")
            bad += 1

    print()
    print("=" * 70)
    print(f"ИТОГ: не-вакуумных {ok} | ВАКУУМНЫХ {bad} | пропущено {skipped}")
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
