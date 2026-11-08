"""Semantic, script-free match-view rendering."""
from datetime import date
from html import escape
from itertools import groupby

ORDER = ("home_win","draw","away_win")
MONTHS = ("January","February","March","April","May","June","July","August","September","October","November","December")
WEEKDAYS = ("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")


def day_label(value,weekday=False):
    day = date.fromisoformat(value)
    prefix = WEEKDAYS[day.weekday()]+", " if weekday else ""
    return f"{prefix}{day.day} {MONTHS[day.month-1]} {day.year}"


def range_label(first,last):
    a,b = date.fromisoformat(first),date.fromisoformat(last)
    return f"{a.day}–{b.day} {MONTHS[a.month-1]} {a.year}" if (a.month,a.year)==(b.month,b.year) else day_label(first)+" – "+day_label(last)


def score_label(score):
    return f"{score['home_goals']} – {score['away_goals']}"


def outcome_label(match):
    probabilities = match["forecast"]["probabilities"]
    selected = max(ORDER,key=lambda key:probabilities[key])
    return "Draw" if selected=="draw" else match["home" if selected=="home_win" else "away"]["name"]+" win"


def badge(kind,mark):
    label = "Outcome" if kind=="outcome" else "Exact score"
    return f'<span class="mark mark-{mark}" data-mark="{kind}"><span class="mark-icon" aria-hidden="true"></span> {label}: {mark.capitalize()}</span>'


def render_match(match):
    home,away = escape(match["home"]["name"]),escape(match["away"]["name"])
    identity = "match-"+match["fixture_id"].replace(":","-")
    heading = identity+"-title"
    probabilities = match["forecast"]["probabilities"]
    scores = match["forecast"]["scorelines"]
    actual = match["actual_full_time"]
    final_label = "Full-time draw" if actual["home_goals"]==actual["away_goals"] else "Full time"
    probability_cells = []
    for key,label in zip(ORDER,("Home win","Draw","Away win")):
        value = probabilities[key]
        probability_cells.append(f'''<div class="probability" data-outcome="{key}">
          <dt>{label}</dt><dd>{value*100:.1f}%<span class="probability-track" aria-hidden="true"><span style="width:{value*100:.6f}%"></span></span></dd>
        </div>''')
    score_rows = []
    for rank,score in enumerate(scores,1):
        score_rows.append(f'''<li data-score-rank="{rank}"><span class="score-rank" aria-hidden="true">0{rank}</span>
          <span class="exact-score">{score_label(score)}</span><span class="score-probability">{score['probability']*100:.1f}%</span></li>''')
    return f'''<article class="match-card" id="{identity}" data-fixture-id="{escape(match['fixture_id'],quote=True)}" aria-labelledby="{heading}">
      <h4 class="sr-only" id="{heading}">{home} versus {away}</h4>
      <details name="prediction">
        <summary>
          <span class="fixture-teams"><span data-home-name>{home}</span><span class="versus">vs</span><span data-away-name>{away}</span></span>
          <span class="forecast-glance"><span class="glance-label">Model forecast</span><strong data-predicted-outcome>{escape(outcome_label(match))}</strong><span class="top-score">Top score <b data-predicted-score>{score_label(scores[0])}</b></span></span>
          <span class="actual-glance"><span class="glance-label">Actual result</span><strong class="actual-score" data-actual-score>{score_label(actual)}</strong><span class="full-time">{final_label}</span></span>
          <span class="summary-action">View prediction <span class="disclosure-icon" aria-hidden="true">+</span></span>
        </summary>
        <div class="prediction-detail">
          <section class="outcomes" aria-label="Outcome probabilities for {home} versus {away}">
            <div class="detail-heading"><h5>Outcome probabilities</h5><span>Poisson model</span></div>
            <dl class="probability-grid">{''.join(probability_cells)}</dl>
            <p class="detail-note">Home win, draw and away win include all possible scorelines.</p>
          </section>
          <section class="scores" aria-label="Ranked scorelines for {home} versus {away}">
            <div class="detail-heading"><h5>Most likely scorelines</h5><span>Home – away</span></div>
            <ol class="score-list">{''.join(score_rows)}</ol>
          </section>
        </div>
      </details>
      <div class="match-verdict" role="group" aria-label="Forecast correctness">{badge('outcome',match['marks']['outcome'])}{badge('exact_score',match['marks']['exact_score'])}</div>
    </article>'''


def render_page(data):
    matches = sorted(data["matches"],key=lambda m:(m["played_date_london"],m["fixture_id"]))
    dates = sorted({m["played_date_london"] for m in matches})
    first,last = dates[0],dates[-1]
    issue = data["slate"]["simulated_issue_date_london"]
    period = range_label(first,last)
    total = len(matches)
    correct = sum(m["marks"]["outcome"]=="correct" for m in matches)
    exact = sum(m["marks"]["exact_score"]=="correct" for m in matches)
    date_links = []
    groups = []
    for day,fixtures in groupby(matches,key=lambda m:m["played_date_london"]):
        d = date.fromisoformat(day)
        date_links.append(f'<a href="#day-{day}">{WEEKDAYS[d.weekday()][:3]} <b>{d.day}</b> {MONTHS[d.month-1][:3]}</a>')
        group = list(fixtures)
        groups.append(f'''<section class="matchday" id="day-{day}" aria-labelledby="title-{day}">
          <div class="day-heading"><h3 id="title-{day}"><time datetime="{day}">{day_label(day,weekday=True)}</time></h3><span>{len(group)} {'match' if len(group)==1 else 'matches'}</span></div>
          <div class="match-list">{''.join(render_match(m) for m in group)}</div>
        </section>''')
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Explore Premonition-FC’s historical Premier League replay: frozen Poisson forecasts and actual results for {escape(period)}.">
  <meta name="color-scheme" content="light">
  <title>Historical replay · {escape(period)} · Premonition-FC</title>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <a class="skip-link" href="#matches">Skip to matches</a>
  <header class="site-header wrap">
    <a class="brand" href="./" aria-label="Premonition-FC home"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Premonition<span class="brand-fc">-FC</span></a>
    <nav aria-label="Main navigation"><a href="#matches">Matches</a><a href="#guide">The guide <span aria-hidden="true">↗</span></a></nav>
  </header>
  <main>
    <section class="hero wrap" aria-labelledby="page-title">
      <div class="hero-copy">
        <div class="eyebrow"><span class="mode-label"><span aria-hidden="true"></span>Historical replay</span><span class="competition-label">Premier League · 2025/26</span></div>
        <p class="kicker">The opening slate, revisited.</p>
        <h1 id="page-title">{escape(period)}</h1>
        <p class="hero-description">Frozen Poisson forecasts from a retrospective backtest, alongside the actual full-time results.</p>
        <dl class="issue-meta"><div><dt>Simulated issue date</dt><dd><time datetime="{issue}">{day_label(issue)}</time></dd></div><div><dt>Presentation model</dt><dd>Poisson</dd></div></dl>
      </div>
      <aside class="slate-record" aria-label="Summary for this {total}-match slate">
        <div class="record-top"><span class="record-label">This {total}-match slate</span><span class="record-symbol" aria-hidden="true">↗</span></div>
        <div class="record-grid"><div><p class="record-value" data-summary="outcome">{correct}<span>/{total}</span></p><h2>Correct outcomes</h2></div><div><p class="record-value" data-summary="exact_score">{exact}<span>/{total}</span></p><h2>Exact scores</h2></div></div>
        <p class="record-note">The top-choice outcome and first-ranked exact score are scored separately.</p>
      </aside>
    </section>
    <section class="fixtures-section wrap" id="matches" tabindex="-1" aria-labelledby="matches-title">
      <div class="section-header"><div><p class="section-kicker">Matchday notebook</p><h2 id="matches-title">The matches <span>{total:02d}</span></h2></div><nav class="date-nav" aria-label="Jump to match date">{''.join(date_links)}</nav></div>
      <p class="section-description">Choose a match to see its probabilities and three most likely scorelines.</p>
      {''.join(groups)}
    </section>
    <section class="guide-section" id="guide" aria-labelledby="guide-title"><div class="guide-inner wrap">
      <div><p class="section-kicker">A little context</p><h2 id="guide-title">How to read<br>the replay.</h2></div>
      <div class="guide-copy"><h3>One scoreline. Three possible results.</h3><p>The most probable exact score is one possible score. Home-win, draw and away-win probabilities add up all scorelines for each result, so the top outcome can differ from the result implied by the top scoreline.</p><h3>A backtest with a shared date.</h3><p>Every match here uses {day_label(issue)} as its simulated issue date, with eligible earlier results as model inputs. This is a historical replay rather than a real pre-kickoff forecast record.</p><p class="rounding-note">Percentages are rounded for display. Rankings and correctness marks use the original frozen values.</p></div>
    </div></section>
  </main>
  <footer class="site-footer wrap"><div><span class="footer-brand">Premonition-FC</span><p>A study in football probabilities.</p></div><div class="data-credit"><p>Historical data from <a href="https://github.com/openfootball/football.json/tree/e6744429ee395bc86f247348c6184bb08d4eb361" rel="noreferrer">OpenFootball <span aria-hidden="true">↗</span></a></p><p>Data terms: <a href="https://creativecommons.org/publicdomain/zero/1.0/" rel="noreferrer">CC0 1.0</a> · Historical replay</p></div></footer>
</body>
</html>
'''
