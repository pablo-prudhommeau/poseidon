# Cortex gate sweet-spot scan

Reference for [`cortex_gate_sweetspot_scan.py`](cortex_gate_sweetspot_scan.py): parameter sweep over the four Cortex gate thresholds, with aggregate metrics on accepted versus rejected observations.

---

## Overview

The script evaluates a Cartesian grid:

`win_threshold × toxicity_threshold × max_hold_minutes × expected_pnl_threshold`

For each combination it applies the same acceptance rules as `apply_trading_cortex_gate_filter` and `_is_cortex_gate_accepted`, then aggregates realized outcome metrics on the accepted subset and compares them to the rejected subset.

Data sources:

| `--dataset` | Source |
|-------------|--------|
| `shadowing` (default) | Resolved shadowing verdicts; Cortex scores from `trading_shadowing_probes.cortex_inference_summary`. |
| `trades` | Closed paper-trade positions; Cortex scores from `trading_evaluations.cortex_inference_summary`, PnL from SELL `trading_trades`. |

Observations without a complete Cortex inference (all four numeric fields) are excluded.

---

## Environment variables and CLI mapping

| Environment variable | Gate rule | CLI argument |
|---------------------|-----------|--------------|
| `TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD` | `success_probability >= threshold` | `--win-thresholds` |
| `TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD` | `toxicity_probability <= threshold` | `--toxicity-thresholds` |
| `TRADING_CORTEX_PNL_THRESHOLD` | `expected_profit_and_loss_percentage >= threshold` | `--expected-pnl-thresholds` |
| `TRADING_CORTEX_HOLDING_TIME_MAX_HOURS` | `predicted_holding_time_minutes <= hours × 60` | `--max-hold-minutes` |

Defaults from [`config.py`](../backend/src/configuration/config.py) when unset: win `0.60`, toxicity `0.35`, PnL `1.00`, holding `10.0` h (`600` min).

In `--breakdown` mode, single-threshold flags (`--win-threshold`, `--toxicity-threshold`, `--expected-pnl-threshold`, `--max-hold-minutes-single`) default to current `settings` values.

The sentinel value `100000000` in `--max-hold-minutes` effectively disables the holding-time cap (rendered as `none` in the text matrix).

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Repository root | Directory containing `backend/`, `scripts/`, `.venv`, `.env`. |
| Python | Project virtual environment: `.venv` at repository root. |
| Dependencies | `numpy` (see `backend/requirements-cortex.txt`). |
| Database | PostgreSQL connection via `DATABASE_*` in `.env`. |
| Imports | The script prepends `backend/` to `sys.path` for `src.*` modules. |

The script loads `load_dotenv(ROOT / ".env")` with `override=False`. Shell-exported variables take precedence; missing keys are filled from the repository `.env`.

### Paths

| Resource | From repository root | From `scripts/` |
|----------|---------------------|-------------------|
| Virtual environment | `.venv` | `../.venv` |
| Environment file | `.env` | `../.env` |

```powershell
cd <repository-root>
.\.venv\Scripts\python.exe scripts/cortex_gate_sweetspot_scan.py --help
```

```bash
cd <repository-root>
.venv/bin/python scripts/cortex_gate_sweetspot_scan.py --help
```

---

## Output artifacts

| Type | Location | Behaviour |
|------|----------|-----------|
| Logs | [`scripts/logs/`](logs/) | Timestamped file `cortex_gate_sweetspot_scan_YYYYMMDD_HHMMSS.log` unless `--no-log-file`. |
| CSV | [`scripts/csv/`](csv/) | Bare filename with `--csv` writes to `scripts/csv/<name>`. |

Both directories are listed in [`scripts/.gitignore`](.gitignore).

---

## Analytical model

1. Load observations from the selected dataset.
2. Build NumPy arrays for scores, realized PnL, and resolution timestamps.
3. For each threshold quadruplet, compute an acceptance mask:
   - `success_probability >= win_threshold`
   - `toxicity_probability <= toxicity_threshold`
   - `predicted_holding_time_minutes <= max_hold_minutes`
   - `expected_profit_and_loss_percentage >= expected_pnl_threshold`
4. Aggregate metrics on accepted observations; compute deltas versus rejected observations.
5. Split accepted observations into first and second halves of the observation window for temporal stability metrics.

---

## Metrics

### Sweep identification columns

`win_threshold`, `toxicity_threshold`, `max_hold_minutes`, `expected_pnl_threshold`

### Accepted regime

| Column | Definition |
|--------|------------|
| `accepted_count` | Observations passing the simulated gate. |
| `pass_rate_pct` | `accepted_count / total × 100` |
| `accepted_per_day` | Accepted count divided by window length in days. |
| `win_rate_pct` | Share of profitable observations (accepted). |
| `total_pnl_usd` | Sum of realized PnL (accepted). |
| `avg_pnl_usd` | Mean realized PnL (accepted). |
| `empirical_pf` | Gross profit / gross loss (accepted). |
| `payoff_ratio` | Mean winning PnL / \|mean losing PnL\| (accepted). |

### Temporal stability (accepted)

`n_first_half`, `pf_first_half`, `win_rate_first_half_pct`, `n_second_half`, `pf_second_half`, `win_rate_second_half_pct`

### Rejected regime and deltas

`rejected_avg_pnl_usd`, `rejected_win_rate_pct`, `rejected_pf`, `avg_pnl_delta_usd`, `win_rate_delta_pct`, `pf_delta`

---

## Sorting and filters

### `--rank-by`

| Value | Sort key |
|-------|----------|
| `pf_stable` (default) | `min(pf_first_half, pf_second_half)`, then `empirical_pf`, then `accepted_count` |
| `empirical_pf` | Accepted-regime profit factor |
| `avg_pnl` | Mean accepted PnL |
| `pf_delta` | Accepted minus rejected profit factor |
| `velocity` | `accepted_per_day` |
| `win_rate` | Accepted win rate |
| `composite` | `pf_stable`, then `avg_pnl`, then `accepted_per_day` |

### `--min-n` / `--min-n-second-half`

Minimum accepted count for the full window and for the second half of the window.

### `--breakdown`

Skips the sweep. Reports per-day (`day`) or per-model-version (`model`) gate health for a fixed threshold set: calibration gap, skill score, directional accuracy, pass rate, gate precision, accepted average PnL, accepted profit factor.

---

## CLI reference

```text
python scripts/cortex_gate_sweetspot_scan.py --help
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--dataset` | `shadowing` | `shadowing` or `trades`. |
| `--lookback-days` | all history | Optional lookback in days. |
| `--max-fetch` | `1000000` | Maximum shadowing verdicts to load. |
| `--win-thresholds` | `0.50,…,0.70` | Minimum success-probability grid. |
| `--toxicity-thresholds` | `0.30,…,0.50` | Maximum toxicity-probability grid. |
| `--max-hold-minutes` | `240,360,480,600,sentinel` | Maximum predicted holding time (minutes). |
| `--expected-pnl-thresholds` | `0,1,3` | Minimum expected PnL percentage grid. |
| `--min-n` | `50` | Minimum accepted count to print/export a row. |
| `--min-n-second-half` | `20` | Minimum accepted count in the second window half. |
| `--rank-by` | `pf_stable` | Row sort order. |
| `--breakdown` | — | `day` or `model`. |
| `--csv` | — | CSV export path. |
| `--max-printed-rows` | `80` | Console row limit. |
| `--no-log-file` | — | Disable log file under `scripts/logs/`. |

---

## Example commands

Full sweep, stable profit factor ranking:

```bash
python scripts/cortex_gate_sweetspot_scan.py \
  --rank-by pf_stable \
  --min-n 500 --min-n-second-half 200 \
  --csv cortex_gate_pf_stable.csv
```

Single-threshold comparison (other parameters fixed):

```bash
python scripts/cortex_gate_sweetspot_scan.py \
  --win-thresholds 0.60 \
  --toxicity-thresholds 0.35,0.40 \
  --max-hold-minutes 600 \
  --expected-pnl-thresholds 1 \
  --min-n 1 --min-n-second-half 0 \
  --csv cortex_gate_compare.csv
```

Paper trades only:

```bash
python scripts/cortex_gate_sweetspot_scan.py \
  --dataset trades \
  --min-n 30 --min-n-second-half 10 \
  --csv cortex_trades_sweep.csv
```

Daily breakdown at current settings:

```bash
python scripts/cortex_gate_sweetspot_scan.py --breakdown day
```

---

## Related files

| File | Role |
|------|------|
| [`cortex_gate_sweetspot_scan.py`](cortex_gate_sweetspot_scan.py) | Implementation. |
| [`shadow_pf_sweetspot_scan.md`](shadow_pf_sweetspot_scan.md) | Companion sweep for shadowing profit-factor SMA parameters. |
| [`.gitignore`](.gitignore) | Ignores `logs/` and `csv/`. |
