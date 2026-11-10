# Отправленные внешние заявки (квитанции)

Отправлено от аккаунта `newmathphys` 2026-11-09 через GitHub API.

| # | репозиторий | SHA проверки | Issue | тема |
|--:|:--|:--|:--|:--|
| 1 | `tidwall/hashmap.c` | `3735986` | https://github.com/tidwall/hashmap.c/issues/50 | `XXH_rotl64`: сдвиг на 64 = UB при `r == 0`; `64 - r` переполняет `int` |
| 2 | `TheAlgorithms/C` | `e5dad3f` | https://github.com/TheAlgorithms/C/issues/1598 | `binary_search.c`: `r - l` переполняется при отрицательном `l` |
| 3 | `TheAlgorithms/C` | `e5dad3f` | https://github.com/TheAlgorithms/C/issues/1599 | `math/prime_sieve.c`: off-by-one `<=` -> heap-buffer-overflow WRITE в `prime()` и READ в `count()` (два TP) |

## Что подтверждено живым компилятором (не только KERN)

```
# 1
gcc -fsanitize=undefined rot.c && ./rot
rot.c:4:26: runtime error: shift exponent 64 is too large for 64-bit type 'long unsigned int'

# 2
gcc -fsanitize=undefined bs2.c && ./bs2
bs_fn.c:5:26: runtime error: signed integer overflow: 2147483647 - -2147483648
              cannot be represented in type 'int'
```

Оба случая — граница домена: внутренние вызовы в репозиториях безопасны, UB достижим
через публичный API. Это указано в тексте заявок прямо, без преувеличения.

## Ожидание

Внешний контур: ответ мейнтейнера. До ответа ничего не заявляем — «отправлено» != «принято».
