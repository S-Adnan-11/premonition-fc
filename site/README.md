# Premonition historical replay website

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
