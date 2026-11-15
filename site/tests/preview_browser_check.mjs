/** Verify both fictional lifecycle snapshots against one immutable saved issue. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, index, args) =>
  index % 2 === 0 ? [...pairs, [arg.replace(/^--/, ''), args[index+1]]] : pairs, []));
for (const key of ['playwright-module', 'axe-script', 'browser-root', 'before', 'after', 'input-before', 'input-after', 'output']) assert(options[key], `Missing --${key}`);
const output = path.resolve(options.output);
await fs.mkdir(output, {recursive:false});
process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(options['browser-root']);
const {chromium} = createRequire(import.meta.url)(path.resolve(options['playwright-module']));
const json = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const snapshots = [];
for (const name of ['before', 'after']) {
  const inputPath = path.resolve(options['input-'+name]);
  const input = await json(inputPath);
  const issuedPath = path.join(path.dirname(inputPath), input.issued_file);
  snapshots.push({name, input, issuedPath, issued:await json(issuedPath), site:path.resolve(options[name])});
}
assert.equal(snapshots[0].issuedPath, snapshots[1].issuedPath, 'Use the same saved forecast file');
assert.equal(snapshots[0].input.issued_sha256, snapshots[1].input.issued_sha256);
assert.deepEqual(snapshots[0].issued, snapshots[1].issued);
const checks = [], external = [], errors = [], screenshots = [];
const record = (name, details) => checks.push({name, status:'PASS', details});
record('same_saved_issue_file_and_checksum');
const types = {'.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8', '.svg':'image/svg+xml'};
const server = http.createServer(async (req, res) => {
  const parts = new URL(req.url, 'http://localhost').pathname.split('/').filter(Boolean);
  const snapshot = snapshots.find(s => s.name === parts[0]);
  const filename = parts[1] || 'index.html';
  if (!snapshot || parts.length > 2 || !['index.html', 'styles.css', 'favicon.svg'].includes(filename)) {
    res.writeHead(404); res.end(); return;
  }
  try { res.writeHead(200, {'content-type':types[path.extname(filename)]}); res.end(await fs.readFile(path.join(snapshot.site, filename))); }
  catch { res.writeHead(500); res.end(); }
});
await new Promise((resolve, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', resolve);});
const base = `http://127.0.0.1:${server.address().port}`;
const score = value => `${value.home_goals} – ${value.away_goals}`;
const keys = ['home_win', 'draw', 'away_win'];
const actualOutcome = value => value.home_goals > value.away_goals ? 'home_win' : value.home_goals === value.away_goals ? 'draw' : 'away_win';
const chosen = forecast => keys.reduce((a,b) => forecast.probabilities[b] > forecast.probabilities[a] ? b : a);
const layout = async page => {
  const value = await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
    overflow:[...document.querySelectorAll('main *,header *,footer *')].filter(el => {
      const r=el.getBoundingClientRect(); return r.width>0 && r.height>0 && !el.classList.contains('sr-only') && (r.right>innerWidth+1 || r.left < -1);
    }).map(el=>el.tagName+'.'+el.className).slice(0,8)}));
  assert(value.scroll <= value.width, JSON.stringify(value)); assert.deepEqual(value.overflow, [], JSON.stringify(value));
};
let browser, failure, version;
const linksBySnapshot = [];
try {
  browser = await chromium.launch({headless:true}); version = browser.version();
  const context = await browser.newContext({viewport:{width:1440, height:1000}, reducedMotion:'reduce'});
  await context.route('**/*', route => {
    if (route.request().url().startsWith(base+'/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  for (const snapshot of snapshots) {
    const {name, input, issued} = snapshot;
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => {if (message.type()==='error') errors.push(message.text());});
    const url = base+'/'+name+'/';
    assert.equal((await page.goto(url, {waitUntil:'networkidle'})).status(), 200);
    assert.match(await page.title(), /Fictional preview/);
    assert.equal((await page.locator('.mode-label').textContent()).trim(), 'Fictional preview');
    assert.equal(await page.locator('script').count(), 0);
    assert.equal(await page.locator('article').count(), issued.fixtures.length);
    const links = {};
    for (const fixture of issued.fixtures) {
      const update = input.updates.find(u=>u.fixture_id === fixture.fixture_id);
      assert(update);
      const article = page.locator(`[data-fixture-id="${fixture.fixture_id}"]`);
      assert.equal(await article.locator('[data-home-name]').innerText(), fixture.home.name);
      assert.equal(await article.locator('[data-away-name]').innerText(), fixture.away.name);
      const times = await article.locator('.fixture-meta time').evaluateAll(nodes=>nodes.map(n=>({stamp:n.dateTime, text:n.textContent})));
      assert.equal(times[0].stamp, update.kickoff_at_utc); assert.equal(times[1].stamp, fixture.issued_at_utc);
      assert(times.every(t=>t.text.endsWith(' UTC')));
      if(update.kickoff_at_utc !== fixture.kickoff_at_utc) assert.equal(times[2].stamp, fixture.kickoff_at_utc);
      links[fixture.fixture_id] = await article.locator('.fixture-link').getAttribute('href');
      assert.equal(links[fixture.fixture_id], '#'+await article.getAttribute('id'));
      if (update.status === 'completed') {
        assert.equal(await article.locator('[data-actual-score]').innerText(), score(update.actual_full_time));
        const outcomeMark = chosen(fixture.forecast) === actualOutcome(update.actual_full_time) ? 'Correct' : 'Incorrect';
        const exactMark = score(fixture.forecast.scorelines[0]) === score(update.actual_full_time) ? 'Correct' : 'Incorrect';
        assert.match(await article.locator('[data-mark="outcome"]').innerText(), new RegExp(`Outcome: ${outcomeMark}$`));
        assert.match(await article.locator('[data-mark="exact_score"]').innerText(), new RegExp(`Exact score: ${exactMark}$`));
      } else {
        assert.equal(await article.locator('[data-actual-score]').count(), 0);
        assert.equal(await article.locator('[data-mark]').count(), 0);
        assert.match(await article.locator('[data-result-state]').innerText(), update.status==='cancelled' ? /Void/ : /Pending/);
      }
      await article.locator('summary').click();
      assert(await article.locator('.prediction-detail').isVisible());
      for(const key of keys) assert.equal((await article.locator(`[data-outcome="${key}"] dd`).innerText()).trim(), (fixture.forecast.probabilities[key]*100).toFixed(1)+'%');
      for(let i=0; i<3; i++) {
        const row = article.locator(`[data-score-rank="${i+1}"]`);
        assert.equal(await row.locator('.exact-score').innerText(), score(fixture.forecast.scorelines[i]));
        assert.equal(await row.locator('.score-probability').innerText(), (fixture.forecast.scorelines[i].probability*100).toFixed(1)+'%');
      }
      record('fixture_fields_and_original_forecast', {snapshot:name, fixture:fixture.fixture_id, status:update.status});
    }
    linksBySnapshot.push(links);
    await layout(page);
    await page.screenshot({path:path.join(output, name+'-desktop.png'), fullPage:true}); screenshots.push(name+'-desktop.png');
    await page.goto(url, {waitUntil:'networkidle'});
    await page.keyboard.press('Tab'); assert.equal(await page.locator(':focus').getAttribute('class'), 'skip-link');
    await page.keyboard.press('Enter'); assert.equal(await page.locator(':focus').getAttribute('id'), 'matches');
    for(let i=0; i<30; i++) {await page.keyboard.press('Tab'); if(await page.locator(':focus').evaluate(el=>el.tagName==='SUMMARY')) break;}
    const focused = page.locator('summary:focus'); assert.equal(await focused.count(), 1);
    const focus = await focused.evaluate(el=>({visible:el.matches(':focus-visible'), style:getComputedStyle(el).outlineStyle, width:getComputedStyle(el).outlineWidth}));
    assert(focus.visible && focus.style !== 'none' && parseFloat(focus.width)>0);
    await page.keyboard.press('Enter'); assert(await focused.evaluate(el=>el.parentElement.open));
    await page.keyboard.press('Space'); assert.equal(await focused.evaluate(el=>el.parentElement.open), false);
    record('keyboard_skip_tab_enter_space_and_visible_focus', {snapshot:name});
    await page.locator('summary').first().click();
    await page.addScriptTag({path:path.resolve(options['axe-script'])});
    const axe = await page.evaluate(async()=>await globalThis.axe.run(document, {runOnly:{type:'tag', values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}}));
    await fs.writeFile(path.join(output, name+'-accessibility.json'), JSON.stringify({violations:axe.violations, incomplete:axe.incomplete}, null, 2));
    assert.equal(axe.violations.length, 0, JSON.stringify(axe.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))));
    assert.equal(axe.incomplete.length, 0, JSON.stringify(axe.incomplete.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))));
    record('axe_wcag_a_aa', {snapshot:name, violations:0, incomplete:0});
    for(const width of [390, 320]) {
      await page.setViewportSize({width, height:844}); await page.goto(url, {waitUntil:'networkidle'}); await layout(page);
      for(const fixture of issued.fixtures) {
        const article = page.locator(`[data-fixture-id="${fixture.fixture_id}"]`);
        await article.locator('summary').click(); await layout(page);
        assert(await article.locator('.prediction-detail').isVisible());
      }
      await page.screenshot({path:path.join(output, `${name}-mobile-${width}.png`), fullPage:true}); screenshots.push(`${name}-mobile-${width}.png`);
      record('narrow_layout_and_all_disclosures', {snapshot:name, width});
    }
    await page.close();
  }
  assert.deepEqual(linksBySnapshot[0], linksBySnapshot[1]); record('fixture_links_survive_kickoff_and_result_updates');
  const after = snapshots[1];
  assert(after.input.updates.some(u=>u.status==='completed' && score(u.actual_full_time)==='0 – 0')); record('genuine_completed_zero_zero');
  for (const status of ['postponed','cancelled','unresolved']) assert(after.input.updates.some(u=>u.status===status));
  record('postponed_cancelled_and_unresolved_examples');
  assert.equal(external.length, 0); assert.equal(errors.length, 0, errors.join('\n')); record('zero_external_requests_and_browser_errors');
  await context.close();
} catch(error) { failure=String(error.stack || error); console.error(failure); }
finally {if(browser) await browser.close(); await new Promise(resolve=>server.close(resolve));}
await fs.writeFile(path.join(output, 'browser-results.json'), JSON.stringify({status:failure?'FAIL':'PASS', browser:version, checks, external_requests:external, browser_errors:errors, screenshots, server_and_browser_closed:true, failure:failure||null, limitations:'Automated Chromium; no physical mobile device or screen-reader session.'}, null, 2)+'\n');
if(failure) process.exitCode=1;
else console.log(`Browser PASS: ${checks.length} checks; ${version}; desktop, 390px and 320px; zero external requests.`);
