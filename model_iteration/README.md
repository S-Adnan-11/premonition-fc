# Goal model experiments

Run this package from the checkout with the Python environment and locked dependencies described in the root README. It reuses the saved preparation and baseline forecasts without changing the original forecasting package.

```powershell
python -B -m model_iteration plan --output D:\football-runs\goal-model\plan
python -B -m model_iteration diagnose --baseline D:\football-runs\baseline --output D:\football-runs\goal-model\diagnostics
python -B -m unittest discover -s iteration_tests -v
```

Diagnostics retain H/D/A confusion counts, class recall and precision, five equal-width reliability bins with counts, classwise Brier scores, draw probability and draw picks, and first/top-three exact-score coverage. Empty bins and absent classes have null rates. Development results include season breakdowns. A season already inspected remains a previously seen historical comparison.

The protocol declares four strength/recency configurations, matched low-score corrections and development-only selection rules. All generated data and reports require explicit fresh output directories outside Git worktrees.
