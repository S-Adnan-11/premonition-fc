/** Check a built issuance snapshot directly against its private original issue record. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';

const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, args) =>
  i % 2 === 0 ? [...pairs, [arg.replace(/^--/, ''), args[i+1]]] : pairs, []));
for (const key of ['playwright-module', 'axe-script', 'browser-root', 'site', 'record', 'input', 'output']) assert(options[key], `Missing --${key}`);
const output = path.resolve(options.output), site = path.resolve(options.site);
await fs.mkdir(output, {recursive:false});
process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(options['browser-root']);
const {chromium} = createRequire(import.meta.url)(path.resolve(options['playwright-module']));
const json = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const events = await json(options.record), input = await json(options.input);
const issue = events.find(e => e.kind === 'issue').payload, display = input.display;
let factualReview;
if (options.results) {
  const history = await json(options.results), latest = history.reviews.at(-1);
  factualReview = await json(path.resolve(path.dirname(options.results), latest.file));
  assert.equal(factualReview.original_issue_event_hash, events.find(e => e.kind === 'issue').event_hash);
}
assert.equal(issue.mode, 'real'); assert.equal(input.mode, 'genuine_issuance');
assert.equal(issue.fixtures.length, 10); assert.equal(display.matches.length, 10);
assert.equal(new Set(issue.fixtures.map(f => f.fixture_id)).size, 10);
assert.deepEqual((await fs.readdir(site)).sort(), ['favicon.svg', 'index.html', 'styles.css']);
const checks = [], external = [], errors = [], screenshots = [];
const record = (name, details) => checks.push({name, status:'PASS', details});
record('only_three_allowlisted_assets_and_ten_unique_original_fixtures');
const server = http.createServer(async (req, res) => {
  const name = new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html';
  if (!['index.html', 'styles.css', 'favicon.svg'].includes(name)) {res.writeHead(404); res.end(); return;}
  try {
    res.writeHead(200, {'content-type':name.endsWith('.html') ? 'text/html; charset=utf-8' : name.endsWith('.css') ? 'text/css' : 'image/svg+xml'});
    res.end(await fs.readFile(path.join(site, name)));
  } catch {res.writeHead(500); res.end();}
});
await new Promise((resolve, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', resolve);});
const base = `http://127.0.0.1:${server.address().port}/`;
const layout = async page => {
  const result = await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
    overflow:[...document.querySelectorAll('main *,header *,footer *')].filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && !el.classList.contains('sr-only') && (r.right > innerWidth+1 || r.left < -1);
    }).map(el => el.tagName+'.'+el.className).slice(0, 8)}));
  assert(result.scroll <= result.width, JSON.stringify(result)); assert.deepEqual(result.overflow, [], JSON.stringify(result));
};
let browser, failure, version;
try {
  browser = await chromium.launch({headless:true}); version = browser.version();
  const context = await browser.newContext({viewport:{width:1440, height:1000}, reducedMotion:'reduce'});
  await context.route('**/*', route => {
    if (route.request().url().startsWith(base)) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
  assert.equal((await page.goto(base, {waitUntil:'networkidle'})).status(), 200);
  assert.match(await page.title(), /Issued forecasts/);
  assert.equal((await page.locator('.mode-label').textContent()).trim(), 'Issued forecasts');
  assert.equal(await page.locator('article').count(), 10);
  assert.equal(await page.locator('script').count(), 0);
  if (!factualReview) assert.equal(await page.locator('[data-actual-score],[data-mark]').count(), 0);
  const body = await page.locator('body').innerText();
  for (const label of ['Schedule checked at issuance', 'Source observation:', 'saved snapshot as of', 'not a live score feed']) assert(body.includes(label));
  for (const excluded of ['Historical replay', 'Fictional preview', 'form_poisson', 'fit_sha256', 'event_hash']) assert(!body.includes(excluded));
  const snapshotTimes = await page.locator('.preview-note time').evaluateAll(nodes => nodes.map(n => n.dateTime));
  assert.deepEqual(snapshotTimes, [factualReview?.snapshot_as_of_utc || issue.issued_at_utc, issue.fixture_snapshot.observed_at_utc]);
  record('genuine_labels_original_issue_schedule_and_result_snapshot_times');
  for (const fixture of issue.fixtures) {
    const saved = issue.forecasts.find(f => f.fixture_id === fixture.fixture_id && f.model === 'team_strength_poisson');
    const projected = display.matches.find(f => f.fixture_id === fixture.fixture_id);
    assert.deepEqual(['home_win', 'draw', 'away_win'].map(key => projected.forecast.probabilities[key]), saved.probabilities);
    assert.deepEqual(projected.forecast.scorelines, saved.scorelines);
    const article = page.locator(`[data-fixture-id="${fixture.fixture_id}"]`);
    assert.equal(await article.locator('[data-home-name]').innerText(), projected.home.name);
    assert.equal(await article.locator('[data-away-name]').innerText(), projected.away.name);
    const chosen = saved.probabilities.reduce((best, value, i, values) => value > values[best] ? i : best, 0);
    assert.equal(await article.locator('[data-predicted-outcome]').innerText(), chosen === 1 ? 'Draw' : projected[chosen === 0 ? 'home' : 'away'].name+' win');
    assert.equal(await article.locator('[data-predicted-score]').innerText(), `${saved.scorelines[0].home_goals} – ${saved.scorelines[0].away_goals}`);
    const times = await article.locator('.fixture-meta time').evaluateAll(nodes => nodes.map(n => ({stamp:n.dateTime, text:n.textContent})));
    assert.deepEqual(times.slice(0, 3).map(t => t.stamp), [fixture.kickoff_at_utc, issue.issued_at_utc, fixture.verified_at_utc]);
    assert(times.filter(t => t.stamp.includes('T')).every(t => t.text.endsWith(' UTC')));
    const factual = factualReview?.results.find(r => r.fixture_id === fixture.fixture_id);
    if (factual) {
      assert.equal(times[3].stamp, factual.verified_at_utc);
      if (factual.status === 'completed') {
        const actual = factual.actual_full_time;
        assert.equal(await article.locator('[data-actual-score]').innerText(), `${actual.home_goals} – ${actual.away_goals}`);
        assert(times.some(t => t.stamp === factual.played_date_london));
        const actualOutcome = actual.home_goals > actual.away_goals ? 0 : actual.home_goals === actual.away_goals ? 1 : 2;
        const exact = saved.scorelines[0].home_goals === actual.home_goals && saved.scorelines[0].away_goals === actual.away_goals;
        assert.equal((await article.locator('[data-mark="outcome"]').innerText()).trim(), `Outcome: ${chosen === actualOutcome ? 'Correct' : 'Incorrect'}`);
        assert.equal((await article.locator('[data-mark="exact_score"]').innerText()).trim(), `Exact score: ${exact ? 'Correct' : 'Incorrect'}`);
      } else {
        assert.equal(await article.locator('[data-actual-score],[data-mark]').count(), 0);
        assert.match(await article.locator('[data-result-state]').innerText(), factual.status === 'cancelled' ? /Void/ : /Pending/);
      }
      record('reviewed_result_and_independent_marks', {fixture:fixture.fixture_id, status:factual.status});
    } else assert.match(await article.locator('[data-result-state]').innerText(), /Scheduled · Pending/);
    assert.equal(await article.locator('.fixture-link').getAttribute('href'), '#match-'+fixture.fixture_id.replaceAll(':', '--'));
    await article.locator('summary').click(); assert(await article.locator('.prediction-detail').isVisible());
    for (const [i, key] of ['home_win', 'draw', 'away_win'].entries()) {
      assert.equal((await article.locator(`[data-outcome="${key}"] dd`).innerText()).trim(), (saved.probabilities[i]*100).toFixed(1)+'%');
    }
    for (const [i, score] of saved.scorelines.entries()) {
      const row = article.locator(`[data-score-rank="${i+1}"]`);
      assert.equal(await row.locator('.exact-score').innerText(), `${score.home_goals} – ${score.away_goals}`);
      assert.equal(await row.locator('.score-probability').innerText(), (score.probability*100).toFixed(1)+'%');
    }
    record('forecast_and_timestamps_match_original_selected_record', {fixture:fixture.fixture_id});
  }
  await layout(page);
  await page.screenshot({path:path.join(output, 'issued-desktop.png'), fullPage:true}); screenshots.push('issued-desktop.png');
  const first = page.locator('article').first(), link = await first.locator('.fixture-link').getAttribute('href');
  await first.locator('.fixture-link').click(); assert.equal(new URL(page.url()).hash, link);
  await page.goto(base+link, {waitUntil:'networkidle'}); assert(await first.isVisible());
  await first.getByRole('link', {name:'Back to slate'}).click(); assert.equal(new URL(page.url()).hash, '#matches');
  record('stable_fixture_direct_link_and_return_to_slate');
  await page.goto(base, {waitUntil:'networkidle'});
  await page.keyboard.press('Tab'); assert.equal(await page.locator(':focus').getAttribute('class'), 'skip-link');
  await page.keyboard.press('Enter'); assert.equal(await page.locator(':focus').getAttribute('id'), 'matches');
  for (let i=0; i<30; i++) {await page.keyboard.press('Tab'); if (await page.locator(':focus').evaluate(el => el.tagName === 'SUMMARY')) break;}
  const focused = page.locator('summary:focus'); assert.equal(await focused.count(), 1);
  const focus = await focused.evaluate(el => ({visible:el.matches(':focus-visible'), style:getComputedStyle(el).outlineStyle, width:getComputedStyle(el).outlineWidth}));
  assert(focus.visible && focus.style !== 'none' && parseFloat(focus.width) > 0);
  await page.keyboard.press('Enter'); assert(await focused.evaluate(el => el.parentElement.open));
  await page.keyboard.press('Space'); assert.equal(await focused.evaluate(el => el.parentElement.open), false);
  record('keyboard_skip_tab_enter_space_and_visible_focus');
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({width, height:844}); await page.goto(base, {waitUntil:'networkidle'}); await layout(page);
    for (const article of await page.locator('article').all()) {await article.locator('summary').click(); await layout(page);}
    await page.screenshot({path:path.join(output, `issued-${width}-detail.png`), fullPage:true}); screenshots.push(`issued-${width}-detail.png`);
    await page.addScriptTag({path:path.resolve(options['axe-script'])});
    const axe = await page.evaluate(async () => await globalThis.axe.run(document, {runOnly:{type:'tag', values:['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}}));
    await fs.writeFile(path.join(output, `accessibility-${width}.json`), JSON.stringify({violations:axe.violations, incomplete:axe.incomplete}, null, 2));
    assert.equal(axe.violations.length, 0, JSON.stringify(axe.violations.map(v => ({id:v.id, targets:v.nodes.map(n => n.target)}))));
    assert.equal(axe.incomplete.length, 0, JSON.stringify(axe.incomplete.map(v => ({id:v.id, targets:v.nodes.map(n => n.target)}))));
    record('layout_all_disclosures_and_axe_wcag_a_aa', {width, violations:0, incomplete:0});
  }
  assert.equal(external.length, 0); assert.equal(errors.length, 0, errors.join('\n'));
  record('zero_external_requests_and_browser_errors'); await context.close();
} catch (error) {failure = String(error.stack || error); console.error(failure);}
finally {if (browser) await browser.close(); await new Promise(resolve => server.close(resolve));}
await fs.writeFile(path.join(output, 'browser-results.json'), JSON.stringify({status:failure ? 'FAIL' : 'PASS', browser:version, checks,
  external_requests:external, browser_errors:errors, screenshots, server_and_browser_closed:true, failure:failure || null,
  limitations:'Automated Chromium; no physical mobile device or screen-reader session.'}, null, 2)+'\n');
if (failure) process.exitCode = 1;
else console.log(`Browser PASS: ${checks.length} checks; ${version}; desktop, 390px and 320px; zero external requests.`);
