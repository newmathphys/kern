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
    "src/kern_bench.zig",
    "src/perf_bench.zig",
    "src/stress_real.zig",
    "tests/stress_1m.zig",
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


def snapshot_faultable() -> dict:
    """SHA-256 «ломаемых» файлов на момент старта."""
    import hashlib
    out = {}
    for f in FAULTABLE:
        p = ROOT / f
        if p.exists():
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def verify_restored(snap: dict) -> list:
    """Проверяет, что после прогона НИ ОДИН исходник не остался испорченным.

    ⚠️ ЗАЧЕМ (найдено на практике, КРИТИЧНО): файл, которого НЕТ в FAULTABLE,
    не откатывается. Так `z3_bridge.zig` остался с диверсией кейса
    `pool-limit` — и она попала в КОММИТ (8c1e540). Этот контроль ловит
    такой класс ошибок: харнесс не должен оставлять следов в дереве.
    """
    import hashlib
    bad = []
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
