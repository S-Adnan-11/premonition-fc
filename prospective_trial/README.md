# Paired prospective trial

This package runs from the checkout using the existing locked Python environment. It freezes independent team-strength Poisson (alpha 0.01, 365.25-day half-life) and the original six-feature form Poisson (alpha 0.1). Historical fit guards and artifacts remain unchanged.

All snapshots, ledgers, models and generated reports belong outside Git worktrees. Inputs use explicit modes. Synthetic runs require a controlled aware clock; real runs reject it and require independently reviewed project/source/plan access, current quota, freshness, model-input/display and retention evidence. There is no provider transport in this package.

```powershell
python -B -m prospective_trial freeze --history D:\football-trial\history.json --ledger D:\football-trial\trial.sqlite --cutoff 2026-11-10T12:00:00Z --mode synthetic --clock 2026-11-10T12:00:00Z
python -B -m unittest discover -s prospective_tests -v
python -B prospective_tests/dry_run.py --output D:\football-trial\fictional-run
```

The as-of fit records exact snapshot hashes, eligible history, training fixture IDs, initial form warm-up exclusions, fixed settings, code fingerprints and scoring rules. Both specifications use the same usable training cohort. It reuses the verified form construction, Poisson distributions and team-strength objective; only the prospective fitting adapter accepts later seasons. Goal effects remain neutral for clubs absent from the latest fitted season. Fits stay frozen for the trial; form inputs may update from results available at each later slate cutoff.

Snapshots require a source ID, aware UTC observation, completeness attestation and evidence digest. Confirmed results require canonical season/home/away IDs, nonnegative full-time goals and either a confirmation timestamp or explicit date-only historical availability. Date-only availability is bounded at the next London midnight; the played London date must still precede the shared cutoff date. Historical feature replay retains the original date-only approximation. Missing scores never become 0–0.

The ledger uses SQLite transactions, unique event keys, update/delete guards and a canonical hash chain. The full frozen fit and input snapshot commit in one transaction. A repeated identical freeze returns the original record; a changed request cannot replace it. Hashes detect altered records; they do not protect against an owner replacing the entire database and its backups.

## Issue and settle

```powershell
python -B -m prospective_trial issue --ledger D:\football-trial\trial.sqlite --fixtures D:\football-trial\slate.json --history D:\football-trial\history-at-issue.json --clock 2026-11-10T13:00:00Z
python -B -m prospective_trial settle --ledger D:\football-trial\trial.sqlite --snapshot D:\football-trial\settlement.json --clock 2026-11-17T12:00:00Z
python -B -m prospective_trial review --ledger D:\football-trial\trial.sqlite --clock 2026-11-17T12:00:00Z
python -B -m prospective_trial export --ledger D:\football-trial\trial.sqlite --output D:\football-trial\report
```

The clocks above apply to a synthetic ledger. A real ledger uses the actual UTC system clock and requires `--approval` at freeze and issue. An approval names this project, source, platform, product and plan, with separate evidence digests and validity periods. Access also records current remaining quota, shared reserve and a project allowance no greater than six. These local attestations must come from an independent review; the package does not measure provider coverage, validate a contract or grant permission itself. It makes no provider requests.

Use the fictional generator as the complete input example. A slate snapshot contains `slate_id` (season plus Tuesday London date), every `expected_fixture_id`, eligible `fixtures` and explicit `omissions`. Every eligible fixture needs a canonical ID, season, clubs, aware kickoff, verification time and scheduled status. Scores are forbidden in slate inputs. Both models use the same issue-time London date and known past results. Changed/missing frozen results, stale observations, missing zones, past kickoffs, duplicate fixtures and incomplete coverage fail before the issue transaction commits. The original pair, feature traces, snapshots and exact byte hashes are saved together. Identical retries return the original; changed retries fail.

`earliest_verified_kickoff_at_utc` bounds the entire slate, including an omitted fixture whose kickoff is known. Such omissions retain kickoff and verification fields. This bound is checked both before prediction and just before saving. An all-omitted slate with no verified kickoff can record omissions with a null bound and no forecasts.

Settlement snapshots cover every issued fixture, including pending and void entries. Completed records require both integer scores and an aware completion time after the original kickoff; genuine 0–0 is valid. Pending/postponed/cancelled records carry no scores. Terminal results cannot change or be counted twice. Postponed pairs remain eligible on eventual completion. `display-reissue` records a separate proposed display kickoff and never changes the forecast or cohort. It is a local annotation, not a fresh model issue or a website publication.

Progress reports show eligible, settled, pending, void and omitted counts. The review command requires 100 settled pairs, selects the first 100 by completion time then canonical ID and saves that cohort once. Later results cannot silently revise it. Settlement coverage must be complete; a late result contradicting the frozen cohort is rejected for investigation. No aggregate model comparison is generated before review. The primary measure is team-minus-form log loss; draw Brier, class recall/reliability with counts and exact-score coverage are secondary. Paired uncertainty uses 2,000 slate-block bootstrap resamples with seed 1729. A candidate passes the fixed review criterion only with log-loss difference ≤−0.005 and draw-Brier increase ≤0.005; a small cohort cannot prove superiority.

Exports require fresh external directories. A complete synthetic run verifies the 99/100 gate and writes two byte-identical exports. Exact fit/code/runtime and dependency-lock fingerprints are checked on use. Frozen fits never read settlement targets. Keep the ledger and its snapshots in protected local backups; real publication requires a separate delivery step.

## Independent qualification before launch and each issue

Real `freeze` and `issue` require `--reference` and `--decisions` as well as the existing approval. Qualification compares the supplied history and slate with an independently reviewed fixture register, verifies local evidence hashes, and saves its decision in a separate append-only SQLite ledger. A qualified synthetic freeze also requires qualification for later issues. The older fictional dry run remains available without a reference.

```powershell
python -B -m prospective_trial qualify --history D:\trial\history.json --reference D:\trial\reference.json --decisions D:\trial\decisions.sqlite --mode real
python -B -m prospective_trial freeze --history D:\trial\history.json --reference D:\trial\reference.json --decisions D:\trial\decisions.sqlite --ledger D:\trial\trial.sqlite --cutoff <actual-aware-cutoff> --mode real --approval D:\trial\approval.json
python -B -m prospective_trial issue --history D:\trial\history-at-issue.json --fixtures D:\trial\slate.json --reference D:\trial\reference-at-issue.json --decisions D:\trial\decisions.sqlite --ledger D:\trial\trial.sqlite --approval D:\trial\approval.json
```

These commands read local files only. Refresh and review the inputs before use; `qualify` does not fit models or grant access approval. A standalone qualification is diagnostic. Freeze and issue repeat it internally, including after fitting or prediction and before committing. An identical issue retry still returns the original forecast.

The version-1 reference has `mode`, `competition`, provider `source_id`, aware `observed_at_utc`, `history_start_season`, `history_through_london_date`, true `history_complete` and `schedule_complete`, `season_clubs`, `fixtures`, `documents`, `amendments` and `season_audit`. Its history date must equal the shared London cutoff date. Observations retain the existing 24-hour age bound. `season_clubs` maps every contiguous season from the declared start through the cutoff season to its canonical club list (20 in real mode). The register must contain every ordered home/away pairing exactly once for those seasons. This prevents a missing row from being hidden by shrinking an expected list.

Every reference fixture has canonical identity fields, a `status` and a `document` ID. A `completed` fixture includes `played_date`, `home_goals` and `away_goals`, backed by `official_result` or preserved `historical_audit` evidence. Other fixtures use `official_schedule` evidence, a Tuesday-based `slate_id` and `kickoff_at_utc` (null only when unverified); `postponed` and `cancelled` require a reason. Unplayed records cannot contain scores. All eligible supplied results must match the independently expected identities, dates and goals exactly. A scheduled past fixture without a result or documented lifecycle exception blocks use. The original conservative London date and availability checks still apply.

Each `documents` entry has a bundle-relative `path`, exact `sha256`, source `url` and `kind` (`official_schedule`, `official_result`, `historical_audit` or `season_audit`). Keep the reference bundle and its actual saved evidence outside Git. Evidence paths cannot escape the bundle. URLs identify provenance for review; the code does not fetch them or authenticate a source merely because its kind says official. The register's completeness and source authority require independent review of the saved league/club records and historical audit.

The latest accepted reference is retained with the frozen fit or issued pair. Later references cannot drop identities, alter reconciled results or replace the original `season_audit` finding. A future schedule change requires an amendment with `fixture_id`, exact `from` and `to` objects containing `status`, `slate_id` and `kickoff_at_utc`, plus a reason and official schedule document ID. A verified move across slates preserves one canonical identity. Unresolved or undated expected fixtures pause the affected slate.

For issuance, every independently expected fixture must be scheduled with a verified kickoff and present in both the supplied rows and expected IDs. Omissions cannot bypass this gate. A missing fixture, kickoff conflict or required result pauses the whole slate; no issue event or partial forecast commits. The separate decision survives the rejected transaction and includes the reason code, actual observation time, cutoff, reference and input digests, full reference and earliest known kickoff. A late detection is explicitly marked as late; it cannot be backdated into a pre-result decision. Stop on any nonzero command exit, inspect the decision, and retry only before the entire slate's earliest verified kickoff.

`season_audit` retains `status`, `returned`, `expected` and its evidence document ID. A failed full-season future tail remains visible while complete history and a complete current slate can qualify. It does not change the fixed 100-settled-fixture review, forecast immutability, postponement settlement, cancellation voids or display-only reissue policy.

Run `python -B prospective_tests/qualification_run.py --output D:\trial\new-offline-proof` for the missing-fixture and rescheduling CLI exercise. Its clubs, scores, documents and clocks are fictional, and it makes no provider requests.
