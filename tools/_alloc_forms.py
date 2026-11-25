import re
from pathlib import Path
STAGED_INT = re.compile(
    r"\b(?:int|unsigned(?:\s+int)?|signed(?:\s+int)?|uint32_t|int32_t|long)\s+(\w+)\s*=\s*"
    r"([\w.>\-]+)\s*\*\s*([\w.>\-]+)\s*(?:\*\s*(\d+)\s*|)\*?\s*;")
USE_OF = r"(?:malloc|calloc|realloc|xmalloc|memcpy|memmove|memset|fread|read|recv)\s*\("
MEMFUNC = re.compile(
    r"\b(memcpy|memmove|memset)\s*\(\s*[^,;]+,\s*[^,;]+,\s*"
    r"([\w.>\-]+)\s*\*\s*([\w.>\-]+)\s*(?:\*\s*(\d+)\s*)?\)")


def _window_taint(src: str, pos: int, name: str) -> str:
    """Источник множителя в окне выше `pos`: файл/вызывающий/нет.

    Окно ограничено 4000 символов: этого хватает на «заголовок прочитан выше в
    этой же функции», и это НЕ межпроцедурный анализ. Ограничение названо.
    """
    if not name:
        return ""
    from api_hunt import _intra_read, _intra_tainted
    if _intra_read(src, max(0, pos - 4000), pos, name):
        return "file"
    if _intra_tainted(src, max(0, pos - 4000), pos, name):
        return "local"
    return ""


def analyse_z3_alloc_staged(src: str, path: str) -> list:
    """ФОРМЫ E/F (#662): размер считается ОТДЕЛЬНО от выделения.

    ЗАЧЕМ. В прогоне A анализатор видел только однострочный `malloc(w*h*k)`, а
    половина C-декодеров пишет размер строкой выше:
        int size = w * h * 3;            // переполняется ЗДЕСЬ
        uint8_t *buf = malloc(size);     // получает уже обрезанное число
    и копирует данные через `memcpy(dst, src, rows * cols * 4)`, где переполняется
    ТРЕТИЙ аргумент. Ни та, ни другая форма прежним набором не покрывалась.

    ЧЕГО НЕ ДЕЛАЕМ (измерено, а не забыто): `calloc(a, b)` — НЕ цель. На LP64
    `calloc(size_t nmemb, size_t size)` сам проверяет `nmemb * size` и вернёт
    NULL; уязвим лишь `calloc(a * b, ...)` с переполнением ВНУТРИ первого
    аргумента, а это уже форма A.
    """
    import sys as _sys
    tools_dir = str(Path(__file__).resolve().parent)
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    from _witness import witness

    if not path.endswith((".c", ".h", ".cc", ".cpp")):
        return []
    lowered = path.lower()
    if any(f"/{d}/" in f"/{lowered}" for d in
           ("tests", "test", "scripts", "tools", "examples", "bench",
            "vendor", "third_party")):
        return []

    out = []
    # ---- ФОРМА E: int size = a * b [* k]; … malloc/fread(size) ----
    for m in STAGED_INT.finditer(src):
        name, a, b, k_lit = m.group(1), m.group(2), m.group(3), m.group(4)
        if a.strip().isdigit() and b.strip().isdigit():
            continue
        # переменная обязана дойти до выделения/чтения, иначе это не размер
        if not re.search(r"\b" + re.escape(name) + r"\b", src[m.end(): m.end() + 800]):
            continue
        if not re.search(USE_OF + r"[^;]{0,80}\b" + re.escape(name) + r"\b",
                         src[m.end(): m.end() + 800]):
            continue
        # КАЛИБРОВКА №22: парный гард обязан проверяться И ЗДЕСЬ. Форма E
        # раньше вообще не смотрела на защиту — отсюда единственный кандидат
        # аудита (`DCMTK/dcddirif.cc:4543`, где оба множителя ограничены).
        # ВНИМАНИЕ: `_has_safe_left_wide_cast` живёт в `_witness`, а НЕ в api_hunt.
        # ИЗМЕРЕНО: неверный импорт дал ImportError, который в api_hunt ловится
        # как `except ImportError: pass` и МОЛЧА отключал всю форму E — все три
        # контроля показывали 0, и это выглядело как «чисто». Это тот же класс,
        # что #657/#661: тихий отказ, замаскированный под результат.
        from api_hunt import _paired_bound_ok
        from _witness import has_safe_left_wide_cast as _has_safe_left_wide_cast
        _guard = src[max(0, m.start() - 1500): m.start()]
        try:
            # каст ищем только в ПРАВОЙ ЧАСТИ: объявление `unsigned long size = …`
            # само по себе не защита (иначе форма E глушилась целиком)
            _rhs = m.group(0).split("=", 1)[1] if "=" in m.group(0) else ""
            if _has_safe_left_wide_cast(_rhs):
                continue
        except Exception:
            pass
        if re.search(r"SIZE_MAX\s*/", _guard):
            continue
        _signed = bool(re.search(r"int\s+" + re.escape(name) + r"", src))
        if _paired_bound_ok(_guard, [a, b], int(k_lit) if k_lit else 1, 1, _signed):
            continue
        marks = [mk for mk in (_window_taint(src, m.start(), a),
                               _window_taint(src, m.start(), b)) if mk]
        if not marks:
            continue
        n_tainted = len(marks)
        k = int(k_lit) if k_lit else 1
        w = witness("product", k=k, n_tainted=n_tainted)
        if not w:
            continue
        out.append({"law": "z3-alloc:form-E", "symbol": f"{Path(path).name}:{name}",
                    "file": path,
                    "detail": (f"{w} (staged: `{m.group(0).strip()[:60]}`; "
                               f"taint: {'+'.join(sorted(set(marks)))}; source: "
                               f"{'file' if 'file' in marks else 'local'})"),
                    "hot": True})

    # ---- ФОРМА F: memcpy/memmove/memset(dst, src, a * b [* k]) ----
    for m in MEMFUNC.finditer(src):
        fn, a, b, k_lit = m.group(1), m.group(2), m.group(3), m.group(4)
        if a.strip().isdigit() or b.strip().isdigit():
            continue
        marks = [mk for mk in (_window_taint(src, m.start(), a),
                               _window_taint(src, m.start(), b)) if mk]
        if not marks:
            continue
        k = int(k_lit) if k_lit else 1
        w = witness("product", k=k, n_tainted=len(marks))
        if not w:
            continue
        out.append({"law": "z3-alloc:form-F", "symbol": f"{Path(path).name}:{fn}",
                    "file": path,
                    "detail": (f"{w} (copy size: `{m.group(0).strip()[:60]}`; "
                               f"taint: {'+'.join(sorted(set(marks)))}; source: "
                               f"{'file' if 'file' in marks else 'local'})"),
                    "hot": True})
    return out
