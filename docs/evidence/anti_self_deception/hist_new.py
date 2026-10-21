def parse_file(path: Path):
    """Вернуть список (имя, params, requires, ensures, body_smt, lineno, причина)."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    # ИЗ НАСТОЯЩИХ КОММЕНТАРИЕВ (tokenize), а не построчно — защита от
    # Comment-in-String Injection.
    anchors: dict[int, dict[str, str]] = _py_comment_anchors(src)
    tree = ast.parse(src)
    out = []
    for node in tree.body:  # только верхний уровень: вложенный def не наследует аннотации
        if not isinstance(node, ast.FunctionDef):
            continue
        # контракт: якоря в нескольких строках НАД функцией
        req = ens = None
        skip_reason = None
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
        # СИМВОЛЬНОЕ ИСПОЛНЕНИЕ: поддерживаются ветвления (`ite`) и локальные
        # присваивания. Путь без `return` -> NoReturn (не глотаем ветку!),
        # циклы/вызовы -> Unsupported.
        _DIV_COLLECTOR.clear()
        _UNROLLED[0] = False
        try:
            body = body_smt(stmts, _self_meta(node, stmts))
        except (NoReturn, Unsupported) as e:
            body = None
            skip_reason = str(e)
        # ДЕФЕКТ #207: была ли трансляция с РАЗВЁРТКОЙ цикла/рекурсии.
        # Развёртка — недо-аппроксимация: SAT на K шагах = честный контрпример,
        # UNSAT на K шагах НЕ доказывает корректность (цикл может идти дальше).
        unrolled = bool(_UNROLLED[0])
        # Делители, встреченные при трансляции -> обязательство «делитель ≠ 0».
        divs = list(dict.fromkeys(_DIV_COLLECTOR))
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, req, ens, body, node.lineno, skip_reason,
                    {"ranges": {}, "ret": None, "divisors": divs,
                     "unrolled": unrolled}))
    return out
