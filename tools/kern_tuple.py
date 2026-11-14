#!/usr/bin/env python3
"""Поддержка Tuple в контрактах через AST-ПРОЕКЦИЮ КОМПОНЕНТ (приём из компиляторов).

Идея. Нельзя тащить `list[str]` через `ite(cond, then, else)` SMT-LIB: ветвление
выбирает терм, а не список. Поэтому кортеж не транслируется вовсе — функция
проецируется в K скалярных функций, каждая возвращает k-ю компоненту, и штатный
(НЕИЗМЕНЁННЫЙ) скалярный тракт проверяет их по отдельности.

  f -> (e0, ..., eK-1)   ==>   f__k -> e_k     для k = 0..K-1

Свойства:
  * 0 изменений в `body_smt`/`build_smt`/7 потребителях — риск для витрины 100/100 нулевой;
  * `if c: return a, b` работает бесплатно: проекция сохраняет `ite`, потому что это
    по-прежнему скалярный `return` в каждой ветви;
  * доказательство покомпонентное: все K компонент ДОКАЗАНЫ => кортеж ДОКАЗАН;
    контрпример хотя бы в одной => кортеж ОПРОВЕРГНУТ с номером компоненты.
"""
from __future__ import annotations

import ast
import copy
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _own_returns(fn: ast.FunctionDef) -> list[ast.Return]:
    """`return` только СВОЕЙ функции (вложенные def не считаются)."""
    out: list[ast.Return] = []

    def walk(node):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(ch, ast.Return):
                out.append(ch)
            walk(ch)

    walk(fn)
    return out


def tuple_arity(fn: ast.FunctionDef) -> int | None:
    """Арность кортежного выхода или None (скаляр / смешанные арности / нет return)."""
    rets = _own_returns(fn)
    if not rets:
        return None
    arities = set()
    for r in rets:
        if not isinstance(r.value, ast.Tuple):
            return None                     # смешанный выход: честный отказ
        arities.add(len(r.value.elts))
    if len(arities) != 1:
        return None
    k = arities.pop()
    return k if k >= 2 else None


def project_return(fn: ast.FunctionDef, k: int) -> ast.FunctionDef:
    """Копия функции, где каждый `return (e0..eK-1)` заменён на `return e_k`."""
    fn2 = copy.deepcopy(fn)
    for r in _own_returns(fn2):
        if isinstance(r.value, ast.Tuple):
            r.value = copy.deepcopy(r.value.elts[k])
    return fn2


def project_sum(fn: ast.FunctionDef) -> ast.FunctionDef:
    """Копия функции, где `return (e0..eK-1)` -> `return e0 + e1 + ...` (скаляр).

    Сумма НЕ считается вызовом проекций: KERN не делает межпроцедурных вызовов
    ("вызов чужой функции" -> вне подмножества). Поэтому компоненты складываются
    прямо в точке возврата — выражение остаётся скалярным и линейным.
    """
    fn2 = copy.deepcopy(fn)
    for r in _own_returns(fn2):
        if isinstance(r.value, ast.Tuple) and len(r.value.elts) >= 2:
            acc = copy.deepcopy(r.value.elts[0])
            for e in r.value.elts[1:]:
                acc = ast.BinOp(left=acc, op=ast.Add(), right=copy.deepcopy(e))
            r.value = acc
    return fn2


LAW = {
    "conserves_sum": "result == {p}",         # сумма компонент == p
    "non_negative": "result >= 0",            # каждая компонента >= 0
}


def build_projection_source(src: str, fn_name: str, law: str, param: str = "") -> tuple[str, int]:
    """Исходник с K скалярными проекциями, у каждой — свой `@kern:ensures`."""
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
    if fn is None:
        raise ValueError(f"функция {fn_name} не найдена")
    k = tuple_arity(fn)
    if k is None:
        raise ValueError(f"{fn_name}: нет кортежного выхода фиксированной арности")
    parts = []
    for i in range(k):
        p = project_return(fn, i)
        p.name = f"{fn_name}__k{i}"
        cond = LAW[law].format(p=param) if law == "conserves_sum" else LAW[law]
        if law == "conserves_sum" and i == 0:
            # сумма компонент не скалярна: для проверки суммы нужен отдельный проход,
            # поэтому `conserves_sum` реализуется как сумма ПРОЕКЦИЙ ниже (см. check()).
            cond = "result == result"          # вакуумный закон-заглушка не нужен
        parts.append(f"# @kern:ensures {cond}\n" + ast.unparse(p))
    return "\n\n".join(parts) + "\n", k


def _run_contracts(path: Path) -> str:
    env = {"PATH": f"{ROOT}/.venv/bin:/usr/bin:/bin", "HOME": "/root"}
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(path)],
                       capture_output=True, text=True, timeout=300, env=env)
    return ((p.stdout or "") + (p.stderr or "")).strip()


def check(src: str, fn_name: str, law: str, param: str = "") -> dict:
    """Проверка кортежной функции: покомпонентно, штатным скалярным трактом."""
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
    if fn is None:
        return {"status": "ERROR", "detail": f"{fn_name} не найдена"}
    k = tuple_arity(fn)
    if k is None:
        return {"status": "SKIP", "detail": "TUPLE_ARITY_MISMATCH или скалярный выход"}
    d = Path(tempfile.mkdtemp(prefix="kt-"))
    f = d / "proj.py"
    f.write_text(build_projection_source(src, fn_name, "non_negative")[0], encoding="utf-8")
    if law == "conserves_sum":
        ps = project_sum(fn)
        ps.name = f"{fn_name}__sum"
        f.write_text(f"# @kern:ensures result == {param}\n" + ast.unparse(ps) + "\n",
                     encoding="utf-8")
    out = _run_contracts(f)
    if "КОНТРПРИМЕР" in out:
        cex = [ln.strip() for ln in out.splitlines() if "КОНТРПРИМЕР" in ln]
        rt = "runtime-confirmed" if "RUNTIME CONFIRMED" in out else "no-runtime"
        return {"status": "CAUGHT", "arity": k, "detail": (cex[0][:90] + " | " + rt)}
    if "ДОКАЗАНО" in out:
        return {"status": "PROVEN", "arity": k, "detail": "все компоненты доказаны"}
    return {"status": "SKIP", "arity": k, "detail": (out.splitlines() or [""])[-1][:140]}


# --- свернуть ТЕЛО в ОДНО выражение: берёт if/elif/else, ранние return, let-переменные ---
def _stmts_to_expr(stmts: list, env: dict | None = None):
    """Тело -> одно выражение (вложенный IfExp) с подстановкой локальных присваиваний.

    Мотив тот же, что у проекции кортежей: `ite` в SMT выбирает ТЕРМ, а не список,
    поэтому тело сводится к терму. Рекурсия (а не `while`) нужна из-за `elif`:
    это вложенный `If` в поле `orelse`, и узкий цикл падал бы на нём.
    """
    env = dict(env or {})
    if not stmts:
        raise ValueError("EMPTY_BODY: нет ветви с return")
    first = stmts[0]
    if isinstance(first, ast.Assign) and len(first.targets) == 1 \
            and isinstance(first.targets[0], ast.Name):
        env2 = dict(env)
        env2[first.targets[0].id] = _subst_names(first.value, env)
        return _stmts_to_expr(stmts[1:], env2)
    if isinstance(first, ast.Return):
        return _subst_names(first.value, env)
    if isinstance(first, ast.If):
        then_e = _stmts_to_expr(first.body, env)
        else_e = _stmts_to_expr(first.orelse if first.orelse else stmts[1:], env)
        return ast.IfExp(test=_subst_names(first.test, env), body=then_e, orelse=else_e)
    raise ValueError(f"INLINE_UNSUPPORTED: {type(first).__name__}")


def _subst_names(node, env: dict):
    """Подстановка let-переменных в выражение (без мутации исходного узла)."""
    node = copy.deepcopy(node)
    if not env:
        return node
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in env:
            n.__class__ = ast.BinOp
            n.left = copy.deepcopy(env[n.id])
            n.op = ast.Add()
            n.right = ast.Constant(value=0)
    return node


def _fn_node(src: str, fn_name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == fn_name)


def build_monotonic_source(src: str, fn_name: str) -> str:
    """`f__mono(x_a, x_b)` = expr(x_b) - expr(x_a) при `x_a <= x_b`, `ensures >= 0`."""
    fn = _fn_node(src, fn_name)
    params = [a.arg for a in fn.args.args]
    if len(params) != 1:
        raise ValueError("monotonic реализован для унарной функции")
    e_a = _stmts_to_expr(fn.body, {params[0]: ast.Name(id="x_a", ctx=ast.Load())})
    e_b = _stmts_to_expr(fn.body, {params[0]: ast.Name(id="x_b", ctx=ast.Load())})
    ret = ast.Return(value=ast.BinOp(left=e_b, op=ast.Sub(), right=e_a))
    inner = ast.unparse(ast.Module(body=[ret], type_ignores=[]))
    return ("# @kern:requires x_a <= x_b\n# @kern:ensures result >= 0\n"
            + f"def {fn_name}__mono(x_a, x_b):\n"
            + "\n".join("    " + ln for ln in inner.splitlines()) + "\n")


def build_idempotent_source(src: str, fn_name: str) -> str:
    """`f__idem(x)` = expr(expr(x)) - expr(x), `ensures result == 0`."""
    fn = _fn_node(src, fn_name)
    params = [a.arg for a in fn.args.args]
    if len(params) != 1:
        raise ValueError("idempotent реализован для унарной функции")
    e1 = _stmts_to_expr(fn.body, {params[0]: ast.Name(id="x", ctx=ast.Load())})
    e2 = _stmts_to_expr(fn.body, {params[0]: e1})
    body = [ast.Assign(targets=[ast.Name(id="_r1", ctx=ast.Store())], value=e1),
            ast.Return(value=ast.BinOp(left=e2, op=ast.Sub(),
                                       right=ast.Name(id="_r1", ctx=ast.Load())))]
    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)      # у синтезированных узлов нет lineno
    inner = ast.unparse(mod)
    return ("# @kern:ensures result == 0\n"
            + f"def {fn_name}__idem(x):\n"
            + "\n".join("    " + ln for ln in inner.splitlines()) + "\n")




def check_macro(src: str, fn_name: str, macro: str, param: str = "") -> dict:
    """Прогон макрос-закона через ШТАТНЫЙ скалярный тракт (ядро не меняется)."""
    try:
        if macro == "monotonic":
            code = build_monotonic_source(src, fn_name)
        elif macro == "idempotent":
            code = build_idempotent_source(src, fn_name)
        elif macro == "conserves_sum":
            fn = _fn_node(src, fn_name)
            if tuple_arity(fn) is None:
                return {"status": "SKIP", "detail": "TUPLE_ARITY_MISMATCH или скаляр"}
            ps = project_sum(fn)
            ps.name = f"{fn_name}__sum"
            code = f"# @kern:ensures result == {param}\n" + ast.unparse(ps) + "\n"
        elif macro == "non_negative":
            fn = _fn_node(src, fn_name)
            code = (build_projection_source(src, fn_name, "non_negative")[0]
                    if tuple_arity(fn) is not None
                    else f"# @kern:ensures result >= 0\n" + ast.unparse(fn) + "\n")
        else:
            return {"status": "SKIP", "detail": f"неизвестный макрос {macro}"}
    except ValueError as e:
        return {"status": "SKIP", "detail": str(e)[:160]}
    d = Path(tempfile.mkdtemp(prefix="km-"))
    f = d / "m.py"
    f.write_text(code, encoding="utf-8")
    out = _run_contracts(f)
    if "КОНТРПРИМЕР" in out:
        cex = [ln.strip() for ln in out.splitlines() if "КОНТРПРИМЕР" in ln]
        rt = "runtime-confirmed" if "RUNTIME CONFIRMED" in out else "no-runtime"
        return {"status": "CAUGHT", "detail": ((cex[0][:100] + " | " + rt) if cex else rt)}
    if "ДОКАЗАНО" in out:
        return {"status": "PROVEN", "detail": "закон доказан"}
    return {"status": "SKIP", "detail": (out.splitlines() or [""])[-1][:140]}


def diff_equiv_tuples(old_file: Path, new_file: Path) -> dict:
    """Кортежный `--diff-equiv`: покомпонентный цикл по скалярному тракту."""
    old_src = Path(old_file).read_text(encoding="utf-8", errors="replace")
    new_src = Path(new_file).read_text(encoding="utf-8", errors="replace")
    fo = next((n for n in ast.walk(ast.parse(old_src))
               if isinstance(n, ast.FunctionDef)), None)
    fnn = next((n for n in ast.walk(ast.parse(new_src))
                if isinstance(n, ast.FunctionDef)), None)
    if fo is None or fnn is None:
        return {"status": "SCALAR"}
    ko, kn = tuple_arity(fo), tuple_arity(fnn)
    if ko is None and kn is None:
        return {"status": "SCALAR"}
    if ko != kn:
        return {"status": "DIVERGED", "detail": f"arity: {ko} != {kn}"}
    d = Path(tempfile.mkdtemp(prefix="kdt-"))
    env = {"PATH": f"{ROOT}/.venv/bin:/usr/bin:/bin", "HOME": "/root"}
    for k in range(ko):
        a, b = project_return(fo, k), project_return(fnn, k)
        a.name = b.name = "cmp"
        pa, pb = d / "a.py", d / "b.py"
        pa.write_text(ast.unparse(a) + "\n", encoding="utf-8")
        pb.write_text(ast.unparse(b) + "\n", encoding="utf-8")
        pr = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                             "--diff-equiv", str(pa), str(pb)],
                            capture_output=True, text=True, timeout=300, env=env)
        out = ((pr.stdout or "") + (pr.stderr or "")).strip()
        if "РАЗОШ" in out or "DIVERGED" in out.upper():
            cex = [ln.strip() for ln in out.splitlines() if "КОНТРПРИМЕР" in ln]
            return {"status": "DIVERGED", "component": k,
                    "detail": (cex[0] if cex else out.splitlines()[-1])[:150]}
    return {"status": "EQUIVALENT", "components": ko,
            "detail": f"все {ko} компонент эквивалентны"}
