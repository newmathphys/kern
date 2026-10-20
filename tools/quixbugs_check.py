#!/usr/bin/env python3
"""QuixBugs baseline: 40 пар buggy/correct через `--diff-equiv`.

Ничего в репозитории не меняет. Классификация исходов:
  DIVERGED   — расхождение ДОКАЗАНО (есть контрпример Z3);
  EQUIVALENT — поведение совпадает на всём Z;
  UNKNOWN    — тело содержит `_havoc_k` (абстракция вызова): расхождение
               НЕДОКАЗУЕМО. Дефект #206: без этой ветки havoc давал ложный
               `[DIVERGED]` (два разных havoc всегда «различны»);
  SKIP       — функция вне подмножества (причина печатается).

Использование:
    git clone --depth 1 https://github.com/jkoppel/QuixBugs /tmp/QuixBugs-master
    python3 tools/quixbugs_check.py [/tmp/QuixBugs-master] [--json out.json]

Заменяет прежний скрипт v1.3, который проверял только `ast.parse` и ничего
не верифицировал.
"""
import ast
import copy
import collections
import importlib.util
import itertools
import json
import re
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "zig-out/bin/kernc"

_spec = importlib.util.spec_from_file_location("kc", ROOT / "tools/kern_contracts.py")
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)

# Ступень 2 (AST-guided trace explorer). Подключается как fallback: если
# Ступень 1 дала SKIP/DISCARDED/UNKNOWN, функция всё равно проверяется —
# живым дифференциальным прогоном по домену, выведенному из её же AST.
_spec2 = importlib.util.spec_from_file_location("te", ROOT / "tools/trace_explorer.py")
te = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(te)


def stage2(buggy: Path, correct: Path) -> tuple[dict | None, int]:
    """Ступень 2. Возвращает (найденное расхождение | None, сколько функций сравнимо)."""
    c_names = set(te.functions_in(correct))
    compared = 0
    for fn in te.functions_in(buggy):
        if fn not in c_names:
            continue
        compared += 1
        r = te.explore(buggy, correct, fn)
        if r["diverged"]:
            return r, compared
    return None, compared


def bodies(path: Path):
    """Как `parse_bodies`, но с ПРИЧИНОЙ отказа для каждой функции."""
    ok, bad = {}, {}
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {}, {"<parse>": f"SyntaxError: {e}"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        stmts = [
            st for st in node.body
            if not isinstance(st, ast.Pass)
            and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))
        ]
        kc._UNROLLED[0] = False
        try:
            body = kc.body_smt(stmts, {})
        except kc.NoReturn:
            bad[node.name] = "путь без return"
            continue
        except kc.Unsupported as e:
            bad[node.name] = str(e) or "Unsupported"
            continue
        except Exception as e:                      # noqa: BLE001
            bad[node.name] = f"{type(e).__name__}: {e}"
            continue
        params = [a.arg for a in node.args.args if a.arg != "self"]
        ok[node.name] = (params, body, bool(kc._UNROLLED[0]))
    return ok, bad


def _model_args(out: str) -> dict:
    """Извлечь аргументы из `[КОНТРПРИМЕР] a = 4, b = 2` (только целые)."""
    line = next((l for l in out.splitlines() if "КОНТРПРИМЕР" in l), "")
    vals: dict[str, int] = {}
    for name, num in re.findall(r"([A-Za-z_]\w*)\s*=\s*(-?\d+)", line):
        if name in ("result", "res_old", "res_new") or name.startswith("_havoc"):
            continue
        vals[name] = int(num)
    return vals


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


# ДЕФЕКТ #209: списочный домен Live Replay. Имена — эвристика «это
# последовательность», а не тип: в QuixBugs `mergesort(arr)` / `find_in_sorted(arr, x)`.
_LIST_PARAM = re.compile(r"^(arr\d*|xs|lst|list|seq|items|nums|data|values)$")
_LIST_DOMAIN: tuple = ([], [1], [0, 1], [1, 0], [1, 2, 3], [2, 1], [-1, -2],
                        [-1, 2], [2, -1, 2], [1, -2, 3, -1])


def _call(fn, kwargs: dict):
    """Живой вызов: (ok, value_or_error). Таймаут 2 с, лимит рекурсии 300."""
    old = signal.signal(signal.SIGALRM, _alarm)
    old_limit = sys.getrecursionlimit()
    signal.alarm(2)
    sys.setrecursionlimit(300)
    try:
        return True, fn(**kwargs)
    except _Timeout:
        return False, "TIMEOUT"
    except RecursionError:
        return False, "RecursionError"
    except Exception as e:                      # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
        sys.setrecursionlimit(old_limit)


def _load_fn(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(f"qb_{path.stem}_{id(path)}", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:                           # noqa: BLE001
        return None
    fn = getattr(mod, name, None)
    return fn if callable(fn) else None


def _confirm(buggy: Path, correct: Path, fn: str, params: list[str],
             model: dict) -> tuple[bool, str]:
    """LIVE REPLAY: подтвердить расхождение РЕАЛЬНЫМ вызовом (правило №4).

    `DIVERGED` заявляется ТОЛЬКО если на КОНКРЕТНОМ входе поведение версий
    действительно различается (значения или «упало/не упало»). Модель Z3 может
    быть неполной (havoc/развёртка), поэтому недостающие аргументы перебираются
    в малом домене — но подтверждением служит только живой вызов, не модель.
    Иначе — `DISCARDED` (0 ложных обвинений, дефект #206).

    ДЕФЕКТ #209: списочные задачи QuixBugs (`mergesort`, `find_in_sorted`)
    доходили до решателя и получали SAT-кандидата, но здесь отбрасывались:
    домен состоял ТОЛЬКО из `int` (`0,1,2,4,8`), поэтому `mergesort(0)` падал
    `TypeError: object of type 'int' has no len()` в ОБЕИХ версиях — расхождения
    «нет». Добавлен списочный домен для параметров-последовательностей и
    фолбэк при TypeError. Звучность не меняется: подтверждение по-прежнему
    живой вызов обеих версий.
    """
    fb = _load_fn(buggy, fn)
    fc = _load_fn(correct, fn)
    if fb is None or fc is None:
        return False, "не загрузить"
    if len(params) > 3:
        return False, "слишком много аргументов"

    def _dom(p: str) -> list:
        vals: list = []
        # ДЕФЕКТ #216: список, ВОССТАНОВЛЕННЫЙ ИЗ МОДЕЛИ Z3.
        # Модель содержит элементы окна (`arr__e0..arr__e2`) и длину
        # (`len__arr`), а НЕ сам список `arr`, поэтому `p in model` не срабатывал
        # и `max_sublist_sum` отбрасывался: ни в модели, ни в запасном домене
        # не было списка вида `[-1, 2]`.
        elems = [model.get(f"{p}__e{i}") for i in range(3)]
        if any(e is not None for e in elems):
            ln = model.get(f"len__{p}")
            n = 3 if ln is None else max(0, min(3, int(ln)))
            lst = [e for e in elems[:n] if e is not None]
            vals.append(lst)
        if p in model:
            vals.append(model[p])
        if _LIST_PARAM.match(p):
            vals.extend(_LIST_DOMAIN)
        vals.extend([0, 1, 2, 4, 8])
        return vals

    def _probe(args: dict) -> tuple[bool, str] | None:
        """None — нет расхождения на этом входе, иначе (True, описание)."""
        ok_b, vb = _call(fb, args)
        ok_c, vc = _call(fc, args)
        if ok_b and ok_c:
            if vb != vc:
                return True, f"{args} buggy={vb!r} correct={vc!r}"
            return None
        if ok_b != ok_c:
            return True, (f"{args} buggy={'ok' if ok_b else vb} "
                          f"correct={'ok' if ok_c else vc}")
        return None

    tries = 0
    type_errors = 0
    for combo in itertools.product(*[_dom(p) for p in params]):
        if tries >= 60:
            break
        tries += 1
        args = {p: copy.deepcopy(v) for p, v in zip(params, combo)}
        hit = _probe(args)
        if hit:
            return hit
        # обе версии упали одинаково: считаем, насколько часто это TypeError
        _okb, vb2 = _call(fb, args)
        if isinstance(vb2, str) and vb2.startswith("TypeError"):
            type_errors += 1
    # ФОЛБЭК #209: аргументы были целыми, а функция списочная -> перебираем
    # только малые списки (для 1–2 параметров это <= 49 входов).
    if type_errors and len(params) <= 2:
        for combo in itertools.product(_LIST_DOMAIN, repeat=len(params)):
            args = {p: copy.deepcopy(v) for p, v in zip(params, combo)}
            hit = _probe(args)
            if hit:
                return hit
    return False, f"нет расхождения на {tries} входах"


def run(qb: Path, json_out: Path | None) -> int:
    tasks = sorted(p.stem for p in (qb / "python_programs").glob("*.py")
                   if not p.stem.endswith("_test") and p.stem != "node")
    rows, reasons = [], collections.Counter()
    stage2_hits = 0
    for name in tasks:
        b_file = qb / "python_programs" / f"{name}.py"
        c_file = qb / "correct_python_programs" / f"{name}.py"
        if not c_file.exists():
            rows.append((name, "NO-CORRECT", "", ""))
            continue
        a, a_bad = bodies(b_file)
        b, b_bad = bodies(c_file)
        common = [n for n in a if n in b]
        if not common:
            for _n, why in {**a_bad, **b_bad}.items():
                reasons[why] += 1
            first = next(iter({**a_bad, **b_bad}.values()), "нет функций в подмножестве")
            # Дефект #234: раньше здесь стоял безусловный continue, и 32 задачи
            # уходили в SKIP, НЕ доходя до Ступени 2. Теперь падение Ступени 1
            # не означает отказа от проверки.
            s2, compared = stage2(b_file, c_file)
            if s2:
                stage2_hits += 1
                rows.append((name, "DIVERGED", "0/0/0/0",
                             f"[S2 {s2['fn']}: {s2['note']}]"))
            elif compared:
                rows.append((name, "STAGE2-CLEAN", "", f"{first} · S2: {compared} функц. без расхождения"))
            else:
                rows.append((name, "SKIP", "", first))
            continue
        diverged = same = unknown = discarded = 0
        seen = []
        for fn in sorted(common):
            pa, ba, ua = a[fn]
            pb, bb, ub = b[fn]
            if pa != pb:
                seen.append(f"{fn}:SKIP-params")
                continue
            if "_havoc_" in ba or "_havoc_" in bb:
                # Дефект #206: havoc сам по себе НЕ доказывает расхождение,
                # но и не запрещает ПОИСК кандидата. Кандидат обязан пройти
                # Live Replay (ниже) — иначе он будет отброшен.
                seen.append(f"{fn}:havoc-model")
            _rc, out = kc.run_kernc(str(KC), kc.diff_equiv_smt(pa, ba, bb))
            if "ДОКАЗАНО" in out:
                if ua or ub:
                    # дефект #207: развёртка — недо-аппроксимация, UNSAT не
                    # доказывает эквивалентность
                    unknown += 1
                    seen.append(f"{fn}:UNKNOWN(unrolled)")
                else:
                    same += 1
                    seen.append(f"{fn}:EQ")
                continue
            # SAT-кандидат: ЗАЯВЛЯТЬ расхождение можно ТОЛЬКО после живого
            # вызова обеих версий на этом входе (правило №4, дефект #206).
            model = _model_args(out)
            fired, note = _confirm(b_file, c_file, fn, pa, model)
            if fired:
                diverged += 1
                seen.append(f"{fn}:DIV[{note}]")
            else:
                discarded += 1
                seen.append(f"{fn}:DIV-DISCARDED({note})")
        verdict = ("DIVERGED" if diverged else
                   ("DISCARDED" if discarded else
                    ("UNKNOWN" if unknown and not same else
                     ("EQUIVALENT" if same else "SKIP"))))
        # СТУПЕНЬ 2 (fallback): если Ступень 1 не дала вердикта, функция всё
        # равно проверяется — живым дифференциальным прогоном по домену,
        # выведенному из её же AST. SKIP перестаёт быть тупиком.
        s2 = None
        if verdict in ("SKIP", "DISCARDED", "UNKNOWN"):
            s2, compared = stage2(b_file, c_file)
            if s2:
                verdict = "DIVERGED"
                stage2_hits += 1
                extra = f" [S2 {s2['fn']}: {s2['note']}]"
            elif compared:
                verdict = "STAGE2-CLEAN"
                extra = " [S2: расхождения нет]"
            else:
                extra = " [S2: не сравнимо]"
        else:
            extra = ""
        rows.append((name, verdict, f"{diverged}/{same}/{unknown}/{discarded}",
                     " ".join(seen) + extra))

    w = max(len(r[0]) for r in rows) + 2
    print(f"{'task':<{w}} {'verdict':<11} {'div/eq/unk':<10} detali")
    for r in rows:
        print(f"{r[0]:<{w}} {r[1]:<11} {r[2]:<10} {r[3]}")
    cnt = collections.Counter(r[1] for r in rows)
    print("\n=== SUMMARY ===")
    for k, v in cnt.most_common():
        print(f"  {k:<14} {v}")
    print(f"\n  Ступень 1 (SMT + Live Replay): DIVERGED {cnt.get('DIVERGED', 0) - stage2_hits}")
    print(f"  Ступень 2 (AST-guided trace):  DIVERGED {stage2_hits}")
    print(f"  Итого живьём подтверждено:     {cnt.get('DIVERGED', 0)} / {len(rows)}")
    print("\n=== SKIP REASONS (by function) ===")
    for why, n in reasons.most_common(20):
        print(f"  {n:3d}  {why}")
    if json_out:
        json_out.write_text(json.dumps({"rows": rows, "counts": cnt,
                                        "reasons": reasons}, ensure_ascii=False,
                                       indent=1), encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    qb = Path("/tmp/QuixBugs-master")
    json_out = None
    i = 1
    while i < len(argv):
        if argv[i] == "--json" and i + 1 < len(argv):
            json_out = Path(argv[i + 1])
            i += 2
            continue
        qb = Path(argv[i])
        i += 1
    if not (qb / "python_programs").is_dir():
        print(f"[!] нет {qb}/python_programs — склонируйте:\n"
              f"    git clone --depth 1 https://github.com/jkoppel/QuixBugs {qb}")
        return 2
    if not KC.exists():
        print(f"[!] не найден kernc: {KC} (соберите: zig build)")
        return 2
    return run(qb, json_out)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
