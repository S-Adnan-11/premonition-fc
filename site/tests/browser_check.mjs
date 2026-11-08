/** Local-only Chromium verification. Testing dependencies and evidence are external. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const options = Object.fromEntries(process.argv.slice(2).reduce((pairs,arg,index,args)=>index%2===0?[...pairs,[arg.replace(/^--/,''),args[index+1]]]:pairs,[]));
for (const name of ['playwright-module','axe-script','browser-root','site','input','output']) {
  assert(options[name],`Missing --${name}`);
}
const output = path.resolve(options.output);
await fs.mkdir(output,{recursive:false});
process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(options['browser-root']);
const require = createRequire(import.meta.url);
const { chromium } = require(path.resolve(options['playwright-module']));
const input = JSON.parse(await fs.readFile(path.resolve(options.input),'utf8'));
const site = path.resolve(options.site);
const allowed = new Map([['/','index.html'],['/index.html','index.html'],['/styles.css','styles.css'],['/favicon.svg','favicon.svg']]);
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'};
const served = [];
const server = http.createServer(async(req,res)=>{
  const filename = allowed.get(new URL(req.url,'http://localhost').pathname);
  if (!filename) { res.writeHead(404);res.end('Not found');return; }
  try {
    const body = await fs.readFile(path.join(site,filename));
    served.push(filename);
    res.writeHead(200,{'content-type':types[path.extname(filename)],'cache-control':'no-store'});
    res.end(body);
  } catch { res.writeHead(500);res.end('Read error'); }
});
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
const base = `http://127.0.0.1:${server.address().port}`;
const checks = [];
const external = [];
const errors = [];
const screenshots = [];
let browser;
let failure;
let browserVersion;
const record = (name,details)=>checks.push({name,status:'PASS',details});
const normalized = value=>value.replace(/\s+/g,' ').trim();
const score = value=>`${value.home_goals} – ${value.away_goals}`;
const percent = value=>(value*100).toFixed(1)+'%';
const expectedOutcome = match=>{
  const keys = ['home_win','draw','away_win'];
  const selected = keys.reduce((a,b)=>match.forecast.probabilities[b]>match.forecast.probabilities[a]?b:a);
  return selected==='draw'?'Draw':match[selected==='home_win'?'home':'away'].name+' win';
};
const rectCheck = async page=>{
  const layout = await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth,
    overflowing:[...document.querySelectorAll('main *,header *,footer *')].filter(el=>{
      const r=el.getBoundingClientRect(),s=getComputedStyle(el);
      return r.width>0&&r.height>0&&s.visibility!=='hidden'&&!(el.classList.contains('sr-only'))&&(r.right>innerWidth+1||r.left < -1);
    }).map(el=>({tag:el.tagName,class:el.className})).slice(0,8)}));
  assert(layout.body<=layout.viewport,JSON.stringify(layout));
  assert.equal(layout.overflowing.length,0,JSON.stringify(layout));
  return layout;
};
try {
  browser = await chromium.launch({headless:true});
  browserVersion = browser.version();
  const context = await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',locale:'en-GB'});
  await context.route('**/*',route=>{
    const url = route.request().url();
    if (url.startsWith(base+'/')) return route.continue();
    external.push(url);return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  const response = await page.goto(base+'/',{waitUntil:'networkidle'});
  assert.equal(response.status(),200);record('local_http_response',200);
  assert.match(await page.title(),/Historical replay.*Premonition-FC/);
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  assert.equal((await page.locator('.mode-label').textContent()).trim(),'Historical replay');
  assert.match(await page.locator('h1').innerText(),/15–18 August 2025/);
  assert.equal(await page.locator('.issue-meta time').getAttribute('datetime'),input.slate.simulated_issue_date_london);
  assert.equal(await page.locator('.issue-meta time').innerText(),'15 August 2025');
  assert.equal(await page.locator('article.match-card').count(),input.matches.length);
  assert.equal(await page.locator('script').count(),0);record('historical_labels_and_script_free_output');
  const expectTotals = {outcome:input.matches.filter(m=>m.marks.outcome==='correct').length,exact_score:input.matches.filter(m=>m.marks.exact_score==='correct').length};
  for (const [key,total] of Object.entries(expectTotals)) {
    assert.equal(normalized(await page.locator(`[data-summary="${key}"]`).innerText()),`${total}/${input.matches.length}`);
  }
  record('slate_summary',expectTotals);
  for (const match of input.matches) {
    const article = page.locator(`[data-fixture-id="${match.fixture_id}"]`);
    assert.equal(await article.locator('[data-home-name]').innerText(),match.home.name);
    assert.equal(await article.locator('[data-away-name]').innerText(),match.away.name);
    assert.equal(await article.locator('[data-actual-score]').innerText(),score(match.actual_full_time));
    assert.equal(await article.locator('[data-predicted-outcome]').innerText(),expectedOutcome(match));
    assert.equal(await article.locator('[data-predicted-score]').innerText(),score(match.forecast.scorelines[0]));
    for (const [key,label] of [['outcome','Outcome'],['exact_score','Exact score']]) {
      const value=match.marks[key];
      assert.match(normalized(await article.locator(`[data-mark="${key}"]`).innerText()),new RegExp(`${label}: ${value[0].toUpperCase()+value.slice(1)}$`));
    }
    const summary=article.locator('summary');
    assert.equal(await summary.getAttribute('aria-label'),null);
    const visibleLabel=normalized(await summary.innerText());
    assert(visibleLabel.includes('View prediction')&&visibleLabel.includes(match.home.name)&&visibleLabel.includes(match.away.name));
    await summary.click();
    assert(await article.locator('details').evaluate(el=>el.open));
    for (const [key,label] of [['home_win','Home win'],['draw','Draw'],['away_win','Away win']]) {
      const cell=article.locator(`[data-outcome="${key}"]`);
      assert.equal(await cell.locator('dt').innerText(),label);
      assert.equal((await cell.locator('dd').innerText()).trim(),percent(match.forecast.probabilities[key]));
    }
    for(let i=0;i<3;i++) {
      const row=article.locator(`[data-score-rank="${i+1}"]`);
      assert.equal(await row.locator('.exact-score').innerText(),score(match.forecast.scorelines[i]));
      assert.equal(await row.locator('.score-probability').innerText(),percent(match.forecast.scorelines[i].probability));
    }
    record('rendered_fixture_matches_proof',match.fixture_id);
  }
  const zero=input.matches.find(m=>m.actual_full_time.home_goals===0&&m.actual_full_time.away_goals===0);
  const zeroArticle=page.locator(`[data-fixture-id="${zero.fixture_id}"]`);
  await zeroArticle.locator('summary').click();
  assert.equal(await zeroArticle.locator('.full-time').innerText(),'Full-time draw');
  record('completed_zero_zero_details_opened',zero.fixture_id);
  await page.evaluate(()=>scrollTo(0,0));
  await rectCheck(page);record('desktop_layout',{width:1440,height:1000});
  await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});screenshots.push('desktop.png');
  await zeroArticle.screenshot({path:path.join(output,'desktop-zero-draw.png')});screenshots.push('desktop-zero-draw.png');
  await page.goto(base+'/',{waitUntil:'networkidle'});
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').innerText(),'Skip to matches');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator(':focus').getAttribute('id'),'matches');
  for(let i=0;i<12;i++) {
    await page.keyboard.press('Tab');
    if(await page.locator(':focus').evaluate(el=>el.tagName==='SUMMARY'))break;
  }
  assert.equal(await page.locator(':focus').evaluate(el=>el.tagName),'SUMMARY');
  const focused=page.locator('summary:focus');
  const outline=await focused.evaluate(el=>({style:getComputedStyle(el).outlineStyle,width:getComputedStyle(el).outlineWidth,visible:el.matches(':focus-visible')}));
  assert.notEqual(outline.style,'none');assert(outline.visible);record('visible_keyboard_focus',outline);
  await page.keyboard.press('Enter');
  assert(await focused.evaluate(el=>el.parentElement.open));
  await page.keyboard.press('Space');
  assert.equal(await focused.evaluate(el=>el.parentElement.open),false);
  await page.keyboard.press('Tab');assert.equal(await page.locator(':focus').evaluate(el=>el.tagName),'SUMMARY');
  record('keyboard_skip_tab_enter_space');
  await page.locator(`[data-fixture-id="${zero.fixture_id}"] summary`).focus();
  await page.keyboard.press('Enter');
  await page.addScriptTag({path:path.resolve(options['axe-script'])});
  const axe=await page.evaluate(async()=>await globalThis.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}}));
  await fs.writeFile(path.join(output,'accessibility.json'),JSON.stringify({violations:axe.violations,incomplete:axe.incomplete,passes:axe.passes.map(p=>p.id)},null,2));
  assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,help:v.help,nodes:v.nodes.map(n=>n.target)}))));
  assert.equal(axe.incomplete.length,0,JSON.stringify(axe.incomplete.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))));
  record('axe_wcag_a_aa',{violations:0,incomplete:axe.incomplete.length,passes:axe.passes.length});
  await fs.writeFile(path.join(output,'accessibility-tree.txt'),await page.locator('body').ariaSnapshot());
  for (const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    await page.goto(base+'/',{waitUntil:'networkidle'});
    await rectCheck(page);
    for(const match of [input.matches[0],input.matches.at(-1),zero]) {
      const card=page.locator(`[data-fixture-id="${match.fixture_id}"]`);
      await card.locator('summary').click();
      assert(await card.locator('.prediction-detail').isVisible());
      await rectCheck(page);
    }
    const mobileZero=page.locator(`[data-fixture-id="${zero.fixture_id}"]`);
    await rectCheck(page);
    assert(await mobileZero.locator('.prediction-detail').isVisible());
    assert.equal(await mobileZero.locator('[data-actual-score]').innerText(),'0 – 0');
    await page.screenshot({path:path.join(output,`mobile-${width}-detail.png`)});screenshots.push(`mobile-${width}-detail.png`);
    await page.goto(base+'/',{waitUntil:'networkidle'});
    await page.evaluate(()=>{document.activeElement?.blur();scrollTo({top:0,behavior:'instant'});});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert(await page.locator('h1').isVisible());
    assert((await page.locator('h1').boundingBox()).y<400);
    await page.screenshot({path:path.join(output,`mobile-${width}.png`)});screenshots.push(`mobile-${width}.png`);
    record('narrow_layout_and_disclosure',{width,height:844,fixture:zero.fixture_id});
  }
  assert.equal(external.length,0);record('no_external_page_requests');
  assert.equal(errors.length,0,errors.join('\n'));record('no_browser_errors');
  await context.close();
} catch(error) {
  failure=String(error.stack||error);
  console.error(failure);
  const failedPage=browser?.contexts()[0]?.pages()[0];
  if(failedPage)try{await failedPage.screenshot({path:path.join(output,'failure.png'),fullPage:true});screenshots.push('failure.png');}catch{}
} finally {
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
await fs.writeFile(path.join(output,'browser-results.json'),JSON.stringify({status:failure?'FAIL':'PASS',browser:browserVersion,checks,external_requests:external,browser_errors:errors,screenshots,served_assets:[...new Set(served)].sort(),server_and_browser_closed:true,failure:failure||null,limitations:'Automated Chromium checks; no physical mobile device or screen-reader session.'},null,2)+'\n');
if(failure)process.exitCode=1;
else console.log(`Browser PASS: ${checks.length} checks; ${browserVersion}; desktop, 390px and 320px; ${screenshots.length} screenshots; zero external requests.`);
