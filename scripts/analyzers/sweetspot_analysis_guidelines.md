# Mission

Produce `V:\opt\poseidon\.env.sweetspot-YYYYMMDD-HHMM` from `V:\opt\poseidon\.env`.

Same file, same order, same keys, with the values you have measured to be better. Nothing else changes. Never write to the input file.

# Decision rule

One criterion: **would Poseidon's total PnL, all outcomes confounded, be higher with this configuration than with the current one?**

If yes, write the value. If no, keep the current value. If nothing improves, write no file and say so.

Throughput multiplied by edge is what pays. A tighter filter that lifts profit factor while starving the flow loses money, and a looser one that floods the flow with losers loses money. Judge every knob on the product, never on one half of it.

# Method

The analyzers in this directory replay the recorded shadowing outcomes against arbitrary parameter values. Read their `.md` files, run them, cross-check them. They are the evidence; your priors are not.

Work cold. Measure the current configuration first so every claim is a delta against a number you produced yourself. Resolve each value actually in force, including the knobs absent from the input file that silently fall back to a code default. Verify that a gain holds on separate time slices of the history before believing it, and re-measure the retained changes together, because filters intersect and individual gains do not add up.

Distrust anything resting on a thin cohort. Distrust a spectacular result more than a modest one.

Some parameters cannot be honestly replayed on recorded outcomes: those governing live execution, and those the recorded exits were themselves produced under. Identify them and leave them alone rather than guessing.

Store whatever you generate here: csv, logs, scratch scripts, notes.

# Report

The proposed file, then a table of every knob you touched with its measured before and after, then the knobs you examined and deliberately left as they are, with the number that made you leave them.

Do not print secrets.
