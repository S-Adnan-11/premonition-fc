"""Fictional events in the genuine issuance format, independent of preview contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from issued import MODELS, display_input
from display import digest
from premonition_fc.storage import object_digest


def chain(payloads):
    events = []
    for kind, payload in zip(("freeze", "issue"), payloads):
        event = {"seq": len(events)+1, "key": "freeze" if kind == "freeze" else "issue:"+payload["slate_id"],
                 "kind": kind, "payload": payload, "previous_hash": events[-1]["event_hash"] if events else "0"*64}
        event["event_hash"] = object_digest(event)
        events.append(event)
    return events


def sample_events():
    fixtures, forecasts = [], []
    letters = "abcdefghij"
    for letter in letters:
        home, away = "fictional-home-"+letter, "fictional-away-"+letter
        fixture = {"fixture_id": f"2026-27:{home}:{away}", "home": home, "away": away,
                   "season": "2026-27", "kickoff_at_utc": "2026-11-21T15:00:00+00:00",
                   "verified_at_utc": "2026-11-14T10:20:05.123456+00:00", "status": "scheduled"}
        fixtures.append({**fixture, "played_date": "2026-11-21"})
        for model in MODELS:
            forecasts.append({key: fixtures[-1][key] for key in ("fixture_id", "home", "away", "season", "played_date")} | {
                "model": model, "issue_date_london": "2026-11-14", "probability_order": ["H", "D", "A"],
                "probabilities": [.500004, .299997, .199999] if model == MODELS[1] else [.4, .35, .25],
                "top_three_certified": True, "home_mean": 1.25, "private_sentinel": "paired-internals",
                "scorelines": [{"home_goals": 1, "away_goals": 1, "probability": .120004},
                              {"home_goals": 1, "away_goals": 0, "probability": .109997},
                              {"home_goals": 2, "away_goals": 0, "probability": .090001}]})
    rules = {"models": list(MODELS)}
    fit = {"form": {"private_sentinel": "form-fit-parameters"}, "strength": {"private_sentinel": "strength-fit-parameters"}}
    freeze = {"mode": "real", "fit": fit, "fit_sha256": object_digest(fit), "rules": rules,
              "rules_sha256": object_digest(rules), "frozen_at_utc": "2026-11-14T10:20:45.234567+00:00"}
    snapshot = {"mode": "real", "competition": "premier-league", "slate_id": "2026-27:2026-11-17",
                "observed_at_utc": "2026-11-14T10:20:05.123456+00:00", "coverage": {"complete": True},
                "expected_fixture_ids": [f["fixture_id"] for f in fixtures], "omissions": [],
                "fixtures": [{k: v for k, v in f.items() if k != "played_date"} for f in fixtures]}
    issue = {"mode": "real", "slate_id": snapshot["slate_id"], "fit_sha256": freeze["fit_sha256"],
             "frozen_event_hash": chain([freeze])[0]["event_hash"], "fixture_snapshot": snapshot,
             "request": {"fixture_snapshot_sha256": hashlib.sha256((json.dumps(snapshot, indent=2)+"\n").encode()).hexdigest()}, "omissions": [],
             "fixtures": fixtures, "forecasts": forecasts, "shared_london_cutoff_date": "2026-11-14",
             "data_cutoff_at_utc": "2026-11-14T10:20:48.456789+00:00",
             "issued_at_utc": "2026-11-14T10:20:48.765432+00:00"}
    return chain([freeze, issue])


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")


def save_issued(folder, events=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    record = folder/"events.json"
    write_json(record, deepcopy(sample_events() if events is None else events))
    pin = digest(record)
    path = folder/"issued_display.json"
    write_json(path, display_input(record, pin))
    return path, record, pin
