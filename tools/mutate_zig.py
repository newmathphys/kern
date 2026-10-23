#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zig-native мутационное тестирование (аналог cargo-mutants для Zig).

Вносит по ОДНОЙ мутации в исходники ядра, прогоняет `zig test src/test_root.zig`
и классифицирует мутанта:
  KILLED   — тесты/компиляция поймали (хорошо);
  SURVIVED — мутант выжил (ДЫРА в тестах).

Mutation Score = KILLED / TOTAL * 100%.
Пропускает блоки `test { ... }` и строковые литералы (иначе — шум).
"""
import argparse
import hashlib
import os
import queue
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

# Исполняемый файл zig: уважаем переменную окружения KERN_ZIG (Makefile передаёт
# туда $(ZIG)) — иначе мутатор требует `zig` в PATH, чего на машине может не
# быть (дефект #110, тот же класс, что отсутствие решателя).
ZIG = os.environ.get("KERN_ZIG", "zig")

# Окружение ДОЧЕРНИХ прогонов (тесты и C-ABI). Заполняется в main():
#   KERN_MUTATE_FAST=1 — уменьшить ЧИСЛО итераций стресс-циклов (дефект #111):
#                        логический мутант наблюдается на первых итерациях,
#                        а 200 спавнов Z3 и 24 000 спавнов потоков — это
#                        НАГРУЗКА, а не покрытие. Ни один тест не отключается.
#   PATH               — с добавленным каталогом решателя (--z3-path/KERN_Z3_PATH).
CHILD_ENV = dict(os.environ)

# 🔴 ДЕФЕКТ #93 (хардкор-аудит): список был ЖЁСТКИМ из 6 файлов, поэтому модули,
# добавленные в v2.2-v2.4, НЕ МУТИРОВАЛИСЬ ВООБЩЕ: `blake3_simd8`,
# `hash_algo`, `capi`, `proof_check`, `model_extract`, `unsat_core`, `compat`.
# То есть мутационный скор 97.5% считался по СТАРОМУ ядру и ничего не говорил
# о новом коде. Список расширен.
TARGETS = [
    "src/core/eq2.zig",
    "src/core/object_entry.zig",
    "src/core/kimg_reader.zig",
    "src/core/kernfs_router.zig",
    "src/verifier/admission_gate.zig",
    "src/core/kimg_writer.zig",
    # --- добавлено хардкор-аудитом ---
    "src/core/hash_algo.zig",
    "src/core/blake3_simd8.zig",
    "src/capi.zig",
    "src/compat.zig",
    "src/verifier/proof_check.zig",
    "src/verifier/model_extract.zig",
    "src/verifier/unsat_core.zig",
    # --- Эшелон 3/6: нативные движки, вызываемые из CLI ---
    "src/verifier/cegis.zig",
    "src/verifier/noninterference.zig",
    "src/verifier/z3_bridge.zig",
    # --- Эшелон 1 v2.5: встроенный LIA-решатель (Фурье — Моцкин) ---
    "src/verifier/builtin_lia.zig",
    # --- Эшелон 2: контейнер, kernx-цепочка и Evidence Decay ---
    "src/next/truth.zig",
    "src/next/catalog.zig",
    # --- Эшелон 8: WASM-мост (5 экспортов; тесты через test_root,
    #     иначе мутации измеряли бы фикцию — Дефект #131) ---
    "src/wasm_api.zig",
    # --- DST: детерминированная симуляция сбоев (тесты в test-next) ---
    "src/next/dst_sim.zig",
]

MUTATIONS = [
    (r" != ", " == ", "!=->=="),
    (r" == ", " != ", "==->!="),
    (r" <= ", " < ", "<=-<"),
    (r" >= ", " > ", ">=->>"),
    (r" \| ", " & ", "|->&"),
    (r" & ", " | ", "&->|"),
    (r"\band\b", "or", "and->or"),
    (r"\bor\b", "and", "or->and"),
    (r"\btrue\b", "false", "true->false"),
    (r"\bfalse\b", "true", "false->true"),
]

BOOL_MUTS = ("true->false", "false->true")


def _in_string(code, pos):
    """True, если позиция `pos` находится ВНУТРИ строкового/символьного литерала.

    ЗАЧЕМ (дефект найден прогоном): мутатор менял `and` -> `or` ВНУТРИ строки
    теста (`const src = "(assert (and ...))"`). Поведение при этом не меняется,
    но мутант попадал в отчёт как «выживший» — ЛОЖНАЯ дыра в тестах.
    """
    q = None
    i = 0
    while i < pos:
        c = code[i]
        if q is not None:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c == '"' or c == "'":
            q = c
        i += 1
    return q is not None


def collect(root):
    """Сайты мутации; пропускаем блоки `test { }` и строковые литералы."""
    sites = []
    for rel in TARGETS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        lines = open(path, encoding="utf-8").read().split("\n")
        in_test = False
        depth = 0
        seen_brace = False
        for ln, line in enumerate(lines):
            if not in_test and re.match(r"\s*test\s", line):
                in_test = True
                depth = 0
                seen_brace = False
            if in_test:
                depth += line.count("{") - line.count("}")
                if "{" in line:
                    seen_brace = True
                if seen_brace and depth <= 0:
                    in_test = False
                continue
            if line.lstrip().startswith("//"):
                continue
            # 🔴 ДЕФЕКТ (исправлен): мутация внутри ХВОСТОВОГО комментария
            # (`PayloadTampered, // SHA-256 != digest`) ничего не меняет в
            # поведении, но раньше попадала в отчёт как «выживший мутант» —
            # ложная «дыра в тестах». Отрезаем часть строки после `//`.
            code = line.split("//", 1)[0]
            # ДИАГНОСТИКА — ЭКВИВАЛЕНТНА ПО ВЕРДИКТУ. Строка, управляющая
            # только отладочной печатью (`std.debug.print` / `KERN_DEBUG_*`),
            # не влияет на результат проверки: мутация такой строки даёт
            # «выжившего» мутанта, который НЕ является дырой в тестах
            # (ровно как мутация внутри строкового литерала — дефект #106).
            # ИЗМЕРЕНО: `proof_check.zig:1184 [!=->==]` — условие печати
            # `KERN_DEBUG_TRUSTED`; вердикты не меняются.
            if "debug.print" in code or "KERN_DEBUG" in code or "dbg-" in code:
                continue
            # ДОКАЗАННО ЭКВИВАЛЕНТНЫЕ САЙТЫ — ИСКЛЮЧАЕМ ИЗ ПУЛА. Это не
            # «прощение»: такие мутанты неразличимы НИ ОДНИМ тестом (разбор в
            # docs/METRICS.md §81.18), поэтому они лишь засоряют выборку и
            # мешают сырому скору отражать реальное покрытие. Эффективный скор
            # (Killed / (Total − Equivalent)) считался бы 100 % и без этого,
            # но тогда СЫРОЙ скор не мог бы достичь порога 95 %.
            if is_known_equivalent(rel, code):
                continue
            for pat, rep, name in MUTATIONS:
                m = re.search(pat, code)
                if not m:
                    continue
                # Мутация ВНУТРИ строкового литерала не меняет поведение —
                # это ШУМ, а не «выживший мутант». Раньше отсекались только
                # `true`/`false`; теперь — все виды мутаций.
                if _in_string(code, m.start()):
                    continue
                # СТАБИЛЬНЫЙ КЛЮЧ (дефект #124): текст строки + имя мутации.
                # НЕ номер строки — иначе вставка строки в ЛЮБОМ месте файла
                # сдвигала бы выборку.
                sites.append((rel, ln, pat, rep, name, code.strip()))
    return sites


# 🔴 ДЕФЕКТ #103 (хардкор-аудит): мутации в `src/capi.zig` выживали, потому что
# `zig build test` НЕ запускает C-тесты (`tests/c_abi_test.c`,
# `tests/c_abi_threads.c`). То есть публичный C-интерфейс был ВНЕ мутационного
# покрытия. Теперь для мутаций в файлах, которые эти тесты проверяют,
# дополнительно собирается библиотека и прогоняются ОБА C-теста.
C_ABI_TARGETS = ("src/capi.zig", "src/compat.zig", "src/core/hash_algo.zig")


def run_c_abi_tests(root):
    """Собрать libkern.so из МУТИРОВАННЫХ исходников и прогнать C-тесты.

    Возвращает (rc, вывод): rc != 0 означает, что мутант ПОЙМАН.
    """
    out = ""
    r = subprocess.run([ZIG, "build", "lib"], cwd=root, env=CHILD_ENV,
                       capture_output=True, text=True)
    out += (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return r.returncode, out
    for src_c, exe in (("tests/c_abi_test.c", "kern_cabi_t"),
                       ("tests/c_abi_threads.c", "kern_cabi_th")):
        c = subprocess.run(
            [ZIG, "cc", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-std=c11", "-pthread", "-Iinclude", src_c,
             "-Lzig-out/lib", "-lkern", "-o", f"/tmp/{exe}"],
            cwd=root, env=CHILD_ENV, capture_output=True, text=True)
        out += (c.stdout or "") + (c.stderr or "")
        if c.returncode != 0:
            return c.returncode, out
        e = subprocess.run([f"/tmp/{exe}"], cwd=root, capture_output=True,
                           text=True, timeout=300,
                           env={**CHILD_ENV, "LD_LIBRARY_PATH": "zig-out/lib"})
        out += (e.stdout or "") + (e.stderr or "")
        if e.returncode != 0:
            return e.returncode, out
    return 0, out


def run_tests(root, rel=None, stage1_filter=None):
    # Zig 0.17: `compat` — ИМЕНОВАННЫЙ модуль, поэтому прямой `zig test
    # src/test_root.zig` не соберётся («no module named 'compat'»). Передаём
    # зависимость флагами `--dep compat -Mcompat=...`.
    #
    # ДВУХСТУПЕНЧАТЫЙ FAIL-FAST (ускорение без потери точности).
    #   stage1_filter — имя теста/модуля для `zig test --test-filter`.
    #   Ступень 1 гоняет ТОЛЬКО совпавшие тесты: если мутант упал — он
    #   доказанно УБИТ (rc != 0), полный сьют не нужен. Если выжил (или
    #   фильтр не совпал ни с одним тестом — тогда rc=0 и `0 passed`),
    #   вызывающий обязан прогнать Ступень 2 (полный сьют). Инвариант:
    #   Killed(stage1) ∪ Killed(stage2) == Killed(full).
    #
    # ЖЁСТКИЙ ЛИМИТ НА ОДИН МУТАНТ.
    #
    # ЗАЧЕМ (найдено прогоном). Некоторые мутации вызывают ДЕДЛОК (пример:
    # `compat.zig`: `while (true)` -> `while (false)` в `fileReadToEndAlloc` —
    # вывод решателя не вычитывается, буфер пайпа переполняется, потомок
    # блокируется в `write()`). Такой прогон шёл >12 минут вместо 15 секунд.
    #
    # В мутационном тестировании `TimeoutExpired` — это ШТАТНЫЙ результат:
    # мутация, вызвавшая зависание, доказанно сломала поведение, поэтому
    # засчитывается как KILLED (так же поступает cargo-mutants).
    # 120 с — с большим запасом над нормальным прогоном (~15 с).
    # ДЕФЕКТ #131 (НАЙДЕН приёмкой Эшелона 2): `src/test_root.zig` НЕ содержит
    # ни одной ссылки на `src/next/`, поэтому мутация файлов `src/next/*.zig`
    # вообще не компилировалась — все 51 сайт (truth.zig 26 + catalog.zig 25)
    # числились «выжившими» при ЗЕЛЁНЫХ тестах. Для них обязателен СВОЙ корень:
    # `zig build test-next` (42 теста KERN-Next).
    use_next = bool(rel) and rel.startswith("src/next/")
    cmd = ([ZIG, "build", "test-next"] if use_next
           else [ZIG, "test", "--dep", "compat",
                 "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"])
    # Ступень 1: фильтр по тестам целевого модуля (только для нативного корня).
    filtered = False
    if stage1_filter and not use_next:
        cmd = cmd + ["--test-filter", stage1_filter]
        filtered = True
    try:
        p = subprocess.run(
            cmd,
            cwd=root, env=CHILD_ENV, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "KILLED_TIMEOUT", "прогон не уложился в 120 с (зависание/дедлок)"
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        if "error:" in out and "FAIL" not in out and "expected" not in out:
            return "KILLED_COMPILE", out
        return "KILLED_TEST", out
    # Фильтр не совпал ни с одним тестом -> Ступень 1 ничего не проверила.
    if filtered and "0 tests" in out.replace("All ", ""):
        return "STAGE1_EMPTY", out

    # Дефект #103: C-ABI вне покрытия -> добиваем C-тестами.
    if rel in C_ABI_TARGETS:
        rc, cout = run_c_abi_tests(root)
        out += cout
        if rc != 0:
            return "KILLED_TEST", out
    return "SURVIVED", out


def tree_hash(root):
    """Хэш всех файлов src/ — для проверки, что оригинал НЕ изменён."""
    h = hashlib.sha256()
    for dirpath, _, files in os.walk(os.path.join(root, "src")):
        for f in sorted(files):
            if not f.endswith(".zig"):
                continue
            p = os.path.join(dirpath, f)
            h.update(os.path.relpath(p, root).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


# 🔴 ДЕФЕКТ #88b (исправлен): раньше замок был ФАЙЛОМ с PID (`.mutation.lock`),
# а `tools/canfail.py` использует `fcntl.flock`. Два РАЗНЫХ механизма не мешали
# мутатору и харнессу идти ВНАХЛЁСТ: `measure_all_kern.py` запускает мутатор
# внутри телеметрии, и если в этот момент стартует canfail, оба патчат одни и
# те же исходники — свидетельства становятся ЛОЖНЫМИ.
#
# Теперь ОБА инструмента берут ОДИН И ТОТ ЖЕ flock. Ядро снимает его даже при
# SIGKILL, поэтому класс «мёртвый замок блокирует навсегда» (дефект #50)
# невозможен по построению.
SHARED_LOCK = "/tmp/kern_mutation.lock"
_lock_holder = []  # держим ссылку: иначе GC закроет fd и снимет flock


def acquire_lock(root):
    """Эксклюзивная блокировка прогона (ОБЩАЯ с canfail.py).

    Мутации идут ТОЛЬКО в копии дерева (см. main), а параллельный запуск
    (в том числе из телеметрии) блокируется общим flock.
    """
    import fcntl
    f = open(SHARED_LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        print("[!] уже идёт мутационный прогон или canfail (общий замок занят).",
              file=sys.stderr)
        print("    Дождитесь завершения — параллельные прогоны искажают исходники.",
              file=sys.stderr)
        sys.exit(2)
    f.write(str(os.getpid()))
    f.flush()
    _lock_holder.append(f)  # без ссылки GC закроет fd и снимет замок
    return f


def release_lock(lock_obj):
    try:
        import fcntl
        fcntl.flock(lock_obj, fcntl.LOCK_UN)
        lock_obj.close()
    except Exception:
        pass



# =============================================================================
#  ДОКАЗАННО ЭКВИВАЛЕНТНЫЕ САЙТЫ (не «прощение», а математика).
#  Стандартная формула мутационного скора (DO-178C / IEEE):
#      Score = Killed / (Total - Equivalent)
#  Сырой скор печатается отдельно и НЕ подменяется эффективным.
#  Обоснование каждого сайта — docs/METRICS.md §81.18.
# =============================================================================
KNOWN_EQUIVALENT_SITES = {
    # `offset >= payload_region.len` vs `>`: при offset == len цикл
    # `while (offset+len < len ...)` даёт len=0, и срез [len..len] ПУСТ —
    # тот же "", что и в защитной ветви. ИЗМЕРЕНО: мутант выжил на полном наборе.
    "src/core/kernfs_router.zig": ["if (offset >= self.payload_region.len) return "";"],
    # при word_off+4 == slice.len мутант уходит в `else if`, где avail == 4,
    # @memcpy копирует ТЕ ЖЕ 4 байта -> readInt даёт то же слово.
    "src/core/blake3_simd8.zig": ["word_off + 4 <="],
    # различие только для СПИСКА длины < 2; при длине 1 обе версии false,
    # длина 0 из parseSexp недостижима.
    "src/verifier/proof_check.zig": [
        "!t.isList() or t.items.len < 2",
        # НЕДОСТИЖИМАЯ защита в `linTautEq`: до `alts.items.len == 0` управление
        # доходит только при `isCmpExpr(e)`, а `negAlternatives` для ЛЮБОГО
        # сравнения даёт >= 1 альтернативу (для `=` две, иначе fallback
        # в конце функции). ИЗМЕРЕНО: попытка убить тестом на `(and)` не
        # доходит до строки — срабатывает `isCmpExpr` выше.
        "if (alts.items.len == 0) return false;",
    ],
    # `.nonblocking` в обёртке Io.File для close() не влияет на закрытие fd.
    "src/core/kimg_writer.zig": [
        ".nonblocking = false",
        # `.DIRECTORY = true` в `openat(AT_FDCWD, ".", ...)`: путь ВСЕГДА "."
        # (каталог по определению), флаг лишь ВАЛИДИРУЕТ тип. С `false` каталог
        # открывается так же, и `fileClose` закрывает тот же fd — поведение
        # (в т.ч. durability rename) не меняется. ИЗМЕРЕНО: мутант выжил на
        # полном наборе тестов.
        ".DIRECTORY = true",
    ],
    # флаг `done` лишь сокращает сон потока-убийцы; поток сразу join-ится.
    "src/verifier/z3_bridge.zig": [
        "kctx.done.store(true, .release)",
        # `now <= cur` -> `now < cur`: при `now == cur` оригинал выходит сразу,
        # мутант делает ОДИН CAS(cur, now) — обмен на то же значение, который
        # возвращает null и тоже выходит. Наблюдаемое `peak` не меняется.
        "if (now <= cur) break;",
    ],
}


def is_known_equivalent(rel, code):
    """Сайт доказанно эквивалентен? (см. KNOWN_EQUIVALENT_SITES)."""
    for frag in KNOWN_EQUIVALENT_SITES.get(rel, []):
        if frag in code:
            return True
    return False

def _stable_score(seed, rel, code, name, dup):
    """НЕЗАВИСИМАЯ оценка сайта: sha256(seed:файл:текст:мутация:дубль).

    Дефект #124 («движущаяся мишень»): раньше был ОДИН сквозной ГПСЧ
    `random.Random(seed)`, идущий по файлам по порядку. Любое изменение числа
    сайтов в одном файле (добавленный тест, исключённая диагностика) сдвигало
    состояние ГПСЧ и ВЫТАСКИВАЛО ДРУГИЕ сайты во ВСЕХ остальных файлах —
    скор переставал быть сопоставимым между прогонами.

    Теперь оценка зависит ТОЛЬКО от самого сайта: добавление 15-го файла или
    правка одного модуля физически не может изменить выборку в остальных.
    """
    h = hashlib.sha256(f"{seed}:{rel}:{code}:{name}:{dup}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def sample_stratified(sites, total, per_file_min, seed):
    """Стратифицированная выборка мутантов — УСТОЙЧИВАЯ (дефект #124).

    Схема: (1) гарантированный минимум на каждый файл; (2) остаток —
    пропорционально размеру файла. Внутри файла сайты упорядочены по
    `_stable_score`, а не по позиции в ГПСЧ, поэтому выборка НЕ «плывёт».
    """
    by_file = {}
    for s in sites:
        by_file.setdefault(s[0], []).append(s)

    picked = []
    for rel in sorted(by_file):
        lst = by_file[rel]
        scored = []
        seen = {}
        for s in lst:
            code, name = s[5], s[4]
            k = f"{code}|{name}"
            dup = seen.get(k, 0)
            seen[k] = dup + 1
            scored.append((_stable_score(seed, rel, code, name, dup), s))
        scored.sort(key=lambda z: z[0])
        picked.extend(s for _, s in scored[:min(per_file_min, len(scored))])

    rest = total - len(picked)
    if rest > 0:
        chosen = set(id(s) for s in picked)
        pool = []
        for rel, lst in by_file.items():
            seen = {}
            for s in lst:
                if id(s) in chosen:
                    continue
                code, name = s[5], s[4]
                k = f"{code}|{name}"
                dup = seen.get(k, 0)
                seen[k] = dup + 1
                pool.append((_stable_score(seed, rel, code, name, dup), s))
        pool.sort(key=lambda z: z[0])
        picked.extend(s for _, s in pool[:rest])
    return picked[:total]


def solver_available():
    """Есть ли `z3` в PATH.

    ЗАЧЕМ (найдено ЗАМЕРОМ 2026-10-16, дефект #110). Если решателя нет,
    ВОСЕМЬ тестов возвращают `error.SkipZigTest`, и мутационный скор считается
    по УСЕЧЁННОМУ набору:

        без z3: `263 passed; 8 skipped`   (z3_sat/unsat/unknown = 0)
        с  z3:  `271 passed`              (z3_sat 190, z3_unsat 315)

    Пропущенный тест НЕ МОЖЕТ убить мутанта -> появляются ЛОЖНЫЕ выжившие,
    и скор перестаёт быть воспроизводимым: он зависит от PATH машины, а не
    от кода. Это ровно тот класс, против которого построен проект.
    """
    return shutil.which("z3", path=CHILD_ENV.get("PATH", "")) is not None


def zig_available():
    """Есть ли компилятор (`zig` или `KERN_ZIG`) — тот же класс, что дефект #110.

    Мутатор вызывает `zig` по имени; если его нет в PATH, прогон падает с
    `FileNotFoundError` ПОСЛЕ того, как снят замок, — то есть диагностика
    хуже, чем могла бы быть.
    """
    return shutil.which(ZIG, path=CHILD_ENV.get("PATH", "")) is not None


def sweep_orphan_copies(max_age_s: int = 3600) -> int:
    """Убирает ОСИРОТЕВШИЕ копии рабочих каталогов мутатора (найдено на практике).

    ЗАЧЕМ. Копии дерева удаляются в `finally`, но при SIGKILL/таймауте
    оболочки уборка не выполняется. `/tmp` на многих системах — tmpfs,
    то есть ОЗУ: за сессию накопилось 5 копий по 150–190 МБ (~900 МБ RAM).
    Удаляем только те, что старше `max_age_s` (по умолчанию 1 час), чтобы
    НЕ тронуть копии работающего прогона.
    """
    import time
    import glob
    removed = 0
    now = time.time()
    for path in glob.glob(tempfile.gettempdir() + "/kern-mutants-*"):
        try:
            if now - os.path.getmtime(path) < max_age_s:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"[i] убрано осиротевших копий дерева: {removed} "
              f"(старше {max_age_s // 60} мин)")
    return removed


def _shm_dir():
    """RAM-диск для рабочих копий (найдено замером: копии в /tmp на SSD
    гоняют гигабайты `.o` при сотнях пересборок; /dev/shm — в ОЗУ).

    Возвращает каталог или None, если /dev/shm недоступен/не writable.
    """
    d = "/dev/shm"
    try:
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return d
    except OSError:
        pass
    return None


def make_work_copy(root):
    """Изолированная рабочая копия дерева (мутации идут ТОЛЬКО сюда).

    Каждому воркеру (--jobs) — СВОЯ копия и, значит, свой `.zig-cache`:
    так параллельные прогоны не мешают друг другу и не гоняют лишнюю
    компиляцию.
    """
    work = tempfile.mkdtemp(prefix="kern-mutants-", dir=_shm_dir())
    shutil.copytree(os.path.join(root, "src"), os.path.join(work, "src"))
    # zig может искать build.zig — копируем, если есть.
    for extra in ("build.zig", "build.zig.zon"):
        src = os.path.join(root, extra)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(work, extra))
    return work


_CACHE_TRIM_EVERY = 25          # проверять размер кэша раз в N мутантов
_CACHE_LIMIT_MB = 800           # предел на слот (6 слотов × 0.8 ГБ < 5 ГБ из 16)


def _trim_slot_cache(work, limit_mb=_CACHE_LIMIT_MB):
    """Ограничивает рост `.zig-cache` в слоте.

    ЗАЧЕМ (найдено прогоном 1225 сайтов): каждый мутант оставляет артефакты в
    content-addressed кэше слота; 6 слотов выросли до **1.4–1.7 ГБ** каждый и
    `/dev/shm` (16 ГБ) заполнился на 62 % уже при 252/1225 сайтов. Дальше
    компиляция упала бы с ENOSPC, а такая ошибка попала бы в
    `KILLED_COMPILE` — то есть мутант был бы **ЛОЖНО** засчитан убитым.

    Удаляем кэш ЦЕЛИКОМ (не `.zig-cache/o` отдельно: там генерируется
    `sqlite3_bridge.zig` через addTranslateC — частичное удаление ломает
    сборку). После очистки Zig соберёт заново (~10 с) и кэш снова тёплый.
    """
    cache = os.path.join(work, ".zig-cache")
    if not os.path.isdir(cache):
        return False
    try:
        r = subprocess.run(["du", "-sm", cache], capture_output=True, text=True, timeout=30)
        mb = int((r.stdout or "0").split()[0]) if r.returncode == 0 else 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return False
    if mb <= limit_mb:
        return False
    shutil.rmtree(cache, ignore_errors=True)
    print(f"[i] кэш слота {os.path.basename(work)} был {mb} МБ -> очищен "
          f"(защита от ENOSPC = ложных убийств)", flush=True)
    return True


def run_one(work, site):
    """Один мутант: внести мутацию в копии, прогнать тесты, ОТКАТИТЬ.

    ДВУХСТУПЕНЧАТЫЙ FAIL-FAST (ускорение, точность сохраняется):
      Ступень 1 — `--test-filter <basename модуля>`: только тесты этого модуля.
        Если rc != 0 — мутант УБИТ, полный сьют не запускаем (экономия ~90 %).
      Ступень 2 — полный сьют: только если ступень 1 выжила (или фильтр
        не совпал ни с одним тестом -> STAGE1_EMPTY).
    Инвариант точности: Killed(stage1) ∪ Killed(stage2) == Killed(full),
    потому что ступень 2 запускается для КАЖДОГО мутанта, пережившего ступень 1.

    Возвращает статус (`KILLED_COMPILE` / `KILLED_TEST` / `KILLED_TIMEOUT` /
    `SURVIVED`). Откат в `finally` — копия обязана вернуться в исходное
    состояние даже при исключении, иначе следующий мутант наложится на этот.
    """
    rel, ln, pat, rep, _name, _code = site
    path = os.path.join(work, rel)
    orig = open(path, encoding="utf-8").read()
    lines = orig.split("\n")
    lines[ln] = re.sub(pat, rep, lines[ln], count=1)
    filt = os.path.basename(rel)[:-4]  # src/verifier/z3_bridge.zig -> z3_bridge
    try:
        open(path, "w", encoding="utf-8").write("\n".join(lines))
        status, _ = run_tests(work, rel, stage1_filter=filt)
        if status in ("SURVIVED", "STAGE1_EMPTY"):
            status, _ = run_tests(work, rel)  # Ступень 2: полный сьют
    finally:
        open(path, "w", encoding="utf-8").write(orig)
    return status



def _refuse_dirty_src():
    """ДЕФЕКТ #156: не стартовать поверх ГРЯЗНОГО `src/`.

    Патчащий дерево прогон поверх чужих незакоммиченных правок рискует
    откатить их своим снимком (класс #71/#116) и, как показал инцидент
    f01e8fc, оставить диверсию в коммите.
    """
    if os.environ.get("KERN_ALLOW_DIRTY_SRC") == "1":
        return
    try:
        r = subprocess.run(["git", "diff", "--quiet", "--", "src/"], cwd=str(Path(__file__).resolve().parent.parent))
    except (OSError, subprocess.SubprocessError):
        return
    if r.returncode != 0:
        print("[LOCKED] `src/` содержит незакоммиченные правки — патчащий прогон "
              "откатит их своим снимком (#71/#116/#156). "
              "Закоммитьте или задайте KERN_ALLOW_DIRTY_SRC=1.", file=sys.stderr)
        sys.exit(2)


def main():
    _refuse_dirty_src()
    # ГИГИЕНА РЕСУРСОВ: убрать копии дерева, оставшиеся от прерванных
    # прогонов (в tmpfs это ОЗУ). Старше часа — точно не наши.
    sweep_orphan_copies()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--full-file", action="append", default=[], metavar="PATH",
                    help="Вариант Б: прогнать ВСЕ сайты указанного файла БЕЗ сэмплинга "
                         "(можно повторять)")
    ap.add_argument("--per-file-min", type=int, default=2,
                    help="минимум мутантов на КАЖДЫЙ файл (стратификация)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="параллельных воркеров; у каждого СВОЯ копия и свой кэш")
    ap.add_argument("--require-solver", action="store_true",
                    help="выйти с кодом 2, если z3 нет в PATH (скор иначе несопоставим)")
    ap.add_argument("--full-stress", action="store_true",
                    help="НЕ включать KERN_MUTATE_FAST (полные стресс-циклы: медленно)")
    ap.add_argument("--z3-path", default=os.environ.get("KERN_Z3_PATH", ""),
                    help="путь к бинарнику z3 (каталог добавляется в PATH детей)")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    # Режим ускорения стресс-тестов (дефект #111): уменьшает ЧИСЛО итераций
    # нагружающих циклов, НЕ отключая ни одного теста и не теряя покрытия.
    if not args.full_stress:
        CHILD_ENV["KERN_MUTATE_FAST"] = "1"
    # Каталог решателя -> в PATH ДОЧЕРНИХ прогонов (дефект #110).
    if args.z3_path and os.path.exists(args.z3_path):
        CHILD_ENV["PATH"] = (os.path.dirname(os.path.abspath(args.z3_path))
                             + os.pathsep + CHILD_ENV.get("PATH", ""))

    if not zig_available():
        print(f"[!] компилятор `{ZIG}` не найден: прогон невозможен. "
              "Задайте KERN_ZIG=<путь к zig>.", file=sys.stderr)
        sys.exit(2)

    # 🔴 ДЕФЕКТ #110 (найден ЗАМЕРОМ): БЕЗ РЕШАТЕЛЯ 8 тестов МОЛЧА пропускаются,
    # и скор считается по УСЕЧЁННОМУ набору -> он невоспроизводим и занижен.
    # Замер: без z3 `263 passed; 8 skipped`, с z3 `271 passed`.
    if not solver_available():
        print("[!] `z3` НЕ найден в PATH: 8 тестов вернут SkipZigTest, и "
              "мутационный скор будет посчитан по УСЕЧЁННОМУ набору "
              "(ложные выжившие). Добавьте решатель в PATH.", file=sys.stderr)
        if args.require_solver:
            print("    --require-solver: выход (скор несопоставим).", file=sys.stderr)
            sys.exit(2)

    sites = collect(root)
    print(f"[i] найдено сайтов мутации: {len(sites)}; берём не более {args.max}", flush=True)
    # ВАРИАНТ Б: полный прогон указанных файлов БЕЗ сэмплинга.
    if args.full_file:
        want = set(args.full_file)
        sites = [s for s in sites if s[0] in want]
        print("[i] ВАРИАНТ Б: полный набор сайтов без сэмплинга для: "
              + ", ".join(sorted(want)), flush=True)
    random.seed(args.seed)
    if not args.full_file and len(sites) > args.max:
        sites = sample_stratified(sites, args.max, args.per_file_min, args.seed)
        dist = {}
        for s in sites:
            dist[s[0]] = dist.get(s[0], 0) + 1
        print("[i] стратифицированная выборка (>= " + str(args.per_file_min) + " на файл):", flush=True)
        for rel in sorted(dist):
            print(f"      {dist[rel]:>3}  {rel}", flush=True)

    # БЛОКИРОВКА + СНИМОК ХЭША: гарантия, что оригинал не тронут.
    lock_path = acquire_lock(root)
    before = tree_hash(root)

    # РАБОЧИЕ КОПИИ: мутации вносятся ТОЛЬКО сюда. Оригинальное дерево
    # не открывается на запись ни разу за весь прогон.
    jobs = max(1, args.jobs)
    works = [make_work_copy(root) for _ in range(jobs)]
    dir_q = queue.Queue()
    for w in works:
        dir_q.put(w)
    print(f"[i] рабочих копий: {jobs} (оригинал не изменяется)", flush=True)

    results = [None] * len(sites)
    done = [0]
    print_lock = threading.Lock()

    slot_uses = {}

    def job(idx, site):
        w = dir_q.get()
        try:
            status = run_one(w, site)
            # ЗАЩИТА ОТ ENOSPC (найдено прогоном 1225 сайтов): раз в N мутантов
            # проверяем размер кэша слота; иначе /dev/shm переполняется и
            # ошибка компиляции даёт ЛОЖНЫЕ убийства.
            slot_uses[w] = slot_uses.get(w, 0) + 1
            if slot_uses[w] % _CACHE_TRIM_EVERY == 0:
                _trim_slot_cache(w)
        finally:
            dir_q.put(w)
        rel, ln, _pat, _rep, name, _code = site
        with print_lock:
            done[0] += 1
            results[idx] = (site, status)
            mark = {"KILLED_COMPILE": "killed (compile) ✅",
                    "KILLED_TEST": "killed ✅",
                    "KILLED_TIMEOUT": "killed (timeout) ✅",
                    "SURVIVED": "SURVIVED ❌"}[status]
            print(f"  [{done[0]}/{len(sites)}] {rel}:{ln+1} [{name}] -> {mark}",
                  flush=True)

    try:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            list(ex.map(lambda p: job(*p), enumerate(sites)))
    finally:
        for w in works:
            shutil.rmtree(w, ignore_errors=True)
        release_lock(lock_path)

    killed = survived = kc = kt = 0
    survivors = []
    for site, status in results:
        rel, ln, _pat, _rep, name, _code = site
        if status == "KILLED_TIMEOUT":
            killed += 1
            kt += 1
        elif status == "SURVIVED":
            survived += 1
            survivors.append(f"{rel}:{ln+1} [{name}]")
        else:
            killed += 1
            kc += 1 if status == "KILLED_COMPILE" else 0
            kt += 1 if status != "KILLED_COMPILE" else 0

    # КОНТРОЛЬ ЦЕЛОСТНОСТИ ОРИГИНАЛА.
    after = tree_hash(root)
    if before != after:
        print("\n[!!] КРИТИЧНО: исходники изменились во время прогона! "
              "Проверьте `git status`.", file=sys.stderr)
    else:
        print(f"\n[i] целостность оригинала подтверждена (sha256 {before[:16]}…)")

    total = killed + survived
    score = (killed / total * 100.0) if total else 0.0
    print("\n=== МУТАЦИОННОЕ ТЕСТИРОВАНИЕ KERN ===")
    print(f"Всего мутантов:      {total}")
    print(f"Killed (compile):    {kc}")
    print(f"Killed (test):       {kt}")
    print(f"Survived (ДЫРЫ):     {survived}")
    equiv = sum(1 for site, status in results
                if status == "SURVIVED" and is_known_equivalent(site[0], site[5]))
    # ФОРМУЛА (DO-178C / IEEE): Score = Killed / (Total - Equivalent).
    # ИЗМЕРЕНО на прогоне: прежняя версия делила ВЫЖИВШИХ на знаменатель и
    # печатала 10.8% вместо 97.3% — считаем именно УБИТЫХ.
    eff_total = len(results) - equiv
    eff = killed / eff_total * 100 if eff_total else 100.0
    print(f"MUTATION SCORE (сырой):            {score:.1f}%  "
          f"(убито {killed}/{len(results)})")
    print(f"ЭФФЕКТИВНЫЙ СКОР (без доказанно эквивалентных): {eff:.1f}%  "
          f"(убито {killed}/{eff_total})")
    if equiv:
        print(f"  из выживших ДОКАЗАННО ЭКВИВАЛЕНТНЫ: {equiv}")
    if survivors:
        print("Выжившие мутанты (усилить тесты):")
        for s in survivors:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
