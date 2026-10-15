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
    "src/capi.zig",
    "src/verifier/noninterference.zig",
    "src/binlevel_probe.zig",
    "src/verifier/admission_gate.zig",
    "src/verifier/array_theory.zig",
    "src/tests/litmus_memory_test.zig",
    "src/smt_bench.zig",
    "src/smt_stress.zig",
    "src/chc_bench.zig",
    "src/semantic_probe.zig",
    "bench/portable_merkle.zig",
    "src/kimg_stress.zig",
    "src/main.zig",
    "src/verifier/chc.zig",
    "src/verifier/dtmc.zig",
    "src/verifier/cegis.zig",
    "src/verifier/nra_quant.zig",
    "src/verifier/z3_bridge.zig",
    "src/verifier/redos.zig",
    "src/verifier/abstract_interp.zig",
    "src/concolic.zig",
    "src/attest.zig",
    "src/verifier/unsat_core.zig",
    "src/verifier/proof_check.zig",
    "tools/proof_checker.py",
    "src/verifier/string_theory.zig",
    "src/tests/alignment_stress.zig",
    "src/core/kernfs_router.zig",
    "src/core/kimg_reader.zig",
    "Makefile",
    "formal/KernSemanticGap.lean",
    "formal/certification/TRACEABILITY_MATRIX.md",
    "src/core/sigbus_guard.zig",
    "src/cov.zig",
    "src/next/truth.zig",
    "src/next/parser.zig",
    "tools/deal_contracts.py",
    "tools/os_signal_flood.py",
    "src/core/eq2.zig",
    "src/core/kimg_writer.zig",
    "tools/mutate_zig.py",
    "src/kern_bench.zig",
    "src/perf_bench.zig",
    "src/stress_real.zig",
    "tests/stress_1m.zig",
    "tests/fixtures/valid_v1_3.kimg",
    "zig-out/bin/kernc",
]


def clean_slate() -> None:
    """Восстанавливает файлы из списка ломаемых, ЕСЛИ они отличаются от git.

    ⚠️ ВАЖНО (дефект #48): раньше восстанавливались только файлы, «повреждённые»
    по признаку «не читается как UTF-8 или пуст». Этого НЕ хватило: если
    харнесс ПРЕРВАТЬ (`pkill`) между правкой и откатом, файл остаётся
    синтаксически ВАЛИДНЫМ, но изменённым — и правка уходит в коммит.
    Именно так в коммит f418c87 попала строка
    `theorem CANFAIL_PROBE : True := by sorry` в `formal/KernAllMath.lean`,
    что ломало заявление «0 sorry».

    ⚠️ И почему нельзя просто `git checkout --` по всему списку: это СТИРАЕТ
    законные незакоммиченные правки (проверено: так пропали фиксы #36/#37).

    РЕШЕНИЕ: восстанавливаем файл, только если он ОТЛИЧАЕТСЯ от версии в
    индексе git (`git diff --quiet`). Незакоммиченные правки разработчика
    тоже отличаются — поэтому такой файл мы НЕ трогаем, а ПРЕДУПРЕЖДАЕМ:
    перед запуском харнесса дерево должно быть чистым.
    """
    dirty = []
    for f in FAULTABLE:
        p = ROOT / f
        if not p.exists():
            # удалён — восстановим (дефект #46)
            subprocess.run(["git", "checkout", "--", f], cwd=str(ROOT),
                           capture_output=True)
            continue
        if p.suffix in (".kimg",) or p.name == "kernc":
            continue  # бинарные — не сравниваем текстом
        r = subprocess.run(["git", "diff", "--quiet", "--", f], cwd=str(ROOT),
                           capture_output=True)
        if r.returncode != 0:
            dirty.append(f)

    if dirty:
        print("[!] ВНИМАНИЕ: файлы из FAULTABLE отличаются от git (незакоммиченные правки):")
        for f in dirty[:10]:
            print(f"      {f}")
        print("    Харнесс НЕ трогает их (чтобы не стереть вашу работу), но после")
        print("    прогона они могут остаться изменёнными. Рекомендация:")
        print("      git add -A && git commit   # зафиксируйте правки ДО прогона")
        print("    Иначе `git add -A` после харнесса может закоммитить диверсию (#48).")


def snapshot_faultable() -> dict:
    """SHA-256 «ломаемых» файлов на момент старта."""
    import hashlib
    out = {}
    for f in FAULTABLE:
        p = ROOT / f
        if p.exists():
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def restore_missing() -> list:
    """Восстанавливает файлы, которые кейс УДАЛИЛ (а не испортил).

    ⚠️ ЗАЧЕМ (ДЕФЕКТ #46, найден на практике): кейс `cert` делал
    `unlink()` для `formal/certification/TRACEABILITY_MATRIX.md`.
    `verify_restored()` проверял только СУЩЕСТВУЮЩИЕ файлы, поэтому
    удаление не заметил — и оно попало в КОММИТ `92bf484` (тот же класс,
    что дефект #38). Теперь отсутствие файла из FAULTABLE — это ОШИБКА,
    и файл немедленно восстанавливается из git.
    """
    missing = []
    for f in FAULTABLE:
        p = ROOT / f
        if not p.exists():
            missing.append(f)
            subprocess.run(["git", "checkout", "--", f], cwd=str(ROOT),
                           capture_output=True)
    return missing


def verify_restored(snap: dict) -> list:
    """Проверяет, что после прогона НИ ОДИН исходник не остался испорченным.

    ⚠️ ЗАЧЕМ (найдено на практике, КРИТИЧНО): файл, которого НЕТ в FAULTABLE,
    не откатывается. Так `z3_bridge.zig` остался с диверсией кейса
    `pool-limit` — и она попала в КОММИТ (8c1e540). Этот контроль ловит
    такой класс ошибок: харнесс не должен оставлять следов в дереве.

    ДЕФЕКТ #46: проверялись только существующие файлы, поэтому УДАЛЕНИЕ
    (`unlink()`) не замечалось. Теперь отсутствие — тоже ошибка.
    """
    import hashlib
    bad = list(restore_missing())
    for f, h in snap.items():
        p = ROOT / f
        cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if cur != h:
            bad.append(f)
    return bad


def patch(path: str, old: str, new: str) -> None:
    """Замена подстроки в файле (падает, если подстрока не найдена).

    ⚠️ ПРЕДОХРАНИТЕЛЬ (найден на практике): если файла НЕТ в FAULTABLE,
    его правка НЕ будет откачена и останется в дереве. Именно так
    `z3_bridge.zig` остался испорченным после кейса `pool-limit`.
    """
    if path not in FAULTABLE:
        raise RuntimeError(
            f"{path} отсутствует в FAULTABLE — правка НЕ будет откачена! "
            f"Добавьте файл в FAULTABLE.")
    p = ROOT / path
    # Ретрай: возможна ГОНКА — файл читается, пока его пишет предыдущая
    # операция отката (найдено на практике: транзиентный UnicodeDecodeError
    # в кейсе pool-limit при полном прогоне).
    s = None
    for attempt in range(5):
        try:
            s = p.read_text(encoding="utf-8")
            break
        except UnicodeDecodeError:
            if attempt == 0:
                # Первая попытка: файл мог быть повреждён прерванным прогоном.
                subprocess.run(["git", "checkout", "--", path], cwd=str(ROOT),
                               capture_output=True, text=True)
            time.sleep(0.2)
    if s is None:
        raise RuntimeError(f"не удалось прочитать {path} как UTF-8 после 5 попыток")
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


def case_torture_payload():
    """Пытки. ЛОМАЕМ: отключаем сверку SHA-256(payload) с digest дескриптора.

    ЭТО НАБЛЮДАЕМЫЙ пробой: подменённый байт содержимого начнёт отдаваться
    читателю. Если `make torture` НЕ покраснеет — значит набор атак не способен
    поймать реальную подмену данных (дефект #14), то есть бесполезен.

    ПОЧЕМУ НЕ ОБХОД ПУТЕЙ: KERNFS — in-memory ФС, она ФИЗИЧЕСКИ не может отдать
    хостовый файл, поэтому утверждение «нет root:x» истинно всегда и такой кейс
    был бы вакуумным. Найдено первым прогоном can-fail (кейс признан вакуумным).
    """
    patch("src/core/kernfs_router.zig",
          "        if (!std.mem.eql(u8, &got, &obj.digest)) return KernFsError.PayloadTampered;",
          "        if (false and !std.mem.eql(u8, &got, &obj.digest)) return KernFsError.PayloadTampered; // ЛОМАЕМ")
    return "make torture"


def case_evidence_propagates():
    """Свидетельства. ЛОМАЕМ: добавляем `sorry` в Lean.

    Коллектор свидетельств ОБЯЗАН пробросить провал подпроверки наружу (RC!=0),
    а не «проглотить» его и записать зелёный лог. Иначе весь `docs/evidence/`
    превращается в декорацию.
    """
    p = ROOT / "formal" / "KernAllMath.lean"
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_PROBE : True := by sorry\n")
    return "make evidence-fast"


def case_telemetry_detects():
    """Телеметрия. ЛОМАЕМ: тот же `sorry` в Lean.

    Стенд обязан НЕ начислить балл за проверку Lean (иначе итог 100/100 —
    фикция). Проверяем на быстром режиме (та же логика начисления).
    """
    p = ROOT / "formal" / "KernAllMath.lean"
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_PROBE : True by sorry\n".replace("True", "True := by"))
    return "make telemetry-quick"



def case_guardrail_refuted_as_proved():
    """Guardrail. ЛОМАЕМ: C-ABI объявляет ОПРОВЕРГНУТЫЙ контракт доказанным.

    Если `make guardrail` не покраснеет, значит прокси не различает вердикты
    и пропускает галлюцинации — то есть он бесполезен как фильтр.
    """
    patch("src/capi.zig",
          "        .Sat => KERN_REFUTED,",
          "        .Sat => KERN_PROVED, // ЛОМАЕМ: контрпример объявлен доказательством")
    return "make guardrail"


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


def case_chc_theory():
    """CHC/Horn. ЛОМАЕМ: всегда сообщаем «баг найден» (Sat)."""
    patch("src/verifier/chc.zig",
          "        return bridge.executeQuery(q).status;\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ",
          "        _ = bridge.executeQuery(q);\n        return .Sat; // ЛОМАЕМ: всегда «баг найден»\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ")
    return "make chc"


def case_dtmc_theory():
    """DTMC. ЛОМАЕМ: стохастичность всегда ложна."""
    patch("src/verifier/dtmc.zig",
          "            if (@abs(s - 1.0) > 1e-9) return false;\n        }\n        return true;",
          "            if (@abs(s - 1.0) > 1e-9) return false;\n        }\n        return false; // ЛОМАЕМ: всегда не стохастична")
    return "make dtmc"


def case_cegis_theory():
    """CEGIS-синтез. ЛОМАЕМ: перебираем только k=0 вместо 0..31."""
    patch("src/verifier/cegis.zig",
          "        var k: usize = 0;\n        while (k < 32) : (k += 1) {",
          "        var k: usize = 0;\n        while (k < 1) : (k += 1) { // ЛОМАЕМ: только k=0")
    return "make cegis"


def case_nra_theory():
    """NRA. ЛОМАЕМ: объявляем ЛИНЕЙНУЮ логику вместо нелинейной."""
    patch("src/verifier/nra_quant.zig",
          "            \\\\(set-logic QF_NRA)",
          "            \\\\(set-logic QF_LIA) // ЛОМАЕМ: нелинейность не поддержана")
    return "make nra"


def case_align_invariant():
    """Эшелон 1 (выравнивание). ЛОМАЕМ: isStrictlyAligned всегда истинна."""
    patch("src/tests/alignment_stress.zig",
          "pub fn isStrictlyAligned(h: kimg.KimgHeader) bool {\n    return h.object_table_offset % 8 == 0 and h.data_payload_offset % 8 == 0;\n}",
          "pub fn isStrictlyAligned(h: kimg.KimgHeader) bool {\n    _ = h;\n    return true; // ЛОМАЕМ: всегда «выровнено»\n}")
    return "make align"


def case_pool_limit():
    """Эшелон 3 (пул). ЛОМАЕМ: acquire НЕ ждёт слот (лимит не соблюдается)."""
    patch("src/verifier/z3_bridge.zig",
          "    pub fn acquire(self: *SolverPool) void {\n        self.sem.waitUncancelable(compat.io());",
          "    pub fn acquire(self: *SolverPool) void {\n        // ЛОМАЕМ: слот не занимается, лимит не соблюдается")
    return "make pool"


def case_strings_theory():
    """Строковая теория. ЛОМАЕМ: подменяем needle на константу."""
    patch("src/verifier/string_theory.zig",
          'const c = try std.fmt.allocPrint(self.allocator, "(str.contains p \\"{s}\\")", .{needle});',
          'const c = try std.fmt.allocPrint(self.allocator, "(str.contains p \\"ZZZ\\")", .{needle}); // ЛОМАЕМ')
    return "make strings"


def case_noninterference_taint():
    """Невлияние (тайнтинг). ЛОМАЕМ: утечка НЕ регистрируется.

    ⚠️ Первая попытка била в `constantTimeEqual` — и цель осталась ЗЕЛЁНОЙ
    (это честный результат: тесты NONINTERFERENCE проверяют АНАЛИЗАТОР
    тайнтов, а не саму функцию сравнения). Правильная мишень — `analyze`.
    """
    patch("src/verifier/noninterference.zig",
          "            .branch_on => |v| if (tainted.contains(v)) {\n                try out.append(.{ .leak = .branch, .at = i });\n            },",
          "            .branch_on => |v| if (tainted.contains(v)) {\n                // ЛОМАЕМ: утечка не регистрируется\n            },")
    return "make noninterference"


def case_perf_threshold():
    """K2: пороги производительности. ЛОМАЕМ: замедляем безопасное чтение.

    Добавляем занятой цикл в горячий путь `payloadSlice` — пропускная
    способность безопасного чтения падает ниже порога 100 МБ/с,
    и цель ОБЯЗАНА покраснеть.
    """
    patch("src/core/kernfs_router.zig",
          "        const sl = self.payload_region[@intCast(obj.payload_offset)..@intCast(end)];",
          "        var spin: u64 = 0;\n        while (spin < 50_000) : (spin += 1) {\n            asm volatile (\"\" : : \"r\" (spin)); // ЛОМАЕМ: замедление\n        }\n        const sl = self.payload_region[@intCast(obj.payload_offset)..@intCast(end)];")
    return "zig build bench-perf"


def case_gate_invariant_stress():
    """K2: инвариант «СТРОГО 0» в стрессах. ЛОМАЕМ: Врата открываются без
    доказательства (по тайм-ауту)."""
    patch("src/verifier/admission_gate.zig",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .N; // тайм-аут не является опровержением",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .T; e_val = 1; // ЛОМАЕМ")
    return "zig build bench-kern"


def case_redos_vuln():
    """ReDoS. ЛОМАЕМ: вложенный квантор не распознаётся."""
    patch("src/verifier/redos.zig",
          "        .star, .plus, .opt => {\n            const c = inner(n);\n            if (isQuantified(c)) return true;",
          "        .star, .plus, .opt => {\n            const c = inner(n);\n            if (isQuantified(c)) return false; // ЛОМАЕМ: не распознаём")
    return "make redos"


def case_concolic_victim():
    """Конколика. ЛОМАЕМ: подменяем «магическую» строку."""
    patch("src/concolic.zig",
          '    const magic = "KERN";',
          '    const magic = "ZZZZ"; // ЛОМАЕМ: не та цель')
    return "make concolic"


def case_absint_inv():
    """Абстрактная интерпретация. ЛОМАЕМ: состояние ВЫХОДА цикла.

    ⚠️ Первая попытка подменяла `init` на 0 — и была СЕМАНТИЧЕСКИ
    НЕЙТРАЛЬНОЙ: тесты вызывают `analyzeLinearLoop(0, 1, 10)`, где init и так
    0. Цель осталась зелёной (честный результат). Правильная мишень —
    вычисление `exit_state`: убираем прибавление шага.
    """
    patch("src/verifier/abstract_interp.zig",
          "    const exit_state = inv.restrictLt(bound).addConst(step).restrictGe(bound);",
          "    const exit_state = inv.restrictLt(bound).addConst(0).restrictGe(bound); // ЛОМАЕМ")
    return "make absint"


def case_attest_sign():
    """Аттестация. ЛОМАЕМ: подпись НЕ проверяется (всегда «валидна»)."""
    patch("src/attest.zig",
          "    const sig = Ed25519.Signature.fromBytes(cert.signature);\n    sig.verify(&payload(cert.contract_digest, cert.merkle_root, cert.verdict), pk) catch return false;\n    return true;",
          "    _ = pk;\n    return true; // ЛОМАЕМ: подпись не проверяется")
    return "make attest"


def case_localize_core():
    """UNSAT-core. ЛОМАЕМ: конфликт не распознаётся."""
    patch("src/verifier/unsat_core.zig",
          '        if (std.mem.startsWith(u8, stdout, "unsat")) {\n            is_conflict = true;',
          '        if (std.mem.startsWith(u8, stdout, "unsat")) {\n            is_conflict = false; // ЛОМАЕМ: конфликт не распознан')
    return "make localize"


def case_sim_invariant():
    """Симуляция (I2: целый образ читается). ЛОМАЕМ: чтение отдаёт НЕ тот срез.

    ⚠️ Урок: одиночная подмена среза НЕ ломает инвариант — её ловит
    проверка целостности (`PayloadTampered`), и sim корректно считает это
    ошибкой чтения, а не ложным допуском. Чтобы нарушить I2, нужно
    ОДНОВРЕМЕННО отключить проверку целостности И подменить срез.
    """
    patch("src/core/kernfs_router.zig",
          "        var got: [32]u8 = undefined;\n        std.crypto.hash.sha2.Sha256.hash(sl, &got, .{});\n        if (!std.mem.eql(u8, &got, &obj.digest)) return KernFsError.PayloadTampered;",
          "        // ЛОМАЕМ: проверка целостности отключена")
    patch("src/core/kernfs_router.zig",
          "        const sl = self.payload_region[@intCast(obj.payload_offset)..@intCast(end)];",
          "        const sl = self.payload_region[0..@min(@as(usize, @intCast(end)), self.payload_region.len)]; // ЛОМАЕМ: не тот срез")
    return "zig build sim-seeds"


def case_proof_check():
    """Независимый proof-checker (Python). ЛОМАЕМ: баланс скобок всегда «ок».

    ⚠️ `make proof-check` запускает `tools/proof_checker.py` — независимый
    чекер на Python, а НЕ Zig-тесты. Первая попытка правила
    `src/verifier/proof_check.zig` и вообще не влияла на цель.
    """
    patch("tools/proof_checker.py",
          "def balanced(s: str) -> bool:",
          "def balanced(s: str) -> bool:\n    return False  # ЛОМАЕМ: баланс всегда «нарушен»\n\n\ndef balanced_orig(s: str) -> bool:")
    return "make proof-check"


def case_verify_cli():
    """CLI `verify`. ЛОМАЕМ: Merkle-корень всегда «не совпал».

    Тогда `kernc check-integrity` на ВАЛИДНОМ образе вернёт ошибку ->
    цель `make verify` обязана покраснеть.
    """
    patch("src/core/kimg_reader.zig",
          "        if (!std.mem.eql(u8, &root, &h.root_digest)) {\n            cov.hit(.merkle_mismatch);\n            return KimgError.MerkleRootMismatch;\n        }\n        cov.hit(.merkle_ok);",
          "        cov.hit(.merkle_mismatch);\n        return KimgError.MerkleRootMismatch; // ЛОМАЕМ: всегда несовпадение")
    return "make verify"


def case_prove_cli():
    """CLI `prove`. ЛОМАЕМ: SMT-мост всегда сообщает ToolError."""
    patch("src/verifier/z3_bridge.zig",
          "    pub fn executeQuery(self: *Z3Bridge, smt_script: []const u8) SmtResponse {",
          "    pub fn executeQuery(self: *Z3Bridge, smt_script: []const u8) SmtResponse {\n        if (true) return .{ .status = .ToolError }; // ЛОМАЕМ: решатель «недоступен»")
    return "make prove"


def case_registry_fuse():
    """Реестр (K5). ЛОМАЕМ: добавляем НЕКЛАССИФИЦИРОВАННУЮ цель.

    Предохранитель обязан это заметить и вернуть ненулевой код.
    """
    p = ROOT / "Makefile"
    s = p.read_text(encoding="utf-8")
    marker = "registry:\n"
    if marker not in s:
        raise RuntimeError("цель registry не найдена в Makefile")
    s = s.replace(marker, "canfail-probe-unclassified-target:\n\t@true\n\n" + marker, 1)
    p.write_text(s, encoding="utf-8")
    return "make registry"


def case_semantic_gap():
    """Эшелон 4 (Lean). ЛОМАЕМ: добавляем `sorry` в KernSemanticGap.lean."""
    p = ROOT / "formal" / "KernSemanticGap.lean"
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_GAP_PROBE : True := by sorry\n")
    return "make semantic-gap"


def case_test_pool_target():
    """Цель `test-pool`. ЛОМАЕМ: тот же лимит пула, но проверяем ИМЕННО
    эту цель (у неё свой фильтр прогона)."""
    patch("src/verifier/z3_bridge.zig",
          "    pub fn acquire(self: *SolverPool) void {\n        self.sem.waitUncancelable(compat.io());",
          "    pub fn acquire(self: *SolverPool) void {\n        // ЛОМАЕМ: лимит не соблюдается")
    return "zig build test-pool"


def case_test_align_target():
    """Цель `test-align`. ЛОМАЕМ: инвариант выравнивания."""
    patch("src/tests/alignment_stress.zig",
          "pub fn isStrictlyAligned(h: kimg.KimgHeader) bool {\n    return h.object_table_offset % 8 == 0 and h.data_payload_offset % 8 == 0;\n}",
          "pub fn isStrictlyAligned(h: kimg.KimgHeader) bool {\n    _ = h;\n    return true; // ЛОМАЕМ")
    return "zig build test-align"


def case_test_fault_target():
    """Цель `test-fault` (SIGBUS). ЛОМАЕМ: обработчик не регистрируется."""
    patch("src/core/sigbus_guard.zig",
          "    posix.sigaction(posix.SIG.BUS, &act, null);\n    posix.sigaction(posix.SIG.SEGV, &act, null);",
          "    _ = act; // ЛОМАЕМ: обработчики не установлены")
    return "zig build test-fault"


def case_coverage_counter():
    """Покрытие решений. ЛОМАЕМ: счётчик НЕ инкрементируется."""
    patch("src/cov.zig",
          "pub inline fn hit(s: Site) void {\n    counters[@intFromEnum(s)] += 1;\n}",
          "pub inline fn hit(s: Site) void {\n    _ = s; // ЛОМАЕМ: счётчик не растёт\n}")
    return "make coverage"


def case_test_next():
    """KERN-Next. ЛОМАЕМ: `status()` всегда возвращает `tested` (T)."""
    patch("src/next/truth.zig",
          "        if (self.p and !self.n) return .tested; // T",
          "        return .tested; // ЛОМАЕМ: всегда T")
    return "zig build test-next"


def case_deal_contracts():
    """Design-by-Contract. ЛОМАЕМ: подменяем ОЖИДАНИЕ вердикта.

    ⚠️ Первая попытка правила декоратор `@deal.post` — но скрипт выносит
    вердикт по ЗАРАНЕЕ СОБРАННОЙ SMT-строке, а не по декоратору. Правильная
    мишень — ожидание в таблице CASES.
    """
    patch("tools/deal_contracts.py",
          '        "(assert (not (> (* x 2) 100)))(check-sat)",\n        "sat",  # контрпример существует',
          '        "(assert (not (> (* x 2) 100)))(check-sat)",\n        "unsat",  # ЛОМАЕМ: неверное ожидание')
    return "make deal"


def case_os_stress():
    """Ресурсы ОС. ЛОМАЕМ: лимит вывода решателя снят (нет аккуратного отказа).

    ⚠️ Первая попытка искала `readToEndAlloc` — в 0.17 функция называется
    `compat.fileReadToEndAlloc` с лимитом 4 МБ.
    """
    patch("src/verifier/z3_bridge.zig",
          "compat.fileReadToEndAlloc(sout, self.allocator, 4 * 1024 * 1024)",
          "compat.fileReadToEndAlloc(sout, self.allocator, 1024 * 1024 * 1024) // ЛОМАЕМ: лимит снят")
    return "make os-stress"


def case_flood():
    """Флуд запросов. ЛОМАЕМ: детектор паник всегда «чисто».

    ⚠️ Замечание: сделать CLI реально паникующим нельзя — это сломает
    ВСЕ остальные цели. Поэтому проверяем, что детектор паник СВЯЗАН с
    кодом возврата: если он сообщает о паниках, цель обязана покраснеть.
    """
    patch("tools/os_signal_flood.py",
          "    bad = len(real_panics)",
          "    bad = len(real_panics) + 1  # ЛОМАЕМ: якобы найдена паника")
    return "make flood"


def case_bench_target():
    """Цель `bench` (kern_bench). ЛОМАЕМ: Врата открываются по тайм-ауту."""
    patch("src/verifier/admission_gate.zig",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .N; // тайм-аут не является опровержением",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .T; e_val = 1; // ЛОМАЕМ")
    return "zig build bench-kern"


def case_stress_target():
    """Цель `stress`. ЛОМАЕМ: нарушение закона Белнапа в stress_real."""
    patch("src/core/eq2.zig",
          "pub fn joinK(a: Eq2, b: Eq2) Eq2 {",
          "pub fn joinK(a: Eq2, b: Eq2) Eq2 {\n    _ = a;\n    return b; // ЛОМАЕМ: перезапись вместо join")
    return "zig build bench-stress-real"


def case_theories_target():
    """Цель `theories` (мета: 5 теорий). ЛОМАЕМ: CHC-теорию."""
    patch("src/verifier/chc.zig",
          "        return bridge.executeQuery(q).status;\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ",
          "        _ = bridge.executeQuery(q);\n        return .Sat; // ЛОМАЕМ\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ")
    return "make theories"


def case_audit_target():
    """Цель `audit` (CLI `kernc audit`). ЛОМАЕМ: запрос разрыва санитайзера.

    ⚠️ Первая попытка правила `buildContainsQuery` — а `kernc audit`
    использует `buildSanitizerGapQuery`. Мишень исправлена.
    """
    patch("src/verifier/string_theory.zig",
          'const c1 = try std.fmt.allocPrint(self.allocator, "(str.contains p \\"{s}\\")", .{danger});',
          'const c1 = try std.fmt.allocPrint(self.allocator, "(str.contains p \\"ZZZ\\")", .{danger}); // ЛОМАЕМ')
    return "make audit"


def case_smt_stress_target():
    """Цель `smt-stress`. ЛОМАЕМ: подменяем ОЖИДАНИЕ в его таблице CASES.

    ⚠️ Две неверные попытки: (1) паттерн NRA с двойным бэкслешем;
    (2) `nra_quant.zig` — но `smt_stress.zig` имеет СВОЮ таблицу CASES
    с инлайн-SMT и движок NRA не использует. Правильная мишень — ожидание.
    """
    patch("src/smt_stress.zig",
          '.{ .name = "NIA: x*x >= 0", .expect = .proved,',
          '.{ .name = "NIA: x*x >= 0", .expect = .refuted, // ЛОМАЕМ: неверное ожидание')
    return "make smt-stress"


def case_memcheck_ubsafe():
    """Цели `memcheck`/`ubsafe`. ЛОМАЕМ: утечка памяти в ядре.

    Оба режима (Debug-GPA и ReleaseSafe) обязаны это заметить.
    """
    patch("src/core/kimg_writer.zig",
          "    pub fn deinit(self: *Builder) void {",
          "    pub fn deinit(self: *Builder) void {\n        return; // ЛОМАЕМ: ресурсы не освобождаются")
    return "make memcheck"


def case_fd_check():
    """Ресурсы ОС (FD). ЛОМАЕМ: дескриптор stdin решателя не закрывается."""
    patch("src/verifier/z3_bridge.zig",
          "            sin.close(io);",
          "            _ = io; // ЛОМАЕМ: дескриптор не закрыт")
    return "make fd-check"


def case_ubsafe():
    """ReleaseSafe (детектор UB). ЛОМАЕМ: безопасную арифметику -> обычную.

    В ReleaseSafe переполнение знакового целого — паника. Значит проверка
    границ обязана это поймать.
    """
    patch("src/core/kimg_reader.zig",
          "        const t_end = std.math.add(u64, h.object_table_offset,\n                                  h.object_table_size) catch\n            return KimgError.OutOfBoundsOffset;",
          "        const t_end = h.object_table_offset + h.object_table_size; // ЛОМАЕМ: без проверки")
    return "make ubsafe"


def case_mutate():
    """Мутационное тестирование. ЛОМАЕМ: мутатор объявляет мутанта убитым.

    Тогда выживших не будет -> mutation score 100% -> цель останется
    зелёной, хотя мутантов никто не проверял. Проверяем, что цель
    СВЯЗАНА с реальным результатом: подменяем вердикт на «выжил».
    """
    # ⚠️ Замечание: подмена вердикта на «выжил» заставляет мутатор гонять
    # ВСЕ 40 мутантов (13+ минут) — для харнесса это слишком долго. Ломаем
    # САМ ЗАПУСК: скрипт обязан упасть быстро, и цель тоже.
    patch("tools/mutate_zig.py",
          "def tree_hash(root):",
          "def tree_hash(root):\n    raise RuntimeError('ЛОМАЕМ: мутатор сломан')")
    return "make mutate"


def case_fuzz_1m():
    """Фаззинг AST. ЛОМАЕМ: паника в парсере.

    ДЕФЕКТ #44: `fuzz_ast.zig` печатал «ПАНИК/SIGSEGV: 0» ЛИТЕРАЛОМ, а не
    измеренным значением. Единственный способ цели упасть — реальный крах
    процесса, что и проверяем.
    """
    patch("src/next/parser.zig",
          "pub fn parse(allocator: std.mem.Allocator, source: []const u8) !ParseResult {",
          "pub fn parse(allocator: std.mem.Allocator, source: []const u8) !ParseResult {\n    if (source.len > 0) @panic(\"ЛОМАЕМ: паника в парсере\");")
    return "zig build bench-fuzz-ast"


def case_cert():
    """Пакет квалификации. ЛОМАЕМ: обнуляем файл матрицы трассируемости.

    ДЕФЕКТ #43: цель `cert` использовала `@grep -c`, где `@` ГЛУШИТ ошибку —
    при отсутствии файла цель оставалась зелёной.

    ⚠️ ДЕФЕКТ #46: сначала кейс делал `unlink()` — и удаление файла попало
    в КОММИТ (харнесс не проверял отсутствие). Теперь файл ОБНУЛЯЕТСЯ:
    `test -s` падает (цель краснеет), а `git checkout` восстанавливает.
    """
    p = ROOT / "formal" / "certification" / "TRACEABILITY_MATRIX.md"
    if not p.exists():
        return None
    p.write_text("", encoding="utf-8")
    return "make cert"


def case_attest_key():
    """Ключ владельца. ЛОМАЕМ: указываем несуществующий путь к ключу.

    Цель обязана упасть (у неё есть `test -f ... || exit 1`).
    """
    patch("Makefile",
          "@test -f $(HOME)/kern_owner_private.pem || { echo \"[!] нет $(HOME)/kern_owner_private.pem\"; exit 1; }",
          "@test -f /nonexistent/kern_owner_private.pem || { echo \"[!] нет ключа\"; exit 1; }")
    return "make attest-key"


def case_audit_manifest():
    """Аттестационный манифест. ЛОМАЕМ: эталонный образ становится битым.

    ДЕФЕКТ #45: скрипт печатал FAIL, но ВСЕГДА выходил с 0. Теперь
    считает провалы и возвращает 1.
    """
    p = ROOT / "tests" / "fixtures" / "valid_v1_3.kimg"
    b = bytearray(p.read_bytes())
    b[len(b) // 2] ^= 0xFF  # портим 1 байт в середине
    p.write_bytes(bytes(b))
    return "make audit-manifest"


def case_chc_bench():
    """Цель `chc-bench`. ЛОМАЕМ: неверное ожидание в таблице CASES.

    ДЕФЕКТ #47: «X/Y совпало» печаталось, но код возврата не менялся.
    """
    patch("src/chc_bench.zig",
          '.{ .name = "countdown: x:=10; while(x>0) x-- => x<=0", .init = "(= x 10)", .guard = "(> x 0)", .step = "(- x 1)", .post = "(<= x 0)", .expect = .Sat },',
          '.{ .name = "countdown: x:=10; while(x>0) x-- => x<=0", .init = "(= x 10)", .guard = "(> x 0)", .step = "(- x 1)", .post = "(<= x 0)", .expect = .Unsat }, // ЛОМАЕМ')
    return "make chc-bench"


def case_probe():
    """Цель `probe`. ЛОМАЕМ: дайджест становится НЕдетерминированным.

    K2: цель была MEASURE (печатала дайджест). Теперь проверяется
    детерминизм: два прогона обязаны дать один SHA-256.
    """
    patch("src/semantic_probe.zig",
          "    std.debug.print(\"SEMANTIC_DIGEST={s}\\n\", .{hex});",
          "    std.debug.print(\"SEMANTIC_DIGEST={s}{d}\\n\", .{ hex, @as(u8, @truncate(@as(u64, @intCast(std.time.nanoTimestamp())))) }); // ЛОМАЕМ: недетерминизм")
    return "make probe"


def case_portable_bench():
    """Цель `portable-bench`. ЛОМАЕМ: `acc` становится вырожденным (0).

    K2: цель была MEASURE (печатала времена). Теперь она проверяет
    СЕМАНТИЧЕСКУЮ ЭКВИВАЛЕНТНОСТЬ компиляторов (root0/acc) — и вырожденный
    `acc` обязан её уронить (иначе загрузки выброшены оптимизатором).
    """
    patch("bench/portable_merkle.zig",
          "        acc +%= buf[off + 32];",
          "        // ЛОМАЕМ: загрузка выброшена — acc вырожден")
    return "make portable-bench"


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
    ("chc-theory",    "CHC/Horn: ложный «баг найден»",         case_chc_theory),
    ("dtmc-theory",   "DTMC: стохастичность всегда ложна",     case_dtmc_theory),
    ("cegis-theory",  "CEGIS: перебор только k=0",             case_cegis_theory),
    ("nra-theory",    "NRA: линейная логика вместо нелинейной", case_nra_theory),
    ("align-inv",     "Эшелон 1: isStrictlyAligned всегда истинна", case_align_invariant),
    ("torture-payload",   "Пытки: подмена payload (SHA-256)",      case_torture_payload),
    ("evidence-propagates", "Свидетельства: провал подпроверки",   case_evidence_propagates),
    ("telemetry-detects", "Телеметрия: балл за провал Lean",       case_telemetry_detects),
    ("guardrail-verdict", "Guardrail: опровергнутое как доказанное", case_guardrail_refuted_as_proved),
    # ПОЛНЫЕ режимы используют ТОТ ЖЕ скрипт, что быстрые (общая логика
    # начисления/проброса) -> проверяем быстрым прогоном, чтобы canfail
    # не длился лишний час. Это зафиксировано явно, а не «предполагается».
    ("evidence-full",  "Свидетельства (полный режим): тот же скрипт", case_evidence_propagates),
    ("telemetry-full", "Телеметрия (полный режим): тот же скрипт",    case_telemetry_detects),
    ("pool-limit",    "Эшелон 3: лимит пула не соблюдается",     case_pool_limit),
    ("strings-theory", "Строковая теория: подмена needle",       case_strings_theory),
    ("noninterf",     "Невлияние: утечка не регистрируется",    case_noninterference_taint),
    ("perf-threshold", "K2: порог безопасного чтения",          case_perf_threshold),
    ("kern-invariant", "K2: инвариант Врат в kern_bench",       case_gate_invariant_stress),
    ("redos-vuln",    "ReDoS: вложенный квантор не распознан",   case_redos_vuln),
    ("concolic-victim", "Конколика: подмена цели",              case_concolic_victim),
    ("absint-inv",    "Абстрактная интерпретация: инвариант",    case_absint_inv),
    ("attest-sign",   "Аттестация: подпись не проверяется",      case_attest_sign),
    ("localize-core", "UNSAT-core: конфликт не распознан",       case_localize_core),
    ("sim-invariant", "Симуляция I2: чтение возвращает пусто",   case_sim_invariant),
    ("proof-check",   "Проверка доказательств: без отрицания",   case_proof_check),
    ("verify-cli",    "CLI verify: Merkle всегда не совпал",     case_verify_cli),
    ("prove-cli",     "CLI prove: мост всегда ToolError",       case_prove_cli),
    ("registry-fuse", "K5: предохранитель ловит новую цель",     case_registry_fuse),
    ("semantic-gap",  "Эшелон 4: sorry в Lean-файле",           case_semantic_gap),
    ("test-pool",     "Цель test-pool: лимит пула",             case_test_pool_target),
    ("test-align",    "Цель test-align: выравнивание",          case_test_align_target),
    ("test-fault",    "Цель test-fault: SIGBUS-обработчик",     case_test_fault_target),
    ("coverage",      "Покрытие решений: счётчик не растёт",     case_coverage_counter),
    ("test-next",     "KERN-Next: status всегда T",              case_test_next),
    ("deal",          "DbC: ложное постусловие стало верным",    case_deal_contracts),
    ("os-stress",     "Ресурсы ОС: лимит вывода снят",          case_os_stress),
    ("flood",         "Флуд: воркер не считает успехи",         case_flood),
    ("bench",         "Цель bench: инвариант Врат",             case_bench_target),
    ("stress",        "Цель stress: закон Белнапа",              case_stress_target),
    ("theories",      "Цель theories: CHC-теория",               case_theories_target),
    ("audit",         "Цель audit: строковая теория",            case_audit_target),
    ("smt-stress",    "Цель smt-stress: NRA-логика",             case_smt_stress_target),
    ("memcheck",      "Утечка памяти (GPA/ReleaseSafe)",         case_memcheck_ubsafe),
    ("fd-check",      "Ресурсы ОС: утечка дескриптора",          case_fd_check),
    ("ubsafe",        "ReleaseSafe: переполнение без проверки",  case_ubsafe),
    ("mutate",        "Мутатор: ложный вердикт",                case_mutate),
    ("fuzz-1m",       "Фаззинг AST: паника в парсере",           case_fuzz_1m),
    ("cert",          "Пакет квалификации: файл обнулён",        case_cert),
    ("attest-key",    "Ключ владельца: несуществующий путь",     case_attest_key),
    ("audit-manifest","Манифест: битый эталонный образ",        case_audit_manifest),
    ("chc-bench",     "CHC-бенчмарк: неверное ожидание",         case_chc_bench),
    ("probe",         "Семантический дайджест: недетерминизм",    case_probe),
    ("portable-bench","Кросс-компилятор: вырожденный acc",       case_portable_bench),
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


def guard_dirty_faultable() -> int:
    """🔴 ДЕФЕКТ #63: ПРЕДОХРАНИТЕЛЬ — не запускаться на «грязных» FAULTABLE.

    ПОЧЕМУ ЭТО КРИТИЧНО. Харнесс вносит диверсию в файл и ПОСЛЕ прогона
    восстанавливает его из git (`git checkout -- <файл>`). Если у файла были
    НЕзакоммиченные правки разработчика, восстановление их УНИЧТОЖАЕТ молча.

    Дефект найден на практике: во время работы над BLAKE3-диспетчеризацией
    `make evidence` запустил canfail, и правки в `src/core/kimg_reader.zig` и
    `src/core/kimg_writer.zig` были стёрты восстановлением из git. Пришлось
    переделывать.

    Теперь: если хотя бы один FAULTABLE-файл имеет незакоммиченные изменения —
    харнесс отказывается работать и объясняет, что делать.
    """
    dirty = []
    for f in FAULTABLE:
        p = ROOT / f
        if not p.exists():
            continue
        r = subprocess.run(["git", "status", "--porcelain", "--", f],
                           cwd=str(ROOT), capture_output=True, text=True)
        if r.stdout.strip():
            dirty.append(f)
    if not dirty:
        return 0
    print("=" * 70)
    print("\033[31m[ПРЕДОХРАНИТЕЛЬ #63] ОТКАЗ: у FAULTABLE-файлов есть")
    print("незакоммиченные правки — харнесс СТЁР БЫ ИХ при восстановлении.\033[0m")
    print("=" * 70)
    for f in dirty:
        print(f"    M {f}")
    print("\nЧТО ДЕЛАТЬ:")
    print("  1) закоммитьте свои правки:   git add -A && git commit -m '...'")
    print("  2) либо временно уберите файл из FAULTABLE в tools/canfail.py")
    print("\nПочему так: харнесс восстанавливает файлы через `git checkout --`,")
    print("поэтому незакоммиченная работа в них не переживёт прогон.")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="K4: проверить ЛОГИКУ харнесса на синтетических входах")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="ОПАСНО: разрешить прогон при грязных FAULTABLE "
                         "(ваши правки в них будут утеряны)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.list:
        for c in CASES:
            print(f"  {c[0]:14s} {c[1]}")
        return 0

    # ДЕФЕКТ #63: ПРЕДОХРАНИТЕЛЬ. Харнесс восстанавливает FAULTABLE-файлы через
    # `git checkout --`, поэтому незакоммиченные правки в них будут УТЕРЯНЫ.
    # Отказываемся работать, пока дерево не закоммичено (или явный --allow-dirty).
    if not args.allow_dirty:
        rc_guard = guard_dirty_faultable()
        if rc_guard != 0:
            return rc_guard

    env = dict(os.environ)
    env["PATH"] = (f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:"
                   f"{ROOT}/.venv/bin:{env.get('PATH','')}")
    os.environ.update(env)

    print("=" * 70)
    print("KERN: CAN-FAIL — проверка, что проверки СПОСОБНЫ УПАСТЬ")
    print("=" * 70)
    print("Метод: ломаем инвариант -> цель ОБЯЗАНА покраснеть.\n")

    clean_slate()
    snap = snapshot_faultable()

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

    # --- КОНТРОЛЬ ЦЕЛОСТНОСТИ: харнесс не должен оставлять следов -----------
    dirty = verify_restored(snap)

    # 🔴 ДЕФЕКТ #65: ИСХОДНИКИ ВОССТАНОВЛЕНЫ, А АРТЕФАКТЫ — НЕТ.
    # Харнесс патчит исходник, собирает артефакт и запускает цель. После отката
    # ИСХОДНИК чист, но собранный бинарник/библиотека ОСТАЮТСЯ ПРОПАТЧЕННЫМИ.
    # Симптом (найден на практике): после кейса `guardrail-verdict` прокси
    # продолжал отвечать 200 на опровергнутый контракт, хотя `src/capi.zig` был
    # уже восстановлен — потому что `libkern.so` осталась собранной с диверсией.
    # Теперь: после отката исходников ПЕРЕСОБИРАЕМ артефакты из чистого кода.
    print("[i] пересборка артефактов из восстановленных исходников...")
    rb = subprocess.run(["zig", "build"], cwd=str(ROOT), capture_output=True, text=True)
    if rb.returncode == 0:
        print("[OK] артефакты пересобраны — пропатченных бинарников не осталось")
    else:
        print("[!] пересборка не удалась:", rb.stderr[-200:])
        bad += 1

    print()
    print("=" * 70)
    if dirty:
        print("[31m[!] ХАРНЕСС ОСТАВИЛ ИЗМЕНЕНИЯ В ДЕРЕВЕ:[0m")
        for f in dirty:
            print(f"      - {f}")
        print("      Это значит, что файла не было в FAULTABLE и откат не сработал.")
        bad += 1
    else:
        print("[32m[OK] дерево чистое: все правки откачены[0m")
    print(f"ИТОГ: не-вакуумных {ok} | ВАКУУМНЫХ {bad} | пропущено {skipped}")
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
