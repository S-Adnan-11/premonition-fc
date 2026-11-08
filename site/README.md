# Historical replay website

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
