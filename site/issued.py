"""Read-only assembly of an opening display from a separately trusted issue export."""
from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path
import re
import sys

# Reuse the ledger's canonical digest and club names without loading any models.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from premonition_fc.data import CLUBS
from premonition_fc.storage import object_digest

from display import BuildError, digest, object_fields, read_json
from preview import MODEL, validate_forecast
from render import ORDER, render_match, render_time

VERSION = "premonition-fc.issued-display.v1"
MODE = "genuine_issuance"
MODELS = ("form_poisson", MODEL)
NAMES = {name.lower().replace(" & ", "-").replace(" ", "-"): name for name in CLUBS}


def utc(value):
    """Preserve the original UTC spelling and fractional-second precision."""
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise BuildError("Expected an explicit UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def trusted_issue(path, expected_sha256):
    """The pin must come from the original trusted checkpoint, outside the display input."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise BuildError("Supply the independently reviewed original record checksum")
    if digest(path) != expected_sha256:
        raise BuildError("Original issue record checksum changed")
    events = read_json(path)
    if not isinstance(events, list) or len(events) != 2:
        raise BuildError("Expected the opening freeze and issue snapshot")
    previous = "0"*64
    for sequence, event in enumerate(events, 1):
        object_fields(event, ("seq", "key", "kind", "payload", "previous_hash", "event_hash"), "issue event")
        envelope = {key: value for key, value in event.items() if key != "event_hash"}
        if type(event["seq"]) is not int or event["seq"] != sequence or event["previous_hash"] != previous or object_digest(envelope) != event["event_hash"]:
            raise BuildError("Original event hash chain failed")
        previous = event["event_hash"]
    frozen, issued = events
    freeze, issue = frozen["payload"], issued["payload"]
    if (frozen["kind"], frozen["key"], issued["kind"], issued["key"]) != (
            "freeze", "freeze", "issue", "issue:"+issue["slate_id"]):
        raise BuildError("Opening issue event identity failed")
    if freeze["mode"] != "real" or issue["mode"] != "real" or issue["frozen_event_hash"] != frozen["event_hash"]:
        raise BuildError("Expected a genuine issue bound to its original freeze")
    if object_digest(freeze["fit"]) != freeze["fit_sha256"] or issue["fit_sha256"] != freeze["fit_sha256"]:
        raise BuildError("Frozen fit identity failed")
    if object_digest(freeze["rules"]) != freeze["rules_sha256"] or freeze["rules"]["models"] != list(MODELS):
        raise BuildError("Frozen paired model identity failed")
    if not utc(freeze["frozen_at_utc"]) <= utc(issue["data_cutoff_at_utc"]) <= utc(issue["issued_at_utc"]):
        raise BuildError("Issue chronology failed")
    snapshot = issue["fixture_snapshot"]
    if snapshot["mode"] != "real" or snapshot["competition"] != "premier-league" or snapshot["slate_id"] != issue["slate_id"]:
        raise BuildError("Wrong issue-time fixture snapshot")
    # The request pins original file bytes, including whitespace. The embedded
    # snapshot is authenticated by the event chain, not by reserializing those bytes.
    if not re.fullmatch(r"[0-9a-f]{64}", str(issue["request"]["fixture_snapshot_sha256"])):
        raise BuildError("Invalid original fixture file checksum")
    if snapshot["coverage"]["complete"] is not True or snapshot["omissions"] or issue["omissions"]:
        raise BuildError("Opening snapshot must be complete with no omissions")
    if not utc(snapshot["observed_at_utc"]) <= utc(issue["data_cutoff_at_utc"]):
        raise BuildError("Schedule observation postdates issuance")
    return frozen, issued


def assemble_display(record_path, record_sha256):
    """Project only saved display fields; preserve both models in the untouched source."""
    try:
        frozen, issued = trusted_issue(record_path, record_sha256)
        issue = issued["payload"]
        snapshot = issue["fixture_snapshot"]
        fixtures = issue["fixtures"]
        expected = snapshot["expected_fixture_ids"]
        if not isinstance(fixtures, list) or len(fixtures) != 10 or len(expected) != 10 or len(set(expected)) != 10:
            raise BuildError("Expected ten unique complete opening fixtures")
        ids = [fixture["fixture_id"] for fixture in fixtures]
        if len(set(ids)) != 10 or set(ids) != set(expected):
            raise BuildError("Opening fixture census failed")
        saved = snapshot["fixtures"]
        if len(saved) != 10 or len({row["fixture_id"] for row in saved}) != 10:
            raise BuildError("Duplicate or missing source fixture")
        by_id = {row["fixture_id"]: row for row in saved}
        seasons = {fixture["season"] for fixture in fixtures}
        if len(seasons) != 1:
            raise BuildError("Opening fixtures must share one season")
        season = seasons.pop()
        if not isinstance(season, str) or not re.fullmatch(r"\d{4}-\d{2}", season) or int(season[5:]) != (int(season[:4])+1) % 100:
            raise BuildError("Invalid issued season")
        pairs = {}
        for row in issue["forecasts"]:
            identity = (row["fixture_id"], row["model"])
            if identity in pairs or identity[0] not in ids or identity[1] not in MODELS:
                raise BuildError("Duplicate or incompatible saved forecast pair")
            fixture = next(f for f in fixtures if f["fixture_id"] == row["fixture_id"])
            if any(row[key] != fixture[key] for key in ("fixture_id", "home", "away", "season", "played_date")) or row["issue_date_london"] != issue["shared_london_cutoff_date"]:
                raise BuildError("Saved forecast fixture identity failed")
            if row["probability_order"] != ["H", "D", "A"] or row["top_three_certified"] is not True or len(row["probabilities"]) != 3:
                raise BuildError("Expected original certified H/D/A forecasts")
            forecast = {"probabilities": dict(zip(ORDER, row["probabilities"])), "scorelines": row["scorelines"]}
            validate_forecast(forecast)
            pairs[identity] = forecast
        if set(pairs) != {(identity, model) for identity in ids for model in MODELS}:
            raise BuildError("Every opening fixture needs both original saved models")
        matches = []
        for fixture in fixtures:
            original = by_id[fixture["fixture_id"]]
            if any(fixture[key] != original[key] for key in original):
                raise BuildError("Issued fixture differs from the checked schedule")
            if fixture["fixture_id"] != ":".join((season, fixture["home"], fixture["away"])) or fixture["home"] == fixture["away"]:
                raise BuildError("Invalid canonical fixture identity")
            for side in ("home", "away"):
                if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fixture[side]):
                    raise BuildError("Invalid club identity")
            issued_at, kickoff, checked = (utc(value) for value in (
                issue["issued_at_utc"], fixture["kickoff_at_utc"], fixture["verified_at_utc"]))
            if not checked <= utc(snapshot["observed_at_utc"]) or not issued_at < kickoff or issued_at-checked > timedelta(hours=24):
                raise BuildError("Issue-time schedule chronology failed")
            if fixture["status"] != "scheduled":
                raise BuildError("Expected the saved pending opening snapshot")
            matches.append({"fixture_id": fixture["fixture_id"],
                **{side: {"id": fixture[side], "name": NAMES.get(fixture[side], fixture[side].replace("-", " ").title())} for side in ("home", "away")},
                "issued_at_utc": issue["issued_at_utc"], "kickoff_at_utc": fixture["kickoff_at_utc"],
                "schedule_checked_at_utc": fixture["verified_at_utc"], "status": "scheduled",
                "actual_full_time": None, "forecast": pairs[(fixture["fixture_id"], MODEL)]})
        return {"label": "Issued forecasts", "competition": "Premier League", "season": season,
            "slate_id": issue["slate_id"], "presentation_model": MODEL, "issued_at_utc": issue["issued_at_utc"],
            "schedule_observed_at_utc": snapshot["observed_at_utc"], "snapshot_as_of_utc": issue["issued_at_utc"],
            "source": {"record_sha256": record_sha256, "issue_event_hash": issued["event_hash"],
                       "frozen_event_hash": frozen["event_hash"], "fit_sha256": issue["fit_sha256"]},
            "matches": sorted(matches, key=lambda m: (m["kickoff_at_utc"], m["fixture_id"]))}
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, BuildError):
            raise
        raise BuildError("Malformed original opening issue record") from exc


def display_input(record_path, record_sha256):
    data = assemble_display(record_path, record_sha256)
    return {"schema_version": VERSION, "mode": MODE, "display_sha256": object_digest(data), "display": data}


def verified_issued(path, record_path, record_sha256, *, results_path=None):
    if record_path is None:
        raise BuildError("Genuine issuance requires the separately pinned original record")
    source = read_json(path)
    object_fields(source, ("schema_version", "mode", "display_sha256", "display"), "issued display input")
    if source["schema_version"] != VERSION or source["mode"] != MODE:
        raise BuildError("Expected a genuine issuance display contract")
    data = source["display"]
    if object_digest(data) != source["display_sha256"]:
        raise BuildError("Display input checksum changed")
    expected = assemble_display(record_path, record_sha256)
    object_fields(data, expected.keys(), "issued display")
    if not isinstance(data["matches"], list) or len(data["matches"]) != 10:
        raise BuildError("Expected all ten displayed fixtures")
    for match in data["matches"]:
        object_fields(match, expected["matches"][0].keys(), "displayed fixture")
        validate_forecast(match["forecast"])
    if data != expected:
        raise BuildError("Display differs from the original issue record")
    # No provenance envelopes, paths, paired alternative or fitted parameters reach rendering.
    display = {key: value for key, value in data.items() if key != "source"} | {
        "matches": [{**match, "marks": None} for match in data["matches"]]}
    if results_path is not None:
        from results import apply_results
        display = apply_results(display, results_path, data["source"]["issue_event_hash"])
    return display


def render_issued(data):
    cards = "".join(render_match(match, issued=True) for match in data["matches"])
    updated = data.get("results_updated", False)
    result_description = ("Results reflect a separately reviewed factual snapshot. Unresolved results have no final score or correctness marks. "
                          if updated else "All ten results remain pending in this saved snapshot. ")
    result_guide = ("Final scores and played dates come from separately reviewed official facts. Outcome and exact-score marks use the original forecast. Unresolved facts have no final score or marks."
                    if updated else "Viewing a prediction opens saved content. It makes no request and runs no model. Pending fixtures have no full-time score or correctness marks.")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Original opening forecasts saved before kickoff, shown from a saved snapshot.">
<title>Issued forecasts · Premonition-FC</title><link rel="icon" type="image/svg+xml" href="favicon.svg"><link rel="stylesheet" href="styles.css"></head>
<body class="prospective-preview issued-display"><a class="skip-link" href="#matches">Skip to matches</a>
<header class="site-header wrap"><a class="brand" href="./">Premonition<span class="brand-fc">-FC</span></a><nav aria-label="Main navigation"><a href="#matches">Opening slate</a><a href="#guide">The guide</a></nav></header>
<main><section class="hero wrap" aria-labelledby="page-title"><div class="hero-copy">
<div class="eyebrow"><span class="mode-label">Issued forecasts</span><span class="competition-label">{escape(data['competition'])} · {escape(data['season'])}</span></div>
<p class="kicker">Saved before kickoff.</p><h1 id="page-title">The opening ten.</h1>
<p class="hero-description">The original team-strength Poisson forecasts for all ten opening fixtures. Open a fixture to see its saved probabilities and three most likely scorelines.</p>
<p class="preview-model">Team-strength Poisson</p><p>Originally issued {render_time(data['issued_at_utc'])}.</p></div>
<aside class="preview-note"><h2>A saved snapshot.</h2><p>Scores and statuses reflect the saved snapshot as of {render_time(data['snapshot_as_of_utc'])}. This page is not a live score feed.</p>
<p>Schedule checked at issuance. Source observation: {render_time(data['schedule_observed_at_utc'])}. These scheduled kickoffs have not been rechecked for this page.</p></aside></section>
<section class="fixtures-section wrap" id="matches" tabindex="-1" aria-labelledby="matches-title"><div class="section-header"><h2 id="matches-title">Opening slate</h2></div>
<p class="section-description">{result_description}Choose View prediction to expand a forecast. Every timestamp is shown in UTC.</p>
<section class="matchday" aria-labelledby="opening-title"><h3 id="opening-title" class="section-kicker">Original issued fixtures</h3><div class="match-list">{cards}</div></section></section>
<section class="guide-section" id="guide" aria-labelledby="guide-title"><div class="guide-inner wrap"><h2 id="guide-title">Read the saved forecast.</h2><div class="guide-copy">
<h3>The original prediction stays.</h3><p>{result_guide}</p>
<h3>Three outcomes, three scorelines.</h3><p>Home win, draw and away win cover all possible scores. The three ranked scorelines show the most likely exact scores from the original forecast.</p>
<p class="rounding-note">Percentages are rounded for display. Rankings use the original unrounded values.</p></div></div></section></main>
<footer class="site-footer wrap"><div><span class="footer-brand">Premonition-FC</span><p>Issued forecasts · Private review snapshot.</p></div><div class="data-credit"><p>Fixture data: <a href="https://highlightly.net/football" rel="noreferrer">Highlightly</a></p><p>Schedule checked against official league and club sources at issuance.</p></div></footer></body></html>
'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--record-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if output.exists() or any((parent/".git").exists() for parent in (output.parent, *output.parents)):
            raise BuildError("Use a fresh display input outside Git worktrees")
        data = display_input(args.record, args.record_sha256)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    except (BuildError, KeyError, TypeError, ValueError, OSError) as exc:
        raise SystemExit(f"Display assembly failed: {exc}") from exc
    print("Assembled ten original selected forecasts for private display.")


if __name__ == "__main__":
    main()
