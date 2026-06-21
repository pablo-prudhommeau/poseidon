# Shadow profit-factor sweet-spot scan

Reference for [`shadow_pf_sweetspot_scan.py`](shadow_pf_sweetspot_scan.py): parameter sweep over shadowing chronicle profit-factor SMA settings, with regime comparison above versus at-or-below each SMA threshold.

---

## Overview

The script evaluates a Cartesian grid:

`lookback_days × bucket_seconds × sma_period × pf_threshold`

For each combination it:

1. Builds a sparse per-bucket profit-factor series aligned with the shadowing chronicle.
2. Optionally winsorizes the series (same behaviour as the chronicle chart).
3. Computes a simple moving average over bucket profit factors.
4. Partitions resolved verdicts into two regimes by comparing each verdict's bucket SMA to `pf_threshold`.
5. Aggregates verdict-level and series-level metrics per regime.

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Repository root | Directory containing `backend/`, `scripts/`, `.venv`, `.env`. |
| Python | Project virtual environment: `.venv` at repository root. |
| Database | PostgreSQL connection via `DATABASE_*` in `.env`; resolved shadowing verdicts required. |
| Imports | The script prepends `backend/` to `sys.path` for `src.*` modules. |

The script loads `load_dotenv(ROOT / ".env")` where `ROOT` is the parent of `scripts/`.

### Paths

| Resource | From repository root | From `scripts/` |
|----------|---------------------|-------------------|
| Virtual environment | `.venv` | `../.venv` |
| Environment file | `.env` | `../.env` |

```powershell
cd <repository-root>
.\.venv\Scripts\python.exe scripts/shadow_pf_sweetspot_scan.py --help
```

```bash
cd <repository-root>
.venv/bin/python scripts/shadow_pf_sweetspot_scan.py --help
```

---

## Output artifacts

| Type | Location | Behaviour |
|------|----------|-----------|
| Logs | [`scripts/logs/`](logs/) | Timestamped file `shadow_pf_sweetspot_scan_YYYYMMDD_HHMMSS.log` unless `--no-log-file`. |
| CSV | [`scripts/csv/`](csv/) | Bare filename with `--csv` writes to `scripts/csv/<name>`. |

Both directories are listed in [`scripts/.gitignore`](.gitignore).

---

## Analytical model

1. Fetch resolved shadowing verdicts for the maximum lookback and granularity required by the sweep.
2. Build sparse bucket profit factors using `_compute_profit_factor` and chronicle bucket flooring.
3. Optionally winsorize (`--no-winsorize` disables).
4. Compute SMA via `_simple_moving_average_like_trading_shadowing_verdict_chronicle_chart`.
5. Assign each verdict to a regime:
   - **Above:** `SMA(PF) > pf_threshold`
   - **At or below:** `SMA(PF) ≤ pf_threshold`
6. Aggregate five verdict metrics per regime and five series metrics over the window buckets.
7. Compute deltas between regimes for sorting and export.

Retention and trailing-bucket settings come from `settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS` and `settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS`.

---

## Metrics

### Sweep identification columns

`lookback_days`, `bucket_seconds`, `sma_period`, `pf_threshold`, `winsorize`, `sparse_buckets`, `verdicts_above`, `verdicts_below`

### Verdict metrics per regime (`_above` / `_below`)

| Column | Definition |
|--------|------------|
| `avg_pnl_*_usd` | Mean realized PnL in the regime. |
| `win_rate_*` | Share of profitable verdicts in the regime. |
| `empirical_pf_*` | Gross profit / gross loss in the regime. |
| `velocity_*_per_day` | Verdict count in the regime divided by `lookback_days`. |
| `payoff_ratio_*` | Mean winning PnL / \|mean losing PnL\| in the regime. |

### Series metrics (SMA / raw bucket PF)

| Column | Definition |
|--------|------------|
| `sma_series_mean` | Mean of the SMA line over window buckets. |
| `sma_series_std` | Standard deviation of the SMA line. |
| `sma_time_fraction_above_threshold` | Fraction of buckets with `SMA > pf_threshold`. |
| `raw_pf_mean_when_sma_above_threshold` | Mean raw bucket PF when SMA is above threshold. |
| `raw_pf_mean_when_sma_at_or_below_threshold` | Mean raw bucket PF when SMA is at or below threshold. |

### Regime deltas

`avg_pnl_delta_usd`, `win_rate_delta`, `empirical_pf_delta`, `velocity_delta_per_day`, `payoff_ratio_delta`

---

## Sorting and filters

### `--rank-by`

| Value | Sort key |
|-------|----------|
| `win_rate_delta` (default) | Win-rate delta between regimes |
| `avg_pnl_delta` | Mean PnL delta between regimes |
| `empirical_pf_delta` | Profit-factor delta between regimes |
| `payoff_ratio_delta` | Payoff-ratio delta between regimes |
| `velocity_above` | `velocity_above_per_day` |
| `composite` | Lexicographic: `win_rate_delta`, `avg_pnl_delta_usd`, `velocity_above_per_day` |

### `--min-regime-n` / `--min-regime-below-n`

Minimum verdict counts in the above-threshold and at-or-below-threshold regimes. `--min-regime-below-n 0` disables the below-regime filter.

---

## CLI reference

```text
python scripts/shadow_pf_sweetspot_scan.py --help
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--lookbacks` | `7,14,30` | Lookback window lengths in days (comma-separated). |
| `--granularities` | `300,900,1800` | Bucket width in seconds. |
| `--sma-periods` | `10,30,50,100,200` | SMA periods on the sparse PF series. |
| `--thresholds` | see `--help` | SMA(PF) thresholds for regime split. |
| `--no-winsorize` | off | Disable winsorization before SMA. |
| `--min-regime-n` | `50` | Minimum verdict count in the above-threshold regime. |
| `--min-regime-below-n` | `0` | Minimum verdict count in the at-or-below regime. |
| `--rank-by` | `win_rate_delta` | Row sort order. |
| `--csv` | — | CSV export path. |
| `--no-log-file` | — | Disable log file under `scripts/logs/`. |

---

## Example commands

Coarse sweep ranked by win-rate delta:

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 7,14 \
  --granularities 300,900 \
  --sma-periods 50,100 \
  --thresholds 1.35,1.45,1.55 \
  --min-regime-n 30 \
  --rank-by win_rate_delta \
  --csv win_rate_delta.csv
```

Mean PnL delta between regimes:

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 14,21,30 \
  --granularities 300 \
  --sma-periods 30,50,80 \
  --thresholds 1.2,1.35,1.5 \
  --min-regime-n 40 --min-regime-below-n 40 \
  --rank-by avg_pnl_delta \
  --csv avg_pnl_delta.csv
```

Throughput-oriented ranking:

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 7 \
  --granularities 300,600 \
  --sma-periods 40,60 \
  --thresholds 1.4,1.45,1.5 \
  --min-regime-n 25 \
  --rank-by velocity_above \
  --csv velocity_above.csv
```

`velocity_*_per_day` is normalized by `lookback_days`; compare rows at a fixed lookback when interpreting throughput.

---

## Related files

| File | Role |
|------|------|
| [`shadow_pf_sweetspot_scan.py`](shadow_pf_sweetspot_scan.py) | Implementation. |
| [`cortex_gate_sweetspot_scan.md`](cortex_gate_sweetspot_scan.md) | Companion sweep for Cortex gate thresholds. |
| [`.gitignore`](.gitignore) | Ignores `logs/` and `csv/`. |
