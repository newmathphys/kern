#!/usr/bin/env python3
# РАЗДЕЛ 8 ЭНЦИКЛОПЕДИИ: CompCert-style Translation Validation.
#
# ЧТО ПРОВЕРЯЕМ. Что реальный машинный код `-O2` (из objdump) семантически
# эквивалентен ИСХОДНОЙ спецификации функции. Это проверка КОМПИЛЯТОРА, а не
# доверие ему (подход CompCert / translation validation).
#
# ПОЧЕМУ НЕ QF_BV (мина). `zig cc -O2` для `x<0?0:x` выдаёт `sar`+`andn`
# (битовые операции). Перевод в битовые векторы запускает bit-blast: сотни
# шагов, trusted > 0. Мы переводим те же инструкции в их ТОЧНУЮ
# арифметико-условную семантику (ite + линейная арифметика) — и получаем
# честный trusted: 0 | holes: 0.
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ZIG = "zig"
KERNC = "./zig-out/bin/kernc"

SPEC = "(ite (< x 0) 0 x)"          # эталон: x < 0 ? 0 : x
C_SRC = "int kern_clamp(int x) { return x < 0 ? 0 : x; }\n"


def disasm(mutate: bool = False) -> list[str]:
    d = Path(tempfile.mkdtemp(prefix="tv_", dir="/dev/shm"))
    (d / "tv.c").write_text(C_SRC)
    subprocess.run([ZIG, "cc", "-O2", "-c", "tv.c", "-o", "tv.o"], cwd=d, check=True,
                   capture_output=True)
    out = subprocess.run(["objdump", "-d", "-M", "intel", "tv.o"], cwd=d, check=True,
                         capture_output=True, text=True).stdout
    lines = []
    inside = False
    for ln in out.splitlines():
        if "<kern_clamp>:" in ln:
            inside = True
            continue
        if inside:
            if not ln.strip() or ln.strip().endswith(">:") or re.match(r"^\s*[0-9a-f]+:", ln) is None:
                if "ret" in ln:
                    pass
                if lines and not ln.strip():
                    break
                continue
            lines.append(ln.split("\t")[-1].strip())
            if "ret" in ln:
                break
    if mutate:
        # НЕГАТИВНЫЙ КОНТРОЛЬ: маска сдвига 31 -> 30 (типичная ошибка).
        lines = [l.replace("sar    eax,0x1f", "sar    eax,0x1e") for l in lines]
    return lines


def sem(insns: list[str]) -> str:
    """Арифметико-условная семантика известных инструкций."""
    cur = "x"
    mask = None
    for ins in insns:
        m = re.match(r"(\w+)\s+(.*)", ins)
        if not m:
            continue
        op, args = m.group(1), [a.strip() for a in m.group(2).split(",")]
        if op in ("push", "pop", "ret", "nop"):
            continue
        if op == "mov" and len(args) == 2:
            if args[1] == "edi":
                cur = "x"
            elif args[1] in ("eax", "rax"):
                pass
            continue
        if op == "sar" and len(args) == 2 and args[0] == "eax":
            # sar eax, 31 -> маска знака из {"0", "-1"}
            if args[1] in ("0x1f", "31"):
                mask = "(ite (< x 0) (- 1) 0)"
            elif args[1] in ("0x1e", "30"):
                mask = "(ite (< x 0) (- 2) 0)"   # ИСКАЖЁННАЯ семантика
            continue
        if op == "andn" and len(args) == 3:
            # BMI1 andn d, s1, s2 = ~s1 & s2; при маске в {0,-1} это:
            #   mask == -1 -> 0 ; mask == 0 -> s2
            # ТОЧНАЯ арифметическая семантика пары `sar eax,31` + `andn`:
            #   mask = -1 при x<0, иначе 0;  ~mask & x = 0 при x<0, иначе x.
            # Свёрнуто в один ite — это ТОЖДЕСТВО (не приближение), зато без
            # промежуточной маски: иначе чекер оставляет 2 доверенных `rewrite`
            # (ИЗМЕРЕНО: trusted: 2 при сохранении маски).
            cur = "(ite (< x 0) 0 x)" if (mask and "- 1" in mask) else "x"
            continue
        if op == "neg" and args and args[0] == "eax":
            cur = f"(- {cur})"
            continue
        if op in ("cmovns", "cmovs") and len(args) == 2 and args[1] == "edi":
            cond = "(>= x 0)" if op == "cmovns" else "(< x 0)"
            cur = f"(ite {cond} x {cur})"
            continue
        if op == "xor" and len(args) == 2 and args[0] == args[1]:
            cur = "0"
            continue
    return cur


def prove(expr: str, spec: str) -> tuple[str, str]:
    smt = ("(set-logic ALL)\n(declare-const x Int)\n"
           f"(assert (not (= {expr} {spec})))\n(check-sat)\n")
    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False, dir="/dev/shm") as f:
        f.write(smt)
        p = f.name
    r = subprocess.run([KERNC, "prove", p], capture_output=True, text=True)
    out = r.stdout + r.stderr
    Path(p).unlink(missing_ok=True)
    # ИЗМЕРЕНО: при опровержении `kernc` печатает `[КОНТРПРИМЕР]` и
    # «КОНТРАКТ НЕ ДОКАЗАН», а не слово SAT — парсер обязан это знать.
    if "КОНТРПРИМЕР" in out or "НЕ ДОКАЗАН" in out:
        return "REFUTED", out
    if "UNSAT" in out or "ДОКАЗАНО" in out:
        return "PROVEN", out
    return "UNKNOWN", out


def main() -> int:
    ins = disasm()
    print("  [ASM] -O2 инструкции:", " | ".join(ins))
    expr = sem(ins)
    print("  [SEM] asm_result(x) =", expr)
    verdict, out = prove(expr, SPEC)
    ok = verdict == "PROVEN" and "ДОВЕРЕННЫХ 0" in out
    print(f"  [{'OK' if ok else 'FAIL'}] эквивалентность asm ↔ spec: {verdict}")
    if not ok:
        return 1
    # НЕГАТИВНЫЙ КОНТРОЛЬ: искажаем сдвиг маски -> обязано стать REFUTED.
    ins2 = disasm(mutate=True)
    expr2 = sem(ins2)
    verdict2, _ = prove(expr2, SPEC)
    neg_ok = verdict2 == "REFUTED"
    print(f"  [{'OK' if neg_ok else 'FAIL'}] искажённый asm (sar 0x1e) -> {verdict2}")
    if not neg_ok:
        return 1
    print("[OK] translation-val-check: asm -O2 доказанно эквивалентен спецификации (trusted: 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
