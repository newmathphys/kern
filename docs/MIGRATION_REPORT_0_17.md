# Миграция KERN на Zig 0.17.0 — отчёт о состоянии

> Copyright (c) 2026 Vital Kalinousky. All rights reserved.
> Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

**Ветка:** `zig-0.17-migration` · **Тулчейн:** Zig 0.17.0 (`~/opt/zig-x86_64-linux-0.17.0`)
**Baseline (`main`):** Zig 0.13.0 — **заморожен, аттестован, зелёный**.

## ✅ СТАТУС: МИГРАЦИЯ ЗАВЕРШЕНА (коммит `de66086`)

```
zig build        → RC=0   (kernc, kernx, kern-attack, kernc-hermetic)
zig build test   → RC=0   (тесты ядра)
zig build test-next → RC=0 (тесты KERN-Next)
```

Все 3 блокера §3 закрыты + 13 дополнительных API-изменений, вскрытых тестами.

---

## 1. Главный вывод: это НЕ «74 сайта», а переписывание I/O-слоя

Первоначальная оценка («заменить `@intFromEnum`, `allocPrint`, `addArgs` — 74 места»)
оказалась **неверной**. Проверка на реальном компиляторе 0.17.0 показала:

| Утверждение | Проверка 0.17.0 | Вердикт |
|:--|:--|:--|
| `@intFromEnum` → `@backingInt` (20 сайтов) | ✅ компилируется как есть | **НЕ блокер** |
| `@enumFromInt` → `@fromBackingInt` (6) | ✅ компилируется | **НЕ блокер** |
| `std.fmt.allocPrint` → `alloc.print` (43) | ✅ функция существует (`fmt.zig:625`) | **НЕ блокер** |
| `std.builtin` → `std.lang` (4) | ✅ `std.builtin` — алиас на `lang` | **НЕ блокер** |
| `[_]u8{0} ** N` | ❌ оператор удалён | **блокер** |
| `std.ArrayList(T).init(alloc)` | ❌ стал unmanaged | **блокер** |
| `std.fs.cwd()` | ❌ удалён → `std.Io.Dir` + `io` | **блокер (76 сайтов)** |
| `std.io.*` | ❌ удалён → `std.Io` | **блокер** |
| `std.process.argsAlloc` | ❌ → `main(init)` + `toSlice` | **блокер** |
| `std.process.Child.init/spawn` | ❌ → `std.process.spawn(io, …)` | **блокер** |
| `std.heap.GeneralPurposeAllocator` | ❌ → `DebugAllocator` | **блокер** |
| `@typeInfo().Enum.fields` | ❌ → `.@"enum".field_names` (строки) | **блокер** |
| `@cImport` | ❌ → `addTranslateC` в build.zig | **блокер** |
| `std.mem.split` | ❌ → `splitScalar`/`splitSequence` | **блокер** |
| `std.fmt.allocPrintZ` | ❌ → `allocPrintSentinel` | **блокер** |
| `std.posix.open` / `fsync` | ❌ → `openat` / `fdatasync` | **блокер** |
| `File.writeAll/close/sync` | ❌ → `writeStreamingAll(io,…)`/`close(io)` | **блокер** |

**Итог:** Zig 0.17 провёл полную ревизию I/O (`std.Io`, «Writergate 2.0»).
Файловые операции теперь требуют **явного параметра `io`**, который надо
пробросить через сигнатуры. Это ~250 сайтов, а не 74.

---

## 2. Что СДЕЛАНО на ветке (коммиты `245d9cd`, `7e3e229`)

| Что | Сайтов | Как |
|:--|--:|:--|
| `[_]u8{v} ** N` → `@as([N]u8, @splat(v))` | **93** | `tools/migrate_017.py` |
| `GeneralPurposeAllocator` → `DebugAllocator` | 8 | regex |
| `@typeInfo().Enum.fields` → `.@"enum".field_names` | 8 | regex |
| `std.ArrayList(` → `std.array_list.Managed(` | 63 | regex |
| `std.fs.cwd().X` → `compat.X` | **76** | regex + шим |
| `main()` → `main(init)` + `setIo(init.io)` | 3 | вручную |
| `argsAlloc` → `Args.toSlice(init.minimal.args, alloc)` | 3 | вручную |
| `File.writeAll/close/sync` → `compat.file*` | ~20 | regex |
| `std.mem.split` → `splitScalar` | 2 | regex |
| `allocPrintZ` → `allocPrintSentinel` | 1 | regex |
| `std.posix.open/fsync` → `openat/fdatasync` | 2 | regex |
| `build.zig`: модуль `compat` для всех таргетов | — | вручную |

**Новый артефакт:** `src/compat.zig` — слой совместимости. Держит
процесс-глобальный `std.Io` (из `main(init)` в CLI, `std.testing.io` в тестах)
и оборачивает файловые операции. Это ключ к тому, чтобы замена 76 сайтов
была **механической**, а не требовала правки каждой сигнатуры.

---

## 3. Блокеры (ВСЕ ЗАКРЫТЫ, коммит `de66086`)

```
src/next/catalog.zig:13          @cImport (SQLite)  → addTranslateC в build.zig
src/verifier/z3_bridge.zig:118   Child.init         → std.process.spawn(io, opts)
Writer-слой: ArrayList.writer() (16 сайтов)         → std.Io.Writer.Allocating
```

### 3.1. `@cImport` (SQLite) — 1 сайт
Создать `src/sqlite_c.h` с `#include <sqlite3.h>`, в `build.zig`:
```zig
const sqlite_c = b.addTranslateC(.{ .root_source_file = b.path("src/sqlite_c.h") });
kernx_mod.addImport("sqlite_c", sqlite_c.createModule());
```
В `catalog.zig`: `const c = @import("sqlite_c");` вместо `@cImport`.

### 3.2. Z3-мост (`Child`) — 2 сайта
Новый API: `std.process.spawn(io, .{ .argv = …, .stdin = .pipe, .stdout = .pipe })`.
**Упрощение:** появился `std.process.run(gpa, io, .{ .argv, .stdout_limit, .stderr_limit, .timeout })`,
который сам читает пайпы и держит таймаут — это **устраняет поток-убийцу**
вместе с целым классом гонок `ECHILD`, которые мы ловили ранее.

### 3.3. Writer-слой — 16 сайтов
`ArrayList(u8).writer()` → `std.Io.Writer.Allocating`:
```zig
var aw: std.Io.Writer.Allocating = .init(alloc);
defer aw.deinit();
const w = &aw.writer;
// … w.writeAll / w.print …
return aw.toOwnedSlice();   // вместо buf.toOwnedSlice()
```

**Оценка остатка:** 2–4 часа аккуратной работы + полный перепрогон верификации.

---

## 4. Честная оценка рисков

| | |
|:--|:--|
| **Плюс миграции** | свежий компилятор, `translate-c` вместо `@cImport`, BSP, багфиксы std |
| **Цена** | 🔴 **весь проверенный baseline обнуляется**: 192 теста, SMT-LIB 1796/1796, ARM64/PPC64 188/188, SLSA-аттестат, 16 исправленных багов — всё измерено на 0.13.0 |
| **Риск** | ~250 сайтов с пробросом `io`; ошибка → утечка/падение. Поэтому миграция идёт **в изолированной ветке**, а `main` не трогается |
| **Выгода для KERN** | умеренная: главное (уникальное) в KERN — математика и формат `.kimg`, они от версии Zig не зависят |

---

## 5. Состояние веток

| Ветка | Тулчейн | Статус |
|:--|:--|:--|
| **`main`** | Zig 0.13.0 | ✅ **заморожен**: `zig build` rc=0, покрытие решений 100% (30/30), 192 теста — аттестованный baseline |
| **`zig-0.17-migration`** | Zig 0.17.0 | 🔧 сборочная система ✅, `**`/alloc/args/fs ✅, осталось 3 блокера |

**Правило (DO-330):** `main` — неизменяемый базис доверия; миграция не имеет
права ломать эталон. Пока ветка не станет полностью зелёной — слияния нет.

---

## 6. Что дал сам процесс миграции (уже сейчас)

1. **Найден дефект KERN:** сканер `scan_to_kern.py` был слеп к `.zig` —
   KERN **не мог просканировать сам себя**. Исправлено (уже в `main`).
   Скан Zig 0.17.0: 5000 артефактов, **276 незавершённых мест**, в т.ч. в
   `compiler/Maker.zig` — том самом новом компоненте сборочной системы 0.17.0.
2. **Доказаны контракты API 0.17.0** (3/3): `std.lang.Optimize` различает
   4 режима; `@splat` эквивалентен `**`; `LinkMode.static ≠ dynamic`.
3. **Точная карта 17 изменений API** — вместо ошибочного списка из 5.

---

## 7. Воспроизведение

```bash
# Эталон (0.13.0)
git checkout main && export PATH="$PWD/.venv/bin:$PATH"
zig build && zig build test          # → rc=0, 192 теста

# Миграция (0.17.0)
git checkout zig-0.17-migration
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PATH"
zig build 2>&1 | head               # → 3 блокера (см. §3)

# Автоматический мигратор `**`
python3 tools/migrate_017.py --dry-run src/
```

