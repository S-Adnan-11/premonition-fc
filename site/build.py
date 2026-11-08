"""Build a static historical replay from a verified display contract."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import re

from render import render_page

ROOT = Path(__file__).resolve().parent
VERSION = "premonition-fc.historical-match-view.v1"
ORDER = ("home_win", "draw", "away_win")


class BuildError(ValueError):
    """The provided input cannot be rendered as a verified historical replay."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise BuildError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(BuildError("Non-finite JSON number")))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read {Path(path).name}: {exc.__class__.__name__}") from exc


def object_fields(value,expected,label):
    if not isinstance(value,dict) or set(value)!=set(expected):
        raise BuildError(f"{label}: missing or unexpected fields")


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


def content_review(html,css,icon):
    body = "\n".join((html,css,icon))
    forbidden = (r"(?<![A-Za-z])[A-Za-z]:[\\/]",r"/(?:Users|home|workspace)/",r"(?:api[_-]?key|raw_payload|source_hashes|models\.joblib)",
                 r"<script\b",r"<iframe\b",r"@import\b",r"https?://[^\s\"']+\.(?:woff|ttf)")
    if any(re.search(pattern,body,re.I) for pattern in forbidden):
        raise BuildError("Rendered content contains a prohibited field, path or resource")


def build(input_path,output_path):
    output = Path(output_path).resolve()
    if output.exists():
        raise BuildError("Use a fresh output directory; existing output is preserved")
    for ancestor in (output,*output.parents):
        if (ancestor/".git").exists():
            raise BuildError("Site output must be outside Git worktrees")
    if output==ROOT or ROOT in output.parents:
        raise BuildError("Site output must be outside the source directory")
    data = verified_input(input_path)
    html = render_page(data)
    css = (ROOT/"assets"/"styles.css").read_text(encoding="utf-8")
    icon = (ROOT/"assets"/"favicon.svg").read_text(encoding="utf-8")
    content_review(html,css,icon)
    output.mkdir(parents=True)
    (output/"index.html").write_text(html,encoding="utf-8",newline="\n")
    (output/"styles.css").write_text(css,encoding="utf-8",newline="\n")
    (output/"favicon.svg").write_text(icon,encoding="utf-8",newline="\n")
    return {"matches":len(data["matches"]),"files":["index.html","styles.css","favicon.svg"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    try:
        result = build(args.input,args.output)
    except (BuildError,KeyError,TypeError,ValueError) as exc:
        raise SystemExit(f"Site build failed: {exc}") from exc
    print(f"Built {result['matches']} historical matches in three static files.")


if __name__=="__main__":
    main()
