# Cortex quantile gate replay

Reference for [`cortex_quantile_gate_replay.py`](cortex_quantile_gate_replay.py): replays the Cortex gate exactly as implemented (quantile thresholds, absolute fallback, six live criteria) over recorded scored probes.

---

## Configuration source

The script loads `V:\opt\poseidon\.env` and raises if that file is not reachable. The repository `.env` is never read. Every threshold and window below is resolved from `settings` after that load, so the replay reflects the deployed configuration rather than development defaults.

---

## What it covers

| Live knob | How |
|---|---|
| `TRADING_CORTEX_QUANTILE_GATE_ENABLED` | If false, every probe uses absolute thresholds. |
| `TRADING_CORTEX_QUANTILE_GATE_SUCCESS/TOXICITY/FRAGILITY_PROBABILITY_QUANTILE` | Quantile of the recent score distribution used as threshold. |
| `TRADING_CORTEX_QUANTILE_GATE_LOOKBACK_DAYS`, `MIN/MAX_SAMPLE_COUNT`, `REFRESH_MINUTES` | Lookback window and sample-count floor. The `LIMIT` is applied before the `model_version` filter, reproducing the live DAO behaviour. |
| Absolute fallbacks `SUCCESS/TOXICITY/FRAGILITY_*_THRESHOLD` | Used when the quantile sample count is below the minimum, which is the post-promotion situation. |
| `TRADING_CORTEX_PNL_THRESHOLD`, `HOLDING_TIME_MIN/MAX_HOURS` | Applied as the remaining live criteria. |

A probe is accepted only when the six criteria hold jointly: success above threshold, toxicity below, fragility below, expected PnL above, holding duration inside the min/max band.

---

## Metrics

Profit factor, win rate and average PnL are computed over probes carrying a realized PnL. Probes resolved as `STALED` have no realized PnL and are reported separately through `staled_rate`.

Reported per run: probe counts loaded and resolved, how many probes were gated by quantile thresholds versus absolute fallback, the median and interquartile range of each effective threshold, and the accepted cohort metrics.

---

## Run

```powershell
cd <repository-root>
.\venv\Scripts\python.exe scripts/analyzers/cortex_quantile_gate_replay.py
```

---

## Reuse

`load_scored_probe_replay_rows`, `build_quantile_gate_replay_arrays`, `compute_effective_quantile_gate_thresholds`, `build_live_cortex_gate_acceptance_mask` and `compute_accepted_probe_identifiers` are importable. [`dex_fundamentals_sweetspot_scan.py`](dex_fundamentals_sweetspot_scan.py) uses them to implement `--require-cortex-quantile-accepted`.

---

## Out of scope

Cortex feature weights, training, promotion and XGBoost device settings. Those are not gate thresholds and this script does not model them.
