# DEX fundamentals sweet-spot scan

Reference for [`dex_fundamentals_sweetspot_scan.py`](dex_fundamentals_sweetspot_scan.py): bucket diagnostics and filter-band sweeps over DEX / market fundamentals, evaluated on recorded shadowing outcomes.

---

## Configuration source

The script loads `V:\opt\poseidon\.env` and raises if that file is not reachable. The repository `.env` is never read. Baseline values, live thresholds shown in sweep headers and the database connection all come from that file.

---

## Modes

| Mode | Purpose |
|------|---------|
| `bucket` | Slice one continuous feature into buckets and report the outcome metrics per bucket |
| `sweep` | Apply filter configurations along one axis (or `all`) and rank the retained universes |

---

## Data

Source: resolved `trading_shadowing_verdicts` joined to their probe market fields.

`--lookback-days` bounds the window. `--exclude-staled` removes probes resolved as `STALED` from the universe.

`--require-cortex-quantile-accepted` restricts the universe to probes accepted by the live six-criterion Cortex gate, via the helpers in [`cortex_quantile_gate_replay.py`](cortex_quantile_gate_replay.py). Use it to measure a fundamentals filter on the population the live pipeline actually reaches, since the Cortex gate runs upstream and has already removed part of what the filter would remove.

---

## Features (`--mode bucket`)

| Feature | Maps toward |
|---------|-------------|
| `mcap_to_liq` | `TRADING_LIQUIDITY_STRUCTURE_MIN/MAX_*` |
| `age_hours` | `TRADING_MIN/MAX_AGE_HOURS` |
| `liquidity_usd` | `TRADING_MIN_LIQUIDITY_USD` |
| `volume_m5_usd` / `volume_h1_usd` / `volume_h6_usd` / `volume_h24_usd` | `TRADING_MIN_VOLUME_*` |
| `fdv_usd` / `market_cap_usd` / `liq_to_fdv` | FDV / market cap bands, `TRADING_MIN_LIQUIDITY_TO_FDV_RATIO` |
| `price_change_percentage_m5/h1/h6` | `TRADING_MIN_PERCENT_CHANGE_*` |
| `abs_price_change_h24` | `TRADING_MAX_ABSOLUTE_PERCENT_24H` |
| `quality_score` | `TRADING_SCORE_MIN_QUALITY`, recomputed with the live `trading_quality_scorer` formula |
| `holding_hours` | Cortex predicted holding duration |

`--bucket-edges` overrides the default edges.

---

## Sweep axes (`--mode sweep`)

| Axis | Live knobs |
|------|------------|
| `liquidity_structure` | Liquidity-structure min/max market-cap-to-liquidity ratio |
| `age` | `TRADING_MIN/MAX_AGE_HOURS` |
| `liquidity_min` | `TRADING_MIN_LIQUIDITY_USD` |
| `volume_m5` / `volume_h1` / `volume_h6` / `volume_h24` | Volume floors |
| `fdv` / `market_cap` / `liq_to_fdv` | Valuation bands and liquidity-to-FDV ratio |
| `momentum_floor_5m/1h/6h/24h` | `TRADING_MIN_PERCENT_CHANGE_*` |
| `momentum_abs_5m/1h/6h/24h` | `TRADING_MAX_ABSOLUTE_PERCENT_*` |
| `quality_min` | `TRADING_SCORE_MIN_QUALITY` |
| `risk_overextended` | `TRADING_RISK_OVEREXTENDED_FACTOR`, combined with the live 5m and 1h absolute caps |
| `risk_weak_buy_flow` | `TRADING_RISK_WEAK_BUY_FLOW_RATIO` and `..._MIN_PERCENT_5M` |
| `holding_hours` / `combo_ls_holding` | Cortex holding band, alone and intersected with liquidity structure |
| `all` | Every axis sequentially |

`--bands` and `--thresholds` override the candidate values of the selected axis.

---

## Gate topology

The liquidity-structure filter is governed by its own flag and is independent of `TRADING_GATE_FUNDAMENTALS_ENABLED`. All other axes above sit behind `TRADING_GATE_FUNDAMENTALS_ENABLED`, which switches them on or off as a block.

`TRADING_REBUY_COOLDOWN_MINUTES`, `TRADING_MAX_SLIPPAGE` and `TRADING_SCAN_INTERVAL` are not modelled: they depend on live execution state that recorded probes do not carry.

---

## Metrics

| Metric | Meaning |
|--------|---------|
| `selected_count` / `count` | Size of the cohort retained by the configuration or falling in the bucket |
| `pass_rate_pct` | Share of the universe retained |
| `trades_per_day` | Daily rate of the retained cohort over the window |
| `empirical_profit_factor` / `average_profit_and_loss_percentage` / `win_rate_pct` | Computed over probes carrying a realized PnL |
| `staled_rate_pct` | Share of the cohort resolved as `STALED`, which have no realized PnL |
| `take_profit_tier_2_rate_pct` | Share of the cohort exited on the second take-profit tier |
| `catastrophic_rate_pct` | Share resolved as `STALED` or with a realized PnL at or below −50 % |
| `rejected_average_profit_and_loss_percentage` | Average PnL of what the configuration rejected |
| `average_profit_and_loss_uplift_versus_rejected` | Retained average PnL minus rejected average PnL |
| `average_profit_and_loss_uplift_versus_baseline` | Retained average PnL minus the unfiltered universe of the same run |

Sweep mode ranks each axis by average PnL and logs the best configuration. `--csv` writes the full matrix to `csv/`.

---

## Run

```powershell
cd <repository-root>
.\venv\Scripts\python.exe scripts/analyzers/dex_fundamentals_sweetspot_scan.py --mode bucket --feature mcap_to_liq
.\venv\Scripts\python.exe scripts/analyzers/dex_fundamentals_sweetspot_scan.py --mode sweep --axis all --require-cortex-quantile-accepted --csv dex_fundamentals_all.csv
```

A value starting with `-` requires the equals form under PowerShell: `"--bands=-5,0,5"`.
