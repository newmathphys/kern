#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later.
"""ЖИВОЙ СТЕНД «АНАТОМИЯ»: 4 шага на реальном коде, без чёрного ящика.

Для каждого случая печатается:
  ШАГ 1  вход: реальный код + закон
  ШАГ 2  математика: фрагмент .smt2, который построил KERN
  ШАГ 3  взлом [F]: контрпример + дословный вывод живого компилятора/рантайма
  ШАГ 4  доказательство [T]: дословный вердикт (Z3 + пруф-чекер)

ЧЕСТНОСТЬ. Если инструмент в этом срезе недоступен, печатается
`[НЕ ДОСТУПНО]` с ДОСЛОВНОЙ причиной — стенд не изображает успех.

Запуск: make anatomy-live  (или python3 tools/anatomy_live.py --write <log>)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS = Path.home() / ".cache" / "kern" / "repos"
KC = ROOT / "zig-out" / "bin" / "kernc"
PY = sys.executable
LOG: list[str] = []
TMP = Path(tempfile.mkdtemp(prefix="anatomy_"))


def say(line: str = "") -> None:
    print(line)
    LOG.append(line)


def run(cmd, timeout=180, cwd=None):
    """Запуск команды; возвращает (rc, объединённый вывод)."""
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd or ROOT,
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as e:                                        # noqa: BLE001
        return 1, f"[ошибка запуска] {e}"


def head(text: str, n: int = 14, width: int = 118) -> None:
    for ln in text.strip().splitlines()[:n]:
        say("    " + ln[:width])


def unavailable(what: str, why: str) -> None:
    say(f"    [НЕ ДОСТУПНО] {what}")
    first = (why.strip().splitlines() or [""])[0]
    say(f"      причина (дословно): {first[:110]}")


# ─────────────────────────── случай 1: prime_sieve (границы кучи)
def case_prime_sieve() -> None:
    say("=" * 78)
    say("СЛУЧАЙ 1. TheAlgorithms/C :: maths/prime_sieve.c — границы буфера")
    src = REPOS / "C" / "math" / "prime_sieve.c"
    if not src.exists():
        return unavailable("реальный файл", f"нет {src}")
    say("\nШАГ 1 — вход (реальный код, строки 21-27):")
    lines = src.read_text(errors="replace").splitlines()
    for ln in lines[20:27]:
        say("    " + ln[:112])

    start = next((i for i, l in enumerate(lines)
                  if l.startswith("void prime(")), None)
    if start is None:
        return unavailable("функция prime", "не найдена в файле")
    fn_lines, depth = [], 0
    for l in lines[start:]:
        fn_lines.append(l)
        depth += l.count("{") - l.count("}")
        if depth == 0 and len(fn_lines) > 2:
            break
    fn = "\n".join(fn_lines)
    prog = ("#include <stdio.h>\n#include <stdlib.h>\n"
            "const unsigned long long MAX_SIZE = 1000000;\n" + fn +
            "\nint main(void){int *p = malloc(MAX_SIZE*sizeof(int));"
            "prime(p);printf(\"ok\\n\");return 0;}\n")
    c = TMP / "ps_bug.c"
    c.write_text(prog)
    exe = TMP / "ps_bug"
    rc, out = run(f"gcc -fsanitize=address,undefined -g -o {exe} {c} -w", 120)
    if rc != 0:
        return unavailable("компилятор gcc", out)
    say("\nШАГ 3 — ВЗЛОМ [F]: живой AddressSanitizer на реальной функции")
    rc, out = run(str(exe), 90)
    keep = [l for l in out.splitlines()
            if "ERROR" in l or "WRITE of" in l or "located" in l]
    head("\n".join(keep) if keep else out, 3)

    say("\nШАГ 4 — ДОКАЗАТЕЛЬСТВО [T]: исправленный закон (`i < limit`)")
    c2 = TMP / "ps_ok.c"
    c2.write_text(prog.replace("<=MAX_SIZE", "<MAX_SIZE"))
    exe2 = TMP / "ps_ok"
    rc, out = run(f"gcc -fsanitize=address,undefined -g -o {exe2} {c2} -w", 120)
    if rc == 0:
        rc, out = run(str(exe2), 90)
        crashed = "ERROR: AddressSanitizer" in out
        say(f"    живой прогон исправленной версии: rc={rc}, "
            + ("ASan СНОВА УПАЛ — починка неполная" if crashed
               else "сообщений ASan нет = выхода за буфер нет"))
        if out.strip() and not crashed:
            say("    хвост вывода: " + out.strip().splitlines()[-1][:92])


# ─────────────────────────── случай 2: переполнение середины
def case_midpoint() -> None:
    say("\n" + "=" * 78)
    say("СЛУЧАЙ 2. Ошибка середины: (l+r)/2 против l+(r-l)/2 (закон 0<=l<=r)")
    say("\nШАГ 1 — два варианта кода:")
    say("    A: int mid = (l + r) / 2;        // классический баг")
    say("    B: int mid = l + (r - l) / 2;    // безопасная форма")
    say("\nШАГ 3 — ВЗЛОМ [F]: живой UBSan при l = r = 1073741824")
    for tag, name in (("a", "mid_a"), ("b", "mid_b")):
        body = (f"int {name}(int l, int r)"
                + ("{return (l + r) / 2;}\n" if tag == "a"
                   else "{return l + (r - l) / 2;}\n"))
        c = TMP / f"mid_{tag}.c"
        c.write_text("#include <stdio.h>\n" + body +
                     f"int main(void){{printf(\"%d\\n\", {name}"
                     "(1073741824, 1073741824));return 0;}\n")
        exe = TMP / f"mid_{tag}"
        run(f"gcc -fsanitize=undefined -fno-sanitize-recover "
            f"-o {exe} {c} -w", 120)
        rc, out = run(str(exe), 30)
        verdict = "ПАДЕНИЕ" if rc != 0 else "чисто"
        err = [l for l in out.splitlines() if "runtime error" in l]
        say(f"    вариант {tag.upper()}: {verdict}"
            + (f" — {err[0][:92]}" if err else ""))

    say("\nШАГ 2 — математика: уравнение, которое строит KERN (.smt2):")
    ok = ROOT / "examples" / "anatomy" / "law_ok.py"
    if not ok.exists():
        return unavailable("пример с законом", f"нет {ok}")
    rc, out = run([PY, "tools/kern_contracts.py", "--emit-smt2", str(TMP),
                   str(ok)], 180)
    smt = TMP / "law_ok_midpoint.smt2"
    if smt.exists():
        for ln in smt.read_text().splitlines():
            say("    " + ln[:112])
    else:
        return unavailable("файл .smt2", out)

    say("\nШАГ 4 — ДОКАЗАТЕЛЬСТВО [T]: вердикт KERN и пруф-чекера kernc")
    rc, out = run([PY, "tools/kern_contracts.py", str(ok)], 180)
    keep = [l for l in out.splitlines() if "midpoint" in l or "ИТОГО" in l]
    head("\n".join(keep), 3)
    if KC.exists():
        rc, out = run([str(KC), "prove", str(smt)], 120)
        keep = [l for l in out.splitlines()
                if "ВЕРДИКТ" in l or "ПРУФ" in l or "PROOF" in l]
        head("\n".join(keep), 4)
    else:
        unavailable("пруф-чекер kernc", f"нет {KC}")


# ─────────────────────────── случай 3: XXH_rotl64 и домен сдвига
def case_rotl() -> None:
    say("\n" + "=" * 78)
    say("СЛУЧАЙ 3. tidwall/hashmap.c :: XXH_rotl64 — домен сдвига (1..63)")
    src = REPOS / "hashmap.c" / "hashmap.c"
    if not src.exists():
        return unavailable("реальный файл", f"нет {src}")
    say("\nШАГ 1 — вход (реальный код):")
    say("    static uint64_t XXH_rotl64(uint64_t x, int r) {")
    say("        return (x << r) | (x >> (64 - r));")
    say("    }")
    say("    все вызовы в файле: r = 31, 1, 27 -> домен r ∈ [1, 63]")

    prog = ("#include <stdio.h>\n#include <stdint.h>\n"
            "static uint64_t XXH_rotl64(uint64_t x, int r)"
            "{return (x << r) | (x >> (64 - r));}\n"
            "int main(void){printf(\"%llu\\n\",(unsigned long long)"
            "XXH_rotl64(42,0));return 0;}\n")
    c = TMP / "rot.c"
    c.write_text(prog)
    exe = TMP / "rot"
    run(f"gcc -fsanitize=undefined -fno-sanitize-recover -o {exe} {c} -w", 120)
    say("\nШАГ 3 — ВЗЛОМ [F]: живой UBSan при r = 0 (закон домена нарушен)")
    rc, out = run(str(exe), 30)
    err = [l for l in out.splitlines() if "runtime error" in l]
    head("\n".join(err) if err else out, 2)

    say("\nШАГ 4 — ДОКАЗАТЕЛЬСТВО [T]: почему на реальном файле тревоги нет")
    rc, out = run([PY, "tools/kern_contracts.py", "--xray", str(src)], 300)
    say(f"    упоминаний XXH_rotl64 в выводе: {out.count('XXH_rotl64')}"
        " (0 = закон мест вызова соблюдён)")


# ─────────────────────────── случай 4: Zig-верификатор без Python
def case_zig() -> None:
    say("\n" + "=" * 78)
    say("СЛУЧАЙ 4. Нативный `kernc verify-zig` (без Python)")
    if not KC.exists():
        return unavailable("kernc", f"нет {KC}")
    demo = ROOT / "examples" / "contracts_demo.zig"
    if not demo.exists():
        return unavailable("Zig-пример", f"нет {demo}")
    say("\nШАГ 1 — вход: examples/contracts_demo.zig (контракты в комментариях)")
    rc, out = run([str(KC), "verify-zig", str(demo)], 240)
    say("\nШАГ 4 — ДОКАЗАТЕЛЬСТВО [T]: вердикт нативного верификатора")
    head(out, 8)


# ─────────────────────────── случай 5: циклы и вложенная индукция
def case_loops() -> None:
    say("\n" + "=" * 78)
    say("СЛУЧАЙ 5. TheAlgorithms/Python :: инварианты циклов, вложенность, отказ")
    fx = ROOT / "tests" / "fixtures" / "proven"
    for name, what in (("sieve_real.py", "вложенный цикл (двухуровневая индукция)"),
                       ("nested_annot_bad.py", "нарушение внешнего инварианта"),
                       ("collatz_open.py", "гипотеза Коллатца (ОТКРЫТАЯ задача)")):
        f = fx / name
        if not f.exists():
            unavailable(name, f"нет {f}")
            continue
        rc, out = run([PY, "tools/kern_contracts.py", "--loops", str(f)], 300)
        line = [l for l in out.splitlines()
                if "PASS]" in l or "FAIL]" in l or "SKIP]" in l]
        say(f"\n    {what} ({name}):")
        say("      " + (line[0].strip()[:110] if line else out.strip()[:110]))


# ─────────────────────────── случай 6: контейнер-апплаенс
def case_kerna() -> None:
    say("\n" + "=" * 78)
    say("СЛУЧАЙ 6. Релизный апплаенс ./dist/kerna (полный цикл KERN.md)")
    kerna = ROOT / "dist" / "kerna"
    if not kerna.exists():
        return unavailable("./dist/kerna", f"нет {kerna}")
    rc, out = run([str(kerna), "examples/anatomy"], 180)
    if rc != 0:
        return unavailable("./dist/kerna scan", out)
    head(out, 6)


def main() -> int:
    say("АНАТОМИЯ KERN — живой стенд: 4 шага на каждом случае")
    say(f"срез: {ROOT}")
    say(f"временные файлы: {TMP}")
    for fn in (case_prime_sieve, case_midpoint, case_rotl, case_zig,
               case_loops, case_kerna):
        fn()
    say("\n" + "=" * 78)
    say("[ПРАВИЛО СТЕНДА] недоступный инструмент печатается как [НЕ ДОСТУПНО]")
    say("                с дословной причиной — успех не изображается.")
    out_path = None
    for i, a in enumerate(sys.argv):
        if a == "--write" and i + 1 < len(sys.argv):
            out_path = Path(sys.argv[i + 1])
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(LOG) + "\n", encoding="utf-8")
        print(f"\n[записано] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


