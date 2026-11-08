# Premonition-FC

Premonition-FC compares Premier League result probabilities from a league-frequency reference, two Poisson goal regressions, and a Random Forest classifier. It runs locally and saves forecasts, scored results, metrics, and plots to an explicitly chosen directory.

The historical dataset covers 2020/21 through 2025/26. Four expanding season folds validate 2021/22–2024/25. The 2025/26 season is held out from model selection and final fitting. Historical replays use simulated issue dates; they are separate from a real pre-kickoff forecast record.

## Setup

The tested environment is CPython 3.15.1 on Windows x64. The full resolved dependency set is in `requirements.lock`. Install binary wheels into an environment outside the repository:

```powershell
python -m venv D:\football-tools\environment
$python = 'D:\football-tools\environment\Scripts\python.exe'
& $python -m pip install --only-binary=:all: -r requirements.lock
& $python -m pip install --no-build-isolation --no-deps -e .
& $python -m pip check
& $python -m unittest discover -s tests -v
```

The tests use small synthetic inputs and require no downloaded match archive. A distribution wheel can also be built with `python -m pip wheel --no-build-isolation --no-deps --wheel-dir D:\football-tools\dist .`.

## Inputs and commands

Keep datasets, environments, models, reports and generated runs outside Git worktrees. Every command accepts explicit paths. Output stages require a fresh directory so an earlier experiment is preserved.

Use the six season files and checksums in [data_sources.json](data_sources.json). Download each URL into the matching season directory, preserving the original bytes. For example, the input root contains `2020-21/en.1.json` through `2025-26/en.1.json`. The importer verifies all six SHA-256 pins and complete-season coverage before preparing features.

```powershell
$inputRoot = 'D:\football-inputs\football.json'
$runRoot = 'D:\football-runs\premonition-fc'

& $python -m premonition_fc prepare --input $inputRoot --manifest .\data_sources.json --output "$runRoot\prepared"
& $python -m premonition_fc develop --prepared "$runRoot\prepared" --output "$runRoot\development"
& $python -m premonition_fc freeze --prepared "$runRoot\prepared" --development "$runRoot\development" --output "$runRoot\frozen"
& $python -m premonition_fc forecast --prepared "$runRoot\prepared" --frozen "$runRoot\frozen" --output "$runRoot\forecasts"
& $python -m premonition_fc score --forecasts "$runRoot\forecasts" --targets "$runRoot\prepared\holdout_targets.json" --frozen "$runRoot\frozen" --development "$runRoot\development" --output "$runRoot\evaluation"
```

An optional independent reference comparison is available after preparation:

```powershell
& $python -m premonition_fc parity --prepared "$runRoot\prepared" --audit D:\football-reference\outputs
```

That comparison expects normalized fixtures, feature replay rows and warm-up exclusions from an independent implementation in `historical_normalized.json`, `feature_replay.json`, and `warmup_exclusions.json`. The forecasting package does not import reference implementation code. If a parity record is present, fitting checks that it belongs to the current preparation.

## Features and information cutoffs

Tuesday–Monday UK calendar buckets define slates. Every fixture in a slate uses the first fixture's played date as its simulated issue date. Only confirmed full-time results on strictly earlier dates contribute to either club form or the league prior. Postponed fixtures use their date played.

Each club uses its latest five eligible league matches from the current and immediately preceding seasons. Missing shares of five matches blend toward the eligible league average per team. Both the team history and the prior obey the same cutoff and season restriction. The first slate's eight fixtures establish the prior and are excluded as forecast targets.

The estimator matrix has exactly six columns: goals for, goals against and points per match for each side. Scores, outcomes, dates, identifiers, history counts and traces remain separate. Home advantage is represented by ordered home/away roles and separate goal regressions. Fixture-only targets can be prepared against a separate results history.

Preparation produces 2,280 normalized fixtures, 2,272 feature rows, 1,892 development rows and 380 holdout rows. It retains genuine 0–0s in both nested score objects and plain arrays. Unknown or malformed scores do not become draws.

## Models and evaluation

| Model | Specification |
| --- | --- |
| League frequencies | Training-partition H/D/A frequencies, recomputed per development fold and frozen for the holdout. |
| Poisson | Separate home and away log-link regressions, with training-only standardization. Development compares L2 strengths 0.1 and 1.0. |
| Random Forest | 300 trees, maximum depth 8, all six features considered at splits, seed 1729 and one worker. Development compares minimum leaf sizes 5 and 15. No class weighting or probability calibration. |

Each fitted model selects its configuration independently by pooled log loss over four expanding season folds. Each model has 1,520 development validation predictions. Development figures are used for selection, so the frozen holdout supplies the final comparison.

The Poisson model assumes independent conditional goal counts. H/D/A probabilities use the full Skellam goal-difference distribution. Its score grid has a tail bound of at most 1e-12, reconciles with the full outcome probabilities, and proves that omitted cells cannot displace the top three scorelines. Scoreline probabilities are unconditional.

Log loss uses unrounded probabilities, natural logarithms and a 1e-15 scoring floor. Result ties choose home win, draw, then away win. Scoreline ties sort by probability descending, then home goals and away goals ascending. Reports also include accuracy, draw recall, fixture counts and Poisson's top-one exact-score hit rate.

## Frozen forecasts and replay

`develop` and `freeze` read development partitions only. `freeze` saves model settings, fitted estimators, training fixture identities, preprocessing state, input hashes, dependency versions, scoring rules and a package-source fingerprint. All 380 holdout rows are excluded from these fits.

`forecast` reads the frozen fit and holdout features, saves 380 predictions per model, and records their checksum before scoring targets are opened. `score` is a separate command with an explicit target path and a one-to-one fixture join. Earlier holdout results can update later rolling form, while estimator and preprocessing fits remain frozen.

To reproduce an existing experiment, reuse its frozen fit and prepared inputs and run `forecast` and `score` into new directories. With the same code and tested environment, prediction, scored-join and metric JSON must be byte-identical. Execution timestamps are recorded in separate manifests. A different configuration belongs in a new experiment directory; it is not a replay of the original holdout evaluation.

The generated evaluation contains `REPORT.md`, `metrics.json`, `scored_holdout.json`, and three PNG figures: model log loss, chronological cumulative loss, and reliability diagrams. Load only model artifacts created locally or otherwise trusted; the fitted model format is Python serialization.

## Data credit

Match data comes from [OpenFootball JSON](https://github.com/openfootball/football.json) at revision `e6744429ee395bc86f247348c6184bb08d4eb361`, cross-checked against [OpenFootball England](https://github.com/openfootball/england) revision `9ee7a0c351805c99cc334478a9bf04b7d0432fec`. These formats share a lineage. Their CC0 terms, attribution and scope are described in [THIRD_PARTY.md](THIRD_PARTY.md).

Historical date checks approximate when results were known. They do not verify real-time data availability. A live record requires a fresh, permitted fixture/result source, an issue-time snapshot and a forecast saved before the slate's earliest verified kickoff.
