# Breakeven stop-offset sweet-spot scan

Reference for [`breakeven_stop_offset_sweetspot_scan.py`](breakeven_stop_offset_sweetspot_scan.py): parameter sweep over `TRADING_EXIT_BREAKEVEN_STOP_OFFSET_FRACTION` using **instrumented** shadowing verdicts (post-TP1 retrace columns).

Use this script in a future context window once enough forward shadowing has accumulated after the Cortex STALED remediation deploy.

---

## Why this exists

Live policy after BE arm (always on — no toggle):

- no partial sell
- raise stop to `entry × (1 − offset)`
- default offset today: **0.05** (−5 %)

That default was a conservative guardrail against wick noise, **not** a measured fee-recovery optimum (~1 %). This scan rechallenges the sweetspot from measured post-BE-arm lows (shadowing still instruments the former TP1 touch level via `take_profit_tier_1_*`).

---

## Data contract (critical)

Universe = resolved shadowing verdicts where:

1. `take_profit_tier_1_hit_at IS NOT NULL`
2. `post_take_profit_tier_1_lowest_price IS NOT NULL`
3. optionally `probe.probed_at >= --probed-since`

**NULL lowest price means “not measured”, not “never retraced”.** Always pass `--probed-since` (instrumentation deploy datetime) or `--lookback-days` covering only the instrumented era.

Shadow exit geometry stays `+10 / +20 / −20`. The script builds a **counterfactual**:

| Case | Counterfactual PnL % |
|------|----------------------|
| Lowest price ≤ `entry × (1 − offset)` | `−offset × 100` (stopped at breakeven band) |
| Otherwise | keep original `realized_pnl_percentage` |

So:

- winners that dipped through the offset then recovered to TP2 are **cut** (cost of `f`)
- losers / STALED that dipped through the offset are **saved** near flat (benefit)

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Repository root | Directory containing `backend/`, `scripts/`, `.venv`, `.env` |
| Python | Project venv at repository root |
| Database | PostgreSQL via `DATABASE_*` in `.env` |
| Instrumentation | Columns on `trading_shadowing_verdicts` from migration `20260801_1240_…` |

```powershell
cd <repository-root>
.\.venv\Scripts\python.exe scripts/breakeven_stop_offset_sweetspot_scan.py --help
```

```bash
cd <repository-root>
.venv/bin/python scripts/breakeven_stop_offset_sweetspot_scan.py --help
```

---

## Recommended first run

After ≥2–3 weeks of instrumented shadowing:

```powershell
.\.venv\Scripts\python.exe scripts/breakeven_stop_offset_sweetspot_scan.py `
  --probed-since 2026-08-01T00:00:00 `
  --apply-live-filters `
  --offsets 0,0.005,0.01,0.015,0.02,0.03,0.05,0.07,0.10 `
  --rank-by average_profit_and_loss_uplift_percentage `
  --csv breakeven_offset_sweep.csv
```

`--apply-live-filters` restricts to the live-like band used when the policy was chosen:

- market-cap / liquidity ∈ `[TRADING_LIQUIDITY_STRUCTURE_MIN…, MAX…]`
- predicted holding hours ∈ `[TRADING_CORTEX_HOLDING_TIME_MIN_HOURS, MAX]`

---

## CLI

| Flag | Meaning |
|------|---------|
| `--offsets` | Comma-separated fractions under entry (default `0,0.01,0.02,0.03,0.05,0.07,0.10`) |
| `--probed-since` | ISO local datetime lower bound on `probe.probed_at` |
| `--lookback-days` | Alternative lower bound = now − N days |
| `--apply-live-filters` | Liquidity-structure + holding-time filters from settings |
| `--max-fetch` | Cap on fetched instrumented TP1 verdicts |
| `--min-n` | Minimum evaluated count for ranking |
| `--rank-by` | `average_profit_and_loss_uplift_percentage` (default), `counterfactual_average_profit_and_loss_percentage`, `counterfactual_empirical_profit_factor`, `profit_factor_uplift` |
| `--csv` | Write full matrix under `scripts/csv/` when bare filename |
| `--no-log-file` | Skip `scripts/logs/` file |

---

## Metrics (per offset)

| Column | Meaning |
|--------|---------|
| `stop_rate` | Fraction of TP1-hit trades that would hit the offset stop |
| `stop_rate_among_original_winners` | Proxy for **f** at that offset (winners cut) |
| `average_profit_and_loss_uplift_percentage` | Counterfactual avg % − baseline avg % (pp) |
| `profit_factor_uplift` | Counterfactual PF − baseline PF |
| `saved_catastrophic_count` | Stopped trades that were STALED or ≤ −50 % originally |
| `cut_original_winner_count` | Originally profitable trades stopped by the offset |

Baseline = actual shadow outcomes (no live breakeven applied in the tracker).

---

## How to decide the next default

1. Prefer rows with `evaluated_count >= min-n` (and preferably hundreds).
2. Maximize `average_profit_and_loss_uplift_percentage` (or PF) on `--apply-live-filters`.
3. Inspect `stop_rate_among_original_winners` (~f): keep it well below the historical ~16 % break-even of the policy.
4. Compare best row vs configured `0.05` logged at the end of the run.
5. If ~`0.01` dominates with stable uplift → update `TRADING_EXIT_BREAKEVEN_STOP_OFFSET_FRACTION`.

---

## Output artifacts

| Type | Location |
|------|----------|
| Logs | `scripts/logs/breakeven_stop_offset_sweetspot_scan_YYYYMMDD_HHMMSS.log` |
| CSV | `scripts/csv/` when `--csv` is set |

Both directories are gitignored via [`scripts/.gitignore`](.gitignore).

---

## Limitations (do not overclaim)

- Counterfactual uses **polling granularity** of the shadowing tracker → measured stop rate is a **floor**.
- Restart of the tracker can reset in-memory min price → rare upward bias on lowest price.
- Does **not** use Nash/preprod live fills (live has only `breakeven_stop_armed_at`, no post-TP1 path).
- Does not re-simulate slippage beyond replacing PnL with `−offset × 100`.
