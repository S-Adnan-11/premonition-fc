# Goal model experiments

Run this package from the checkout with the Python environment and locked dependencies described in the root README. It reuses the saved preparation and baseline forecasts without changing the original forecasting package.

```powershell
python -B -m model_iteration plan --output D:\football-runs\goal-model\plan
python -B -m model_iteration diagnose --baseline D:\football-runs\baseline --output D:\football-runs\goal-model\diagnostics
python -B -m model_iteration develop --prepared D:\football-runs\baseline\prepared --baseline D:\football-runs\baseline --protocol D:\football-runs\goal-model\plan\protocol.json --output D:\football-runs\goal-model\development
python -B -m model_iteration freeze --prepared D:\football-runs\baseline\prepared --development D:\football-runs\goal-model\development --protocol D:\football-runs\goal-model\plan\protocol.json --output D:\football-runs\goal-model\frozen
python -B -m model_iteration forecast --prepared D:\football-runs\baseline\prepared --frozen D:\football-runs\goal-model\frozen --output D:\football-runs\goal-model\forecasts
python -B -m model_iteration score --forecasts D:\football-runs\goal-model\forecasts --targets D:\football-runs\baseline\prepared\holdout_targets.json --frozen D:\football-runs\goal-model\frozen --baseline D:\football-runs\baseline --output D:\football-runs\goal-model\evaluation
python -B -m unittest discover -s iteration_tests -v
```

Diagnostics retain H/D/A confusion counts, class recall and precision, five equal-width reliability bins with counts, classwise Brier scores, draw probability and draw picks, and first/top-three exact-score coverage. Empty bins and absent classes have null rates. Development results include season breakdowns. A season already inspected remains a previously seen historical comparison.

The protocol declares four strength/recency configurations, matched low-score corrections and development-only selection rules. All generated data and reports require explicit fresh output directories outside Git worktrees.

## Rates and correction

The home log rate is `intercept + home_advantage + attack[home] + defence[away]`; the away rate is `intercept + attack[away] + defence[home]`. Positive defence means more goals conceded. Attack and defence each sum to zero. The weighted mean of the two Poisson negative log likelihoods per match has an L2 penalty `alpha/2 * sum(attack² + defence²)`. The intercept and home advantage are unpenalized. Deterministic bounded L-BFGS-B uses an analytic gradient and one numerical-library thread.

Development compares alpha 0.01 and 0.1, each with uniform weights or a 365.25-day half-life anchored on the last training date. Four expanding folds validate 2021/22 through 2024/25. The independent model's pooled log loss selects the strength configuration. Candidate order resolves exact ties. This is a small search on development data, so its reported winner has selection optimism.

The matched correction keeps these strengths fixed and estimates one rho from the same weighted training scores. It is a conditional correction experiment, rather than a joint refit of strengths under the full corrected likelihood. Following [Dixon and Coles (1997)](https://doi.org/10.1111/1467-9876.00065), the independent score probability is multiplied by:

| Score | Multiplier |
| --- | --- |
| 0–0 | `1 - home_rate * away_rate * rho` |
| 0–1 | `1 + home_rate * rho` |
| 1–0 | `1 + away_rate * rho` |
| 1–1 | `1 - rho` |
| Other | 1 |

Rho is bounded by ±0.2 and stricter positivity constraints covering every fitted-team pairing and neutral fallback. Negative rho raises low-score draws. At rho zero the distribution is exactly independent Poisson. The four cell changes sum to zero and preserve goal marginals. Full H/D/A probabilities use Skellam plus the analytic correction. The bounded grid independently checks mass, tail, outcome reconciliation and the top-three ranking; no truncated-grid renormalization is used.

## Chronology and fallback

The original prepared fixture identities, dates, slate issue cutoffs and eight warm-up exclusions are reused. Each strength fit uses only the earlier seasons and remains fixed throughout its validation season. The baseline's saved rolling-form inputs can incorporate earlier results within that season. This comparison tests two forecasting strategies with different update behavior; it does not isolate club identity from every other modeling choice.

A team absent from the latest training season receives zero attack and defence, even if it appeared in older training seasons. This explicitly tests a neutral promoted-club fallback and avoids stale returning-club effects. Missing team names, dates or scores fail validation. The neutral fallback can be optimistic for promoted clubs and cannot represent differences in their prior leagues.

`develop` and `freeze` open development partitions only. `forecast` saves both challengers and checksums before `score` opens targets. The frozen JSON contains coefficients, training fixture IDs, rho, selected settings, scoring rules, input pins and source fingerprints. Reusing the fit in the same locked runtime must produce identical prediction and metric JSON. Use fresh output paths for replay. The commands run from the checkout; the experimental package is not included in the original distribution wheel.

## Decision rule

A challenger is eligible for a future trial if it improves pooled development log loss by at least 0.005, improves at least three of four seasons, and increases draw Brier by at most 0.005. Among eligible challengers, lowest development log loss wins; otherwise retain the baseline. Seen-year results cannot change this selection.

The protocol also fixes a future 100-fixture paired trial with no optional stopping. Before its first fixture, freeze the selected code, fit, cohort and scoring rules and satisfy source access, freshness and use-permission gates. Evaluate log loss first, then draw Brier, class recall/reliability with counts and exact-score coverage. Historical results and simulated dates do not establish a prospective forecast record.
