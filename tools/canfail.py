#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
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
import json
import os
import signal
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


# ============================================================================
#  ИНФРАСТРУКТУРА ОТКАТА И ВЗАИМОИСКЛЮЧЕНИЯ
# ============================================================================
# ЗАЧЕМ. Харнесс пишет прямо в рабочие файлы. Нужно три гарантии:
#   1) откат возвращает ТОЧНО то, что было (включая незакоммиченные правки);
#   2) откат не затирает правку, сделанную третьей стороной во время прогона;
#   3) два экземпляра харнесса не могут работать одновременно.

# Относительные пути файлов, которые ТЕКУЩИЙ кейс реально изменил.
# Заполняется через touch()/patch(). Откат трогает только их.
TOUCHED: set[str] = set()

# Байтовый снимок FAULTABLE-файлов на момент СТАРТА прогона.
# Именно он — источник истины для восстановления: он захватывает и
# незакоммиченные правки, поэтому `git checkout --` больше не нужен.
ORIG_SNAPSHOT: dict[str, bytes] = {}
# ДЕФЕКТ #283: откат восстанавливал БАЙТЫ, но не РЕЖИМ. Кейс, снимающий бит
# исполнения с tools/*.sh (именно так проверяют, что гейт замечает неxecutable
# скрипт), после прерывания оставлял 29 файлов с режимом 644 — и следующий
# прогон падал на «permission denied» вдали от места поломки.
ORIG_MODES: dict[str, int] = {}
ORIG_HASHES: dict[str, str] = {}

# 🔴 ДЕФЕКТ #116 (найден на практике). SHA-256 содержимого файла СРАЗУ ПОСЛЕ
# подсадки кейса (`patch()`), в рамках ТЕКУЩЕГО кейса.
#
# Зачем: `Fault` знает о файле только состояние на СТАРТЕ кейса (бэкап). Если
# файл — который кейс САМ правил — дополнительно изменён третьей стороной
# ПОСЛЕ подсадки, откат из бэкапа молча уничтожает эту правку (защита
# `TOUCHED` такие файлы НЕ ловит: они помечены как «трогал кейс»).
# Практический случай: правка `README.md` во время полного прогона `make
# canfail` была стёрта откатом кейса `artifact-check`.
#
# Решение: перед откатом сверяем ТЕКУЩИЙ хеш с хешем того, что записали МЫ.
# Не совпало -> печатаем предупреждение и НЕ откатываем (чужую правку
# сохраняем; подсадка останется в файле, и финальная проверка «дерево чистое»
# это ГРОМКО покажет — молчаливой потери больше нет).
PATCHED_HASHES: dict[str, str] = {}

# Дефект #242: аттестат — ГЕНЕРИРУЕМЫЙ артефакт. Кейсы `slsa`/`attest`
# пересобирают и переподписывают его; это не «правка третьей стороны»,
# поэтому откат из снимка старта обязан срабатывать всегда.
GENERATED = {"kern.intoto.jsonl", "kern.intoto.sig"}


# 🔴 Держатель файлового объекта блокировки. Без ссылки из модуля Python
# соберёт локальный объект сборщиком мусора, закроет fd и СНИМЕТ flock —
# блокировка «исчезнет» сразу после выхода из функции.
_LOCK_HOLDER: list = []


def touch(rel: str) -> None:
    """Помечает файл как изменённый текущим кейсом (разрешает откат).

    🔴 ДЕФЕКТ #225 (найден аудитом): `patch()` отказывался работать с файлом
    вне FAULTABLE, а `touch()` — молча помечал. В результате кейс правил
    `docs/PROJECT.md` через `touch()` + `write_atomic()`, откат не срабатывал,
    подсадка оставалась в дереве, а финальная проверка (`verify_restored`
    смотрит только FAULTABLE) докладывала «дерево чистое». Класс дефекта #48.
    Теперь `touch()` ведёт себя так же строго, как `patch()`.
    """
    if rel not in FAULTABLE:
        raise RuntimeError(
            f"{rel} отсутствует в FAULTABLE — правка НЕ будет откачена! "
            f"Добавьте файл в FAULTABLE (дефект #225).")
    TOUCHED.add(rel)


def write_atomic(p: Path, data: bytes) -> None:
    """Атомарная запись: tmp в том же каталоге + os.replace.

    Прямая `write_bytes` при прерывании (SIGKILL, таймаут) может оставить
    файл полузаписанным. os.replace в пределах одной ФС атомарен.

    🔴 ДЕФЕКТ #157 (НАЙДЕН полным прогоном canfail): `os.replace` переносит
    режим ВРЕМЕННОГО файла, а tmp создавался с umask-режимом (0644). Поэтому
    после откатa исполняемые скрипты (`tools/*_check.sh`, 0755) теряли бит
    `+x` — 29 файлов оставались с `old mode 100755 / new mode 100644`.
    ИСПРАВЛЕНО: режим СУЩЕСТВУЮЩЕГО файла сохраняется и применяется к tmp
    ДО `replace`; для нового файла берётся 0644.
    """
    tmp = p.with_name(p.name + ".canfail_tmp")
    tmp.write_bytes(data)
    try:
        mode = p.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, p)


def capture_snapshot() -> None:
    """Считывает байты всех FAULTABLE-файлов ДО прогона."""
    import hashlib
    ORIG_SNAPSHOT.clear()
    ORIG_HASHES.clear()
    ORIG_MODES.clear()
    for rel in FAULTABLE:
        p = ROOT / rel
        if p.exists():
            data = p.read_bytes()
            ORIG_SNAPSHOT[rel] = data
            ORIG_HASHES[rel] = hashlib.sha256(data).hexdigest()
            try:
                ORIG_MODES[rel] = p.stat().st_mode & 0o777
            except OSError:
                pass


def restore_file(rel: str) -> bool:
    """Восстанавливает файл из снимка СТАРТА прогона (без git checkout).

    Возвращает True, если файл действительно был восстановлен.
    Если снимка нет (файла не было на старте) — удаляем созданный файл.
    """
    import hashlib
    p = ROOT / rel
    if rel in ORIG_SNAPSHOT:
        write_atomic(p, ORIG_SNAPSHOT[rel])
        if rel in ORIG_MODES:
            try:
                os.chmod(p, ORIG_MODES[rel])
            except OSError:
                pass
        ok = hashlib.sha256(p.read_bytes()).hexdigest() == ORIG_HASHES[rel]
        if not ok:
            print(f"  [!] ОТКАТ НЕ СОШЁЛСЯ по хешу: {rel}")
        return ok
    if p.exists():
        p.unlink()  # файла не было на старте — значит его создал кейс
        return True
    return False


def acquire_run_lock():
    """Эксклюзивная блокировка прогона через fcntl.flock (ядро снимает её
    даже при SIGKILL — в отличие от файла-флага, дефект #50).

    Возвращает открытый файловый дескриптор (держать до конца процесса)
    либо None, если блокировка уже занята.
    """
    try:
        import fcntl
    except ImportError:  # не POSIX
        return None
    f = open("/tmp/kern_mutation.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        f.close()
        return "BUSY"
    return f



# =========================================================================
#  ДЕФЕКТ #156: ДИВЕРСИЯ ПРИ ВНЕШНЕМ SIGTERM.
# =========================================================================
# ИЗМЕРЕНО (реальный инцидент f01e8fc): прогон, убитый таймаутом оболочки
# (SIGTERM), НЕ выполнил `finally` у `Fault.__exit__`, и патч `.little` ->
# `.big` из кейса `opt-diff-check` остался в дереве, а затем попал в коммит.
# `try/finally` в Python НЕ перехватывает SIGTERM (только KeyboardInterrupt).
# Теперь перед выходом по сигналу откатываем ТЕКУЩИЙ патч из снимка.
_ACTIVE_BACKUP: dict = {}


def _emergency_restore(signum, _frame):
    for path, data in list(_ACTIVE_BACKUP.items()):
        try:
            tmp = path.with_suffix(path.suffix + ".kern_restore")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            print(f"[SIGTERM] восстановлен {path.name} из снимка", file=sys.stderr)
        except OSError as e:
            print(f"[SIGTERM] НЕ удалось восстановить {path}: {e}", file=sys.stderr)
    sys.exit(130)


for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    try:
        signal.signal(_sig, _emergency_restore)
    except (ValueError, OSError):
        pass


class Fault:
    """Контекстный менеджер: ломает файл(ы) и ГАРАНТИРОВАННО откатывает.

    🔴 ДЕФЕКТ #71 (найден на практике, уточняет #63/#69). Раньше `__exit__`
    восстанавливал ВСЕ файлы из переданного списка, а не только те, которые
    кейс РЕАЛЬНО менял. Последствие: если во время кейса файл правил кто-то
    ещё (редактор, другой инструмент), откат возвращал СТАРЫЙ бэкап и молча
    уничтожал эту правку. Именно так была стёрта правка `tools/canfail.py`
    (кейс `svg-overflow`), сделанная во время прогона `make evidence`.

    ИСПРАВЛЕНО:
      * откатываются ТОЛЬКО файлы, помеченные как изменённые (`TOUCHED`);
      * если файл из списка изменился, но кейс его НЕ трогал — это правка
        третьей стороны: печатаем предупреждение и НЕ перезаписываем;
      * запись атомарная (tmp + os.replace), чтобы откат не оставил
       полузаписанный файл при прерывании.
    """

    def __init__(self, files):
        self.files = [ROOT / f for f in files]
        self.backup = {}

    def __enter__(self):
        # 🔴 Дефекты #116/#71: наборы «трогали» и «что записали» — В РАМКАХ
        # кейса. Без сброса файл, тронутый кейсом A, оставался «откатываемым»
        # в кейсе B — и правка третьей стороны затиралась бэкапом кейса B.
        TOUCHED.clear()
        PATCHED_HASHES.clear()
        for f in self.files:
            if f.exists():
                self.backup[f] = f.read_bytes()
                _ACTIVE_BACKUP[f] = self.backup[f]  # для SIGTERM-откатa (#156)
        return self

    def __exit__(self, *exc):
        import hashlib
        for f, data in self.backup.items():
            rel = str(f.relative_to(ROOT))
            cur = f.read_bytes() if f.exists() else None
            if cur == data:
                continue  # кейс файл не менял — трогать нечего
            if rel in GENERATED:
                # Аттестат пересобран/переподписан кейсом — возвращаем снимок
                # старта, не считая это чужой правкой (дефект #242).
                write_atomic(f, data)
                continue
            if rel not in TOUCHED:
                print(f"  [!] ВНИМАНИЕ: {rel} изменился во время кейса, "
                      f"но кейс его НЕ трогал — похоже на правку третьей "
                      f"стороны. НЕ перезаписываю (сохранена).")
                continue
            # 🔴 ДЕФЕКТ #116: файл, который кейс САМ правил, мог быть изменён
            # третьей стороной ПОСЛЕ подсадки. Сверяем с хешем того, что
            # записали МЫ: не совпало -> чужую правку НЕ затираем.
            ph = PATCHED_HASHES.get(rel)
            if ph is not None and cur is not None \
                    and hashlib.sha256(cur).hexdigest() != ph:
                print(f"  [!] ВНИМАНИЕ: {rel} изменён ПОСЛЕ подсадки кейса "
                      f"(хеш не совпал) — откат из бэкапа НЕ выполняю, чтобы "
                      f"не стереть чужую правку. ПРОВЕРЬТЕ ФАЙЛ ВРУЧНУЮ!")
                continue
            write_atomic(f, data)
        return False


FAULTABLE = [
    "docs/evidence/scorecard.json",
    # Дефект #225: кейс `metrics-guard` правит PROJECT.md, а файла не было
    # в списке -> откат не срабатывал, и подсадка оставалась в дереве.
    "docs/PROJECT.md",
    # Дефект #225: кейс `slsa-bad-sig` правит подпись аттестата — тот же класс.
    "kern.intoto.sig",
    "kern.intoto.jsonl",
    "server.json",
    "tests/fixtures/zig_plain_add.zig",
    "tests/fixtures/zig_saturating_add.zig",
    "tests/fixtures/rust_saturating_add.rs",
    "examples/hadamard_matrix.py",
    "tools/parser_security_check.sh",
    "tests/fixtures/inject_comment_in_string.py",
    "tools/evo_fuzzer.py",
    "tools/translation_val_check.py",
    "tools/concolic_check.sh",
    "src/wasm_api.zig",
    "tools/opt_diff_check.sh",
    "tools/dst_check.sh",
    "tools/heal_check.sh",
    "docs/CAPABILITY_STATUS.md",
    "tools/tree_lock.py",
    # Кейс `trace-check` правит движок Ступени 2 — файл обязан быть в
    # FAULTABLE, иначе подсадка останется в дереве (класс #225).
    "tools/trace_explorer.py",
    "tools/hw_binary_audit.py",
    "tools/bitrot_chaos_check.py",
    "tools/pcc_check.py",
    "tools/xray_check.sh",
    "tools/gen_tests_check.sh",
    "tools/simplify_check.sh",
    "tools/bounds_check.sh",
    "tools/loop_check.sh",
    "tools/state_inv_check.sh",
    "tools/presets_check.sh",
    "tools/fuzz_corpus_check.py",
    "tools/fuzz_corpus_check.sh",
    "tools/html_canvas_check.sh",
    "tools/bug_hunter.py",
    "tools/bug_hunt_check.sh",
    "tools/rlvr_oracle_check.sh",
    "tools/rag_conflict_check.sh",
    "tools/action_firewall_check.sh",
    "tools/belnap_swarm_check.sh",
    "tools/noninterference_check.sh",
    "tools/mcp_audit_check.sh",
    "tools/anti_cheat_check.sh",
    "tools/pricing_matrix_check.sh",
    "tools/sql_policy_check.sh",
    "tools/ffi_bridge_check.sh",
    "tools/double_spend_check.sh",
    "tools/arbitrage_check.sh",
    "tools/polyglot7_check.sh",
    "tools/float_nan_check.sh",
    "tools/string_contracts_check.sh",
    "examples/xray_demo.py",
    "src/compat.zig",
    "src/core/hash_algo.zig",
    "tools/artifact_check.py",
    "README.md",
    "tools/kern_contracts.py",
    "tools/audits_run.py",
    "src/next/truth.zig",
    "src/main.zig",
    "src/verifier/model_extract.zig",
    "src/core/codec.zig",
    "examples/kern_mcp_server.py",
    "tools/canfail.py",
    "tools/cache_avalanche_bench.py",
    "formal/KernAllMath.lean",
    "src/capi.zig",
    "src/verifier/noninterference.zig",
    "src/verifier/builtin_lia.zig",
    "src/binlevel_probe.zig",
    "src/verifier/admission_gate.zig",
    "src/verifier/array_theory.zig",
    "src/tests/litmus_memory_test.zig",
    "src/smt_bench.zig",
    "src/smt_stress.zig",
    "src/chc_bench.zig",
    "src/semantic_probe.zig",
    "docs/kern-architecture.svg",
    "docs/evidence/bench_smt.log",
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
    "src/next/state_axes.zig",
    "src/next/evidence_ledger.zig",
    "src/core/kimg_reader.zig",
    "src/proof_cache.zig",
    "src/runtime/kern_x.zig",
    "audits/codecheck/py_abs_ok.py.expect.json",
    "audits/codecheck/py_abs_bad.py.expect.json",
    "src/core/kernfs_router.zig",
    "src/core/kimg_writer.zig",
    "tools/mutate_zig.py",
    "tools/bench_json.py",
    "src/kern_bench.zig",
    "src/perf_bench.zig",
    "src/stress_real.zig",
    "tests/stress_1m.zig",
    "tests/fixtures/valid_v1_3.kimg",
    "zig-out/bin/kernc",
    # 🔴 ДЕФЕКТ #115: аттестуется НЕ `kernc`, а `kernc-hermetic` (`SUBJECTS`
    # в tools/slsa_provenance.py). Кейс `slsa` подсаживал неаттестуемый файл,
    # цель оставалась зелёной -> кейс был ВАКУУМНЫМ. Файл обязан быть здесь,
    # иначе `touch()` откажет и правка не будет откачена.
    "zig-out/bin/kernc-hermetic",
    "src/core/blake3_simd8.zig",
    # УЛУЧШЕНИЯ v2.5: фикстуры и цели, которые canfail обязан уметь ломать.
    "examples/contracts_demo.py",
    "examples/refactor_before.py",
    "examples/refactor_after.py",
    "examples/self_verify.zig",
    "examples/edge_cases.zig",
    "examples/edge_cases.py",
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

    ⚠️ Дефект #71: поэтому восстановление идёт из БАЙТОВОГО СНИМКА, снятого
    НА СТАРТЕ прогона (`ORIG_SNAPSHOT`) — он включает и незакоммиченные
    правки. Удалённые файлы возвращает `restore_file()` из того же снимка.

    РЕШЕНИЕ: этот шаг только СООБЩАЕТ о файлах, отличающихся от git, чтобы
    разработчик знал, что дерево грязное. Отказом это быть перестало —
    откат из снимка безопасен для незакоммиченной работы.
    """
    dirty = []
    for f in FAULTABLE:
        p = ROOT / f
        if not p.exists():
            # удалён — восстановим из снимка (дефект #46)
            restore_file(f)
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


def is_build_output(rel: str) -> bool:
    """Артефакт сборки (выход `zig build`), а не исходник.

    🔴 ДЕФЕКТ #76: `zig-out/bin/kernc` входил в снимок целостности. Кейс
    `slsa-hash` дописывает в бинарник байты, харнесс затем ПЕРЕСОБИРАЕТ
    артефакты — а Debug-сборка Zig 0.17 не бит-воспроизводима (дефект #56,
    недетерминированный порядок error-set в .debug_info/.debug_str).
    Поэтому после финальной пересборки хеш артефакта не совпадал со снимком,
    и `verify_restored` ложно сообщал «харнесс оставил изменения» ->
    `canfail` выходил с кодом 1 -> КРАСНЫЙ CI (KERN CI #53-#54).

    Проверка целостности существует ради ИСХОДНИКОВ: «харнесс не оставил
    следов в дереве». Выходы сборки к этому не относятся — их всё равно
    перезаписывает следующий `zig build`.
    """
    return rel.startswith("zig-out/") or rel.startswith(".zig-cache/")


def snapshot_faultable() -> dict:
    """SHA-256 «ломаемых» ИСХОДНИКОВ на момент старта (артефакты сборки — нет)."""
    import hashlib
    out = {}
    for f in FAULTABLE:
        if is_build_output(f):
            continue
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
        if is_build_output(f):
            continue
        p = ROOT / f
        if not p.exists():
            missing.append(f)
            restore_file(f)
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
    touch(path)
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
                restore_file(path)
            time.sleep(0.2)
    if s is None:
        raise RuntimeError(f"не удалось прочитать {path} как UTF-8 после 5 попыток")
    if old not in s:
        raise RuntimeError(f"шаблон не найден в {path}: {old[:60]!r}")
    # ДЕФЕКТ #297: якорь, встречающийся БОЛЬШЕ ОДНОГО РАЗА, — это ловушка.
    # `replace(..., 1)` молча бьёт по ПЕРВОМУ вхождению. Так кейс `contracts`
    # после появления `explain` (в котором тот же `if "ДОКАЗАНО" ...`) patched
    # ЧУЖОЕ место: поломка внесена, цель зелёная → ВАКУУМНЫЙ кейс, и CI
    # покраснел по неверной причине. Теперь неоднозначность — ошибка кейса.
    hits = s.count(old)
    if hits > 1:
        raise RuntimeError(
            f"якорь НЕОДНОЗНАЧЕН в {path}: {hits} вхождений — уточните контекст "
            f"(добавьте соседние строки): {old[:80]!r}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    # 🔴 Дефект #116: фиксируем, ЧТО именно записали МЫ. По этому хешу откат
    # отличит собственную подсадку от правки третьей стороны (см. Fault.__exit__).
    import hashlib
    PATCHED_HASHES[path] = hashlib.sha256(p.read_bytes()).hexdigest()


# ==========================================================================
# КЕЙСЫ: (имя, что проверяем, команда, инъекция поломки, таймаут)
# ==========================================================================


def patch_all(path: str, old: str, new: str) -> None:
    """Заменить ВСЕ вхождения подстроки (осознанно, не «угадать нужное»).

    Нужен там, где одна и та же проверка продублирована в коде (например,
    сверка digest в двух путях KERNFS) и диверсия обязана попасть в каждый
    экземпляр, иначе «зелёная» цель ничего не докажет.
    """
    if path not in FAULTABLE:
        raise RuntimeError(
            f"{path} отсутствует в FAULTABLE — правка НЕ будет откачена! "
            f"Добавьте файл в FAULTABLE.")
    touch(path)
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    if old not in s:
        raise RuntimeError(f"шаблон не найден в {path}: {old[:60]!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")
def case_avalanche():
    """Лавина SHA-256. ЛОМАЕМ: подменяем SHA-256 на «наивный» хэш."""
    patch("tools/cache_avalanche_bench.py",
          "    return h.digest()",
          "    return weak_key(proof)")
    return "make avalanche"


def case_bench_json():
    """Детерминированный бенчмарк. ЛОМАЕМ: считаем «наивный» хэш основным ключом.

    Тогда лавина перестаёт быть ~50 % (становится ~3 %), цепочка коллизий вырастает до
    размера таблицы, и вердикт инструмента ОБЯЗАН стать FAIL (ненулевой код возврата).
    Если цель останется зелёной — значит бенчмарк перестал что-либо проверять.
    """
    patch("tools/bench_json.py",
          "    kern = measure(args.n, kern_key)",
          "    kern = measure(args.n, weak_key)")
    return "make bench-json"


def case_lean_sorry():
    """Lean без sorry. ЛОМАЕМ: добавляем `sorry` в доказательство."""
    p = ROOT / "formal" / "KernAllMath.lean"
    touch("formal/KernAllMath.lean")
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


def case_svg_overflow():
    """Геометрия SVG-баннера. ЛОМАЕМ: подставляем строку шире панели.

    XML остаётся ВАЛИДНЫМ, поэтому проверка XML-валидности такой дефект не
    видит — подпись «уезжает» в соседнюю панель. Именно так выглядел баннер.
    """
    p = ROOT / "docs" / "kern-architecture.svg"
    touch("docs/kern-architecture.svg")
    s2 = p.read_text(encoding="utf-8")
    s2 = s2.replace(
        '<text x="303" y="171" class="lbl">BLAKE3 default / raw ~90 GB/s</text>',
        '<text x="303" y="171" class="lbl">BLAKE3 default / raw ~90 GB/s / safe 390 MB/s (2.6 GB/s @64K) / extra</text>',
        1,
    )
    p.write_text(s2, encoding="utf-8")
    return "make svg-check"


def case_simd8_masking():
    """Пакетный SIMD-8 BLAKE3. ЛОМАЕМ: убираем ПОЛОСНОЕ маскирование.

    В одной пачке длины объектов разные (0..1024), поэтому число блоков у полос
    разное. `@select(u32, active, next_cv, cv[i])` не даёт «лишним» полосам
    испортить своё состояние. Если маскирование убрать, дайджесты коротких
    объектов перестанут совпадать со `std.Blake3` — тест бит-в-бит обязан
    покраснеть.
    """
    patch(
        "src/core/blake3_simd8.zig",
        "        cv[i] = @select(u32, active, next_cv, cv[i]);",
        "        cv[i] = next_cv; // ДЫРА: неактивные полосы тоже перезаписаны\n"
        "        _ = active;",
    )
    return "zig test src/core/blake3_simd8.zig"


def case_proof_checker_hole():
    """Независимый пруф-чекер. ЛОМАЕМ: отключаем запрет дыр в выводе.

    Если проверка `isHole` перестанет срабатывать, подделанный сертификат с
    правилом `hole` пройдёт как «доказанный» — то есть KERN снова начнёт верить
    решателю на слово. Тест «правило-дыра hole отвергается» обязан покраснеть.
    """
    patch(
        "src/verifier/proof_check.zig",
        "fn isHole(r: []const u8) bool {\n"
        "    for (HOLE_RULES) |h| if (std.mem.eql(u8, h, r)) return true;\n"
        "    return false;\n}",
        "fn isHole(r: []const u8) bool {\n"
        "    _ = r;\n"
        "    return false; // ДЫРА: запрет дыр отключён\n}",
    )
    return "zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig"


def case_proof_checker_binding():
    """Независимый пруф-чекер. ЛОМАЕМ: отключаем привязку посылок к контракту.

    Тогда `(asserted (< x 999))` — формула, которой в задаче НЕ было, — пройдёт
    как законная посылка. Тест «подменённая посылка (fake assume) отвергается»
    обязан покраснеть.
    """
    patch(
        "src/verifier/proof_check.zig",
        "            if (found) v.premises_bound += 1 else v.premises_unbound += 1;",
        "            v.premises_bound += 1; // ДЫРА: привязка не проверяется\n"
        "            _ = found;",
    )
    return "zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig"


def case_evidence_gate():
    """Жёсткий гейт свидетельств. ЛОМАЕМ: дописываем RC=1 в опубликованный лог.

    Гейт обязан это заметить: каталог docs/evidence/ — то, что аудитор
    открывает первым, и лог с ненулевым кодом означает «проект публикует
    провал рядом с заявлением об успехе».
    """
    p = ROOT / "docs" / "evidence" / "bench_smt.log"
    touch("docs/evidence/bench_smt.log")
    with p.open("a", encoding="utf-8") as f:
        f.write("\nRC=1\n")
    return "make evidence-gate"


def case_mcp_server():
    """MCP-сервер: конфликт Белнапа схлопывается в доказательство.

    ЛОМАЕМ: в JOIN_K убираем ветку конфликта, и при p=1, n=1 сервер отвечает
    `T` вместо `B`. Это ровно тот класс дефекта, против которого построен
    проект: противоречие выдаётся за доказательство. Живой self-test
    (tools/mcp_selftest.py) обязан это заметить.
    """
    patch("examples/kern_mcp_server.py",
          'state = "B" if (p and n) else ("T" if p else ("F" if n else "N"))',
          'state = ("T" if p else ("F" if n else "N"))')
    return "make mcp-selftest"


def readme_hash_anchor() -> str:
    """Строка объявленного в README sha256 — её и «ломает» кейс артефакта.

    🔴 ДЕФЕКТ, НАЙДЕННЫЙ CI #68/#69 (коммиты 7c44115 и ac6ed4f, шаг CAN-FAIL).
    Здесь был ЖЁСТКО ЗАПИСАН хеш `4360a1cb…`. При релизе v2.4.0 артефакт был
    ЗАКОННО пересобран, README получил новый хеш `f03ab8e6…`, строка-якорь
    исчезла, и `patch()` упал с «подстрока не найдена» -> КЕЙС ОШИБСЯ ->
    `python3 tools/canfail.py` вернул 1 -> шаг CAN-FAIL покраснел в CI,
    хотя ни одна проверка проекта не была нарушена.

    УРОК: тест не должен зависеть от КОНКРЕТНОГО значения данных, которыми он
    не владеет. Теперь якорь берётся ИЗ README, поэтому пересборка релиза
    кейс не ломает.
    """
    import re as _re
    txt = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    m = _re.search(r"#\s*[0-9a-f]{64}", txt)
    if not m:
        raise RuntimeError("в README.md нет объявленного sha256 (64 hex) — "
                           "кейс артефакта не может быть применён")
    return m.group(0)






def case_contracts():
    """Контракты: нарушение контракта объявляется ДОКАЗАННЫМ.

    ЛОМАЕМ: снимаем условие вердикта, поэтому ЛЮБОЙ контракт печатается как
    `[PASS] ... ДОКАЗАНО`. Тогда `withdraw_buggy` (в котором списание уходит
    в минус) перестаёт быть отвергнутым, и `--expect-demo` обязан покраснеть.
    """
    # ЯКОРЬ ОБЯЗАН БЫТЬ СИНХРОНЕН С КОДОМ. Здесь стояло
    # `if "ДОКАЗАНО" in out and r.returncode == 0:` — после рефакторинга
    # `_demo()` (переход на общий `run_kernc`, возвращающий `rc`) шаблон
    # исчез, и кейс ОШИБСЯ. Найдено ПОЛНЫМ локальным прогоном canfail —
    # то есть ровно тем шагом, который краснел в облачном CI.
    patch("tools/kern_contracts.py",
          '            if "ДОКАЗАНО" in out and rc == 0:\n'
          '                proof = ""',
          '            if True:  # ДИВЕРСИЯ: любой контракт объявляется доказанным\n'
          '                proof = ""')
    return "make contracts"


def kern_version_anchor() -> str:
    """Строка объявления версии в `src/main.zig` — её и «ломает» кейс версии.

    🔴 ТОТ ЖЕ КЛАСС, ЧТО ДЕФЕКТ #113 (и ещё один корень красного CI #68/#69).
    Здесь была ЖЁСТКО ЗАПИСАНА версия `v2.3.0`. Релиз v2.4.0 обновил строку,
    якорь исчез, `patch()` упал -> КЕЙС ОШИБСЯ -> шаг CAN-FAIL покраснел.
    Теперь версия берётся ИЗ КОДА, поэтому ЛЮБОЙ будущий релиз кейс не ломает.
    """
    import re as _re
    txt = (ROOT / "src" / "main.zig").read_text(encoding="utf-8", errors="replace")
    m = _re.search(r'pub const KERN_VERSION = "[^"]+";', txt)
    if not m:
        raise RuntimeError("в src/main.zig нет `pub const KERN_VERSION = \"...\";`")
    return m.group(0)


def case_version_consistency():
    """Версия: баннер `usage` отстал от `--version` (дефект #97).

    ЛОМАЕМ: в баннере возвращаем старую версию. `make version-check` обязан
    покраснеть: пользователь, запустивший `kernc` без аргументов, увидел бы
    ДРУГУЮ версию, чем `kernc --version`.
    """
    patch("src/main.zig",
          kern_version_anchor(),
          'pub const KERN_VERSION = "v1.3";')
    return "make version-check"


def case_skip_exit_n():
    """kernx: `exit 2` (SKIP) снова считается ОПРОВЕРЖЕНИЕМ (F), а не N.

    ЛОМАЕМ: убираем ветку пропуска в `Bit.ofExit`, и код 2 снова даёт `n = true`
    (F). Тест «SKIP (exit 2) -> N» обязан покраснеть: пропущенная проверка
    не является ни доказательством, ни опровержением (дефект #96).
    """
    patch("src/next/truth.zig",
          "        if (exit_code == skip_exit_code) return .{}; // N: нет свидетельства",
          "        if (false) return .{};  // ДИВЕРСИЯ: SKIP снова даёт F")
    return "make test-next"


def case_kimg_deflate():
    """Сжатие: флаг `--deflate` печатает «включено», но НЕ сжимает.

    ЛОМАЕМ: кодек остаётся `raw`, хотя сообщение о сжатии выводится. Это
    ровно класс «молчаливо сломанная проверка»: инструмент ЗАЯВЛЯЕТ сжатие,
    а образ не уменьшается. `make kimg-deflate` обязан покраснеть.
    """
    patch("src/main.zig",
          "            b.compress = .deflate;",
          "            b.compress = .raw;  // ДИВЕРСИЯ: заявляем сжатие, не сжимаем")
    return "make kimg-deflate"


def case_contracts_branches():
    """Ветвления: `if` НЕ транслируется в `ite` (ветка отброшена).

    ЛОМАЕМ: `ast.If` перестаёт обрабатываться, поэтому функции с ветвлениями
    уходят в SKIP. Тогда `withdraw_missing_neg` (баг с отрицательной суммой)
    НЕ будет найден, и `--expect-demo` обязан покраснеть: проверка, которая
    не ловит баг, не должна оставаться зелёной.
    """
    # #297: якорь уточнён контекстом — `if isinstance(st, ast.If):` встречается 8 раз.
    patch("tools/kern_contracts.py",
          "        if isinstance(st, ast.If):\n"
          "            then_env = dict(env)",
          "        if False and isinstance(st, ast.If):  # ДИВЕРСИЯ: ветки отброшены\n"
          "            then_env = dict(env)")
    return "make contracts"


def case_vacuous_requires():
    """Вакуумное предусловие: `false => anything` объявляется ДОКАЗАННЫМ.

    ЛОМАЕМ: снимаем отдельную проверку ВЫПОЛНИМОСТИ `requires`. Тогда
    `withdraw_vacuous` (противоречивое `amount > 10 and amount < 5` и
    НАМЕРЕННО сломанное тело) проходит как ДОКАЗАННЫЙ, а `--expect-demo`
    обязан покраснеть: детектор вакуумных контрактов не должен быть
    декоративным (УЛУЧШЕНИЕ №1).
    """
    patch("tools/kern_contracts.py",
          '                if "ДОКАЗАНО" in outv:',
          '                if False:  # ДИВЕРСИЯ: вакуумный requires не проверяем')
    return "make contracts"


def case_contract_lock():
    """Замок контрактов: ОСЛАБЛЕНИЕ спецификации не замечается.

    ЛОМАЕМ: удаляем строку `# @kern:ensures` из демо-файла — ровно тот чит,
    которым ИИ-агент «проходит» `make contracts`, не чиня код. Цель
    `contracts-lock-check` ОБЯЗАНА покраснеть (rc=2); если остаётся зелёной,
    замок бесполезен (УЛУЧШЕНИЕ №2).
    """
    patch("examples/contracts_demo.py",
          "# @kern:ensures  result == balance - amount and result < balance\n"
          "def withdraw(",
          "def withdraw(")
    return "make contracts-lock-check"


def case_diff_equiv():
    """Эквивалентность рефакторинга: РАСХОЖДЕНИЕ объявляется эквивалентным.

    ЛОМАЕМ: считаем «ДОКАЗАНО» всегда, поэтому пара `refactor_before/after`
    со ПЕРЕПУТАННЫМ знаком проходит как EQUIVALENT. Цель `diff-equiv`
    обязана покраснеть: доказательство эквивалентности, не отличающее
    сломанный рефакторинг от корректного, — фикция (УЛУЧШЕНИЕ №3).
    """
    # Дефект #243: классификация перенесена на вывод решателя (rc у
    # «доказано» и «опровергнуто» одинаковый). Диверсия подменяет ВЕРДИКТ,
    # а не проверку строки — иначе патч не нашёл бы цель и кейс стал бы
    # вакуумным.
    patch("tools/kern_contracts.py",
          '        verdict = classify_prove(rc, out)',
          '        verdict = "equivalent"  # ДИВЕРСИЯ: любая пара эквивалентна')
    return "make diff-equiv"


def case_self_verify():
    """Самоверификация: контракт СВОЕГО кода перестаёт доказываться.

    ЛОМАЕМ: в `examples/self_verify.zig` меняем `len - off` на `len + off` —
    остаток полезной нагрузки становится отрицательным, и `ensures result >= 0`
    обязано покраснеть. Цель `self-verify` — ПРОВЕРКА: если она остаётся
    зелёной, значит KERN «доказывает» что угодно про себя (Этап 2).
    """
    patch("examples/self_verify.zig",
          "    return len - off;",
          "    return len + off;  // ДИВЕРСИЯ: остаток может стать отрицательным")
    return "make self-verify"


def case_sarif_output():
    """SARIF: отчёт пуст, хотя нарушения ЕСТЬ (плашки в PR исчезнут молча).

    ЛОМАЕМ: `write_sarif` пишет пустой список `results`. Цель `sarif-check`
    обязана покраснеть: отчёт без находок бесполезен для Code Scanning
    (Этап 1).
    """
    patch("tools/kern_contracts.py",
          '            "results": results,',
          '            "results": [],  # ДИВЕРСИЯ: находки выброшены')
    return "make sarif-check"


def case_contracts_json():
    """JSON-отчёт контрактов: функции выброшены из отчёта (пустой `files`).

    ЛОМАЕМ: `write_json_report` пишет пустой список `files`. Цель
    `contracts-json` обязана покраснеть: пустой JSON-отчёт при реальных
    нарушениях ослепляет CI и агентов.
    """
    patch("tools/kern_contracts.py",
          '        "files": json_files,',
          '        "files": [],  # ДИВЕРСИЯ: функции выброшены из JSON')
    return "make contracts-json"


def case_hook_gate():
    """Git-шлюз: pre-commit пропускает СЛОМАННЫЙ контракт.

    ЛОМАЕМ: в теле хука снимаем проверку (`exit 0` вместо вызова проверки).
    Цель `hook-check` обязана покраснеть: хук, который ничего не блокирует, —
    декорация (Этап 1).
    """
    patch("tools/kern_contracts.py",
          '"$PY" tools/kern_contracts.py --git-diff HEAD --github-annotations || {',
          'exit 0  # ДИВЕРСИЯ: проверку контрактов пропускаем\n'
          'if false; then')
    return "make hook-check"


def case_slsa_bad_sig():
    """SLSA: Ed25519-подпись аттестата ПОДМЕНЕНА (портится 1 байт).

    ЛОМАЕМ: портим первый байт `kern.intoto.sig`. Проверка `--check` обязана
    покраснеть — иначе аттестат можно подменить незаметно, и «подпись» была бы
    декорацией (УЛУЧШЕНИЕ №13, закрытие ограничения «unsigned (no cosign)»).

    Запускаем ИМЕННО `--check`: `make slsa` пересобирает и ПЕРЕПОДПИСЫВАЕТ
    аттестат, поэтому порча подписи там «самолечилась» бы.
    """
    p = ROOT / "kern.intoto.sig"
    if not p.exists():
        return None  # нет ключа владельца -> подписи нет, кейс неприменим
    touch("kern.intoto.sig")
    txt = p.read_text(encoding="utf-8").strip()
    p.write_text(("f" if txt[0] != "f" else "0") + txt[1:] + "\n",
                 encoding="utf-8")
    return "python3 tools/slsa_provenance.py --check"


def case_edge_cases():
    """Крайние случаи парсера: цель `edge-cases` перестаёт видеть форму.

    ЛОМАЕМ: в `examples/edge_cases.zig` заменяем `x - y` на `x` — u32-underflow
    исчезает, и ожидаемый вердикт «ПЕРЕПОЛНЕНИЕ типа u32» больше не появляется.
    Цель `edge-cases` ОБЯЗАНА покраснеть: иначе она не проверяет парсер, а
    просто печатает текст.
    """
    patch("examples/edge_cases.zig",
          "    return x - y;   // u32: при y > x результат уходит в минус -> underflow",
          "    return x;       // ДИВЕРСИЯ: underflow убран")
    return "make edge-cases"


def case_trace_check():
    """Ступень 2 QuixBugs: цель `trace-check` перестаёт ловить расхождение.

    ЛОМАЕМ: в `tools/trace_explorer.py` сравнение значений `if nb != nc:`
    заменяется на `if False:` — движок больше не видит расхождений и
    объявляет «нет расхождения» на заведомо багованной функции.
    Цель `trace-check` ОБЯЗАНА покраснеть: иначе она проверяет не движок,
    а печатает текст (класс #130/#131/#132).
    """
    patch("tools/trace_explorer.py",
          "            if nb != nc:",
          "            if False:  # ДИВЕРСИЯ: сравнение отключено")
    return "make trace-check"


def case_ai_demo():
    """Стенд «KERN против ИИ»: цель `ai-demo` перестаёт видеть чит.

    ЛОМАЕМ: в `tools/kern_contracts.py` правило «проглоченное исключение»
    (`except: pass`) выключается. Стенд обязан покраснеть: если он всё равно
    печатает «обман пойман», то он проверяет не инструмент, а свой текст
    (класс #130/#131/#132).
    """
    patch("tools/kern_contracts.py",
          "            if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):",
          "            if False:  # ДИВЕРСИЯ: детектор проглоченных исключений отключён")
    return "make ai-demo"

def case_audits():
    """Золотой корпус аудитов: цель `audits` перестаёт видеть ядро.

    ЛОМАЕМ: путь к `kernc` в раннере указывает на несуществующий файл. Раннер
    ОБЯЗАН вернуть rc != 0, а не «напечатать таблицу и сделать вид, что всё
    проверено». Цель `audits` обязана покраснеть — иначе она не проверяет
    корпус, а просто печатает текст.
    """
    patch("tools/audits_run.py",
          'KERNC = ROOT / "zig-out" / "bin" / "kernc"',
          'KERNC = ROOT / "zig-out" / "bin" / "kernc-nonexistent"')
    return "make audits"


def case_model_negative():
    """Контрпример: в модель попадают ФУНКЦИИ С АРГУМЕНТАМИ.

    ЛОМАЕМ: снимаем фильтр 0-арности. Тогда в контрпример попадают не только
    значения входа, но и определения вида `(define-fun f ((x Int)) Int ...)` —
    пользователь видит мусор вместо значений, сломавших контракт (дефект #88).
    Тест «функции С АРГУМЕНТАМИ пропускаются» обязан это заметить.
    """
    patch("src/verifier/model_extract.zig",
          "if (args.len != 0) continue;",
          "if (false) continue;  # ДИВЕРСИЯ: функции с аргументами тоже берём")
    return "make test"


def case_codec_dispatch():
    """Кодеки: сжатый объект читается как СЫРОЙ (диспетчер отключён).

    ЛОМАЕМ: в `Codec.fromInt` код 0x02 возвращает `.raw`. Тогда сжатый объект
    начнёт выдаваться как обычный payload — содержимое станет мусором, а
    защита от подмены потеряет смысл. Тест «СЖАТИЕ: сквозной roundtrip»
    обязан это заметить.
    """
    patch("src/core/codec.zig", "            0x02 => .deflate,", "            0x02 => .raw,")
    return "make test"


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
    touch("tests/fixtures/valid_v1_3.kimg")
    if not p.exists():
        return None
    b = bytearray(p.read_bytes())
    b[130] ^= 0xFF          # внутри таблицы объектов
    p.write_bytes(bytes(b))
    return "zig build && ./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg"


def slsa_subject_path() -> str:
    """Путь к АТТЕСТУЕМОМУ бинарнику — из `SUBJECTS` самого чекера.

    🔴 ДЕФЕКТ #115 (найден ПОЛНЫМ прогоном canfail). Кейс `slsa` подсаживал
    `zig-out/bin/kernc`, а аттестуется ДРУГОЙ файл — `kernc-hermetic`
    (дефект #92 перевёл `SUBJECTS` на артефакт релиза, а кейс не обновили).
    Подсадка в НЕаттестуемый файл ничего не ломала: цель оставалась ЗЕЛЁНОЙ,
    кейс был ВАКУУМНЫМ, и у проверки SLSA НЕ БЫЛО доказательства, что она
    СПОСОБНА упасть. Имя берём из `SUBJECTS`, чтобы оно не разошлось снова.
    """
    import re as _re
    txt = (ROOT / "tools" / "slsa_provenance.py").read_text(encoding="utf-8")
    m = _re.search(r"SUBJECTS\s*=\s*\[([^\]]*)\]", txt)
    names = _re.findall(r'"([^"]+)"', m.group(1)) if m else []
    if not names:
        raise RuntimeError("в tools/slsa_provenance.py нет SUBJECTS — "
                           "кейс `slsa` не знает, ЧТО аттестуется")
    return f"zig-out/bin/{names[0]}"


def case_slsa_hash():
    """SLSA. ЛОМАЕМ: подменяем АТТЕСТУЕМЫЙ бинарник ПОСЛЕ аттестации."""
    rc, _ = sh_out("zig build && python3 tools/slsa_provenance.py --no-build", 300)
    if rc != 0:
        return None
    # touch(): кейс РЕАЛЬНО меняет этот файл -> Fault.__exit__ обязан его вернуть.
    # Без пометки механизм «откат только изменённых» (дефект #71) счёл бы
    # правку третьей стороной и НЕ восстановил бинарник.
    target = slsa_subject_path()
    touch(target)
    with open("/tmp/kernc_pad", "ab") as f:
        f.write(b"\x00" * 8)
    sh(f"cat /tmp/kernc_pad >> {target}", 60)
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
    touch("src/verifier/array_theory.zig")
    s = p.read_text(encoding="utf-8")
    if 'test "ARRAY' not in s:
        return None
    p.write_text(s.replace('test "ARRAY', 'test "ZZZ_'), encoding="utf-8")
    return "make arrays"


def case_grep_vacuity_litmus():
    """ГРЕП-ФИЛЬТР (#34), вторая цель. ЛОМАЕМ: переименовываем LITMUS-тесты."""
    p = ROOT / "src" / "tests" / "litmus_memory_test.zig"
    touch("src/tests/litmus_memory_test.zig")
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
    touch("src/verifier/admission_gate.zig")
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


def case_adversarial_payload():
    """Пытки. ЛОМАЕМ: отключаем сверку SHA-256(payload) с digest дескриптора.

    ЭТО НАБЛЮДАЕМЫЙ пробой: подменённый байт содержимого начнёт отдаваться
    читателю. Если `make adversarial` НЕ покраснеет — набор атак не способен
    поймать реальную подмену данных (дефект #14), то есть бесполезен.

    # #297: сверка продублирована в ДВУХ путях (raw и чтение) — ломаем ОБА,
    # иначе диверсия может не попасть в тот путь, который щупает цель.
    """
    patch_all("src/core/kernfs_router.zig",
              "        if (!std.crypto.timing_safe.eql([32]u8, got, obj.digest))",
              "        if (false and !std.crypto.timing_safe.eql([32]u8, got, obj.digest))")
    return "make adversarial"


def case_evidence_propagates():
    """Свидетельства. ЛОМАЕМ: добавляем `sorry` в Lean.

    Коллектор свидетельств ОБЯЗАН пробросить провал подпроверки наружу (RC!=0),
    а не «проглотить» его и записать зелёный лог. Иначе весь `docs/evidence/`
    превращается в декорацию.

    🔴 ДЕФЕКТ #114 (найден ПОЛНЫМ локальным прогоном canfail). Кейс запускал
    `make evidence-fast`, а тот пишет ~20 логов ПРЯМО В `docs/evidence/`.
    `Fault` восстанавливает только `formal/KernAllMath.lean`, поэтому ЛОГИ
    оставались снятыми В СОСТОЯНИИ ПРОБЫ (`sorry` в `lean_proofs.log`,
    провал Lean в `audit_manifest.log`) — ровно сценарий дефекта #70,
    только источник другой. В CI это незаметно (раннер эфемерный), локально
    же загрязняло ЗАКОММИЧЕННЫЕ свидетельства. Теперь коллектор пишет во
    ВРЕМЕННЫЙ каталог (`KERN_EVIDENCE_DIR`), репозиторий не трогается.
    """
    p = ROOT / "formal" / "KernAllMath.lean"
    touch("formal/KernAllMath.lean")
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_PROBE : True := by sorry\n")
    # 🔴 ДЕФЕКТ #175 (найден полным прогоном): вложенный сборщик брал
    # ТОТ ЖЕ базис /tmp/kern_evidence_guard.json, что и внешний, и — после
    # введения write-once (#173b) — УДАЛЯЛ его (`rm -f "$GUARD"`). Внешний
    # прогон после этого видел «нет снимка» и помечал КАЖДЫЙ следующий шаг
    # как «ВНЕШНЯЯ ПРАВКА ФАЙЛА!», хотя файлы были целы. Теперь у вложенного
    # прогона СВОЙ базис: он не может испортить чужой.
    return ("KERN_EVIDENCE_DIR=/tmp/kern-canfail-evidence "
            "GUARD=/tmp/kern_guard_nested.json "
            "make evidence-fast")


def case_telemetry_detects():
    """Телеметрия. ЛОМАЕМ: тот же `sorry` в Lean.

    Стенд обязан НЕ начислить балл за проверку Lean (иначе итог 100/100 —
    фикция). Проверяем на быстром режиме (та же логика начисления).
    """
    p = ROOT / "formal" / "KernAllMath.lean"
    touch("formal/KernAllMath.lean")
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
    touch("src/verifier/array_theory.zig")
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
          "        return bridge.executeStatus(q);\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ",
          "        _ = bridge.executeStatus(q);\n        return .Sat; // ЛОМАЕМ: всегда «баг найден»\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ")
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
    """NRA. ЛОМАЕМ: объявляем ЛИНЕЙНУЮ логику вместо нелинейной.

    # #297: `set-logic QF_NRA` есть в ∃- и ∀-проверке — ломаем ВСЕ.
    """
    patch_all("src/verifier/nra_quant.zig",
              r"\\(set-logic QF_NRA)",
              r"\\(set-logic QF_LIA) // ЛОМАЕМ: нелинейность не поддержана")
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


def case_attest_sig_missing():
    """Аттестат (0K.2/0K.3). ЛОМАЕМ: подпись НЕ предъявлена.

    Файл не трогаем — передаём несуществующий путь через `--sig`. Кейс
    проверяет РЕАЛЬНУЮ ветку «нет подписи»: до 0K.3 `--check` печатал
    «АТТЕСТАТ ВАЛИДЕН» при отсутствующей подписи, то есть подтверждал
    валидность ОТСУТСТВИЕМ доказательства.
    """
    return ("python3 tools/verify_attestation.py "
            "--sig /nonexistent/kern.intoto.sig")


def case_secret_in_tree():
    """Секреты (0K.4). ЛОМАЕМ: кладём ключ во временный файл.

    Дерево не трогаем: сканируется /tmp через `--path`. Проверка
    ОБЯЗАНА покраснеть, иначе сканер секретов — фикция.
    """
    return ("bash -c 'f=/tmp/kern_fake_secret.txt; "
            "printf \"nvapi-%030d\" 0 > $f; "
            "python3 tools/secrets_check.py --path $f; rc=$?; "
            "rm -f $f; exit $rc'")


def case_nondeterministic():
    """Детерминизм (0K.6). ЛОМАЕМ: подменяем ОЖИДАНИЕ вердикта.

    Стенд не меняется — значит расхождение может поймать только сверка
    результата с ожиданием. Если проверка промолчит, она бесполезна.
    """
    return "python3 tools/determinism_check.py --override unsat=F"


def case_changelog_drift():
    """CHANGELOG (0K.8). ЛОМАЕМ: файл без раздела текущей версии."""
    return ("bash -c 'f=/tmp/kern_changelog_drift.md; "
            "printf \"# Changelog\n\n## [0.0.1] - old\n\" > $f; "
            "python3 tools/changelog_check.py --path $f; rc=$?; rm -f $f; exit $rc'")


def case_lean_pin_drift():
    """Пин Lean (0K.7). ЛОМАЕМ: замок ждёт другую версию тулчейна."""
    return "python3 tools/lean_pin_check.py --override-lean 9.9.9"


def case_trust_docs_missing():
    """Документы доверия (0K.9). ЛОМАЕМ: пустой каталог вместо docs."""
    return ("bash -c 'mkdir -p /tmp/kern_trust_empty; "
            "python3 tools/trust_docs_check.py --dir /tmp/kern_trust_empty'")


def case_perf_regression():
    """Производительность (0K.12). ЛОМАЕМ: порог 0.01x и нулевой допуск.

    Замер не меняется — провал обязан дать именно СРАВНЕНИЕ с базой.
    """
    return "python3 tools/perf_check.py --threshold 0.01 --slack-ms -1000"


def case_citations_unknown_key():
    """Библиография (0J). ЛОМАЕМ: пустая bib -> все §REF становятся неизвестными.

    Проверяется именно резолвинг ключей: пустой каталог записей — это
    ситуация «источника нет», а не «источник другой».
    """
    return ("bash -c 'b=/tmp/kern_empty.bib; : > $b; "
            "python3 tools/citations_check.py --bib $b; rc=$?; "
            "rm -f $b; exit $rc'")


def case_axes_law_break():
    """Семь осей (Ф1). ЛОМАЕМ: таймаут объявлен ложью (`timeout -> F`).

    Это ровно та ошибка, из-за которой фаза и появилась: отсутствие
    результата не должно выглядеть как опровержение.
    """
    patch("src/next/state_axes.zig",
          "        .unknown, .timeout, .out_of_fuel, .invalid_certificate, .tool_error => .N,",
          "        .timeout => .F, // ЛОМАЕМ: таймаут объявлен ложью\n"
          "        .unknown, .out_of_fuel, .invalid_certificate, .tool_error => .N,")
    return "make axes-check"


def case_ledger_retract_break():
    """Журнал свидетельств (Ф2). ЛОМАЕМ: `n` не сбрасывается при пересчёте.

    Тогда `retract` ошибочного свидетельства НЕ снимает конфликт:
    состояние навсегда остаётся `B`, и отзыв становится фикцией.
    """
    patch("src/next/evidence_ledger.zig",
          "        var s = State{};",
          "        var s = State{ .n = self.snapshot.n }; // ЛОМАЕМ: n не сбрасывается")
    return "make ledger-check"


def case_graph_parity_break():
    """Граф G_src (Ф2). ЛОМАЕМ: требуем заведомо больше узлов, чем есть.

    Паритет проверяет не «файл существует», а совпадение множеств
    узлов и рёбер между ядром и витриной.
    """
    return "python3 tools/graph_parity.py --min-nodes 999"


def case_kimg_flag_policy():
    """KIMG (Ф3). ЛОМАЕМ: неизвестный REQUIRED-флаг больше не отвергается.

    Тогда образ, требующий неизвестного расширения, разбирается по
    старым правилам МОЛЧА — ровно то, от чего защищает политика.
    """
    patch("src/core/kimg_reader.zig",
          "        if (unknown_required != 0) return KimgError.UnsupportedRequiredFeature;",
          "        if (unknown_required == 0xFFFF_FFFF) return KimgError.UnsupportedRequiredFeature;")
    return "make storage-check"


def case_cache_key_13():
    """Кэш (Ф3). ЛОМАЕМ: `checker_version` перестаёт входить в ключ.

    Тогда смена версии чекера вернёт закэшированный вердикт,
    посчитанный ДРУГИМ чекером.
    """
    patch("src/proof_cache.zig",
          "                self.schema_hash, self.policy_hash, self.checker_version }) |f|",
          "                self.schema_hash, self.policy_hash }) |f|")
    return "make storage-check"


def case_kimg_cli():
    """CLI KIMG (Ф3.2). ЛОМАЕМ: требуем заведомо больше объектов.

    Внешний конформанс увидит только код возврата, поэтому CLI
    обязан падать, если файл не тот.
    """
    return "python3 tools/kimg_cli_check.py --min-objects 99"


def case_kimg_endianness():
    """KIMG (Ф3). ЛОМАЕМ: big-endian перестаёт отличаться от чужой версии."""
    patch("src/core/kimg_reader.zig",
          "            if (as_be == 1) return KimgError.WrongEndianness;",
          "            if (as_be == 999) return KimgError.WrongEndianness; // ЛОМАЕМ")
    return "make storage-check"


def case_kernfs_no_mmap():
    """KERNFS (Ф3). ЛОМАЕМ: `no-mmap` больше не копирует образ."""
    patch("src/core/kernfs_router.zig",
          "        const owned = try allocator.dupe(u8, image);",
          "        const owned = @constCast(image); // ЛОМАЕМ: срез чужого буфера")
    return "make storage-check"


def case_kernx_shared_fuel():
    """KERN-X (Ф3). ЛОМАЕМ: топливо «на прогон» вместо общего счётчика."""
    patch("src/runtime/kern_x.zig",
          "        self.pc = 0;\n        self.rsp = 0;",
          "        self.pc = 0;\n        self.rsp = 0;\n        self.budget.fuel.* = 100; // ЛОМАЕМ: свежее топливо")
    return "make storage-check"

def case_quixbugs_replay_break():
    """QuixBugs (Ф4). ЛОМАЕМ: требуем заведомо больше расхождений.

    Проверка читает СПИСОК задач из лога и прогоняет каждую заново;
    порог ловит случай, когда лог перестал соответствовать коду.
    """
    return "python3 tools/quixbugs_replay.py /tmp/QuixBugs-master --min-diverged 999"


def case_codecheck_fp():
    """Phase 4B. SABOTAGE: make a file that KERN refutes look "clean".

    ДЕФЕКТ #287 (найдено ревью): прежняя версия правила `py_abs_ok.py`
    (`expect T -> F`) при `got = T`, то есть давала пару (F, T) — это FN
    (пропущенный баг), а НЕ ложное обвинение. Кейс назывался `codecheck-fp`,
    доказывая другое свойство.

    Теперь правится `py_abs_bad.py`: там `got = F`, а ожидание ставим `T`.
    Пара (T, F) — это ровно FP: файл объявлен корректным, а KERN его обвинил.
    Врата обязаны покраснеть именно на FP.
    """
    patch("audits/codecheck/py_abs_bad.py.expect.json",
          '"expect": "F"', '"expect": "T"')
    return "make codecheck"


def case_hypotheses_nonproof():
    """Vector 3 SABOTAGE: гипотеза выдаётся, не будучи доказанной.

    Снимаем фильтр «кандидат обязан доказать контракт» (`if not (...): continue`
    -> `if False: continue`). Тогда `explain` печатает и такие условия, которые
    контрпример не отсекают, а `hypotheses-corpus-check` обязан это поймать на
    обратном прогоне: применяем гипотезу к копии — контракт НЕ доказан.
    """
    patch("tools/kern_contracts.py",
          '        if not ("ДОКАЗАНО" in out2 and rc2 == 0):\n'
          '            continue                      # кандидат НЕ отсекает контрпример',
          '        if False:\n'
          '            continue  # ЛОМАЕМ: выдаём недоказанные гипотезы')
    return "make hypotheses-corpus-check"


def case_hypotheses_write():
    """Ф6.3 SABOTAGE: объяснение начинает ПИСАТЬ в исходник.

    `before = _sha(...)` -> та же строка плюс дозапись в файл. Тогда sha256
    до/после расходятся, инструмент обязан вернуть 1, а гейт покраснеть.
    Это единственный способ доказать, что read-only реально проверяется.
    """
    patch("tools/kern_contracts.py",
          "    before = _sha(path.read_bytes()).hexdigest()",
          "    before = _sha(path.read_bytes()).hexdigest()\n"
          "    path.write_text(path.read_text(encoding='utf-8') + '\n', "
          "encoding='utf-8')  # ЛОМАЕМ: пишем в исходник")
    return "make explain-hypotheses-check"


def case_advisory_fold():
    """Ф6.1 SABOTAGE: advisory вердикт складывается в счётчик доказанного T.

    `advisory_ok += 1` -> `ok += 1`: summary печатает «доказано 2», то есть
    обещание `T_advisory` перестаёт отличаться от доказательства.
    Гейт обязан это поймать.
    """
    patch("tools/kern_contracts.py",
          "                    advisory_ok += 1",
          "                    ok += 1  # ЛОМАЕМ: advisory засчитан как T")
    return "make advisory-check"

def case_conformance_break():
    """Phase 5 META-CASE: break ONE requirement, the exam must go red.

    Sabotage: conflation (~) becomes the identity map. Section 3 asserts
    ~N = B, ~B = N and that ~ reverses <=k, so it must fail. This proves the
    exam is not a rubber stamp (its own `--selftest` covers the rest).
    """
    patch("src/core/eq2.zig",
          "return @enumFromInt(((1 - n) & 0b01) | (((1 - p) & 0b01) << 1));",
          "return @enumFromInt(((n) & 0b01) | (((1 - p) & 0b01) << 1)); // ЛОМАЕМ: ~ больше не инверсия")
    return "make conformance-check"


# ДЕФЕКТ #285: кейсы `artifact-check`/`artifact-check-offline` удалены.
# Они требовали объявленного в README sha256 бинарника, а дефект #250 убрал
# этот хардкод НАМЕРЕННО (он дрейфовал при каждом релизе). Без объявления
# `artifact_check.py` выходит с 1 всегда — то есть диверсия «доказывала»
# нечувствительность ворот, которых больше нет. Проверка артефакта остаётся
# релизной: там README объявляет хеш, и цепочка README<->сборка<->asset жива.

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
          "        var got: [32]u8 = undefined;\n        self.hash_algo.hash(sl, &got);\n        // КОНСТАНТНО-ВРЕМЕННАЯ СВЕРКА (УЛУЧШЕНИЕ №5, FIPS 140-3): обычный\n        // `mem.eql` выдаёт число совпавших байт по времени сравнения.\n        if (!std.crypto.timing_safe.eql([32]u8, got, obj.digest))\n            return KernFsError.PayloadTampered;",
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
          "        if (!std.crypto.timing_safe.eql([32]u8, root, h.root_digest)) {\n            cov.hit(.merkle_mismatch);\n            return KimgError.MerkleRootMismatch;\n        }\n        cov.hit(.merkle_ok);",
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
    touch("Makefile")
    s = p.read_text(encoding="utf-8")
    marker = "registry:\n"
    if marker not in s:
        raise RuntimeError("цель registry не найдена в Makefile")
    s = s.replace(marker, "canfail-probe-unclassified-target:\n\t@true\n\n" + marker, 1)
    p.write_text(s, encoding="utf-8")
    return "make registry"


def case_registry_dup_numbers():
    """Реестр (K5b). ЛОМАЕМ: дублируем НОМЕР дефекта в таблице.

    Дефект #88: при добавлении записи я создал дубликат #83 (номер был занят).
    Предохранитель обязан поймать повтор и вернуть ненулевой код.
    """
    p = ROOT / "docs" / "CAPABILITY_STATUS.md"
    touch("docs/CAPABILITY_STATUS.md")
    s = p.read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r"^\| \*\*(\d+)\*\*", s, _re.M)
    if not m:
        raise RuntimeError("в таблице дефектов нет ни одной строки")
    n = m.group(1)
    # Вторую по счёту строку делаем дубликатом первой.
    idxs = [mm.start() for mm in _re.finditer(r"^\| \*\*\d+\*\*", s, _re.M)]
    if len(idxs) < 2:
        raise RuntimeError("нужно минимум 2 строки дефектов")
    j = idxs[1]
    s = s[:j] + f"| **{n}** |" + s[j + len(f"| **{m.group(1)}** |"):]
    p.write_text(s, encoding="utf-8")
    return "make registry"


def case_evidence_guard():
    """Предохранитель #88. ЛОМАЕМ: правим FAULTABLE-файл ПОСЛЕ снимка.

    Сверка обязана заметить внешнюю правку и вернуть НЕНУЛЕВОЙ код. Без этого
    свидетельства, снятые при пропатченных исходниках, выглядели бы валидными.

    🔴 ДЕФЕКТ #173d: после введения «снимок пишется ОДИН раз» (защита от
    перезаписи базиса посреди прогона) старый `/tmp/guard_probe.json` от
    предыдущего запуска делал `--snapshot` красным по ЛОЖНОЙ причине: кейс
    «доказывал» падение сторожа, хотя падал сам снимок. Теперь базис кейса
    всегда свежий: `rm -f` + `--force`, и проверяется ИМЕННО реакция на правку.
    """
    touch("README.md")
    return ("rm -f /tmp/guard_probe.json && "
            "python3 tools/evidence_guard.py --snapshot /tmp/guard_probe.json --force && "
            "sed -i '1s/^/ /' README.md && "
            "python3 tools/evidence_guard.py --verify /tmp/guard_probe.json")


def case_ecosystem():
    """Внешние каталоги MCP. ЛОМАЕМ: выкидываем инструмент из server.json.

    Манифест перестаёт совпадать с `tools/list`, и `make ecosystem-check`
    обязан это заметить: иначе каталоги (m8ven/Smithery) снова увидят
    «tool surface unread», а мы — не узнаем.
    """
    touch("server.json")
    p = ROOT / "server.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["tools"] = d["tools"][:-1]
    write_atomic(p, (json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode())
    return "make ecosystem-check"


def case_scorecard():
    """Траст-карточка. ЛОМАЕМ: подменяем ОПУБЛИКОВАННЫЙ scorecard.json.

    Гейт обязан заметить, что карточка на сайте разошлась с пересчётом
    (класс дефекта #82: опубликованные числа устарели).
    """
    import json as _json
    touch("docs/evidence/scorecard.json")
    p = ROOT / "docs" / "evidence" / "scorecard.json"
    d = _json.loads(p.read_text(encoding="utf-8"))
    d["score"] = 41
    d["grade"] = "D"
    write_atomic(p, (_json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode())
    return "make scorecard-check"


def case_c_abi_null():
    """Хардкор-аудит C-ABI. ЛОМАЕМ: убираем NULL-защиту в `kern_kimg_valid`.

    C-тест передаёт NULL при len=200. Без проверки это SIGSEGV -> ненулевой код.
    """
    patch("src/capi.zig",
          "    if (isNull(img) or len < 128) return 0;",
          "    if (len < 128) return 0; // ЛОМАЕМ: NULL-защита убрана")
    return "make c-abi-test"


def case_c_abi_hash():
    """Хардкор-аудит C-ABI. ЛОМАЕМ: хэшируем только ПЕРВЫЙ байт входа.

    Тест потоков сверяет результат с КОНСТАНТОЙ (независимый BLAKE3),
    поэтому такой мутант обязан упасть.
    """
    patch("src/capi.zig",
          "    a.hash(data[0..len], &out);",
          "    a.hash(data[0..@min(len, 1)], &out); // ЛОМАЕМ: не весь вход")
    return "make c-abi-threads"


def case_semantic_gap():
    """Эшелон 4 (Lean). ЛОМАЕМ: добавляем `sorry` в KernSemanticGap.lean."""
    p = ROOT / "formal" / "KernSemanticGap.lean"
    touch("formal/KernSemanticGap.lean")
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
          "compat.fileReadToEndAlloc(sout, self.allocator, self.max_stdout)",
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
          "        return bridge.executeStatus(q);\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ",
          "        _ = bridge.executeStatus(q);\n        return .Sat; // ЛОМАЕМ\n    }\n};\n\n// =========================================================================\n// ТЕСТЫ")
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
    touch("formal/certification/TRACEABILITY_MATRIX.md")
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
    touch("tests/fixtures/valid_v1_3.kimg")
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


def case_model_verify_spurious():
    """Проверка SAT-модели (пункт 2 плана v2.5). ЛОМАЕМ: ЛЮБАЯ модель верна.

    Если falsifiable-тест «ЛОЖНЫЙ ассерт -> spurious» исчезнет, фальшивый
    контрпример снова дойдёт до пользователя: KERN предъявит значения, которые
    контракт НЕ нарушают, и человек пойдёт «чинить» корректный код. Тест
    `MODEL CHECK: ЛОЖНЫЙ ассерт -> spurious` обязан покраснеть.
    """
    patch(
        "src/verifier/model_extract.zig",
        "        if (!truth) return .{ .spurious = .{ .index = checked, .term = term } };",
        "        if (!truth) return .{ .ok = checked }; // ЛОМАЕМ: ложный ассерт верен",
    )
    return "make test"



def case_float_nan_check():
    """ПУНКТ 22. ЛОМАЕМ: доверенный шаг выдаём за проверенный ->
    цель обязана покраснеть (требует trusted: 0)."""
    patch(
        "src/verifier/proof_check.zig",
        "        saw_remaining = true;",
        "        saw_remaining = false;  # ЛОМАЕМ: доверенный шаг за проверенный",
    )
    return "make float-nan-check"


def case_string_contracts_check():
    """ПУНКТ 23. ЛОМАЕМ: то же правило резолюции -> цель краснеет."""
    patch(
        "src/verifier/proof_check.zig",
        "        saw_remaining = true;",
        "        saw_remaining = false;  # ЛОМАЕМ: доверенный шаг за проверенный",
    )
    return "make string-contracts-check"


def case_polyglot7_check():
    """ЭШЕЛОН 5, ПУНКТ 25. ЛОМАЕМ: TS/JS/Go-функции перестают разбираться (тип
    `int32` выпадает из таблицы диапазонов) -> цели `polyglot-7-check` обязана
    покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '    "int32": (-2**31, 2**31 - 1), "uint32": (0, 2**32 - 1),',
        '    "int32XX": (-2**31, 2**31 - 1), "uint32": (0, 2**32 - 1),',
    )
    return "make polyglot-7-check"


def case_double_spend_check():
    """ПУНКТ 28. ЛОМАЕМ: сообщение `[FAIL] ... REFUTED` превращаем в `[INFO]` ->
    гонка двойного списания перестаёт быть видимой -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        "                    print(f\"  [FAIL] {fn.name}: {kind} REFUTED — {first_fail}\")",
        "                    print(f\"  [INFO] {fn.name}: {kind} REFUTED — {first_fail}\")",
    )
    return "make double-spend-check"


def case_ffi_bridge_check():
    """ПУНКТ 29. ЛОМАЕМ: `_prove_checked` объявляет SAT как UNSAT -> усечение
    в i32/u32 перестаёт ловиться -> цель обязана покраснеть.

    ИЗМЕРЕНО (6-й вакуумный кейс): первый патч бил в `_smt_verdict`, а пресеты
    идут через `_prove_checked` — цель оставалась зелёной. Якорь —
    `return ("sat", ce, None)` (уникален для `_prove_checked`)."""
    patch(
        "tools/kern_contracts.py",
        '        return ("sat", ce, None)',
        '        return ("unsat", ce, None)',
    )
    return "make ffi-bridge-check"


def case_pricing_matrix_check():
    """ПУНКТ 31. ЛОМАЕМ: сообщение PRICING GAP превращаем в `[INFO]` -> дыра в
    тарифах перестаёт быть видимой -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '                print(f\"  [FAIL] {fn.name}: PRICING GAP (unhandled input, \u043f\u0443\u0442\u044c {i + 1}) \u2014 {ce}\")',
        '                print(f\"  [INFO] {fn.name}: PRICING GAP (unhandled input, \u043f\u0443\u0442\u044c {i + 1}) \u2014 {ce}\")',
    )
    return "make pricing-matrix-check"


def case_sql_policy_check():
    """ПУНКТ 30. ЛОМАЕМ: сообщение RLS BYPASS превращаем в `[INFO]` -> обход
    изоляции тенантов перестаёт быть видимым -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '                    print(f"  [FAIL] {fn.name}: RLS POLICY BYPASS FOUND "',
        '                    print(f"  [INFO] {fn.name}: RLS POLICY BYPASS FOUND "',
    )
    return "make sql-policy-check"


def case_anti_cheat_check():
    """ПУНКТ 32. ЛОМАЕМ: сообщение CHEAT DETECTED превращаем в `[INFO]` -> читы перестают
    быть видимыми -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '        print(f"  [CHEAT DETECTED: {kind}] строка {ln}")',
        '        print(f"  [INFO] {kind}] строка {ln}")',
    )
    return "make anti-cheat-check"


def case_mcp_audit_check():
    """ПУНКТ 33. ЛОМАЕМ: сверка замка отключена -> rug-pull не ловится."""
    patch(
        "tools/kern_contracts.py",
        '                if name in old and old[name] != h:',
        '                if False and name in old and old[name] != h:',
    )
    return "make mcp-audit-check"


def case_noninterference_check():
    """ПУНКТ 34. ЛОМАЕМ: сообщение SECRET LEAK -> `[INFO]` -> утечка не видна."""
    patch(
        "tools/kern_contracts.py",
        '            print(f"  [FAIL] {fn.name}: SECRET LEAK / NON-INTERFERENCE VIOLATED — {ce}")',
        '            print(f"  [INFO] {fn.name}: SECRET LEAK / NON-INTERFERENCE VIOLATED — {ce}")',
    )
    return "make noninterference-check"


def case_belnap_swarm_check():
    """ПУНКТ 35. ЛОМАЕМ: JOIN_K теряет n-бит (противоречие не запоминается)."""
    patch(
        "src/next/truth.zig",
        "        return .{ .p = a.p or b.p, .n = a.n or b.n };",
        "        return .{ .p = a.p or b.p, .n = false };",
    )
    return "make belnap-swarm-check"


def case_action_firewall_check():
    """ПУНКТ 36. ЛОМАЕМ: сообщение ALLOW VIOLATED -> `[INFO]` -> превышение
    бюджета перестаёт быть видимым -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '            print(f"  [FAIL] Firewall: ALLOW VIOLATED -> F (0,1), e=0, "',
        '            print(f"  [INFO] Firewall: ALLOW VIOLATED -> F (0,1), e=0, "',
    )
    return "make action-firewall-check"


def case_rag_conflict_check():
    """ПУНКТ 37. ЛОМАЕМ: сообщение CONFLICT B(1,1) -> `[INFO]` -> противоречие
    в документе не видно."""
    patch(
        "tools/kern_contracts.py",
        '    print(f"  [FAIL] CONFLICT B(1,1): document UNSAT (trusted: 0 | holes: 0), "',
        '    print(f"  [INFO] CONFLICT B(1,1): document UNSAT (trusted: 0 | holes: 0), "',
    )
    return "make rag-conflict-check"


def case_rlvr_oracle_check():
    """ПУНКТ 38. ЛОМАЕМ: штраф за чит становится ПОЛОЖИТЕЛЬНЫМ
    (+2.0) -> оракул лжёт -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        '        print(f"[REWARD] R=-2.0 [REWARD HACKING PENALTY, Belnap F] "',
        '        print(f"[REWARD] R=+2.0 [REWARD HACKING PENALTY, Belnap F] "',
    )
    return "make rlvr-oracle-check"


def case_audit_repo_check():
    """УНИВЕРСАЛЬНЫЙ АУДИТОР. ЛОМАЕМ: блок «ТОП-5 по Маккейбу» не печатается ->
    приёмка (grep этого блока) обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        "        if worst:\n            print(\"  ТОП-5 по Маккейбу:\")",
        "        if False:\n            print(\"  ТОП-5 по Маккейбу:\")",
    )
    return "make audit-repo-check"


def case_bug_hunt_check():
    """ПУНКТ 39. ЛОМАЕМ: `scan()` всегда возвращает пусто -> КОНТРОЛЬ
    (известные находки) перестаёт проходить -> цель краснеет."""
    patch(
        "tools/bug_hunter.py",
        "    found = [ln.strip() for ln in out.splitlines() if RE_FIND.search(ln)]",
        "    found = []",
    )
    return "make bug-hunt-check"


def case_html_canvas_check():
    """ПУНКТ 40Б. ЛОМАЕМ: путь к шаблону сломан -> холст
    не создаётся -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        'CANVAS_TMPL = Path(__file__).resolve().parent / "canvas_template.html"',
        'CANVAS_TMPL = Path(__file__).resolve().parent / "no_such_template.html"',
    )
    return "make html-canvas-check"


def case_fuzz_corpus_check():
    """ПУНКТ 40Д. ЛОМАЕМ: итоговая строка "0 паник" -> `[FAIL]`
    -> приёмка не видит подтверждения детерминизма."""
    patch(
        "tools/fuzz_corpus_check.py",
        '    print("  [OK] 0 паник, 0 segfault, 0 утечек (детерминизм подтверждён)")',
        '    print("  [FAIL] 0 паник, 0 segfault, 0 утечек (детерминизм подтверждён)")',
    )
    return "make fuzz-corpus-check"



def case_wasm_check():
    """ПУНКТ 40А. ЛОМАЕМ: экспорт переименован -> в байтах модуля его нет
    -> приёмка обязана покраснеть (магия и размер останутся верными!)."""
    patch(
        "src/wasm_api.zig",
        "export fn kern_wasm_belnap_allow(v: u8) u8 {",
        "export fn kern_wasm_belnap_allowX(v: u8) u8 {",
    )
    return "make wasm-check"


def case_kimg_grep_check():
    """ПУНКТ 40В. ЛОМАЕМ: `rc=1 при отсутствии` -> `rc=0`
    (поиск «всегда находит») -> приёмка обязана покраснеть."""
    patch(
        "src/main.zig",
        "        if (hits == 0) std.process.exit(1);",
        "        if (hits == 0) std.process.exit(0);",
    )
    return "make kimg-grep-check"



def case_dst_check():
    """РАЗДЕЛ 7. ЛОМАЕМ: Врата открываются БЕЗ T (инвариант 1) -> kern-dst
    обязан вернуть rc!=0, приёмка покраснеть."""
    patch(
        "src/next/truth.zig",
        "    return if (b.p and !b.n) 1 else 0;",
        "    return 1;",
    )
    return "make dst-check"



def case_homeostatic_heal_check():
    """ГОМЕОСТАЗ. ЛОМАЕМ: гард вставляется, но ПЕРЕПРОВЕРКА отключена
    (всегда «0 крашей») -> приёмка обязана покраснеть: файл без патча
    нельзя объявлять вылеченным."""
    # ЛОМАЕМ САМО ЛЕЧЕНИЕ, а не откат: гард НЕ вставляется в файл.
    # Тогда после --heal краши остаются, и приёмка обязана покраснеть.
    patch(
        "tools/kern_contracts.py",
        'lines.insert(idx, f"{indent}if {guard_py}:  # [KERN HEAL] {fname}: защита от деления на 0")',
        'pass  # [canfail] гард НЕ вставляется',
    )
    return "make homeostatic-heal-check"



def case_opt_diff_check():
    """РАЗДЕЛ 5. ЛОМАЕМ САМ ГЕЙТ (а не src/main.zig!): иначе инвалидируется кэш
    Zig и 3 полные сборки внутри кейса упираются в таймаут (ИЗМЕРЕНО: 90 с).
    Теперь успешная ветка недостижима -> rc=1, приёмка краснеет за миллисекунды.
    """
    patch(
        "tools/opt_diff_check.sh",
        '[ "$fail" -eq 0 ] && { echo \'[OK] opt-diff-check: 0 расхождений\'; exit 0; }',
        '[ "$fail" -eq 99 ] && { echo \'[OK] opt-diff-check: 0 расхождений\'; exit 0; }',
    )
    return "make opt-diff-check"



def case_concolic_check():
    """РАЗДЕЛ 5. ЛОМАЕМ извлечение модели: Z3 больше не даёт новых входов ->
    покрытие падает, и приёмка обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        "    return vals if vals else None",
        "    return None",
    )
    return "make concolic-check"



def case_translation_val_check():
    """РАЗДЕЛ 8. ЛОМАЕМ семантику `andn`: пара sar+andn перестаёт сворачиваться
    в `x<0?0:x` -> ассемблер больше не эквивалентен спецификации -> красный."""
    patch(
        "tools/translation_val_check.py",
        'cur = "(ite (< x 0) 0 x)" if (mask and "- 1" in mask) else "x"',
        'cur = "x"',
    )
    return "make translation-val-check"



def case_evo_fuzz_check():
    """РАЗДЕЛ 1/5. ЛОМАЕМ оракул: эталон принимается как «ложный допуск»
    (сравнение вывода отключено) -> фаззер обязан покраснеть."""
    # ЛОМАЕМ ПОЗИТИВНЫЙ КОНТРОЛЬ: эталон объявляется НЕпринятым -> фаззер
    # завершается с rc=1 и приёмка краснеет. (Поломка счётчика ложных допусков
    # давала ВАКУУМНЫЙ кейс — ИЗМЕРЕНО.)
    patch(
        "tools/evo_fuzzer.py",
        "    if rc0 != 0:",
        "    if rc0 == 0:",
    )
    return "make evo-fuzz-check"



def case_parser_security_check():
    """ЗАЩИТА ПАРСЕРА. ЛОМАЕМ tokenize-фильтр: подделка внутри строки снова
    считается контрактом -> приёмка обязана покраснеть."""
    # ЛОМАЕМ ИМЕННО ЗАЩИТУ: возвращаем УЯЗВИМЫЙ построчный обход (как было до
    # tokenize) -> подделка внутри строкового литерала снова «видна».
    patch(
        "tools/kern_contracts.py",
        "    anchors: dict[int, dict[str, str]] = _py_comment_anchors(src)",
        "    anchors: dict[int, dict[str, str]] = {}\n"
        "    for _i, _ln in enumerate(lines, 1):\n"
        "        _m = ANNOT.match(_ln)\n"
        "        if _m: anchors.setdefault(_i, {})[_m.group(1)] = _m.group(2)",
    )
    return "make parser-security-check"



def case_hadamard_check():
    """ЭКСТРЕМАЛЬНАЯ МАТРИЦА. ЛОМАЕМ успешную ветку (rc=1 на корректном
    входе) -> приёмка обязана покраснеть."""
    patch(
        "examples/hadamard_matrix.py",
        "    return 0 if ok else 1",
        "    return 1",
    )
    return "make hadamard-check"


def case_presets_check():

    """ЭШЕЛОН 5, ПУНКТ 26. ЛОМАЕМ: сообщение `[FAIL] ... REFUTED` превращаем в
    `[INFO]` -> нарушение пресета перестаёт быть видимым -> цель обязана
    покраснеть (иначе `make presets-check` вакуумна)."""
    patch(
        "tools/kern_contracts.py",
        "                print(f\"  [FAIL] {fn.name}: {label} REFUTED — {ce}\")",
        "                print(f\"  [INFO] {fn.name}: {label} REFUTED — {ce}\")",
    )
    return "make presets-check"


def case_arbitrage_check():
    """ЭШЕЛОН 5, ПУНКТ 27. ЛОМАЕМ: арбитраж (дробление платежа выгоднее целого)
    перестаёт помечаться -> цель обязана покраснеть."""
    patch(
        "tools/kern_contracts.py",
        "                print(f\"  [FAIL] {fn.name}: {label} REFUTED — {ce}\")",
        "                print(f\"  [INFO] {fn.name}: {label} REFUTED — {ce}\")",
    )
    return "make arbitrage-check"


def case_state_inv_check():
    """ПУНКТ 24. ЛОМАЕМ: вердикт SAT объявляем UNSAT -> нарушение инварианта
    перестаёт ловиться -> цель обязана покраснеть."""
    # ИЗМЕРЕНО (5-й вакуумный кейс): я патчил `_smt_counterexample`, но Пункт 24
    # использует ТРЁХЗНАЧНЫЙ `_smt_verdict` -> патч не влиял -> цель зелёная.
    # Правильный якорь — строка FAIL-сообщения в `cmd_state_inv`.
    patch(
        "tools/kern_contracts.py",
        "                out.append(f\"[FAIL] {fn.name}: STATE INVARIANT VIOLATED at line {ln}; \"",
        "                out.append(f\"[INFO] {fn.name}: STATE INVARIANT VIOLATED at line {ln}; \"",
    )
    return "make state-inv-check"


def case_loop_check():
    """ПУНКТ 20. ЛОМАЕМ: вердикт SAT объявляем UNSAT -> нарушение инварианта и
    незавершающийся цикл перестают ловиться -> цель обязана покраснеть.

    # #297: `if "КОНТРПРИМЕР" in out:` встречается трижды. Нужен путь,
    # который щупает `make loop-check` — тот, где контрпример разбирается
    # построчно (первое вхождение); якорь уточнён следующей строкой.
    """
    patch(
        "tools/kern_contracts.py",
        "    if \"КОНТРПРИМЕР\" in out:\n        for ln in out.splitlines():",
        "    if False:  # ЛОМАЕМ: игнорируем контрпримеры\n        for ln in out.splitlines():",
    )
    return "make loop-check"


def case_bounds_check():
    """ПУНКТ 21. ЛОМАЕМ детектор границ: контрпримеры игнорируются ->
    get_unsafe перестаёт обвиняться -> цель обязана покраснеть."""
    # ИЗМЕРЕНО (Дефект #140): после архитектурной ревизии Пункта 21 код
    # `_walk_bounds` изменился (`if ce is not None:` -> трёхзначный `if v == "sat":`),
    # и старый якорь стал НЕПРИМЕНИМЫМ (harness сообщил «якоря не применимы»).
    # Якорь сделан УНИКАЛЬНЫМ (двухстрочным), чтобы патч не мог уйти в `check_loop`.
    patch(
        "tools/kern_contracts.py",
        "            v, ce = _smt_verdict(kernc, decls, pre + path + [bad])",
        "            v, ce = (\"unsat\", None)  # ЛОМАЕМ: игнорируем контрпримеры",
    )
    return "make bounds-check"


def case_simplify_check():
    """ПУНКТ 17. ЛОМАЕМ: решатель объявляет ЛЮБУЮ ветку недостижимой ->
    --simplify вырежет ЖИВЫЕ ветки, и НЕЗАВИСИМАЯ рантайм-сверка обязана
    это поймать (цель краснеет)."""
    # ИЗМЕРЕНО: первый вариант кейса ломал `if "НЕ доказано" ...` -> SAT
    # превращался в `None` (unknown), живые ветки НЕ вырезались, цель оставалась
    # зелёной => ВАКУУМНЫЙ кейс (Дефект #133). Правильная поломка: объявить
    # SAT как UNSAT (`return True` -> `return False`) — тогда ВСЕ ветки
    # считаются мёртвыми и вырезаются ЖИВЫЕ, что обязана поймать
    # НЕЗАВИСИМАЯ рантайм-сверка поведения.
    patch(
        "tools/kern_contracts.py",
        "    kind, _ce = _smt_verdict(kernc, params, asserts)",
        '    kind = "unsat"  # ЛОМАЕМ: SAT объявляем невыполнимым',

    )
    return "make simplify-check"


def case_xray_check():
    """ПУНКТ 13. ЛОМАЕМ: подмена порога в условии фикстуры делает мёртвую ветку
    ЖИВОЙ, поэтому --xray ОБЯЗАН перестать её находить и цель покраснеть."""
    patch(
        "examples/xray_demo.py",
        "    elif x > 10:  # НЕДОСТИЖИМА: перекрыта первым условием",
        "    elif x > 5:  # ЛОМАЕМ: ветка СТАНОВИТСЯ достижимой",
    )
    return "make xray-check"


def case_gen_tests_check():
    """ПУНКТ 14. ЛОМАЕМ ГЕНЕРАТОР: эталонный ответ считается с ошибкой (+1).

    ИЗМЕРЕНО (первая версия кейса была ВАКУУМНОЙ): поломка ФИКСТУРЫ
    вакуумна по построению — генератор берёт эталон ИСПОЛНЕНИЕМ той же
    функции, поэтому ожидание и факт согласованы. Правильная поломка —
    сам генератор: тогда сгенерированные тесты обязаны УПАСТЬ.
    """
    patch(
        "tools/kern_contracts.py",
        "                    expected = ns[fnname](*[model.get(p, 0) for p in params])",
        "                    expected = ns[fnname](*[model.get(p, 0) for p in params]) + 1  # ЛОМАЕМ",
    )
    return "make gen-tests-check"


def case_pcc_check():
    """ПУНКТ 9. ЛОМАЕМ: PCC принимает ЛЮБОЙ сертификат (условие приёмки -> true).

    ИЗМЕРЕНО (первая версия кейса была ВАКУУМНОЙ): поломка `checksPass()`
    НЕ отключала поимку — подделку ловил `proof_concludes_false`, поэтому цель
    оставалась зелёной. Правильная поломка — именно условие приёмки в PCC.
    """
    patch(
        "src/main.zig",
        "                            if (v.checksPass() and v.proof_concludes_false and v.trusted_steps == 0) {",
        "                            if (true) { // ЛОМАЕМ: любой сертификат принят",
    )
    return "make pcc-check"


def case_bitrot_chaos():
    """ПУНКТ 12. ЛОМАЕМ: глубокую проверку данных в check-integrity.

    Убираем пересчёт дайджестов объектов — тогда порча ДАННЫХ (bit-rot)
    снова перестанет ловиться, и хаос-тест обязан покраснеть.
    """
    patch(
        "src/main.zig",
        "            for (fs.objects, 0..) |obj, oi| {",
        "            for (fs.objects, 0..) |obj, oi| { if (true) continue; // ЛОМАЕМ",
    )
    return "make bitrot-chaos"


def case_binary_audit():
    """АППАРАТНО-БИНАРНЫЙ АУДИТ. ЛОМАЕМ: инвертируем проверку флагов стека.

    Тогда неисполняемый стек (`GNU_STACK RW` без `E`) будет объявлен ПРОВАЛОМ —
    цель обязана покраснеть. Это доказывает, что путь отказа ВЕДЁТ к rc != 0,
    то есть аудит реально способен упасть.
    """
    patch(
        "tools/hw_binary_audit.py",
        "        if \"E\" in flags:",
        "        if \"E\" not in flags:  # ЛОМАЕМ: RW объявляем провалом",
    )
    return "make binary-audit"


def case_tree_lock():
    """ДЕФЕКТ #126. ЛОМАЕМ: при занятом замке второй экземпляр НЕ выходит.

    Тогда он начнёт править дерево параллельно — ровно та гонка, которая
    оставила мутации в файле (§81.23). Проверка обязана покраснеть.
    """
    patch(
        "tools/tree_lock.py",
        "        sys.exit(2)",
        "        return  # ЛОМАЕМ: выхода нет, второй экземпляр пойдёт править",
    )
    return "make tree-lock"


def case_proof_tamper():
    """ИСПЫТАНИЕ А. ЛОМАЕМ: пруф-чекер объявляет ЛЮБОЙ вывод подтверждённым.

    Тогда адверсариальный фаззер обязан ПОКРАСНЕТЬ: 30 подделок реального
    вывода abs.c будут «приняты». Если `make proof-tamper` не краснеет,
    фаззер бесполезен, а `trusted: 0` на abs.c ничего не гарантирует.
    """
    patch(
        "src/verifier/proof_check.zig",
        "        if (self.proof_steps == 0) return false;",
        "        if (self.proof_steps > 0) return true; // ЛОМАЕМ: всё «подтверждено»",
    )
    return "make proof-tamper"


def case_lia_soundness():
    """Встроенный LIA-решатель (пункт 1 v2.5). ЛОМАЕМ: всегда «доказано».

    Если `make lia-diff` не покраснеет, дифференциальный гейт против Z3
    бесполезен, и встроенный решатель сможет выдавать ЛОЖНЫЕ «доказано» —
    ровно тот исход, против которого построен проект.
    """
    patch(
        "src/verifier/builtin_lia.zig",
        "pub fn checkUnsatFallible(self: *Solver, input: []const Lin) !Verdict {\n"
        "    var set = std.ArrayListUnmanaged(Lin).empty;",
        "pub fn checkUnsatFallible(self: *Solver, input: []const Lin) !Verdict {\n"
        "    if (input.len > 0) return .unsat; // ЛОМАЕМ: всегда «доказано»\n"
        "    var set = std.ArrayListUnmanaged(Lin).empty;",
    )
    return "make lia-diff"


def case_metrics_guard():
    """Счётчики на витрине (класс #220/#223). ЛОМАЕМ: число каталога в PROJECT.md.

    `make metrics-guard` сверяет обещания с ИЗМЕРИМЫМИ свидетельствами
    (`core_tests.log`, `kern_next_tests.log`, пересчёт каталога, `registry.py`).
    Если подмена числа проходит незамеченной, витрина снова начнёт врать
    (ровно это и случилось: 308/424 вместо 401/425 и «120 Lean 4 theorems»
    при фактических 137).
    """
    touch("docs/PROJECT.md")
    p = ROOT / "docs" / "PROJECT.md"
    s = p.read_text(encoding="utf-8")
    # ДЕФЕКТ #282: якорь был ЖЁСТКО зашит как «**425 объявлений**», а `make sync`
    # переписывает это число (каталог вырос до 464) — кейс падал с
    # AssertionError ещё до диверсии. Ищем число шаблоном, а не литералом.
    import re as _re
    pattern = _re.compile(r"\*\*\d+ объявлений\*\*")
    bad, n = pattern.subn("**999 объявлений**", s, count=1)
    assert n == 1 and bad != s, "якорь каталога в PROJECT.md не найден — кейс не сломает гейт"
    write_atomic(p, bad.encode())
    return "make metrics-guard"


CASES = [
    ("avalanche",     "лавина SHA-256 (Hash Flooding)",       case_avalanche),
    ("bench-json",    "Детерминированный бенчмарк: деградация хэша", case_bench_json),
    ("lean-sorry",    "Lean: отсутствие `sorry`",              case_lean_sorry),
    ("binlevel",      "constant-time (ранний выход)",          case_binlevel_earlyexit),
    ("svg-overflow",  "SVG: подпись выходит за панель",     case_svg_overflow),
    ("evidence-gate",  "Свидетельства: лог с RC!=0",        case_evidence_gate),
    ("metrics-guard", "Счётчики витрины разошлись с фактами", case_metrics_guard),
    ("proof-hole",     "Пруф-чекер: правило hole",          case_proof_checker_hole),
    ("simd8-masking",  "SIMD-8: полосное маскирование",      case_simd8_masking),
    ("mcp-selftest",   "MCP: конфликт T⊔F схлопнут в T",    case_mcp_server),
    ("contracts",      "Контракты: нарушение объявлено доказанным", case_contracts),
    ("vacuous-requires", "Контракты: вакуумное requires = «доказано»", case_vacuous_requires),
    ("contract-lock",  "Контракты: ослабление спецификации не замечено", case_contract_lock),
    ("diff-equiv",     "Рефакторинг: расхождение объявлено эквивалентным", case_diff_equiv),
    ("self-verify",    "Самоверификация: контракт своего кода сломан", case_self_verify),
    ("edge-cases",     "Парсер: крайняя форма перестала разбираться", case_edge_cases),
    ("trace-check",    "Ступень 2: расхождение перестало ловиться", case_trace_check),
    ("ai-demo",        "стенд «ИИ против KERN»: чит перестал ловиться", case_ai_demo),
    ("audits",         "Аудиты: раннер перестал видеть ядро", case_audits),
    ("sarif-output",   "SARIF: находки выброшены из отчёта", case_sarif_output),
    ("contracts-json", "JSON контрактов: функции выброшены из отчёта", case_contracts_json),
    ("hook-gate",      "Git-шлюз: сломанный контракт пропущен", case_hook_gate),
    ("slsa-bad-sig",   "SLSA: Ed25519-подпись аттестата подменена", case_slsa_bad_sig),
    ("codec-dispatch",  "Кодеки: сжатый объект как raw",        case_codec_dispatch),
    ("model-negative",  "Контрпример: (- N) не свёрнут",      case_model_negative),
    ("contracts-branches", "Ветвления: if отброшен",           case_contracts_branches),
    ("kimg-deflate",    "Сжатие: --deflate не сжимает",     case_kimg_deflate),
    ("skip-exit-n",     "kernx: SKIP (exit 2) -> F вместо N",  case_skip_exit_n),
    ("version-consistency", "Версия: баннер != --version",      case_version_consistency),
    ("proof-binding",  "Пруф-чекер: привязка посылок",        case_proof_checker_binding),
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
    ("adversarial-payload",   "Подмена payload (SHA-256)",      case_adversarial_payload),
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
    ("attest-sig-missing", "Аттестат: подписи нет -> проверка падает",
     case_attest_sig_missing),
    ("secret-in-tree", "Секреты: ключ в файле -> скан падает",
     case_secret_in_tree),
    ("nondeterministic", "Вердикт недетерминирован -> проверка падает",
     case_nondeterministic),
    ("changelog-drift", "Версия без раздела CHANGELOG -> падает",
     case_changelog_drift),
    ("lean-pin-drift", "Тулчейн не совпал с замком -> падает",
     case_lean_pin_drift),
    ("trust-docs-missing", "Нет документов доверия -> падает",
     case_trust_docs_missing),
    ("perf-regression", "Регресс производительности -> падает",
     case_perf_regression),
    ("citations-unknown-key", "Нет источника -> ссылки не резолвятся",
     case_citations_unknown_key),
    ("axes-law-break", "timeout объявлен F -> законы осей падают",
     case_axes_law_break),
    ("ledger-retract-break", "retract не снимает конфликт -> падает",
     case_ledger_retract_break),
    ("graph-parity-break", "Графы разошлись -> паритет падает",
     case_graph_parity_break),
    ("kimg-flag-policy", "REQUIRED-флаг не отвергается -> падает",
     case_kimg_flag_policy),
    ("cache-key-13", "ключ кэша теряет поле -> падает",
     case_cache_key_13),
    ("kimg-cli", "CLI не падает на чужом файле", case_kimg_cli),
    ("kimg-endianness", "BE не отличается от версии -> падает",
     case_kimg_endianness),
    ("kernfs-no-mmap", "no-mmap не копирует -> падает",
     case_kernfs_no_mmap),
    ("kernx-shared-fuel", "топливо на прогон -> падает",
     case_kernx_shared_fuel),
    ("quixbugs-replay-break", "Лог требует больше, чем есть -> падает",
     case_quixbugs_replay_break),
    ("codecheck-fp", "Buggy file declared clean -> FP -> gate red",
     case_codecheck_fp),
    ("conformance-break", "One requirement broken -> exam must fail",
     case_conformance_break),
    ("advisory-fold", "Advisory counted as proven -> gate red",
     case_advisory_fold),
    ("hypotheses-write", "Explanation writes to the source -> gate red",
     case_hypotheses_write),
    ("hypotheses-nonproof", "Unproven hypothesis reported -> gate red",
     case_hypotheses_nonproof),
    ("localize-core", "UNSAT-core: конфликт не распознан",       case_localize_core),
    ("sim-invariant", "Симуляция I2: чтение возвращает пусто",   case_sim_invariant),
    ("proof-check",   "Проверка доказательств: без отрицания",   case_proof_check),
    ("verify-cli",    "CLI verify: Merkle всегда не совпал",     case_verify_cli),
    ("prove-cli",     "CLI prove: мост всегда ToolError",       case_prove_cli),
    ("registry-fuse", "K5: предохранитель ловит новую цель",     case_registry_fuse),
    ("registry-dup-numbers", "K5b: предохранитель ловит ДУБЛИКАТ номера дефекта", case_registry_dup_numbers),
    ("evidence-guard", "#88: предохранитель ловит ВНЕШНЮЮ правку во время прогона", case_evidence_guard),
    ("c-abi-null", "C-ABI: NULL-указатель -> SIGSEGV (защита обязана ловить)", case_c_abi_null),
    ("c-abi-hash", "C-ABI: хэш не всего входа ловится КОНСТАНТОЙ эталона", case_c_abi_hash),
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
    ("model-verify",  "Модель: ложный ассерт объявлен верным",    case_model_verify_spurious),
    ("lia-soundness",  "LIA: незвучивый решатель ловится гейтом",  case_lia_soundness),
    ("proof-tamper",   "ФАЗЗЕР: подделка вывода ловится чекером",  case_proof_tamper),
    ("tree-lock",      "ЗАМОК: гонка патчащих дерево запрещена",    case_tree_lock),
    ("binary-audit",   "АУДИТ: AVX2/NX/латентность измеряются",     case_binary_audit),
    ("bitrot-chaos",   "BIT-ROT: порча данных в .kimg ловится",      case_bitrot_chaos),
    ("pcc-check",      "PCC: подделка сертификата отвергается",    case_pcc_check),
    ("scorecard-check", "ТРАСТ-КАРТОЧКА: паспорт == пересчёт", case_scorecard),
    ("ecosystem-check", "Внешние каталоги: манифесты MCP == tools/list", case_ecosystem),
    ("xray-check",     "XRAY: находки без аннотаций",           case_xray_check),
    ("gen-tests-check","SBST: сгенерированные тесты проходят",    case_gen_tests_check),
    ("simplify-check",  "SIMPLIFY: эквивалентность доказана",      case_simplify_check),
    ("bounds-check",    "BOUNDS: границы arr[i] проверены",       case_bounds_check),
    ("loop-check",      "LOOPS: инвариант и остановка циклов",   case_loop_check),
    ("polyglot-7-check", "ПОЛИГЛОТ: 7 языков (.ts/.js/.go) + Sorbet-типы", case_polyglot7_check),
    ("presets-check",  "ПРЕСЕТЫ: нарушение однословного пресета ловится", case_presets_check),
    ("double-spend-check", "ГОНКА: двойное списание поймано", case_double_spend_check),
    ("ffi-bridge-check", "FFI: усечение i32/u32 поймано",   case_ffi_bridge_check),
    ("sql-policy-check", "RLS: обход изоляции тенантов пойман",  case_sql_policy_check),
    ("pricing-matrix-check", "ТАРИФЫ: дыра/конфликт пойманы",   case_pricing_matrix_check),
    ("anti-cheat-check", "ЧИТЫ: 5 классов поймано",            case_anti_cheat_check),
    ("mcp-audit-check", "MCP: инъекция/rug-pull пойманы",     case_mcp_audit_check),
    ("noninterference-check", "SECRET: утечка поймана",          case_noninterference_check),
    ("belnap-swarm-check", "РОЙ: JOIN_K(T,F)=B проверен",           case_belnap_swarm_check),
    ("action-firewall-check", "FIREWALL: 200/422/409 проверены",      case_action_firewall_check),
    ("rag-conflict-check", "RAG: ядро конфликта найдено",         case_rag_conflict_check),
    ("rlvr-oracle-check", "RLVR: +1/-1/-2 проверены",              case_rlvr_oracle_check),
    ("audit-repo-check", "AUDIT-REPO: паспорт + HTML",            case_audit_repo_check),
    ("bug-hunt-check", "TROPHIES: трофеи 8/8",                   case_bug_hunt_check),
    ("html-canvas-check", "CANVAS: холст автономен",                case_html_canvas_check),
    ("fuzz-corpus-check", "FUZZ: 0 паник, детерминизм",          case_fuzz_corpus_check),
    ("wasm-check", "WASM: экспорты + No-Bloat",                case_wasm_check),
    ("kimg-grep-check", "KIMG: 3 исхода grep",                  case_kimg_grep_check),
    ("dst-check", "DST: сериализуемые сбои",                    case_dst_check),
    ("homeostatic-heal-check", "Гомеостаз: F -> патч -> T",         case_homeostatic_heal_check),
    ("opt-diff-check", "OPT: Debug == RS == Small",              case_opt_diff_check),
    ("concolic-check", "CONCOLIC: живые запуски + Z3",            case_concolic_check),
    ("translation-val-check", "TV: asm -O2 == spec",                    case_translation_val_check),
    ("evo-fuzz-check", "EVO: 0 паник / 0 ложных допусков",         case_evo_fuzz_check),
    ("parser-security-check", "PARSER: подделка/алиасы",                case_parser_security_check),
    ("hadamard-check", "HADAMARD: SAT N=2,4 / UNSAT N=3",              case_hadamard_check),
    ("arbitrage-check", "АРБИТРАЖ: дробление платежа выгоднее целого",  case_arbitrage_check),
    ("state-inv-check",  "STATE: инвариант состояния сохранён",   case_state_inv_check),
    ("float-nan-check", "FLOAT: IEEE-754 NaN, trusted: 0",        case_float_nan_check),
    ("string-contracts-check", "STRINGS: QF_S, trusted: 0",      case_string_contracts_check),
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
    """🔴 ДЕФЕКТ #63 / #71: ПРЕДУПРЕЖДЕНИЕ о «грязных» FAULTABLE-файлах.

    ИСТОРИЯ. Изначально харнесс восстанавливал файлы через
    `git checkout -- <файл>`, поэтому незакоммиченные правки разработчика
    УНИЧТОЖАЛИСЬ молча. Дефект найден на практике: во время работы над
    BLAKE3-диспетчеризацией `make evidence` запустил canfail, и правки в
    `src/core/kimg_reader.zig` + `src/core/kimg_writer.zig` были стёрты.

    ТЕКУЩЕЕ ПОВЕДЕНИЕ (дефект #71 исправлен). Откат идёт из БАЙТОВОГО
    СНИМКА, снятого НА СТАРТЕ прогона (`ORIG_SNAPSHOT`), а `git checkout`
    в коде не используется вовсе. Снимок включает незакоммиченные правки,
    поэтому они ПЕРЕЖИВАЮТ прогон (доказано экспериментом: sha256 файла
    до и после совпал). Отказывать в запуске больше незачем.

    Функция оставлена как ИНФОРМАЦИОННАЯ: она печатает список грязных
    FAULTABLE-файлов, чтобы разработчик понимал, что попадёт в `git add -A`
    после прогона. Возвращает 1, если такие файлы есть (вызывающий код
    только предупреждает, а не отказывает).
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
    print("[i] ВНИМАНИЕ: у FAULTABLE-файлов есть незакоммиченные правки:")
    print("=" * 70)
    for f in dirty:
        print(f"    M {f}")
    print("\nЭто НЕ отказ: откат идёт из байтового снимка, снятого СЕЙЧАС,")
    print("поэтому ваши правки переживут прогон (проверено экспериментом).")
    print("Напоминание: после прогона `git add -A` зафиксирует их вместе")
    print("с изменениями харнесса — проверьте diff перед коммитом.")
    return 1


def check_anchors() -> int:
    """Проверить, что ВСЕ литеральные якоря canfail применимы к текущим файлам.

    🔴 ЗАЧЕМ (дефект #113, красный CI #68/#69). Кейсы правят файлы
    ЛИТЕРАЛЬНЫМИ подстроками. Как только код вокруг якоря меняется
    (пересборка релиза обновила хеш в README, релиз сменил версию в
    `main.zig`, рефакторинг заменил `r.returncode` на `rc`), `patch()` падает
    «подстрока не найдена», и ВЕСЬ шаг CAN-FAIL краснеет — при том что ни одна
    проверка проекта нарушена не была. Полный прогон идёт ~15 минут, а узнать
    об этом хочется за секунду, а не в конце.

    Якоря разбираются СТАТИЧЕСКИ (AST) и сверяются с файлами. Якоря, которые
    вычисляются в рантайме (`readme_hash_anchor()`, `kern_version_anchor()`),
    пропускаются — они не могут «устареть».
    """
    import ast as _ast
    src = Path(__file__).read_text(encoding="utf-8")
    bad: list[tuple[str, int, str]] = []
    total = 0
    for node in _ast.walk(_ast.parse(src)):
        if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                and node.func.id == "patch" and len(node.args) >= 2):
            continue
        p, o = node.args[0], node.args[1]
        if not (isinstance(p, _ast.Constant) and isinstance(o, _ast.Constant)
                and isinstance(p.value, str) and isinstance(o.value, str)):
            continue
        total += 1
        t = ROOT / p.value
        if not t.exists():
            bad.append((p.value, node.lineno, "ФАЙЛА НЕТ"))
        elif o.value not in t.read_text(encoding="utf-8", errors="replace"):
            bad.append((p.value, node.lineno, o.value[:64]))
    if bad:
        print("[!] ЯКОРЯ НЕ ПРИМЕНИМЫ — кейсы ОШИБНУТСЯ (дефект #113):")
        for f, ln, frag in bad:
            print(f"      {f} (canfail.py:{ln}): {frag!r}")
        print("      Поправьте якорь под текущий код ЛИБО сделайте его "
              "динамическим (см. readme_hash_anchor).")
        return 1
    print(f"[OK] якоря применимы: {total} литеральных "
          f"(динамические проверяются в рантайме)")
    return 0



def _refuse_dirty_src():
    """ДЕФЕКТ #156: не стартовать поверх ГРЯЗНОГО `src/`.

    Патчащий дерево прогон поверх чужих незакоммиченных правок рискует
    откатить их своим снимком (класс #71/#116) и, как показал инцидент
    f01e8fc, оставить диверсию в коммите.
    """
    # ДЕФЕКТЫ #168/#170: маркеры инъекций в src/ = прогон НЕДОПУСТИМ
    _ig = os.path.join(os.path.dirname(os.path.abspath(__file__)), "injection_guard.py")
    if os.path.exists(_ig):
        _r = subprocess.run([sys.executable, _ig], capture_output=True, text=True)
        if _r.returncode != 0:
            sys.stderr.write(_r.stdout)
            sys.stderr.write("[LOCKED] маркеры инъекций/грязный src — откат обязателен (#168/#170).\n")
            return 2
    if os.environ.get("KERN_ALLOW_DIRTY_SRC") == "1":
        return
    try:
        r = subprocess.run(["git", "diff", "--quiet", "--", "src/"], cwd=str(ROOT))
    except (OSError, subprocess.SubprocessError):
        return
    if r.returncode != 0:
        print("[LOCKED] `src/` содержит незакоммиченные правки — патчащий прогон "
              "откатит их своим снимком (#71/#116/#156). "
              "Закоммитьте или задайте KERN_ALLOW_DIRTY_SRC=1.", file=sys.stderr)
        sys.exit(2)


def main():
    _refuse_dirty_src()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="K4: проверить ЛОГИКУ харнесса на синтетических входах")
    ap.add_argument("--check-anchors", action="store_true",
                    help="быстро проверить, что все якоря canfail применимы "
                         "(дефект #113: устаревший якорь роняет весь шаг CI)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="совместимость: отказ при грязных FAULTABLE отменён, "
                         "флаг оставлен для обратной совместимости")
    args = ap.parse_args()

    if args.check_anchors:
        return check_anchors()

    if args.selftest:
        return selftest()

    if args.list:
        for c in CASES:
            print(f"  {c[0]:14s} {c[1]}")
        return 0

    # ДЕФЕКТ #63: ПРЕДОХРАНИТЕЛЬ. Харнесс восстанавливает FAULTABLE-файлы через
    # `git checkout --`, поэтому незакоммиченные правки в них будут УТЕРЯНЫ.
    # Отказываемся работать, пока дерево не закоммичено (или явный --allow-dirty).
    # 🔴 ДЕФЕКТ #71: взаимное исключение через fcntl.flock. Ядро снимает
    # блокировку даже при SIGKILL — в отличие от файла-флага (дефект #50),
    # который после аварии остаётся и блокирует все будущие прогоны.
    lock = acquire_run_lock()
    _LOCK_HOLDER.append(lock)  # держим ссылку: иначе GC снимет flock
    if lock == "BUSY":
        print("[!] ОТКАЗ: другой экземпляр canfail.py уже выполняется.")
        print("    Харнесс пишет прямо в рабочие файлы, поэтому два прогона")
        print("    одновременно недопустимы. Дождитесь завершения первого.")
        return 1

    # ПРЕДУПРЕЖДЕНИЕ (не отказ). Дефект #63 отказывал при незакоммиченных
    # правках, потому что откат шёл через `git checkout --`. Теперь откат
    # идёт из байтового снимка, СДЕЛАННОГО С ТЕКУЩЕГО СОСТОЯНИЯ, поэтому
    # незакоммиченные правки переживают прогон — и отказывать незачем.
    rc_guard = guard_dirty_faultable()
    if rc_guard != 0 and not args.allow_dirty:
        print("    Продолжаю: откат идёт из снимка текущего состояния, а не из git.")

    env = dict(os.environ)
    env["PATH"] = (f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:"
                   f"{ROOT}/.venv/bin:{env.get('PATH','')}")
    os.environ.update(env)

    print("=" * 70)
    print("KERN: CAN-FAIL — проверка, что проверки СПОСОБНЫ УПАСТЬ")
    print("=" * 70)

    # 🔴 БЫСТРЫЙ ОТКАЗ (дефект #113, красный CI #68/#69): если хоть один якорь
    # устарел, кейс ОШИБНЕТСЯ, и ВЕСЬ шаг CI покраснеет — но только через
    # ~15 минут. Проверяем за секунду и называем файл + фрагмент.
    if check_anchors() != 0:
        return 1

    print("Метод: ломаем инвариант -> цель ОБЯЗАНА покраснеть.\n")

    clean_slate()
    capture_snapshot()   # дефект #71: байтовый снимок = источник истины для отката
    snap = snapshot_faultable()

    ok = bad = meta_bad = skipped = err_bad = dirty_bad = 0
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
                # 🔴 ДЕФЕКТ #67 (найден при сверке отчётности): мета-контроль
                # иногда завершался кодом rc=2. Это код ошибки `make` (провал
                # рецепта/сборки), а НЕ семантическое покраснение цели.
                # Причина — конкуренция за кэш Zig сразу после предыдущего
                # кейса. Даём ОДНУ повторную попытку, чтобы не выдавать
                # инфраструктурный сбой за «харнесс сломан».
                if expect_vacuous and rc == 2:
                    time.sleep(1.0)
                    rc, out = sh_out(cmd, 900)
        except subprocess.TimeoutExpired:
            rc, out = 124, "TIMEOUT"
        except Exception as e:
            # 🔴 ДЕФЕКТ #89 (найден на практике): здесь стояло `skipped += 1`,
            # то есть ОШИБКА КЕЙСА молча превращала его в «пропущенный».
            # Симптом: после рефакторинга BLAKE3 шаблон патча в кейсе
            # `sim-invariant` устарел, кейс падал с RuntimeError, попадал в
            # «пропущено 1» — и харнесс отчитывался об УСПЕХЕ, хотя
            # CHECK-цель осталась БЕЗ доказательства «может упасть».
            # Это ровно класс «молчаливо сломанных проверок», против которого
            # построен проект. Теперь ошибка кейса — ЖЁСТКИЙ ПРОВАЛ.
            import traceback
            print(f"  [FAIL] {name:14s} {desc}")
            print(f"         ОШИБКА КЕЙСА: {e}")
            print("         Похоже, шаблон патча устарел после рефактора —")
            print("         сверьте кейс с текущим кодом цели.")
            traceback.print_exc()
            err_bad += 1
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
            meta_bad += 1
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
        dirty_bad += 1
    else:
        print("[32m[OK] дерево чистое: все правки откачены[0m")
    print(f"ИТОГ: не-вакуумных {ok} | ВАКУУМНЫХ {bad} | ГРЯЗНЫХ {dirty_bad} | "
          f"ЛОЖНЫХ СРАБАТЫВАНИЙ ХАРНЕССА {meta_bad} | "
          f"ОШИБОК КЕЙСОВ {err_bad} | пропущено {skipped}")
    if err_bad:
        print()
        print("🔴 ОШИБКИ КЕЙСОВ — это НЕ «пропуск»: цель осталась без доказательства")
        print("   «может упасть». Обновите устаревшие шаблоны патчей.")
    print("=" * 70)
    # Дефект #89: err_bad обязан ронять прогон (раньше он молча шёл в skipped).
    #
    # ДЕФЕКТ #275 (найден на Ф3): кейс без `return` возвращал None и молча
    # попадал в `skipped` — «пропущено 1» выглядело безобидно, хотя проверка
    # не выполнялась вообще. При ЯВНОМ `--only` пропуск теперь ошибка.
    skip_is_error = bool(args.only) and skipped > 0
    if skip_is_error:
        print()
        print("🔴 ЯВНО ВЫБРАННЫЙ КЕЙС ПРОПУЩЕН: предусловие не выполнено или "
              "кейс не вернул команду — это НЕ доказательство")
    return 1 if (bad or dirty_bad or meta_bad or err_bad or skip_is_error) else 0


if __name__ == "__main__":
    sys.exit(main())
