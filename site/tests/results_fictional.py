"""Fictional official-review records; never fetch or write a live trial."""
from copy import deepcopy
from pathlib import Path

from display import digest, read_json
from issued_fictional import save_issued, write_json
from premonition_fc.storage import object_digest
from results import REVIEW_VERSION, VERSION


def save_results(folder):
    folder = Path(folder)
    source, record, pin = save_issued(folder)
    data = read_json(source)["display"]
    body = folder/"fictional-official.txt"
    body.write_text("Fictional official match records for offline tests only.\n", encoding="utf-8")
    document = {"id": "fictional-league", "source_url": "https://www.premierleague.com/fictional-offline-test",
                "authority": "official_league", "observed_at_utc": "2026-11-24T10:00:00Z", "sha256": digest(body),
                "relative_path": body.name, "http_status": 200, "transport": "direct_public_get",
                "precision": "date", "semantics": "Fictional regulation-time status/score and actual London played date."}
    rows = [{"fixture_id": m["fixture_id"], "status": "scheduled", "actual_full_time": None,
             "played_date_london": None, "kickoff_at_utc": None, "evidence_document_ids": [document["id"]],
             "verified_at_utc": "2026-11-24T10:01:00Z", "precision": "observation_only",
             "semantics": "Fictional reviewed status; observation time is not a whistle instant.", "gaps": [], "correction": None}
            for m in data["matches"]]
    for row, score in zip(rows, ((0, 0), (1, 1), (1, 0))):
        row.update(status="completed", actual_full_time={"home_goals": score[0], "away_goals": score[1]},
                   played_date_london="2026-11-21", precision="date")
    rows[3].update(status="postponed", kickoff_at_utc="2026-11-30T15:00:00Z")
    rows[4].update(status="cancelled")
    rows[5].update(status="unresolved", gaps=["Fictional contradictory source status; no final fact accepted."])
    review = {"schema_version": REVIEW_VERSION, "mode": "real", "snapshot_as_of_utc": "2026-11-24T10:03:00Z",
              "reviewed_at_utc": "2026-11-24T10:02:00Z", "reviewer": "Fictional offline reviewer",
              "original_issue_event_hash": data["source"]["issue_event_hash"],
              "expected_fixture_ids": [m["fixture_id"] for m in data["matches"]], "previous_review_sha256": None,
              "documents": [document], "results": rows}
    reviewed = folder/"reviewed_facts.json"; write_json(reviewed, review)
    manifest = {"schema_version": VERSION, "mode": "verified_results", "original_issue_event_hash": review["original_issue_event_hash"],
                "reviews": [{"file": reviewed.name, "sha256": digest(reviewed)}]}
    path = folder/"results.json"; write_json(path, manifest)
    return source, record, pin, path


def change_review(path, change):
    manifest = read_json(path)
    review_path = path.parent/manifest["reviews"][-1]["file"]
    review = read_json(review_path); change(review); write_json(review_path, review)
    manifest["reviews"][-1]["sha256"] = digest(review_path); write_json(path, manifest)


def append_correction(path, *, attribute=True):
    manifest = read_json(path); old = read_json(path.parent/manifest["reviews"][-1]["file"])
    new = deepcopy(old); new["previous_review_sha256"] = manifest["reviews"][-1]["sha256"]
    new.update(snapshot_as_of_utc="2026-11-25T12:03:00Z", reviewed_at_utc="2026-11-25T12:02:00Z")
    row = new["results"][0]; row["actual_full_time"] = {"home_goals": 1, "away_goals": 0}
    row["verified_at_utc"] = "2026-11-25T12:01:00Z"
    if attribute:
        row["correction"] = {"previous_result_sha256": object_digest(old["results"][0]), "reason": "Fictional official score correction."}
    filename = "corrected_facts.json"; write_json(path.parent/filename, new)
    manifest["reviews"].append({"file": filename, "sha256": digest(path.parent/filename)}); write_json(path, manifest)
