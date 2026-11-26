"""Build a static historical replay, fictional preview or genuine issued snapshot."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import math
from pathlib import Path, PurePosixPath
import re

from render import SOURCE_REVISION, render_archive, render_page, slate_filename
from display import BuildError, digest, object_fields, read_json
from preview import render_preview, verified_preview
from issued import render_issued, verified_issued

ROOT = Path(__file__).resolve().parent
VERSION = "premonition-fc.historical-match-view.v1"
ARCHIVE_VERSION = "premonition-fc.historical-archive.v1"
SOURCE_FILES = ("forecasts/predictions.json", "forecasts/forecast_manifest.json",
                "evaluation/scored_holdout.json", "evaluation/metrics.json",
                "frozen/freeze.json", "frozen/models.joblib", "prepared/holdout_features.json")
ORDER = ("home_win", "draw", "away_win")


def check_schema(value,schema,path="input"):
    """Validate the small JSON Schema vocabulary used by this versioned contract."""
    known = {"$schema","$id","title","type","additionalProperties","properties","required","const","enum",
             "items","minItems","maxItems","minimum","maximum","minLength","format"}
    if not isinstance(schema,dict) or set(schema)-known:
        raise BuildError("Unsupported display schema")
    tests = {"object":lambda x:isinstance(x,dict),"array":lambda x:isinstance(x,list),
        "string":lambda x:isinstance(x,str),"number":lambda x:type(x) in (int,float) and math.isfinite(x),
        "integer":lambda x:type(x) is int,"null":lambda x:x is None}
    expected = schema.get("type")
    expected = expected if isinstance(expected,list) else [expected]
    if not expected or any(t not in tests for t in expected) or not any(tests[t](value) for t in expected):
        raise BuildError(f"{path}: invalid value type")
    if "const" in schema and value!=schema["const"]:
        raise BuildError(f"{path}: unexpected value")
    if "enum" in schema and value not in schema["enum"]:
        raise BuildError(f"{path}: unsupported state")
    if value is None:
        return
    if isinstance(value,dict):
        props = schema.get("properties",{})
        if set(schema.get("required",[]))-value.keys() or (schema.get("additionalProperties") is False and set(value)-props.keys()):
            raise BuildError(f"{path}: missing or unexpected fields")
        for key,item in value.items():
            if key not in props:
                raise BuildError(f"{path}: unapproved field")
            check_schema(item,props[key],path+"."+key)
    elif isinstance(value,list):
        if len(value)<schema.get("minItems",0) or len(value)>schema.get("maxItems",len(value)):
            raise BuildError(f"{path}: invalid entry count")
        for i,item in enumerate(value):
            check_schema(item,schema["items"],f"{path}[{i}]")
    elif type(value) in (float,int):
        if value<schema.get("minimum",value) or value>schema.get("maximum",value):
            raise BuildError(f"{path}: number out of range")
    elif isinstance(value,str):
        if len(value)<schema.get("minLength",0):
            raise BuildError(f"{path}: empty value")
        if schema.get("format")=="date":
            try:
                if date.fromisoformat(value).isoformat()!=value:
                    raise ValueError()
            except ValueError as exc:
                raise BuildError(f"{path}: expected an ISO calendar date") from exc


def expected_marks(match):
    actual = match["actual_full_time"]
    if match["status"]!="completed" or actual is None:
        raise BuildError("Only completed historical fixtures can enter this replay")
    object_fields(actual,("home_goals","away_goals"),"full-time score")
    if any(type(n) is not int or n<0 for n in actual.values()):
        raise BuildError("Invalid full-time score")
    hg,ag = actual["home_goals"],actual["away_goals"]
    actual_outcome = "home_win" if hg>ag else "draw" if hg==ag else "away_win"
    chosen = max(ORDER,key=lambda k:match["forecast"]["probabilities"][k])
    top = match["forecast"]["scorelines"][0]
    return {"outcome":"correct" if chosen==actual_outcome else "incorrect",
            "exact_score":"correct" if (top["home_goals"],top["away_goals"])==(hg,ag) else "incorrect"}


def validate_contract(data,manifest):
    object_fields(data,("schema_version","mode","label","competition","season","slate","presentation_model","matches"),"display input")
    if data["schema_version"]!=VERSION or data["mode"]!="historical_replay" or data["label"]!="Historical replay":
        raise BuildError("Expected the historical replay contract; live input is not supported")
    object_fields(data["competition"],("id","name"),"competition")
    if data["competition"]!={"id":"premier-league","name":"Premier League"} or data["season"]!="2025-26":
        raise BuildError("Unexpected competition or historical season")
    object_fields(data["slate"],("id","start_date_london","end_date_london","simulated_issue_date_london"),"slate")
    object_fields(data["presentation_model"],("name","version"),"presentation model")
    if data["presentation_model"]["name"]!="Poisson":
        raise BuildError("Poisson is the historical presentation model")
    source_hash = manifest.get("source_hashes",{}).get("frozen/models.joblib","")
    if not re.fullmatch(r"[0-9a-f]{64}",source_hash) or data["presentation_model"]["version"]!="historical-fit-"+source_hash[:12]:
        raise BuildError("Presentation model does not match the proof provenance")
    matches = data["matches"]
    if not isinstance(matches,list) or not matches or len(matches)!=manifest.get("fixture_count"):
        raise BuildError("Incomplete historical fixture coverage")
    start,end,issue = (date.fromisoformat(data["slate"][key]) for key in ("start_date_london","end_date_london","simulated_issue_date_london"))
    if start.weekday()!=1 or end!=start+timedelta(days=6) or data["slate"]["id"]!=data["season"]+":"+start.isoformat():
        raise BuildError("Invalid Tuesday-Monday slate")
    if issue!=min(date.fromisoformat(m["played_date_london"]) for m in matches) or issue.isoformat()!=manifest.get("source_issue_date_london"):
        raise BuildError("The shared simulated issue date does not reconcile")
    ids = []
    for match in matches:
        object_fields(match,("fixture_id","played_date_london","home","away","status","forecast","actual_full_time","marks"),"fixture")
        for side in ("home","away"):
            object_fields(match[side],("id","name"),"team")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",match[side]["id"]):
                raise BuildError("Invalid club identifier")
        if match["home"]["id"]==match["away"]["id"] or match["fixture_id"]!=":".join((data["season"],match["home"]["id"],match["away"]["id"])):
            raise BuildError("Fixture identity does not reconcile")
        ids.append(match["fixture_id"])
        if not start<=date.fromisoformat(match["played_date_london"])<=end:
            raise BuildError("Fixture is outside the slate")
        object_fields(match["forecast"],("probabilities","scorelines"),"forecast")
        p = match["forecast"]["probabilities"]
        object_fields(p,ORDER,"outcome probabilities")
        if any(type(n) not in (float,int) or not math.isfinite(n) or not 0<=n<=1 for n in p.values()) or abs(sum(p.values())-1)>2e-12:
            raise BuildError("Outcome probabilities must be finite and sum to one")
        scores = match["forecast"]["scorelines"]
        if not isinstance(scores,list) or len(scores)!=3:
            raise BuildError("Expected three scorelines")
        for score in scores:
            object_fields(score,("home_goals","away_goals","probability"),"scoreline")
            if any(type(score[k]) is not int or score[k]<0 for k in ("home_goals","away_goals")) or type(score["probability"]) not in (float,int) or not math.isfinite(score["probability"]) or not 0<=score["probability"]<=1:
                raise BuildError("Invalid scoreline probability or goals")
        if len({(s["home_goals"],s["away_goals"]) for s in scores})!=3 or scores!=sorted(scores,key=lambda s:(-s["probability"],s["home_goals"],s["away_goals"])):
            raise BuildError("Scoreline ranking is inconsistent")
        if match["marks"]!=expected_marks(match):
            raise BuildError("Independent correctness marks do not reconcile")
    if len(ids)!=len(set(ids)):
        raise BuildError("Duplicate fixture IDs")
    for key,value in (("outcome_correct",sum(m["marks"]["outcome"]=="correct" for m in matches)),
                      ("exact_score_correct",sum(m["marks"]["exact_score"]=="correct" for m in matches)),
                      ("completed_zero_zero_fixtures",sum(m["actual_full_time"]=={"home_goals":0,"away_goals":0} for m in matches))):
        if manifest.get(key)!=value:
            raise BuildError("Slate totals do not match the proof")


def verified_input(path):
    path = Path(path).resolve()
    data = read_json(path)
    schema_path = path.with_name("display_input.schema.json")
    manifest_path = path.with_name("proof_manifest.json")
    schema,manifest = read_json(schema_path),read_json(manifest_path)
    if not isinstance(manifest,dict) or manifest.get("status")!="PASS" or manifest.get("mode")!="historical_replay" or manifest.get("network_used") is not False or manifest.get("api_attempts")!=0 or manifest.get("real_issue_timestamp_in_input") is not False:
        raise BuildError("Missing or incompatible offline historical proof manifest")
    hashes = manifest.get("output_hashes",{})
    if digest(path)!=hashes.get("historical_display_input.json") or digest(schema_path)!=hashes.get("display_input.schema.json"):
        raise BuildError("Input/schema checksum does not match the adjoining proof manifest")
    check_schema(data,schema)
    validate_contract(data,manifest)
    return data


def verified_archive(path):
    """Read a curated archive whose entries pin complete, independently proved slates."""
    path = Path(path).resolve()
    archive = read_json(path)
    object_fields(archive,("schema_version","mode","source_revision","source_hashes","slates"),"archive")
    if archive["schema_version"]!=ARCHIVE_VERSION or archive["mode"]!="historical_replay":
        raise BuildError("Expected a historical replay archive")
    if archive["source_revision"]!=SOURCE_REVISION:
        raise BuildError("Archive must use the pinned historical source revision")
    hashes = archive["source_hashes"]
    object_fields(hashes,SOURCE_FILES,"archive provenance")
    if any(not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value) for value in hashes.values()):
        raise BuildError("Invalid archive provenance checksum")
    entries = archive["slates"]
    if not isinstance(entries,list) or not entries:
        raise BuildError("Archive must contain at least one complete slate")
    slates,slate_ids,fixture_ids,inputs = [],set(),set(),set()
    for entry in entries:
        object_fields(entry,("input","proof_sha256","fixture_ids"),"archive entry")
        relative = entry["input"]
        if not isinstance(relative,str) or not re.fullmatch(r"[A-Za-z0-9_./-]+",relative):
            raise BuildError("Archive input must be a relative path within its bundle")
        parts = PurePosixPath(relative)
        if parts.is_absolute() or any(part in ("",".","..") for part in relative.split("/")) or parts.name!="historical_display_input.json":
            raise BuildError("Archive input must name a display input within its bundle")
        source = (path.parent/relative).resolve()
        if not source.is_relative_to(path.parent) or source in inputs:
            raise BuildError("Duplicate or escaped archive input")
        inputs.add(source)
        proof = source.with_name("proof_manifest.json")
        if any(not evidence.resolve().is_relative_to(path.parent) for evidence in
               (proof,source.with_name("display_input.schema.json"))):
            raise BuildError("Archive evidence must stay within its bundle")
        if not isinstance(entry["proof_sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",entry["proof_sha256"]):
            raise BuildError("Invalid archive proof checksum")
        try:
            proof_hash = digest(proof)
        except OSError as exc:
            raise BuildError("Missing archive slate proof") from exc
        if proof_hash!=entry["proof_sha256"]:
            raise BuildError("Archive proof checksum does not match")
        manifest = read_json(proof)
        if not isinstance(manifest,dict) or manifest.get("source_hashes")!=hashes:
            raise BuildError("Archive slates must share the frozen source provenance")
        data = verified_input(source)
        expected = entry["fixture_ids"]
        if not isinstance(expected,list) or not expected or any(not isinstance(value,str) for value in expected) or len(expected)!=len(set(expected)):
            raise BuildError("Archive entry needs unique complete fixture membership")
        actual = {match["fixture_id"] for match in data["matches"]}
        if actual!=set(expected):
            raise BuildError("Incomplete or incorrect archive slate membership")
        identity = data["slate"]["id"]
        if identity in slate_ids or fixture_ids & actual:
            raise BuildError("Duplicate archive slate or fixture")
        slate_ids.add(identity)
        fixture_ids.update(actual)
        slates.append(data)
    return sorted(slates,key=lambda data:data["slate"]["id"],reverse=True)


def content_review(html,css,icon):
    body = "\n".join((html,css,icon))
    forbidden = (r"(?<![A-Za-z])[A-Za-z]:[\\/]",r"/(?:Users|home|workspace)/",r"(?:api[_-]?key|raw_payload|source_hashes|models\.joblib)",
                 r"<script\b",r"<iframe\b",r"@import\b",r"https?://[^\s\"']+\.(?:woff|ttf)")
    if any(re.search(pattern,body,re.I) for pattern in forbidden):
        raise BuildError("Rendered content contains a prohibited field, path or resource")


def build(input_path,output_path,*,archive=False,preview=False,issued=False,record_path=None,record_sha256=None,results_path=None):
    output = Path(output_path).resolve()
    if output.exists():
        raise BuildError("Use a fresh output directory; existing output is preserved")
    for ancestor in (output,*output.parents):
        if (ancestor/".git").exists():
            raise BuildError("Site output must be outside Git worktrees")
    if output==ROOT or ROOT in output.parents:
        raise BuildError("Site output must be outside the source directory")
    if sum((archive, preview, issued)) > 1 or (not issued and (record_path is not None or record_sha256 is not None or results_path is not None)):
        raise BuildError("Choose one source mode; original record options require genuine issuance")
    if issued:
        slates = [verified_issued(input_path,record_path,record_sha256,results_path=results_path)]
        pages = {"index.html":render_issued(slates[0])}
    elif preview:
        slates = [verified_preview(input_path)]
        pages = {"index.html":render_preview(slates[0])}
    elif archive:
        slates = verified_archive(input_path)
        pages = {"index.html":render_archive(slates)}
        pages.update({slate_filename(data):render_page(data,archive=True) for data in slates})
    else:
        slates = [verified_input(input_path)]
        pages = {"index.html":render_page(slates[0])}
    css = (ROOT/"assets"/"styles.css").read_text(encoding="utf-8")
    icon = (ROOT/"assets"/"favicon.svg").read_text(encoding="utf-8")
    for html in pages.values():
        content_review(html,css,icon)
    output.mkdir(parents=True)
    for name,html in pages.items():
        (output/name).write_text(html,encoding="utf-8",newline="\n")
    (output/"styles.css").write_text(css,encoding="utf-8",newline="\n")
    (output/"favicon.svg").write_text(icon,encoding="utf-8",newline="\n")
    return {"matches":sum(len(data["matches"]) for data in slates),
            "slates":len(slates),"files":[*pages,"styles.css","favicon.svg"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input",type=Path)
    source.add_argument("--archive",type=Path)
    source.add_argument("--preview",type=Path)
    source.add_argument("--issued",type=Path)
    parser.add_argument("--record",type=Path,help="Original opening events export for genuine issuance")
    parser.add_argument("--record-sha256",help="Original export pin from an independently trusted checkpoint")
    parser.add_argument("--results",type=Path,help="Explicit reviewed factual snapshot history for genuine issuance")
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    try:
        result = build(args.issued or args.preview or args.archive or args.input,args.output,
                       archive=args.archive is not None,preview=args.preview is not None,issued=args.issued is not None,
                       record_path=args.record,record_sha256=args.record_sha256,results_path=args.results)
    except (BuildError,KeyError,TypeError,ValueError,OSError) as exc:
        raise SystemExit(f"Site build failed: {exc}") from exc
    print(f"Built {result['matches']} matches across {result['slates']} slate(s) in {len(result['files'])} static files.")


if __name__=="__main__":
    main()
