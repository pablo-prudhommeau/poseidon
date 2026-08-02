# DEX fundamentals sweet-spot scan

Reference for [`dex_fundamentals_sweetspot_scan.py`](dex_fundamentals_sweetspot_scan.py): bucket diagnostics and filter-band sweeps over **DEX / market fundamentals** on shadowing outcomes (liquidity structure, age, volume, FDV, market cap, momentum, holding time).

This is the capitalised tool to rechallenge findings like mcap/liq `[10, 50]` — including STALED mortality.

---

## Modes

| Mode | Purpose |
|------|---------|
| `bucket` | Slice one continuous feature into buckets; report EV / PF / STALED / TP2 per bucket (discovery) |
| `sweep` | Apply filter configurations on one axis (or `all`) and rank retained universes |

---

## Data

Source: resolved `trading_shadowing_verdicts` joined to probe market fields.

**STALED are kept by default** (mortality analysis). Use `--exclude-staled` only if you explicitly want the non-STALED subset.

Optional base filter:

- `--require-cortex-accepted` → keep only probes with persisted `cortex_inference_summary.gate_verdict.is_accepted == true` (closest to the plan’s “gate + mcap/liq” universe)

---

## Features (`--mode bucket`)

| Feature | Meaning |
|---------|---------|
| `mcap_to_liq` | `market_cap_usd / liquidity_usd` |
| `age_hours` | token age |
| `liquidity_usd` | pool liquidity |
| `volume_h1_usd` / `volume_h24_usd` | volumes |
| `fdv_usd` / `market_cap_usd` | valuations |
| `liq_to_fdv` | `liquidity / FDV` |
| `abs_price_change_h24` | `abs(price_change_h24)` |
| `holding_hours` | Cortex predicted holding time (hours) |

Custom edges: `--bucket-edges 0,5,10,30,50,inf`

---

## Sweep axes (`--mode sweep`)

| Axis | Configuration shape | Default grid |
|------|---------------------|--------------|
| `liquidity_structure` | `[min, max]` mcap/liq | includes `[10,50]`, `[10,30]`, `[10,inf]`, toxic `<5` / `>50` |
| `age` | `[min, max]` hours | |
| `liquidity_min` | `>=` USD | |
| `volume_h1` / `volume_h24` | `>=` USD | |
| `fdv` / `market_cap` | `[min, max]` USD | |
| `liq_to_fdv` | `>=` ratio | |
| `momentum_abs_24h` | `\|d24h\| <=` | |
| `holding_hours` | `[min, max]` hours | includes `2–10`, `2–6` |
| `combo_ls_holding` | mcap/liq × holding | plan’s complementary levers |
| `all` | run every axis sequentially | |

Custom bands: `--bands 10:50;10:30;10:inf`  
Custom floors: `--thresholds 5000,10000,25000`

---

## Prerequisites

```powershell
cd <repository-root>
.\.venv\Scripts\python.exe scripts/dex_fundamentals_sweetspot_scan.py --help
```

---

## Recommended runs

Recreate the mcap/liq discovery (plan-style, gate-accepted universe):

```powershell
.\.venv\Scripts\python.exe scripts/dex_fundamentals_sweetspot_scan.py `
  --mode bucket --feature mcap_to_liq --require-cortex-accepted `
  --csv mcap_liq_buckets.csv
```

Sweep liquidity-structure bands:

```powershell
.\.venv\Scripts\python.exe scripts/dex_fundamentals_sweetspot_scan.py `
  --mode sweep --axis liquidity_structure --require-cortex-accepted `
  --rank-by average_profit_and_loss_percentage `
  --csv ls_sweep.csv
```

Live-like combo (mcap/liq × holding):

```powershell
.\.venv\Scripts\python.exe scripts/dex_fundamentals_sweetspot_scan.py `
  --mode sweep --axis combo_ls_holding --require-cortex-accepted `
  --csv ls_holding_combo.csv
```

Overall fundamentals tour:

```powershell
.\.venv\Scripts\python.exe scripts/dex_fundamentals_sweetspot_scan.py `
  --mode sweep --axis all --require-cortex-accepted `
  --csv dex_fundamentals_all.csv
```

---

## Metrics

| Metric | Meaning |
|--------|---------|
| `average_profit_and_loss_percentage` | Mean realized % on selected |
| `empirical_profit_factor` | Gross wins / abs(gross losses) on % |
| `staled_rate_pct` | Share of STALED exits |
| `catastrophic_rate_pct` | STALED or PnL ≤ −50 % |
| `take_profit_tier_2_rate_pct` | Share of TP2 exits |
| `average_profit_and_loss_uplift_versus_baseline` | Selected avg − full-universe avg |
| `average_profit_and_loss_uplift_versus_rejected` | Selected avg − rejected avg |

---

## How this relates to `[10, 50]`

That band came from the same style of analysis as `--mode bucket --feature mcap_to_liq` + `--mode sweep --axis liquidity_structure` on a Cortex-accepted shadow universe. This script makes that reproducible instead of one-off notebook logic.

Caveat (same as the plan): in-sample discovery unless you hold out a later window via `--lookback-days` / successive eras.

---

## Outputs

| Type | Location |
|------|----------|
| Logs | `scripts/logs/dex_fundamentals_sweetspot_scan_*.log` |
| CSV | `scripts/csv/` when `--csv` is set (`_axis` suffix when `--axis all`) |
