"""Saved fictional forecasts reused across status-only preview snapshots."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def sample_preview():
    pairs = (("harbour-athletic", "vale-city"), ("moor-united", "rail-rovers"),
             ("orchard-town", "fen-athletic"), ("hill-city", "brook-united"),
             ("marsh-fc", "ridge-town"), ("park-united", "quay-rovers"))
    fixtures = []
    for home, away in pairs:
        fixtures.append({"fixture_id": f"2026-27:{home}:{away}",
            "home": {"id": home, "name": "Fictional "+home.replace("-", " ").title()},
            "away": {"id": away, "name": "Fictional "+away.replace("-", " ").title()},
            "issued_at_utc": "2026-11-10T12:00:00Z", "kickoff_at_utc": "2026-11-13T20:00:00Z",
            "forecast": {"probabilities": {"home_win": .5, "draw": .3, "away_win": .2},
                "scorelines": [{"home_goals": 1, "away_goals": 1, "probability": .12},
                              {"home_goals": 1, "away_goals": 0, "probability": .11},
                              {"home_goals": 2, "away_goals": 0, "probability": .09}]}})
    issued = {"schema_version": "premonition-fc.saved-preview-forecasts.v1", "mode": "fictional_preview",
              "competition": "Fictional League", "season": "2026-27",
              "presentation_model": "team_strength_poisson", "fixtures": fixtures}
    updates = [{"fixture_id": f["fixture_id"], "kickoff_at_utc": f["kickoff_at_utc"],
                "status": "scheduled", "actual_full_time": None} for f in fixtures]
    preview = {"schema_version": "premonition-fc.prospective-preview.v1", "mode": "fictional_preview",
               "label": "Fictional preview", "issued_file": "issued_forecasts.json",
               "issued_sha256": "", "updates": updates}
    return issued, preview


def later_preview(preview):
    result = deepcopy(preview)
    for row, score in zip(result["updates"], ((1, 1), (2, 0), (0, 0))):
        row.update(status="completed", actual_full_time={"home_goals": score[0], "away_goals": score[1]})
    result["updates"][0]["kickoff_at_utc"] = "2026-11-14T20:00:00Z"
    for row, status in zip(result["updates"][3:], ("postponed", "cancelled", "unresolved")):
        row["status"] = status
    result["updates"][3]["kickoff_at_utc"] = "2026-12-02T19:45:00Z"
    return result


def save_preview(folder, issued=None, preview=None, *, filename="preview.json"):
    default_issued, default_preview = sample_preview()
    issued = deepcopy(default_issued if issued is None else issued)
    preview = deepcopy(default_preview if preview is None else preview)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder/"issued_forecasts.json"
    source.write_text(json.dumps(issued, indent=2)+"\n", encoding="utf-8")
    preview["issued_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = folder/filename
    path.write_text(json.dumps(preview, indent=2)+"\n", encoding="utf-8")
    return path
