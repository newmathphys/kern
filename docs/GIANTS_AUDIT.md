# Giants audit: money rounding and systems arithmetic

Twelve canonical formulas from practice (ERC-4626, AMM, vesting, fee splits,
C11 integer promotion, u32 midpoint). Each ships with the developer's own tests
on typical numbers; a physical oracle then runs the same code with real numbers
and shows the loss, the created money or the overflow.

**Provenance note.** This is *not* a dump of GPT-4/Claude answers (that would
require raw API logs). These are canonical formulations from audits and
benchmarks; what is verified here is the arithmetic, not the authorship.


| Case | Domain | The trap | Author's tests | Oracle verdict | KERN |
|:--|:--|:--|:--|:--|:--|
| `erc4626_inflation` | DeFi | ERC-4626: первая доля за 1 wei обесценивает вклад следующего | green | clean | нет находок |
| `fee_split_odd` | FinTech | Деление комиссии на две части: нечётный цент исчезает | green | **exploit** | нет находок |
| `pool_weights` | FinTech | Распределение пула по весам: остаток не возвращается | green | **exploit** | нет находок |
| `vesting_cliff` | DeFi | Вестинг: округление вниз запирает 1 единицу навсегда | green | clean | CRASH PATH |
| `amm_fee_evasion` | DeFi | AMM-комиссия 0.3%: мелкие сделки платят ноль | green | **exploit** | нет находок |
| `liq_intermediate_trunc` | DeFi | Ликвидация: промежуточное отсечение меняет вердикт | red | clean | нет находок |
| `c11_promotion` | Systems | C11 integer promotion: (uint8_t)0 - 1 == -1, а не 255 | green | **exploit** | нет находок |
| `u32_midpoint` | Systems | midpoint на u32: (lo + hi) >> 1 переполняется на границе | green | **exploit** | нет находок |
| `banker_rounding` | FinTech | Банковское округление Python против коммерческого полувверх | green | **exploit** | нет находок |
| `compound_trunc` | FinTech | Сложный процент: отсечение на каждом периоде теряет деньги | green | **exploit** | нет находок |
| `coupon_first_user` | FinTech | Купоны: остаток достаётся первому — систематическая привилегия | green | **exploit** | CRASH PATH |
| `negative_floor` | FinTech | Отрицательные суммы: // округляет вниз, а не к нулю | green | **exploit** | нет находок |

**Result: 12 cases, 11 with green author's tests, 9 where the oracle proves an exploit behind green tests.**

## What this proves, and what it does not

Every row with a proven exploit has **green author's tests**: the tests are not
wrong, they are blind to the edge. The KERN column is reported as measured —
where `--xray` finds nothing, it says nothing.

