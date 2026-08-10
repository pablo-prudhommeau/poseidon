# Breakeven stop PnL sweet-spot scan

Reference for [`breakeven_stop_pnl_sweetspot_scan.py`](breakeven_stop_pnl_sweetspot_scan.py): signed parameter sweep over post-BE-arm stop level using **instrumented** shadowing verdicts (post-arm retrace columns).

---

## Overview

Live policy after BE arm (always on):

- no partial sell
- raise stop to `entry × (1 + TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION)`
- default today: **−0.05** (locked PnL **−5 %**)

The script rechallenges loss-side and gain-side BE stops from measured post-arm lows. Shadowing still instruments the former TP1 / BE-arm touch via `take_profit_tier_1_*`.

### Signed PnL semantics

| `TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION` / `--pnl-fractions` | Stop price | Locked PnL |
|---------------------------------------------------------------|------------|------------|
| `-0.05` | `entry × 0.95` | **−5 %** |
| `0` | `entry` | **0 %** |
| `+0.05` | `entry × 1.05` | **+5 %** |

- `stop_price = entry × (1 + pnl_fraction)`
- locked PnL% = `pnl_fraction × 100`
- valid open interval: `(-1, TRADING_BREAKEVEN_ARM_FRACTION)`

### Counterfactual

| Case | Counterfactual PnL % |
|------|----------------------|
| Lowest price ≤ `entry × (1 + pnl_fraction)` | `pnl_fraction × 100` |
| Otherwise | keep original `realized_pnl_percentage` |

---

## Data contract

Universe = resolved shadowing verdicts where:

1. `take_profit_tier_1_hit_at IS NOT NULL`
2. `post_take_profit_tier_1_lowest_price IS NOT NULL`
3. optionally `probe.probed_at >= --probed-since`

**NULL lowest price means “not measured”, not “never retraced”.** Always pass `--probed-since` or `--lookback-days` covering only the instrumented era.

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Repository root | Directory containing `backend/`, `scripts/`, `.venv`, `.env` |
| Python | Project virtual environment at repository root |
| Database | PostgreSQL via `DATABASE_*` in `.env` |
| Instrumentation | Columns on `trading_shadowing_verdicts` from migration `20260801_1240_…` |

```powershell
cd <repository-root>
.\.venv\Scripts\python.exe scripts/breakeven_stop_pnl_sweetspot_scan.py --help
```

```bash
cd <repository-root>
.venv/bin/python scripts/breakeven_stop_pnl_sweetspot_scan.py --help
```

---

## Recommended run

```powershell
.\.venv\Scripts\python.exe scripts/breakeven_stop_pnl_sweetspot_scan.py `
  --probed-since 2026-08-01T00:00:00 `
  --apply-live-filters `
  --pnl-fractions -0.10,-0.07,-0.05,-0.03,-0.02,-0.01,0,0.01,0.02,0.03,0.05 `
  --rank-by average_profit_and_loss_uplift_percentage `
  --csv breakeven_stop_pnl_sweep.csv
```

`--apply-live-filters` restricts to:

- market-cap / liquidity ∈ `[TRADING_LIQUIDITY_STRUCTURE_MIN…, MAX…]`
- predicted holding hours ∈ `[TRADING_CORTEX_HOLDING_TIME_MIN_HOURS, MAX]`

---

## CLI

| Flag | Meaning |
|------|---------|
| `--pnl-fractions` | Signed BE stop PnL fractions versus entry |
| `--probed-since` | ISO local datetime lower bound on `probe.probed_at` |
| `--lookback-days` | Alternative lower bound = now − N days |
| `--apply-live-filters` | Liquidity-structure + holding-time filters from settings |
| `--max-fetch` | Cap on fetched instrumented BE-arm verdicts |
| `--min-n` | Minimum evaluated count for ranking |
| `--rank-by` | Ranking objective (default avg PnL uplift) |
| `--csv` | Write full matrix under `scripts/csv/` when bare filename |
| `--no-log-file` | Skip `scripts/logs/` file |

---

## Metrics

| Column | Meaning |
|--------|---------|
| `breakeven_stop_pnl_percentage` | Locked PnL % if the stop triggers |
| `stop_rate` | Fraction of BE-arm-hit trades that would hit the stop |
| `stop_rate_among_original_winners` | Proxy for **f** (winners cut) |
| `average_profit_and_loss_uplift_percentage` | Counterfactual avg % − baseline avg % (pp) |
| `profit_factor_uplift` | Counterfactual PF − baseline PF |
| `saved_catastrophic_count` | Stopped trades that were STALED or ≤ −50 % originally |
| `cut_original_winner_count` | Originally profitable trades stopped by the level |

Baseline = actual shadow outcomes (no live breakeven applied in the tracker).

---

## How to decide the next default

1. Prefer rows with `evaluated_count >= min-n` (and preferably hundreds).
2. Maximize `average_profit_and_loss_uplift_percentage` (or PF) on `--apply-live-filters`.
3. Inspect `stop_rate_among_original_winners` (~f).
4. Compare best row vs configured `TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION` (default **−0.05**).

---

## Output artifacts

| Type | Location |
|------|----------|
| Logs | `scripts/logs/breakeven_stop_pnl_sweetspot_scan_YYYYMMDD_HHMMSS.log` |
| CSV | `scripts/csv/` when `--csv` is set |

Both directories are gitignored via [`scripts/.gitignore`](.gitignore).

---

## Limitations

- Counterfactual uses **polling granularity** of the shadowing tracker → measured stop rate is a **floor**.
- Restart of the tracker can reset in-memory min price → rare upward bias on lowest price.
- Does **not** use Nash/preprod live fills (live has only `breakeven_stop_armed_at`, no post-arm path).
- Does not re-simulate slippage beyond replacing PnL with the locked stop PnL.
- Gain locks at/above BE arm are rejected.
