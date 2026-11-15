# Static match website

This is a script-free static match view built with Python's standard library. The forecasting package and its fitted models are separate from this directory.

The builder reads a verified historical display input plus the adjoining `display_input.schema.json` and `proof_manifest.json`. It checks their checksums, schema, historical mode, fixture identities, probabilities, scoreline ranking, simulated date, actual scores and correctness marks before rendering.

## Build and preview

Use Python 3.15.1 and choose an output directory outside Git worktrees that does not already exist:

```powershell
python -B .\site\build.py --input D:\football-review\proof\historical_display_input.json --output D:\football-review\replay-site
python -B -m http.server 8765 --bind 127.0.0.1 --directory D:\football-review\replay-site
```

Open `http://127.0.0.1:8765/`. The built `index.html` also opens directly from disk. Stop the preview server with Ctrl+C.

The output contains only `index.html`, `styles.css`, and an original geometric favicon. It includes no input JSON, manifests, raw snapshots, model files, provider assets, client JavaScript, analytics, remote fonts, or generated timestamps. Only attribution links leave the page; it loads no external resources.

Each match uses a native disclosure with an accessible “View prediction” label. The actual score and independent outcome/exact-score marks stay visible while it is closed. The layout supports narrow screens, keyboard navigation, visible focus and reduced-motion preferences. Historical labels and simulated dates distinguish this replay from a real pre-kickoff record.

## Checks

The focused tests use two fictional matches and need no real dataset or third-party dependencies:

```powershell
python -B -m unittest discover -s site/tests -v
```

Build the same verified input into two fresh directories and compare all three files byte for byte. Missing or changed evidence, malformed input, unexpected fields, nonhistorical modes and inconsistent scores/probabilities fail before output is written. Existing outputs are preserved.

Browser verification is provided by `tests/browser_check.mjs`. Install Playwright and axe-core into an external testing directory, with browser binaries outside the repository, then supply their locations explicitly:

```powershell
npm install --prefix D:\football-tools\browser --no-audit --no-fund playwright@1.65.0 axe-core@4.14.0
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\football-tools\browsers'
node D:\football-tools\browser\node_modules\playwright\cli.js install chromium
node .\site\tests\browser_check.mjs --playwright-module D:\football-tools\browser\node_modules\playwright --axe-script D:\football-tools\browser\node_modules\axe-core\axe.min.js --browser-root D:\football-tools\browsers --site D:\football-review\replay-site --input D:\football-review\proof\historical_display_input.json --output D:\football-review\browser-evidence
```

The browser check serves only the three built assets on loopback, inspects every match, exercises native controls by keyboard, checks desktop and narrow layouts, runs automated accessibility checks, and saves screenshots and a result log. It closes its browser and server when done. Automated checks do not replace assistive-technology testing.

Historical facts are credited to the pinned OpenFootball source, under the data terms in the project's `THIRD_PARTY.md`. Keep private build inputs and review evidence out of source and published output.

## Fictional upcoming-match preview

The separate `--preview` entry point exercises saved upcoming forecasts and later results. It accepts only `fictional_preview` mode, explicitly fictional team names and the designated `team_strength_poisson` presentation model. It never reads the trial ledger, fits a model or calls a provider. Both trial models continue to be stored privately by the paired workflow; this display contains only the chosen candidate's saved probabilities and scorelines.

```powershell
python -B .\site\build.py --preview D:\football-review\fictional\before.json --output D:\football-review\upcoming
python -B .\site\build.py --preview D:\football-review\fictional\after.json --output D:\football-review\results
```

Both snapshots reference the **same unchanged** adjoining `issued_forecasts.json` and SHA-256. Keep that saved issue file and its pin when assembling later updates. A changed file fails validation. The pin checks integrity against the reviewed snapshot; it does not authenticate an independently edited replacement bundle. No real-input or publication workflow is provided.

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
