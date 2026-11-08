"""Small fictional display contracts; no real match archive is included."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def sample():
    def match(home,away,home_name,away_name,played,goals,top):
        correct = "correct" if goals==top else "incorrect"
        return {"fixture_id":"2025-26:"+home+":"+away,"played_date_london":played,
            "home":{"id":home,"name":home_name},"away":{"id":away,"name":away_name},"status":"completed",
            "forecast":{"probabilities":{"home_win":0.5,"draw":0.3,"away_win":0.2},"scorelines":[
                {"home_goals":top[0],"away_goals":top[1],"probability":0.12},
                {"home_goals":1,"away_goals":0,"probability":0.10},
                {"home_goals":3,"away_goals":0,"probability":0.08}]},
            "actual_full_time":{"home_goals":goals[0],"away_goals":goals[1]},
            "marks":{"outcome":"correct" if goals[0]>goals[1] else "incorrect","exact_score":correct}}
    return {"schema_version":"premonition-fc.historical-match-view.v1","mode":"historical_replay","label":"Historical replay",
        "competition":{"id":"premier-league","name":"Premier League"},"season":"2025-26",
        "slate":{"id":"2025-26:2025-08-12","start_date_london":"2025-08-12","end_date_london":"2025-08-18","simulated_issue_date_london":"2025-08-15"},
        "presentation_model":{"name":"Poisson","version":"historical-fit-"+("ab"*6)},
        "matches":[match("harbour-athletic","vale-city","Harbour Athletic","Vale City","2025-08-15",(0,0),(1,1)),
                   match("moor-united","rail-rovers","Moor United","Rail Rovers","2025-08-16",(2,1),(2,1))]}


def schema_for(value):
    if isinstance(value,dict):
        return {"type":"object","properties":{k:schema_for(v) for k,v in value.items()},"required":list(value),"additionalProperties":False}
    if isinstance(value,list):
        return {"type":"array","items":schema_for(value[0]),"minItems":1}
    if isinstance(value,str):
        return {"type":"string","minLength":1}
    if type(value) is int:
        return {"type":"integer","minimum":0}
    return {"type":"number","minimum":0,"maximum":1}


def save_input(folder,data=None):
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    data = deepcopy(sample() if data is None else data)
    source = folder/"historical_display_input.json"
    schema = folder/"display_input.schema.json"
    source.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    schema.write_text(json.dumps(schema_for(sample()),indent=2)+"\n",encoding="utf-8")
    manifest = {"status":"PASS","mode":"historical_replay","network_used":False,"api_attempts":0,
        "real_issue_timestamp_in_input":False,"fixture_count":len(data["matches"]),"source_issue_date_london":data["slate"]["simulated_issue_date_london"],
        "outcome_correct":sum(m["marks"]["outcome"]=="correct" for m in data["matches"]),
        "exact_score_correct":sum(m["marks"]["exact_score"]=="correct" for m in data["matches"]),
        "completed_zero_zero_fixtures":sum(m["actual_full_time"]=={"home_goals":0,"away_goals":0} for m in data["matches"]),
        "source_hashes":{"frozen/models.joblib":"ab"*32},
        "output_hashes":{"historical_display_input.json":hashlib.sha256(source.read_bytes()).hexdigest(),"display_input.schema.json":hashlib.sha256(schema.read_bytes()).hexdigest()}}
    (folder/"proof_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return source
