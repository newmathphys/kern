# Платформы: что проверено, что собирается, что не поддерживается

> **Статус документа:** заполнен по результатам фактических прогонов (0K.11).
> Ни одна строка ниже не является обещанием: где написано «собирается» — это
> проверено командой, где написано «не поддерживается» — указан точный блокер.

## Матрица

| Цель | Ядро (`kernc`) | C-ABI (`libkern`) | Тесты | Как проверяется |
|:--|:--|:--|:--|:--|
| **x86_64-linux** | ✅ | ✅ | ✅ 402 | `make ci-fast`, `make ci` |
| **aarch64-linux** | ✅ | ✅ | ✅ 394 passed + 8 skipped | QEMU, `make cross-arch` |
| **powerpc64-linux (big-endian)** | ✅ | ✅ | ✅ 394 passed + 8 skipped | QEMU, `make cross-arch` |
| **x86_64-linux-musl (static)** | ✅ | — | — | `zig build hermetic` (аттестуемый артефакт) |
| **wasm32** | ✅ | — | — | `zig build wasm` (`kernc.wasm`, 85 КБ) |
| **aarch64-macos** | ❌ | ✅ | — | CI: `zig build lib -Dtarget=aarch64-macos` |
| **x86_64-windows** | ❌ | ❌ | — | не собирается, см. блокеры |

## Почему macOS — только библиотека

`kernc` для macOS собрать можно, но `zig build` (шаг `install`) тянет `kernx`,
который линкуется с системным `sqlite3`:

```
error: unable to find dynamic system library "sqlite3" using strategy paths_first
```

Кросс-сборка Zig не содержит macOS SDK stubs для `libsqlite3.tbd`. Библиотека
`libkern.dylib` при этом собирается и проверяется в CI.

## Почему Windows не поддерживается

Три ошибки компиляции в POSIX-специфичном коде (проверено
`zig build lib -Dtarget=x86_64-windows-gnu`):

| Файл:строка | Причина |
|:--|:--|
| `src/compat.zig:143` | `process.Environ.GlobalBlock` не имеет поля `slice` вне POSIX |
| `src/verifier/z3_bridge.zig:227` | ожидается `i32`, получен `*anyopaque` (тип из POSIX-вызова) |
| `src/core/kimg_writer.zig:219` | `c.AT.FDCWD` (`AT_FDCWD`) отсутствует в Windows CRT |

Плюс `kernx` требует `-lsqlite3`, для которого нет Windows-артефакта в CI.

**Это не «известное ограничение на будущее», а честная граница:** код ядра
использует POSIX-API для процессов и файловых дескрипторов. Поддержка Windows —
отдельный трек (backlog), а не «должно работать».

## Что проверяется автоматически

| Гейт | Что доказывает |
|:--|:--|
| `make cross-arch` | ядро проходит тесты на aarch64 и ppc64 (big-endian) под QEMU |
| CI job `cross-compile` | `libkern` собирается под `aarch64-macos` |
| `make c-abi-test`, `make c-abi-threads` | C-ABI линкуется и работает (в т.ч. 8 потоков) |
| `make hermetic` | статический musl-бинарник, воспроизводимый побайтно |

## Правило

Если платформа не в этой таблице — она **не поддерживается**, даже если
случайно собирается. Добавление платформы начинается с прогона тестов на ней,
а не с записи в README.
