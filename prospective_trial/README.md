# Paired prospective trial

This package runs from the checkout using the existing locked Python environment. It freezes independent team-strength Poisson (alpha 0.01, 365.25-day half-life) and the original six-feature form Poisson (alpha 0.1). Historical fit guards and artifacts remain unchanged.

All snapshots, ledgers, models and generated reports belong outside Git worktrees. Inputs use explicit modes. Synthetic runs require a controlled aware clock; real runs reject it and require independently reviewed project/source/plan access, current quota, freshness, model-input/display and retention evidence. There is no provider transport in this package.

```powershell
python -B -m prospective_trial freeze --history D:\football-trial\history.json --ledger D:\football-trial\trial.sqlite --cutoff 2026-11-10T12:00:00Z --mode synthetic --clock 2026-11-10T12:00:00Z
python -B -m unittest discover -s prospective_tests -v
```

The as-of fit records exact snapshot hashes, eligible history, training fixture IDs, initial form warm-up exclusions, fixed settings, code fingerprints and scoring rules. Both specifications use the same usable training cohort. It reuses the verified form construction, Poisson distributions and team-strength objective; only the prospective fitting adapter accepts later seasons. Goal effects remain neutral for clubs absent from the latest fitted season. Fits stay frozen for the trial; form inputs may update from results available at each later slate cutoff.

Snapshots require a source ID, aware UTC observation, completeness attestation and evidence digest. Confirmed results require canonical season/home/away IDs, nonnegative full-time goals and either a confirmation timestamp or explicit date-only historical availability. Date-only availability is bounded at the next London midnight; the played London date must still precede the shared cutoff date. Historical feature replay retains the original date-only approximation. Missing scores never become 0–0.

The ledger uses SQLite transactions, unique event keys, update/delete guards and a canonical hash chain. The full frozen fit and input snapshot commit in one transaction. A repeated identical freeze returns the original record; a changed request cannot replace it. Hashes detect altered records; they do not protect against an owner replacing the entire database and its backups.
