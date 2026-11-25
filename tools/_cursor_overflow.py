"""Детектор курсорного переполнения: offset + len > buf_size (CWE-190 -> 122/125).

КЛАСС. В C-парсерах остаток буфера проверяют сложением:
    if (offset + len > buf_size) return -1;
    memcpy(dst, buf + offset, len);
Если оба слагаемых 32-битные, сумма оборачивается, проверка ПРОХОДИТ, и копирование
уходит за границу. Это не переполнение размера выделения (z3-alloc), а переполнение
ПРОВЕРКИ — отдельный класс, который формы A-F не видят.

ЧЕГО НЕ ЛОВИМ (негативные формы, обязаны давать 0):
  * вычитательная проверка: `len > buf_size || offset > buf_size - len`;
  * расширение любого слагаемого: `(uint64_t)offset + len`, `(size_t)offset + len`;
  * слагаемые объявлены как size_t / uint64_t / uintptr_t.
"""
import re
from pathlib import Path

_W32 = r"(?:uint32_t|unsigned\s+int|unsigned|int32_t|int|u32|WORD|DWORD)"
_RD = (r"(?:fread|read|recv|ntohl|be32toh|le32toh|read_u32|read_u16|getc|fgetc|"
       r"memcpy_from_reader)")

COMPARE = re.compile(
    r"\bif\s*\(\s*([A-Za-z_]\w*)\s*\+\s*([A-Za-z_]\w*)\s*(>=?|<=?)\s*([A-Za-z_]\w*)\s*\)")
SAFE_SUB = re.compile(
    r"\b([A-Za-z_]\w*)\s*>\s*([A-Za-z_]\w*)\s*-\s*([A-Za-z_]\w*)")
SAFE_CAST = re.compile(r"\(\s*(?:uint64_t|size_t|uintptr_t)\s*\)\s*[A-Za-z_]\w*\s*\+")


def _decl_type(src: str, name: str) -> str:
    """Тип переменной из ОБЪЯВЛЕНИЯ, включая списки `uint32_t offset, len, size;`."""
    # 1) ПАРАМЕТРЫ ФУНКЦИИ: `uint32_t buf_size` в сигнатуре встречается чаще,
    #    чем объявление в теле (ИЗМЕРЕНО: без этого контроль с параметрами
    #    давал 0 вместо 1 — детектор молчал на самом частом случае).
    for sig in re.finditer(r"\(([^()]{1,400})\)\s*\{", src):
        for part in sig.group(1).split(","):
            m2 = re.match(r"\s*(?:const\s+)?(" + _W32 +
                          r"|uint64_t|size_t|uintptr_t)\s+\**\s*([A-Za-z_]\w*)", part)
            if m2 and m2.group(2) == name:
                return m2.group(1)
    # 2) объявления в теле, включая списки `uint32_t offset, len, size;`
    for m in re.finditer(r"\b(" + _W32 + r"|uint64_t|size_t|uintptr_t)\s+([^;{}]{1,200});", src):
        head, rest = m.group(1), m.group(2)
        for part in rest.split(","):
            nm = re.match(r"\s*\**\s*([A-Za-z_]\w*)", part)
            if nm and nm.group(1) == name:
                return head
    return ""


def analyse_cursor_overflow(src: str, path: str) -> list:
    if not path.endswith((".c", ".h", ".cc", ".cpp")):
        return []
    low = path.lower()
    if any(f"/{d}/" in f"/{low}" for d in ("tests", "test", "examples", "bench",
                                           "vendor", "third_party")):
        return []
    out = []
    for m in COMPARE.finditer(src):
        a, b, op, size = m.group(1), m.group(2), m.group(3), m.group(4)
        if op not in (">", ">="):
            continue
        ta, tb = _decl_type(src, a), _decl_type(src, b)
        # оба слагаемых обязаны быть 32-битными (иначе сумма не обернётся)
        if not (ta and tb):
            continue
        if any(t in ("uint64_t", "size_t", "uintptr_t") for t in (ta, tb)):
            continue
        window = src[max(0, m.start() - 600): m.end() + 600]
        # отрицательные формы рядом -> защищено
        if SAFE_CAST.search(window):
            continue
        if SAFE_SUB.search(window) and not re.search(
                re.escape(a) + r"\s*\+\s*" + re.escape(b) + r"\s*(?:>=?|<=?)", window):
            pass
        # слагаемое пришло из чтения потока (в этой же функции ~600 символов выше)
        read_ok = any(re.search(_RD + r"\s*\([^;]{0,120}\b" + re.escape(n) + r"\b",
                                src[max(0, m.start() - 1200): m.start()])
                      for n in (a, b))
        if not read_ok:
            continue
        # после проверки обязан быть доступ по buf + offset длиной len
        tail = src[m.end(): m.end() + 800]
        use = re.search(r"(?:memcpy|memmove|fwrite|fread|recv)\s*\([^;]{0,120}\b"
                        + re.escape(a) + r"\b", tail) or \
              re.search(r"\[\s*" + re.escape(a) + r"\s*\+", tail)
        if not use:
            continue
        out.append({
            "law": "cursor-overflow",
            "symbol": f"{Path(path).name}:{a}+{b}>{size}",
            "file": path,
            "detail": (f"`{a} + {b} > {size}` при 32-битных слагаемых ({ta}, {tb}): "
                       f"сумма оборачивается, проверка проходит, затем доступ по "
                       f"`{a}` с длиной `{b}`; оба из чтения потока"),
        })
    return out
