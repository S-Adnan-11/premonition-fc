"""Fictional saved forecasts joined to status updates; no model or ledger access."""
from datetime import date, datetime
from html import escape
import math
from pathlib import Path
import re

from display import BuildError, digest, object_fields, read_json
from render import ORDER, render_match

VERSION = "premonition-fc.prospective-preview.v1"
ISSUED_VERSION = "premonition-fc.saved-preview-forecasts.v1"
MODEL = "team_strength_poisson"
STATUSES = ("scheduled", "postponed", "cancelled", "completed", "unresolved")


def utc_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise BuildError("Expected a UTC timestamp with seconds and explicit Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BuildError("Invalid UTC timestamp") from exc


def validate_forecast(forecast):
    object_fields(forecast, ("probabilities", "scorelines"), "saved forecast")
    probabilities = forecast["probabilities"]
    object_fields(probabilities, ORDER, "outcome probabilities")
    def probability(value):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
    if not all(probability(p) for p in probabilities.values()) or abs(sum(probabilities.values())-1) > 2e-12:
        raise BuildError("Outcome probabilities must be finite and sum to one")
    scores = forecast["scorelines"]
    if not isinstance(scores, list) or len(scores) != 3:
        raise BuildError("Expected three saved ranked scorelines")
    masses = dict.fromkeys(ORDER, 0)
    for score in scores:
        object_fields(score, ("home_goals", "away_goals", "probability"), "scoreline")
        validate_score({key: score[key] for key in ("home_goals", "away_goals")})
        if not probability(score["probability"]):
            raise BuildError("Invalid scoreline probability")
        masses[score_outcome(score)] += score["probability"]
    if len({(s["home_goals"], s["away_goals"]) for s in scores}) != 3 or scores != sorted(
            scores, key=lambda s: (-s["probability"], s["home_goals"], s["away_goals"])):
        raise BuildError("Scoreline ranking is inconsistent")
    if any(masses[key] > probabilities[key]+2e-12 for key in ORDER):
        raise BuildError("Ranked scoreline mass exceeds its outcome probability")


def validate_score(score):
    object_fields(score, ("home_goals", "away_goals"), "full-time score")
    if any(type(value) is not int or value < 0 for value in score.values()):
        raise BuildError("Invalid full-time goals")


def score_outcome(score):
    home, away = score["home_goals"], score["away_goals"]
    return "home_win" if home > away else "draw" if home == away else "away_win"


def marks_for(forecast, actual):
    chosen = max(ORDER, key=lambda key: forecast["probabilities"][key])
    top = forecast["scorelines"][0]
    return {"outcome": "correct" if chosen == score_outcome(actual) else "incorrect",
            "exact_score": "correct" if all(top[key] == actual[key] for key in actual) else "incorrect"}


def verified_preview(path):
    path = Path(path).resolve()
    data = read_json(path)
    object_fields(data, ("schema_version", "mode", "label", "issued_file", "issued_sha256", "updates"), "preview")
    if data["schema_version"] != VERSION or data["mode"] != "fictional_preview" or data["label"] != "Fictional preview":
        raise BuildError("Expected a fictional preview contract")
    # One adjoining file, no directory traversal or absolute source paths.
    if data["issued_file"] != "issued_forecasts.json":
        raise BuildError("Expected the adjoining saved forecast file")
    issued_path = path.with_name(data["issued_file"])
    if not issued_path.resolve().is_relative_to(path.parent):
        raise BuildError("Saved forecasts must stay within the preview bundle")
    if not isinstance(data["issued_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["issued_sha256"]):
        raise BuildError("Invalid saved forecast checksum")
    try:
        if digest(issued_path) != data["issued_sha256"]:
            raise BuildError("Saved forecast checksum changed")
    except OSError as exc:
        raise BuildError("Missing saved forecast file") from exc
    issued = read_json(issued_path)
    object_fields(issued, ("schema_version", "mode", "competition", "season", "presentation_model", "fixtures"), "saved issue")
    if issued["schema_version"] != ISSUED_VERSION or issued["mode"] != "fictional_preview":
        raise BuildError("Only fictional saved forecasts are supported")
    if issued["presentation_model"] != MODEL or issued["competition"] != "Fictional League":
        raise BuildError("Expected the fictional team-strength Poisson preview")
    season = issued["season"]
    if not isinstance(season, str) or not re.fullmatch(r"\d{4}-\d{2}", season) or int(season[5:]) != (int(season[:4])+1) % 100:
        raise BuildError("Invalid preview season")
    year = int(season[:4])
    def kickoff(value):
        result = utc_time(value)
        if not date(year, 7, 1) <= result.date() <= date(year+1, 6, 30):
            raise BuildError("Kickoff is outside the season")
        return result
    fixtures = issued["fixtures"]
    if not isinstance(fixtures, list) or not fixtures:
        raise BuildError("No saved fixtures")
    saved = {}
    for fixture in fixtures:
        object_fields(fixture, ("fixture_id", "home", "away", "issued_at_utc", "kickoff_at_utc", "forecast"), "saved fixture")
        for side in ("home", "away"):
            team = fixture[side]
            object_fields(team, ("id", "name"), "fictional team")
            if not isinstance(team["id"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", team["id"]):
                raise BuildError("Invalid club identity")
            if not isinstance(team["name"], str) or not team["name"].startswith("Fictional ") or not team["name"][10:].strip():
                raise BuildError("Team names must explicitly identify fictional examples")
        identity = ":".join((season, fixture["home"]["id"], fixture["away"]["id"]))
        if fixture["home"]["id"] == fixture["away"]["id"] or fixture["fixture_id"] != identity or identity in saved:
            raise BuildError("Duplicate or incompatible saved fixture identity")
        if utc_time(fixture["issued_at_utc"]) >= kickoff(fixture["kickoff_at_utc"]):
            raise BuildError("Saved issue must precede original kickoff")
        validate_forecast(fixture["forecast"])
        saved[identity] = fixture
    updates = data["updates"]
    if not isinstance(updates, list):
        raise BuildError("Updates must be an array")
    matches, seen = [], set()
    for update in updates:
        object_fields(update, ("fixture_id", "kickoff_at_utc", "status", "actual_full_time"), "fixture update")
        identity = update["fixture_id"]
        if not isinstance(identity, str) or identity not in saved or identity in seen:
            raise BuildError("Duplicate or unknown updated fixture identity")
        seen.add(identity)
        original = saved[identity]
        if kickoff(update["kickoff_at_utc"]) <= utc_time(original["issued_at_utc"]):
            raise BuildError("Updated kickoff cannot precede the saved issue")
        status, actual = update["status"], update["actual_full_time"]
        if status not in STATUSES:
            raise BuildError("Unsupported preview status")
        if status == "completed":
            validate_score(actual)
            marks = marks_for(original["forecast"], actual)
        else:
            if actual is not None:
                raise BuildError("Unfinished, unresolved or cancelled fixtures cannot have a score")
            marks = None
        matches.append({**original, "original_kickoff_at_utc": original["kickoff_at_utc"],
                        **update, "marks": marks})
    if seen != set(saved):
        raise BuildError("Updates must cover every saved fixture exactly once")
    # Only these display fields leave validation. Hashes, file paths and envelopes stay private.
    return {"competition": issued["competition"], "matches": matches}


def render_preview(data):
    cards = []
    for match in sorted(data["matches"], key=lambda m: (m["kickoff_at_utc"], m["fixture_id"])):
        cards.append(render_match(match, preview=True))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Fictional saved match forecasts and results for private preview.">
<title>Fictional preview · Premonition-FC</title><link rel="icon" type="image/svg+xml" href="favicon.svg"><link rel="stylesheet" href="styles.css"></head>
<body class="prospective-preview"><a class="skip-link" href="#matches">Skip to matches</a>
<header class="site-header wrap"><a class="brand" href="./">Premonition<span class="brand-fc">-FC</span></a><nav aria-label="Main navigation"><a href="#matches">Matches</a><a href="#guide">The guide</a></nav></header>
<main><section class="hero wrap" aria-labelledby="page-title"><div class="hero-copy">
<div class="eyebrow"><span class="mode-label">Fictional preview</span><span class="competition-label">{escape(data['competition'])}</span></div>
<p class="kicker">Saved before kickoff.</p><h1 id="page-title">The prediction stays.</h1>
<p class="hero-description">Open a saved forecast, then see it beside the confirmed full-time result. All teams, fixtures, predictions and results here are fictional examples.</p>
<p class="preview-model">Team-strength Poisson</p></div>
<aside class="preview-note"><h2>A match can move.</h2><p>Its original prediction and issue time stay with the fixture. Pending results have no correctness marks. Cancellations are void.</p></aside></section>
<section class="fixtures-section wrap" id="matches" tabindex="-1" aria-labelledby="matches-title"><div class="section-header"><h2 id="matches-title">Saved fixtures</h2></div>
<p class="section-description">Choose View prediction to see the three outcome probabilities and ranked scorelines. Every timestamp is shown in UTC.</p>
<section class="matchday" aria-labelledby="examples-title"><h3 id="examples-title" class="section-kicker">Fictional match notebook</h3><div class="match-list">{''.join(cards)}</div></section></section>
<section class="guide-section" id="guide" aria-labelledby="guide-title"><div class="guide-inner wrap"><h2 id="guide-title">Read the saved forecast.</h2><div class="guide-copy">
<h3>Two separate marks.</h3><p>The highest original outcome probability chooses home win, draw or away win. The first ranked scoreline chooses the exact score. A correct outcome can have an incorrect exact score, and a correct exact score can have an incorrect outcome.</p>
<h3>Open it any time.</h3><p>Viewing the prediction opens saved content. It makes no request and runs no model. Rescheduling keeps the original forecast and fixture link. Scheduled, postponed and unresolved results stay pending; cancelled fixtures are void.</p>
<p class="rounding-note">Percentages are rounded for display. Rankings and marks use the original values. Outcome ties use home win, then draw, then away win.</p></div></div></section></main>
<footer class="site-footer wrap"><div><span class="footer-brand">Premonition-FC</span><p>Fictional preview · No real trial results.</p></div></footer></body></html>
'''
