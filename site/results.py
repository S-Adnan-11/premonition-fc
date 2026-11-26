"""Reviewed factual snapshots for display only; no trial ledger or model access."""
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from display import BuildError, digest, object_fields, read_json
from issued import utc
from premonition_fc.storage import object_digest
from preview import marks_for, validate_score

VERSION = "premonition-fc.result-snapshots.v1"
REVIEW_VERSION = "premonition-fc.reviewed-results.v1"
STATUSES = ("scheduled", "postponed", "cancelled", "completed", "unresolved")
CLUB_DOMAINS = {
    "arsenal": ("arsenal.com",), "aston-villa": ("avfc.co.uk",), "bournemouth": ("afcb.co.uk",),
    "brentford": ("brentfordfc.com",), "brighton-hove-albion": ("brightonandhovealbion.com",),
    "chelsea": ("chelseafc.com",), "coventry-city": ("ccfc.co.uk",), "crystal-palace": ("cpfc.co.uk",),
    "everton": ("evertonfc.com",), "fulham": ("fulhamfc.com",), "hull-city": ("wearehullcity.co.uk",),
    "ipswich-town": ("itfc.co.uk",), "leeds-united": ("leedsunited.com",), "liverpool": ("liverpoolfc.com",),
    "manchester-city": ("mancity.com",), "manchester-united": ("manutd.com",),
    "newcastle-united": ("newcastleunited.com", "nufc.co.uk"), "nottingham-forest": ("nottinghamforest.co.uk",),
    "sunderland": ("safc.com",), "tottenham-hotspur": ("tottenhamhotspur.com",),
}


def local_file(root, relative):
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative):
        raise BuildError("Evidence must name a relative file in its bundle")
    if PurePosixPath(relative).is_absolute() or any(part in ("", ".", "..") for part in relative.split("/")):
        raise BuildError("Evidence path escapes its bundle")
    path = (root/relative).resolve()
    if not path.is_relative_to(root):
        raise BuildError("Evidence path escapes its bundle")
    return path


def pinned_file(root, relative, pin):
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise BuildError("Invalid factual evidence checksum")
    path = local_file(root, relative)
    if digest(path) != pin:
        raise BuildError("Reviewed factual evidence checksum changed")
    return path


def official_domain(document):
    url = urlsplit(document["source_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.port:
        raise BuildError("Expected an official HTTPS source URL")
    host = url.hostname.removeprefix("www.")
    allowed = ("premierleague.com",) if document["authority"] == "official_league" else tuple(
        domain for domains in CLUB_DOMAINS.values() for domain in domains) if document["authority"] == "official_club" else ()
    if host not in allowed:
        raise BuildError("Source URL does not match an allowed official authority")
    return host


def reviewed_results(path, original):
    """Validate a complete chain of independently reviewed, hashed source documents."""
    path = Path(path).resolve()
    manifest = read_json(path)
    object_fields(manifest, ("schema_version", "mode", "original_issue_event_hash", "reviews"), "result snapshots")
    if manifest["schema_version"] != VERSION or manifest["mode"] != "verified_results":
        raise BuildError("Expected an explicit reviewed result snapshot")
    issue_hash = original["issue_event_hash"]
    if manifest["original_issue_event_hash"] != issue_hash:
        raise BuildError("Results belong to a different original issue")
    if not isinstance(manifest["reviews"], list) or not manifest["reviews"]:
        raise BuildError("A result snapshot needs reviewed factual evidence")
    fixtures = {match["fixture_id"]: match for match in original["matches"]}
    previous_pin, previous, last_asof = None, {}, utc(original["issued_at_utc"])
    seen = set()
    for entry in manifest["reviews"]:
        object_fields(entry, ("file", "sha256"), "review reference")
        review_path = pinned_file(path.parent, entry["file"], entry["sha256"])
        if entry["sha256"] in seen:
            raise BuildError("Duplicate reviewed snapshot")
        seen.add(entry["sha256"])
        review = read_json(review_path)
        object_fields(review, ("schema_version", "mode", "snapshot_as_of_utc", "reviewed_at_utc", "reviewer",
            "original_issue_event_hash", "expected_fixture_ids", "previous_review_sha256", "documents", "results"), "factual review")
        if review["schema_version"] != REVIEW_VERSION or review["mode"] != "real" or review["original_issue_event_hash"] != issue_hash:
            raise BuildError("Wrong factual review mode or original issue identity")
        if review["previous_review_sha256"] != previous_pin:
            raise BuildError("Factual correction history is incomplete or reordered")
        asof, reviewed = utc(review["snapshot_as_of_utc"]), utc(review["reviewed_at_utc"])
        if not last_asof <= reviewed <= asof <= datetime.now(timezone.utc):
            raise BuildError("Factual observation/review chronology failed")
        if not isinstance(review["reviewer"], str) or not review["reviewer"].strip():
            raise BuildError("A factual review must identify its reviewer")
        expected = review["expected_fixture_ids"]
        if not isinstance(expected, list) or len(expected) != len(fixtures) or len(set(expected)) != len(expected) or set(expected) != set(fixtures):
            raise BuildError("Factual review must identify the complete original fixture census")
        if not isinstance(review["documents"], list):
            raise BuildError("Factual source documents must be an array")
        documents = {}
        for document in review["documents"]:
            object_fields(document, ("id", "source_url", "authority", "observed_at_utc", "sha256", "relative_path", "http_status", "transport", "precision", "semantics"), "official document")
            if not isinstance(document["id"], str) or not document["id"] or document["id"] in documents:
                raise BuildError("Duplicate or invalid official document identity")
            host = official_domain(document)
            if not utc(original["issued_at_utc"]) <= utc(document["observed_at_utc"]) <= reviewed:
                raise BuildError("Official observation is outside the review window")
            if any(not isinstance(document[key], str) or not document[key].strip() for key in ("precision", "semantics")):
                raise BuildError("Official fields need their original precision and semantics")
            if document["relative_path"] is not None:
                pinned_file(review_path.parent, document["relative_path"], document["sha256"])
            elif document["sha256"] is not None or document["http_status"] == 200:
                raise BuildError("Successful official evidence needs a preserved source document")
            if document["transport"] not in ("direct_public_get", "indexed_official_text"):
                raise BuildError("Unknown official source observation transport")
            if document["http_status"] is not None and (type(document["http_status"]) is not int or not 100 <= document["http_status"] <= 599):
                raise BuildError("Invalid official source response status")
            if document["transport"] == "indexed_official_text" and document["http_status"] is not None:
                raise BuildError("Indexed official text has no observed origin HTTP status")
            documents[document["id"]] = (document, host)
        rows = review["results"]
        if not isinstance(rows, list) or len(rows) != len(fixtures):
            raise BuildError("Results must cover all original fixtures exactly once")
        current = {}
        for row in rows:
            object_fields(row, ("fixture_id", "status", "actual_full_time", "played_date_london", "kickoff_at_utc",
                "evidence_document_ids", "verified_at_utc", "precision", "semantics", "gaps", "correction"), "reviewed result")
            identity = row["fixture_id"]
            if not isinstance(identity, str) or identity not in fixtures or identity in current:
                raise BuildError("Duplicate or unknown factual fixture identity")
            if row["status"] not in STATUSES:
                raise BuildError("Exceptional and unknown dispositions must remain unresolved")
            checked = utc(row["verified_at_utc"])
            if not utc(original["issued_at_utc"]) <= checked <= reviewed:
                raise BuildError("Factual verification time is outside its review")
            refs = row["evidence_document_ids"]
            if not isinstance(refs, list) or len(set(refs)) != len(refs) or any(ref not in documents for ref in refs):
                raise BuildError("Unknown or duplicate factual source reference")
            for ref in refs:
                doc, host = documents[ref]
                if utc(doc["observed_at_utc"]) > checked:
                    raise BuildError("Verification precedes source observation")
                clubs = (fixtures[identity]["home"]["id"], fixtures[identity]["away"]["id"])
                if doc["authority"] == "official_club" and host not in tuple(d for club in clubs for d in CLUB_DOMAINS.get(club, ())):
                    raise BuildError("Official club evidence belongs to a different fixture")
            if not isinstance(row["gaps"], list) or any(not isinstance(gap, str) or not gap.strip() for gap in row["gaps"]):
                raise BuildError("Factual gaps must be explicit text entries")
            if any(not isinstance(row[key], str) or not row[key].strip() for key in ("precision", "semantics")):
                raise BuildError("Factual fields require precision and semantics")
            def substantiated(ref):
                doc = documents[ref][0]
                return doc["relative_path"] is not None and (doc["http_status"] == 200 or doc["transport"] == "indexed_official_text")
            if row["status"] != "unresolved" and (not refs or row["gaps"] or not all(substantiated(ref) for ref in refs)):
                raise BuildError("Unverified or contradictory facts must remain unresolved")
            if row["status"] == "unresolved" and not row["gaps"]:
                raise BuildError("An unresolved result must identify its verification gap")
            if row["status"] == "completed":
                validate_score(row["actual_full_time"])
                played = date.fromisoformat(row["played_date_london"])
                season = original["season"]
                if played.isoformat() != row["played_date_london"] or row["precision"] != "date" or not date(int(season[:4]), 7, 1) <= played <= min(date(int(season[:4])+1, 6, 30), checked.astimezone(ZoneInfo("Europe/London")).date()):
                    raise BuildError("A final score requires a verified actual London played date")
            elif row["actual_full_time"] is not None or row["played_date_london"] is not None:
                raise BuildError("Unfinished, unresolved or void fixtures cannot have final scores or played dates")
            if row["kickoff_at_utc"] is not None and (not refs or not utc(original["issued_at_utc"]) < utc(row["kickoff_at_utc"]) or not all(substantiated(ref) for ref in refs)):
                raise BuildError("A reviewed scheduled kickoff requires qualified official evidence")
            old = previous.get(identity)
            if old and checked < utc(old["verified_at_utc"]):
                raise BuildError("Factual verification time cannot move backward")
            correction = row["correction"]
            changed_terminal = old and old["status"] in ("completed", "cancelled") and any(
                row[key] != old[key] for key in ("status", "actual_full_time", "played_date_london"))
            if correction is not None:
                object_fields(correction, ("previous_result_sha256", "reason"), "result correction")
                if old is None or correction["previous_result_sha256"] != object_digest(old) or not isinstance(correction["reason"], str) or not correction["reason"].strip():
                    raise BuildError("Correction must identify its prior factual record and reason")
            elif changed_terminal:
                raise BuildError("Changed terminal facts require an attributable correction")
            current[identity] = row
        previous_pin, previous, last_asof = entry["sha256"], current, asof
    return review, previous


def apply_results(data, path, issue_event_hash):
    try:
        review, results = reviewed_results(path, {**data, "issue_event_hash": issue_event_hash})
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, BuildError):
            raise
        raise BuildError("Malformed reviewed result evidence") from exc
    matches = []
    for original in data["matches"]:
        result = results[original["fixture_id"]]
        actual = result["actual_full_time"]
        matches.append({**original, "status": result["status"], "actual_full_time": actual,
            "marks": marks_for(original["forecast"], actual) if actual is not None else None,
            "result_reviewed_at_utc": result["verified_at_utc"], "played_date_london": result["played_date_london"],
            "reviewed_kickoff_at_utc": result["kickoff_at_utc"]})
    return {**data, "matches": matches, "snapshot_as_of_utc": review["snapshot_as_of_utc"], "results_updated": True}
