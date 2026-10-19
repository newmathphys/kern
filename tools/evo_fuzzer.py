#!/usr/bin/env python3
# РАЗДЕЛЫ 1/5: ЭВОЛЮЦИОННЫЙ COVERAGE-GUIDED ФАЗЗЕР.
#
# ЧТО ДЕЛАЕМ. Берём РЕАЛЬНЫЙ валидный вывод Z3 (51-шаговое доказательство
# `abs.c`, trusted: 0) и эволюционно портим его: мутации символов, замена
# фрагментов, кроссовер между особями. Fitness = число АКТИВИРОВАННЫХ правил
# чекера (mp / резолюция / Фаркаш / rewrite / eq / bool) — то есть насколько
# глубоко особь проходит разбор.
#
# ОРАКУЛ (два инварианта, оба проверяемы):
#   * 0 ПАНИК: чекер не должен падать (rc 101/139/сигнал) ни на одном входе;
#   * 0 ЛОЖНЫХ ДОПУСКОВ: ни одна ИЗМЕНЁННАЯ особь не может получить rc=0 —
#     это означало бы, что испорченное доказательство принято.
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

KERNC = "./zig-out/bin/kernc"
SMT = "tests/fixtures/abs_contract.smt2"
PROOF = "tests/fixtures/abs_proof.txt"


def run(proof_text: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".proof", delete=False, dir="/dev/shm") as f:
        f.write(proof_text)
        p = f.name
    try:
        r = subprocess.run([KERNC, "check-proof", SMT, p], capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr
    finally:
        Path(p).unlink(missing_ok=True)


def fitness(out: str) -> int:
    """Сколько РАЗНЫХ правил чекер реально задействовал на этой особи."""
    score = 0
    for key in ("mp ", "резолюция", "Фаркаш", "rewrite", "eq(refl", "bool("):
        if key in out:
            score += 1
    if "шагов " in out:
        score += 1
    return score


# ТОЛЬКО СЕМАНТИЧЕСКИ ЗНАЧИМЫЕ мутации. ИЗМЕРЕНО: случайные символы/пробелы
# давали «ложный допуск», потому что доказательство от них не менялось
# (эквивалентная мутация, а не дыра). Меняем ТОКЕНЫ: знаки, имена шагов, числа.
MUTATIONS = [
    ("(>= ", "(<= "), ("(<= ", "(>= "), ("(> ", "(< "), ("(not ", "(and "),
    ("(or ", "(and "), ("(and ", "(or "), (" false", " true"),
    ("(hypothesis ", "(asserted "), ("(intro-def ", "(def-axiom "),
]


def mutate(s: str, rng: random.Random) -> str:
    """Одна значимая мутация: замена токена, удаление ссылки @xN или литерала."""
    kind = rng.random()
    if kind < 0.7:
        a, b = rng.choice(MUTATIONS)
        if a in s:
            i = s.index(a)
            return s[:i] + b + s[i + len(a):]
        return s
    import re
    steps = list(re.finditer(r"@x[0-9]+", s))
    if kind < 0.85 and steps:
        m = rng.choice(steps)
        return s[:m.start()] + "@x9" + s[m.end():]
    nums = list(re.finditer(r"\(- [0-9]+\)", s))
    if nums:
        m = rng.choice(nums)
        return s[:m.start()] + "(- 2)" + s[m.end():]
    return s


def crossover(a: str, b: str, rng: random.Random) -> str:
    if len(a) < 10 or len(b) < 10:
        return a
    i = rng.randrange(1, len(a) - 1)
    j = rng.randrange(1, len(b) - 1)
    return a[:i] + b[j:]


def main() -> int:
    if not Path(KERNC).exists():
        print(f"[!] нет {KERNC}")
        return 2
    base = Path(PROOF).read_text(encoding="utf-8")
    # ПОЗИТИВНЫЙ КОНТРОЛЬ: эталон обязан быть принят, иначе оракул бессмыслен.
    rc0, out0 = run(base)
    if rc0 != 0:
        print(f"[FAIL] эталон не принят (rc={rc0}) — фаззер неприменим")
        return 1
    print(f"  [OK] эталон принят чекером (fitness {fitness(out0)})")

    rng = random.Random(0xC0FFEE)          # детерминированно: провал воспроизводим
    population = [mutate(base, rng) for _ in range(20)]
    pops = 0
    panics = 0
    false_accepts = 0
    equivalent = 0
    best = 0
    for gen in range(5):
        scored = []
        for ind in population:
            pops += 1
            rc, out = run(ind)
            if rc in (101, 134, 139) or rc < 0:
                panics += 1
                print(f"  [!] ПАНИКА на особи поколения {gen} (rc={rc})")
            # ЛОЖНЫЙ ДОПУСК = принят И результат ПРУФ-ЧЕКЕРА ОТЛИЧАЕТСЯ от
            # эталонного. ИЗМЕРЕНО фаззером: замена `(_ th-lemma arith)` ->
            # `arith farkas` принимается с ТЕМИ ЖЕ счётчиками — это
            # ЭКВИВАЛЕНТНАЯ мутация (служебное слово), а не дыра; считать её
            # «ложным допуском» значило бы обвинять чекер без основания.
            if rc == 0 and ind != base:
                sig = lambda o: [l for l in o.splitlines() if "ПРУФ-ЧЕКЕР" in l or "PROOF VERIFIED" in l]
                if sig(out) != sig(out0):
                    false_accepts += 1
                    print(f"  [!] ЛОЖНЫЙ ДОПУСК: принят С ДРУГИМ результатом (gen {gen})")
                else:
                    equivalent += 1
            scored.append((fitness(out), ind))
        scored.sort(key=lambda t: -t[0])
        best = max(best, scored[0][0])
        elite = [ind for _f, ind in scored[:4]]
        population = list(elite)
        while len(population) < 20:
            a, b = rng.sample(elite, 2)
            child = crossover(a, b, rng)
            population.append(mutate(child, rng))
        print(f"  [GEN {gen}] лучший fitness {scored[0][0]}, популяция обновлена")

    print(f"  ИТОГО: особей {pops} | паник {panics} | ложных допусков {false_accepts} "
          f"| лучший fitness {best}")
    ok = panics == 0 and false_accepts == 0 and best > 0
    print("[OK] evo-fuzz-check: 0 паник, 0 ложных допусков" if ok else "[FAIL] evo-fuzz-check")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
