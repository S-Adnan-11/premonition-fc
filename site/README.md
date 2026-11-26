# Premonition static match website

This is a script-free static match view built with Python's standard library. Choose exactly one source mode: `--input` for a single historical slate, `--archive` for a historical archive, `--preview` for a fictional upcoming/results snapshot, or `--issued` for a genuine opening issue snapshot. All four share output protections and the match renderer. The genuine adapter reuses canonical record hashing and club names from the source package; it never loads or runs a fitted model.

The builder reads a verified historical display input plus the adjoining `display_input.schema.json` and `proof_manifest.json`. It checks their checksums, schema, historical mode, fixture identities, probabilities, scoreline ranking, simulated date, actual scores and correctness marks before rendering.

## Build and preview

Use Python 3.15.1 and choose an output directory outside Git worktrees that does not already exist:

```powershell
python -B .\site\build.py --input D:\football-review\proof\historical_display_input.json --output D:\football-review\replay-site
python -B -m http.server 8765 --bind 127.0.0.1 --directory D:\football-review\replay-site
```

Open `http://127.0.0.1:8765/`. The built `index.html` also opens directly from disk. Stop the preview server with Ctrl+C.

The output contains only `index.html`, `styles.css`, and an original geometric favicon. It includes no input JSON, manifests, raw snapshots, model files, provider assets, client JavaScript, analytics, remote fonts, or generated timestamps. Only attribution links leave the page; it loads no external resources.

## Build an archive

The original `--input` command remains available. To build several independently proved slates with an archive index:

```powershell
python -B .\site\build.py --archive D:\football-review\proof\archive.json --output D:\football-review\archive-site
```

The archive contains `index.html`, one stable `slate-<season>-<Tuesday date>.html` per slate, and the same two shared assets. Each slate links back to the archive and keeps its own simulated issue date, saved match disclosures, results and correctness marks. The archive lists the latest slate first. All labels use historical dates.

Keep the archive input and every adjoining proof bundle outside Git. `archive.json` is a reviewed proof index with these exact fields:

| Field | Required value |
| --- | --- |
| `schema_version` | `premonition-fc.historical-archive.v1` |
| `mode` | `historical_replay` |
| `source_revision` | The pinned OpenFootball revision `e6744429ee395bc86f247348c6184bb08d4eb361` |
| `source_hashes` | The common SHA-256 values for `forecasts/predictions.json`, `forecasts/forecast_manifest.json`, `evaluation/scored_holdout.json`, `evaluation/metrics.json`, `frozen/freeze.json`, `frozen/models.joblib` and `prepared/holdout_features.json` |
| `slates` | A nonempty array of entries described below |

Each entry contains only `input` (a relative POSIX path ending in `historical_display_input.json`), `proof_sha256` (the adjoining proof manifest's SHA-256), and `fixture_ids` (the complete expected fixture identities from the saved prepared slate). Input, schema and proof files must resolve within the archive bundle. Each slate uses the existing display contract and its adjoining `display_input.schema.json` and `proof_manifest.json`.

Assemble the index from verified saved evidence: reconcile every forecast with its unchanged scored join, confirm the full prepared fixture set, check source/frozen hashes, and preserve the original proof. The builder checks that each proof matches the index, all slates share the same frozen provenance, and their fixture sets exactly match the declared complete membership. It rejects duplicates within or across slates. Checksums pin reviewed evidence; they do not replace source review or authenticate a newly fabricated bundle.

Every input and rendered page is validated before creating the output directory. Use a new output directory for each build; an existing preview is always preserved.

Each match uses a native disclosure with an accessible “View prediction” label. The actual score and independent outcome/exact-score marks stay visible while it is closed. The layout supports narrow screens, keyboard navigation, visible focus and reduced-motion preferences. Historical labels and simulated dates distinguish this replay from a real pre-kickoff record.

## Checks

The focused tests use fictional single slates and archive bundles and need no real dataset or third-party dependencies:

```powershell
python -B -m unittest discover -s site/tests -v
```

Build the same verified input into two fresh directories and compare every output file byte for byte. Missing or changed evidence, malformed input, unexpected fields, nonhistorical modes and inconsistent scores/probabilities fail before output is written. Existing outputs are preserved. Archive tests also cover proof pins, shared provenance, complete membership, stable links, reordered entries and recovery with a fresh output.

Browser verification is provided by `tests/browser_check.mjs`. Install Playwright and axe-core into an external testing directory, with browser binaries outside the repository, then supply their locations explicitly:

```powershell
npm install --prefix D:\football-tools\browser --no-audit --no-fund playwright@1.65.0 axe-core@4.14.0
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\football-tools\browsers'
node D:\football-tools\browser\node_modules\playwright\cli.js install chromium
node .\site\tests\browser_check.mjs --playwright-module D:\football-tools\browser\node_modules\playwright --axe-script D:\football-tools\browser\node_modules\axe-core\axe.min.js --browser-root D:\football-tools\browsers --site D:\football-review\replay-site --input D:\football-review\proof\historical_display_input.json --output D:\football-review\browser-evidence
```

For archive verification, replace `--input` with `--archive D:\football-review\proof\archive.json` and point `--site` at the archive output. Use a fresh evidence directory. The browser check serves only the built pages and shared assets on loopback, inspects every match, follows archive and return links, opens each slate directly, exercises native controls by keyboard, checks desktop and narrow layouts, runs automated accessibility checks, and saves screenshots and a result log. It closes its browser and server when done. Automated checks do not replace assistive-technology testing.

Historical facts are credited to the pinned OpenFootball source, under the data terms in the project's `THIRD_PARTY.md`. Keep private build inputs and review evidence out of source and published output.

## Fictional upcoming-match preview

The separate `--preview` entry point exercises saved upcoming forecasts and later results. It accepts only `fictional_preview` mode, explicitly fictional team names and the designated `team_strength_poisson` presentation model. It never reads the trial ledger, fits a model or calls a provider. Both trial models continue to be stored privately by the paired workflow; this display contains only the chosen candidate's saved probabilities and scorelines.

```powershell
python -B .\site\build.py --preview D:\football-review\fictional\before.json --output D:\football-review\upcoming
python -B .\site\build.py --preview D:\football-review\fictional\after.json --output D:\football-review\results
```

Both snapshots reference the **same unchanged** adjoining `issued_forecasts.json` and SHA-256. Keep that saved issue file and its pin when assembling later updates. A changed file fails validation. The pin checks integrity against the reviewed snapshot; it does not authenticate an independently edited replacement bundle. Genuine inputs use the separate path below. Publication remains a separate decision.

The v1 contract allowlists every field; additional fields fail validation:

| Document | Fields |
| --- | --- |
| Preview snapshot | `schema_version`: `premonition-fc.prospective-preview.v1`; `mode`: `fictional_preview`; `label`: `Fictional preview`; `issued_file`: `issued_forecasts.json`; `issued_sha256`: lowercase SHA-256; `updates`: nonempty array |
| Saved issue file | `schema_version`: `premonition-fc.saved-preview-forecasts.v1`; `mode`: `fictional_preview`; `competition`: `Fictional League`; `season`: consecutive `YYYY-YY`; `presentation_model`: `team_strength_poisson`; `fixtures`: nonempty array |
| Saved fixture | `fixture_id`: `season:home-id:away-id`; `home` and `away`: objects with `id` and `name`; `issued_at_utc`; original `kickoff_at_utc`; `forecast` |
| Forecast | `probabilities`: `home_win`, `draw`, `away_win`; `scorelines`: exactly three objects with integer `home_goals`, integer `away_goals` and `probability` |
| Update | `fixture_id`; current scheduled `kickoff_at_utc`; `status`; `actual_full_time` |

Club IDs are lowercase alphanumeric words joined by single hyphens. Names start with `Fictional `. All timestamps use `YYYY-MM-DDTHH:MM:SSZ` and display their UTC time zone. Original and updated scheduled kickoff must be within the season and after issue time. A postponed fixture may retain its last known scheduled kickoff. Fixture links depend only on identity, so changing kickoff does not change the link.

Updates must cover the saved identities exactly once. They cannot supply a forecast, replacement issue time or marks. Probabilities must be finite in [0,1], with outcome mass summing to one. Scorelines must be unique and ranked by descending original probability, then home goals and away goals; their mass cannot exceed their corresponding outcome probabilities.

| Status | Score input | Display |
| --- | --- | --- |
| `completed` | Required object containing nonnegative integer `home_goals` and `away_goals` | Full-time score and two independently computed marks, including genuine 0–0 |
| `scheduled`, `postponed`, `unresolved` | Required `null` | Pending; no final score or marks |
| `cancelled` | Required `null` | Void; no final score or marks |

Unknown statuses, unfinished placeholder scores, contradictory results and all wrong modes fail before output is created. Outcome correctness uses the highest original probability (ties: home win, draw, away win). Exact-score correctness uses only the first ranked scoreline. Rounded percentages never choose the marks. This is a display lifecycle, separate from the trial's settlement evidence and timestamp requirements.

The preview reuses the native match disclosure, responsive styles, keyboard focus and output content review. It emits the same three static files as a historical single-slate build, with explicit fictional labels and no running comparison. `tests/preview_fictional.py` constructs small fictional contract examples for the source tests.

Check both built snapshots against the same saved issue file with the installed external browser tools:

```powershell
node .\site\tests\preview_browser_check.mjs --playwright-module D:\football-tools\browser\node_modules\playwright --axe-script D:\football-tools\browser\node_modules\axe-core\axe.min.js --browser-root D:\football-tools\browsers --before D:\football-review\upcoming --after D:\football-review\results --input-before D:\football-review\fictional\before.json --input-after D:\football-review\fictional\after.json --output D:\football-review\preview-browser
```

## Genuine opening issuance snapshot

The `genuine_issuance` contract is independent of the fictional preview contract. It projects the selected `team_strength_poisson` forecast from the original opening export: exactly one freeze, one genuine issue, ten unique fixtures, and twenty original paired forecast rows. Both models remain in the untouched private record. Assembly checks the event chain, issue/freeze linkage, frozen fit/rules identity, complete issue-time fixture snapshot and both saved models. It copies the selected probabilities and certified three scorelines without recalculation or rounding.

Resolve the original export through its preserved launch report. Reconcile the launch verification's export hashes, original paired record, fit/model identity, official fixture census and scope evidence before assembly. Supply the **original trusted export checksum from that checkpoint** separately from the display input:

```powershell
python -B .\site\issued.py --record D:\football-review\original-export\events.json --record-sha256 <original-checkpoint-sha256> --output D:\football-review\issued\display.json
python -B .\site\build.py --issued D:\football-review\issued\display.json --record D:\football-review\original-export\events.json --record-sha256 <original-checkpoint-sha256> --output D:\football-review\issued-site
```

The assembler preserves existing input files and rejects output in Git worktrees. The builder requires the original record again and independently reconstructs the expected display. Changing a forecast and recomputing the local display checksum still fails against that record. Changing the original record fails its independently supplied pin. These checks establish integrity relative to the trusted checkpoint; replacing both the original export and its trusted checkpoint cannot establish provenance. Keep the trusted checkpoint under separate review and preserve its original evidence.

The display envelope has exactly `schema_version` (`premonition-fc.issued-display.v1`), `mode` (`genuine_issuance`), `display_sha256` (canonical digest of `display`), and `display`. The display contains its label, competition, season, slate identity, selected model, original issue time, saved schedule observation and result snapshot times, source identity pins, and ten allowlisted matches. It must equal the projection of the original record exactly. Matches retain canonical identity, club names/IDs, original issue time, issue-time checked kickoff and schedule check time, saved pending status, null result and original forecast. Other fields, later results, replacement issue times or model choices fail validation.

The page labels the schedule as checked at issuance and gives the actual saved source observation time. Result statuses are explicitly as of the original issue snapshot, even when viewed after those scheduled dates. It shows UTC and preserves the issue timestamp's fractional seconds. Pending fixtures have no actual scores or correctness marks. Each fixture has a stable identity link, a return to the slate, and the existing native prediction disclosure. Percentages alone are rounded for display.

Only `index.html`, `styles.css` and `favicon.svg` are emitted. The builder drops source pins/envelopes, paired alternative forecasts and fitted parameters before rendering; raw exports and display JSON are never copied. The page uses Highlightly fixture credit and explains that it is a saved private snapshot. It makes no provider request or live ledger write and adds no live feed, settlement action or publication command.

Committed source tests use fictional fixtures in the genuine event format. Real export reconciliation and browser evidence stay private. Run the site suite above, smoke-check all four CLI modes, and compare fresh genuine builds byte for byte.

Use the installed external browser tools to compare the page with every original selected record, exercise fixture/return links and keyboard disclosures, and check layout and accessibility at desktop, 390px and 320px:

```powershell
node .\site\tests\issued_browser_check.mjs --playwright-module D:\football-tools\browser\node_modules\playwright --axe-script D:\football-tools\browser\node_modules\axe-core\axe.min.js --browser-root D:\football-tools\browsers --site D:\football-review\issued-site --input D:\football-review\issued\display.json --record D:\football-review\original-export\events.json --output D:\football-review\issued-browser
```
