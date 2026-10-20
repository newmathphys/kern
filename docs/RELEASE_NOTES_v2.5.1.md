# KERN v2.5.1 — release notes

**Дата:** 2026-10-20 · **База:** v2.5.0 (`54439ee`)

## Главное

- **QuixBugs честно:** `6/40` формальный SMT (Ступень 1, `trusted: 0`) и
  `33/40` живой дифференциальный детектор (24 значения + 8 падений +
  1 незавершение; 9 из 33 не требуют эталона; 7 EXPLORED).
- **`make sync`:** `docs/facts.json` + якоря `<!-- fact:key -->N`;
  числа обновляются в EN и RU одновременно, история не переписывается.
- **EN/RU parity:** 8 пар, `make docs-parity`; `make ai-traces-check` —
  без шаблонов ассистента.
- **`make seal`:** `attests_commit`, `dirtyTree=false`, Ed25519.
- **canfail:** 144 non-vacuous, 0 vacuous, 0 dirty, 0 errors, `RC=0`.

## Метрики

| Метрика | Значение |
|:--|:--|
| Ядро | 402 / 402 |
| KERN-Next | 53 / 53 |
| CHECK-цели | 128 / 128 |
| can-fail кейсы | 144 |
| Цели реестра | 160 (BUILD 7 · META 21) |
| Lean 4 | 8 файлов / 137 теорем / 0 sorry |
| Scorecard | 100 / 100 · A+ |

## Артефакты

```bash
curl -fsSLO https://github.com/newmathphys/kern/releases/download/v2.5.1/kernc-x86_64-linux-musl
curl -fsSLO https://github.com/newmathphys/kern/releases/download/v2.5.1/SHA256SUMS
sha256sum -c SHA256SUMS
```

`v2.5.0` остаётся доступным как предыдущий релиз.
