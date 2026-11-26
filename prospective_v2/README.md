# Explicit prospective cohort v2

Run `python -B -m prospective_v2` from the source checkout. This is an opt-in workflow with a separate registration and ledger. Normal `prospective_trial` callers keep v1 semantics. The new package does not alter v1's fingerprinted source files, numerical model specifications, metrics or thresholds.

Prepare an unactivated draft using an independently pinned original v1 events export:

```powershell
python -B -m prospective_v2 draft --parent D:\review\original\events.json --parent-sha256 <trusted-original-export-pin> --mode real --output D:\review\v2-draft.json
```

Preparation reads the parent export and creates no ledger. It validates the complete event chain and native v1 frozen code/rules/runtime/fit identity, then records their hashes beside separate v2 code/rules hashes. The numerical fits remain unchanged. A trusted original pin is required independently of the draft; replacing both the export and trusted pin does not establish provenance.

Registration is a distinct operation requiring a genuinely future complete first slate, current history, independent official reference and valid operational approval:

```powershell
python -B -m prospective_v2 register --ledger D:\review\new-v2.sqlite --draft D:\review\v2-draft.json --parent D:\review\original\events.json --parent-sha256 <trusted-original-export-pin> --fixtures D:\review\fresh\first-slate.json --history D:\review\fresh\history.json --reference D:\review\fresh\reference.json --approval D:\review\fresh\approval.json
python -B -m prospective_v2 issue --ledger D:\review\new-v2.sqlite --fixtures D:\review\fresh\first-slate.json --history D:\review\fresh\history.json --reference D:\review\fresh\reference.json --approval D:\review\fresh\approval.json
```

These commands perform real operations only when explicitly invoked. Real mode always uses the actual clock and rejects `--clock`; synthetic mode requires it. Registration must precede issuance and every first-slate kickoff. Preparation never activates automatically. Old issued v1 identities cannot be admitted. If a future window passes, obtain the next complete future slate and prepare current evidence; do not backfill earlier forecasts.

Existing source snapshots/reference files retain their v1 **input format**, independently of the explicit v2 **protocol identity** on registration, factual snapshots and every ledger event. Registration and issuance reuse the native complete-history, strict London-date cutoff, availability, full-slate, official-reference, freshness and operational gates. They use the saved numerical fit through the existing forecasting function, with no fitting function called. Raw inputs and all ledgers/exports belong outside Git worktrees.

The immutable order is original issue event sequence, original issue-time scheduled kickoff UTC, then canonical fixture ID. Later observations and replay dates cannot move a pair. Earlier scheduled, postponed, suspended, abandoned or unresolved positions block closure. Verified cancellations and administrative awards are void without scores. Review freezes the first 100 completed non-void positions only after every earlier position has a final disposition. No interim comparative metrics are exported.

`settle --snapshot <file>` accepts a complete v2 factual census. Its strict envelope contains `schema_version` (`premonition-fc.prospective-cohort.v2.facts`), `protocol_version` (2), `rules_sha256`, `mode`, `source_id`, actual `observed_at_utc`, `reviewed_at_utc`, `reviewed_by`, `documents` and `updates`. Each document has a relative `path`, original byte `sha256`, ordinary HTTPS `url`, `authority` (`official_league`/`official_club`), true `observed_at_utc` and explicit `precision`. Real authority kinds must match the supported official domain. Evidence hashes and paths are checked before acceptance.

Each row has canonical `fixture_id`, `season`, `home`, `away`, `status`, `home_goals`, `away_goals`, `played_date`, `available_at_utc`, `document`, `basis`, `supersedes` and `correction_reason`. Completed sporting matches require nonnegative integer scores, an ISO calendar played date and an honest result-availability bound. The basis is `sporting_completion` or verified `official_replay`. Final evidence observation must follow original issuance. There is no fabricated whistle timestamp. Pending states use null score/date/availability and `awaiting_review`; cancelled uses `official_cancellation`, and awarded uses `administrative_award`, also with null scores.

Official factual review is an explicit human assertion backed by saved source documents. Hashes verify those documents' integrity; they do not independently establish the truth of an extracted score or source semantics. Contradictory/unverified evidence belongs in unresolved state until reviewed. An observation/availability bound is never described as actual completion time.

Every changed semantic result, status, played date, availability bound or basis requires the previous `fact_sha256` in `supersedes` plus an attributable `correction_reason`. Unchanged reobservations retain their original fact identity and add snapshot evidence; they do not need invented corrections. Exact duplicate issue/factual delivery is idempotent. Corrections are append-only. `review` returns the original frozen review forever. A later correction adds an integrity notice; `corrected-review --reason <text>` may append a clearly attributed corrected analysis on the same 100 identities. A disposition change across the cohort/void boundary blocks that path and requires a separately reviewed amendment. Original metrics and members are preserved.

Existing databases are checked through immutable read-only SQLite before any v2 transaction. Wrong-version databases are rejected before writable access. First registration publishes a closed temporary database atomically, preserving a concurrent existing target. Interrupted registration/issue/factual/review operations roll back and can be retried.

```powershell
python -B -m unittest discover -s prospective_tests -v
python -B -m unittest discover -s cohort_v2_tests -v
python -B -m cohort_v2_tests.rehearsal --output D:\review\fictional-v2-rehearsal
```

The rehearsal uses fictional inputs and disables network access in CLI children. It proves v1/v2 replay, complete-slate rejection, the pending frontier and 99/100/101 boundaries, completed 0-0, voids, duplicate delivery, mixed-version rejection, original fit/pair retention and post-review correction without replacing the cohort. Independent fresh rehearsals should produce identical final export bytes. Keep real registration drafts, study plans and rehearsal evidence private.
