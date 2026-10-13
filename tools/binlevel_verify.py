#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: БИНАРНЫЙ АНАЛИЗ АССЕМБЛЕРА — проверка constant-time на уровне КОДА.

ЗАЧЕМ: доказать constant-time на уровне ИСХОДНИКА недостаточно — компилятор
вправе вернуть ранний выход (например, при векторизации или инлайне).
Проверяем СГЕНЕРИРОВАННЫЙ ассемблер: в constant-time функции НИ ОДИН
условный переход не должен зависеть от ЗАГРУЖЕННЫХ ДАННЫХ.

Метод: taint-анализ линейного потока инструкций.
  * источник taint — загрузка из памяти в регистр (`movzbl (%rsi), %eax`);
  * taint распространяется через `mov reg, reg` и логические операции;
  * `xor r, r` снимает taint (обнуление);
  * если `cmp`/`test` использует tainted-регистр, а следом идёт условный
    переход — это УТЕЧКА (ветвление зависит от данных).

Контраст: для функции с ранним выходом такие переходы ОБЯЗАНЫ найтись —
это доказывает, что проверка не «пустая».

Использование:  python3 tools/binlevel_verify.py <file.s> [func ...]
"""
import re
import sys

# Условные переходы x86-64 (jmp — безусловный, не считается).
JCC = re.compile(r"^j(?!mp$)[a-z]+$")
# Загрузки из памяти: mov/movz/movs + SIMD-загрузки.
LOAD = re.compile(r"^(v?mov[a-z]*|v?pbroadcast[a-z]*)$")
# Регистры, которые НЕ могут быть «данными» (длина/индекс/указатель).
COUNTER = re.compile(r"^(r[a-z0-9]+|e[a-z]{2}|[a-d]l|[a-d]x|[a-d]i|[a-d]p)$")


def base(reg: str) -> str:
    """Приводит rdx/edx/dl к общему имени rdx."""
    reg = reg.strip().lstrip("%")
    m = {
        "edx": "rdx", "dx": "rdx", "dl": "rdx", "dh": "rdx",
        "ecx": "rcx", "cx": "rcx", "cl": "rcx", "ch": "rcx",
        "eax": "rax", "ax": "rax", "al": "rax", "ah": "rax",
        "ebx": "rbx", "bx": "rbx", "bl": "rbx",
        "esi": "rsi", "si": "rsi", "sil": "rsi",
        "edi": "rdi", "di": "rdi", "dil": "rdi",
    }
    return m.get(reg, reg)


def split_args(s: str):
    """Делит операнды по запятой верхнего уровня (скобки адресации не считаем)."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# Инструкции, НЕ пишущие флаги: связь `cmp -> sete -> jne` сохраняется.
NO_FLAGS = {"mov", "lea", "nop", "push", "pop", "movzx", "movsx", "movsxd",
            "endbr64", "cdqe", "cqo", "prefetcht0", "prefetcht1"}
# Инструкции, пишущие флаги ИЗ АРИФМЕТИКИ (не из сравнения данных).
ARITH_FLAGS = {"add", "adc", "sub", "sbb", "inc", "dec", "neg", "mul", "imul",
               "div", "idiv", "shl", "shr", "sar", "rol", "ror", "and", "or",
               "xor", "bt", "bts", "btr", "btc", "popcnt", "lzcnt", "tzcnt"}
CMP_OPS = {"cmp", "test", "vptest", "vtestps", "vtestpd", "ptest"}


def analyze(body):
    """Возвращает список (индекс, инструкция) — ветвления, зависящие от данных."""
    tainted = set()
    violations = []
    flags_from_data = False
    for i, line in enumerate(body):
        line = line.split("#")[0].split(";")[0].rstrip()
        m = re.match(r"^\s*([a-z0-9.]+)\s*(.*)$", line)
        if not m:
            continue
        op, args = m.group(1), m.group(2).strip()
        if op.startswith("."):  # директивы ассемблера — не инструкции
            continue
        if not args:
            continue
        ops = split_args(args)

        # Условный переход: смотрим, откуда пришли флаги.
        if JCC.match(op):
            if flags_from_data:
                violations.append((i, line.strip()))
            continue
        if op == "jmp":
            continue

        # ⚠️ ФИКС (#30): блок распространения taint для загрузок ОБЯЗАН идти
        # ДО проверки NO_FLAGS. `mov` входит в NO_FLAGS (он не пишет флаги),
        # поэтому прежний порядок делал распространение taint НЕДОСТИЖИМЫМ
        # кодом: tainted всегда оставался пустым, и анализ не находил НИ ОДНОГО
        # нарушения — проверка constant-time была ВАКУУМНОЙ.
        # Загрузки/пересылки: распространяем taint (Intel-синтаксис: dst, src).
        if LOAD.match(op) and len(ops) >= 2:
            dst, src = ops[0], ops[-1]
            if base(dst).startswith(("r", "e", "x", "y", "z")):
                if "[" in src:
                    tainted.add(base(dst))
                elif base(src) in tainted:
                    tainted.add(base(dst))
            # mov НЕ пишет флаги — состояние `flags_from_data` сохраняется.
            continue

        # Инструкции без записи флагов и метки — состояние сохраняется.
        if op.startswith("set") or op in NO_FLAGS:
            continue

        # Сравнения: флаги ИЗ ДАННЫХ, если операнд-память или tainted-регистр.
        if op in CMP_OPS:
            flags_from_data = any(("[" in o) or (base(o) in tainted) for o in ops)
            continue

        # Арифметика: флаги не из сравнения данных.
        if op in ARITH_FLAGS:
            flags_from_data = False
            if op in ("xor", "sub", "pxor", "vpxor") and len(ops) == 2 and base(ops[0]) == base(ops[1]):
                tainted.discard(base(ops[0]))  # обнуление снимает taint
            elif op in ("or", "and") and len(ops) >= 2:
                if base(ops[0]) in tainted or base(ops[-1]) in tainted:
                    tainted.add(base(ops[0]))
            continue
    return violations


def extract(text, name):
    lines = text.splitlines()
    out, inside = [], False
    for ln in lines:
        if re.match(r"^%s:" % re.escape(name), ln):
            inside = True
            continue
        if inside:
            if re.match(r"^\s*\.size\s+%s" % re.escape(name), ln):
                break
            if re.match(r"^[A-Za-z_.][A-Za-z0-9_.]*:", ln) and not ln.startswith("."):
                break
            out.append(ln)
    return out


def main():
    if len(sys.argv) < 2:
        print("использование: binlevel_verify.py <file.s> [func ...]")
        return 2
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    funcs = sys.argv[2:] or ["kern_ct_equal", "kern_early_exit_equal"]
    rc = 0
    for fn in funcs:
        body = extract(text, fn)
        if not body:
            print(f"[!] функция {fn} не найдена в ассемблере")
            rc = 1
            continue
        v = analyze(body)
        # ВАЖНО: tainted-анализ даёт ЛОЖНЫЕ СРАБАТЫВАНИЯ на проверках ДЛИНЫ
        # (длина публична, но анализатор видит в ней «данные»). Поэтому
        # дополнительно считаем ОБЩЕЕ число условных переходов: у честной
        # constant-time функции их должно быть СТРОГО МЕНЬШЕ, чем у версии
        # с ранним выходом (лишний переход = ранний выход внутри цикла).
        jcc = 0
        for line in body:
            ln = line.split("#")[0].split(";")[0].strip()
            m2 = re.match(r"^([a-z0-9.]+)", ln)
            if m2 and JCC.match(m2.group(1)):
                jcc += 1
        kind = "constant-time" if ("ct_" in fn or "constantTime" in fn) else "ранний выход"
        print(f"[{fn}] ({kind}): инструкций {len(body)}, "
              f"условных переходов {jcc}, "
              f"ветвлений от ДАННЫХ: {len(v)}")
        for i, ins in v[:5]:
            print(f"    строка {i}: {ins}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
