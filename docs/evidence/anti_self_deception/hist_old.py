def parse_file(path: Path):
    """Вернуть список (имя, params, requires, ensures, body_expr, lineno)."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    anchors: dict[int, dict[str, str]] = {}
    for i, ln in enumerate(lines, 1):
        m = ANNOT.match(ln)
        if m:
            anchors.setdefault(i, {})[m.group(1)] = m.group(2)
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # контракт: якоря в нескольких строках НАД функцией
        req = ens = None
        for k in range(max(1, node.lineno - 6), node.lineno):
            if k in anchors:
                req = anchors[k].get("requires", req)
                ens = anchors[k].get("ensures", ens)
        if req is None and ens is None:
            continue
        # 🔴 ДЕФЕКТ (найден прогоном на функции с циклом): недостаточно взять
        # последний `return` — тогда функция с циклом/ветвлением принималась за
        # чистое тело и давала ЛОЖНЫЙ FAIL. Тело обязано быть РОВНО одним
        # оператором `return <выражение>`; всё прочее — вне подмножества.
        body = None
        stmts = [
            st for st in node.body
            if not isinstance(st, ast.Pass)
            # докстрока — не оператор
            and not (isinstance(st, ast.Expr)
                     and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))
        ]
        if (len(stmts) == 1 and isinstance(stmts[0], ast.Return)
                and stmts[0].value is not None):
            body = stmts[0].value
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, req, ens, body, node.lineno))
    return out
