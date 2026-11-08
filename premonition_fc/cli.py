"""Explicit preparation, development, freeze, forecast and score entry points."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import platform
import sys

import joblib

from .data import HOLDOUT, load_pinned
from .evaluation import METRIC_RULES, metrics, score_predictions, select_development
from .features import FEATURE_CONTRACT, FEATURES, prepare_features
from .models import CANDIDATES, FOREST_COMMON, ORDER, SEED, fit_models, predict
from .reporting import build_report
from .storage import code_fingerprint, digest, external_directory, object_digest, read_json, write_json


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def prepare(args):
    output = external_directory(args.output,fresh=True)
    fixtures,pins = load_pinned(args.input,args.manifest)
    rows,traces,excluded = prepare_features([replace(m,home_goals=None,away_goals=None) for m in fixtures],fixtures)
    by_id = {m.fixture_id:m for m in fixtures}
    development = [r for r in rows if r["season"]<HOLDOUT]
    holdout = [r for r in rows if r["season"]==HOLDOUT]
    if (len(fixtures),len(rows),len(excluded),len(development),len(holdout))!=(2280,2272,8,1892,380):
        raise ValueError("Unexpected historical preparation counts")
    def targets(subset):
        return [{"fixture_id":r["fixture_id"],"home_goals":by_id[r["fixture_id"]].home_goals,
                 "away_goals":by_id[r["fixture_id"]].away_goals} for r in subset]
    exports = {"normalized.json":[asdict(m) for m in fixtures],"fixtures.json":[m.metadata() for m in fixtures],
               "development_features.json":development,"development_targets.json":targets(development),
               "holdout_features.json":holdout,"holdout_targets.json":targets(holdout),
               "feature_traces.json":traces,"warmup_exclusions.json":excluded}
    for name,value in exports.items():
        write_json(output/name,value)
    write_json(output/"preparation.json",{"code_fingerprint":code_fingerprint(),"pins":pins,"feature_contract":FEATURE_CONTRACT,
        "counts":{"fixtures":2280,"usable":2272,"development":1892,"holdout":380,"warmup":8},
        "files":{name:digest(output/name) for name in exports}})
    print("Prepared 2,272 feature rows: 1,892 development, 380 holdout; eight warm-up exclusions.")


def check_prepared(path):
    path = Path(path)
    manifest = read_json(path/"preparation.json")
    if manifest["code_fingerprint"]!=code_fingerprint():
        raise ValueError("Preparation code differs; prepare again and verify parity before fitting")
    return path,manifest


def parity(args):
    prepared,meta = check_prepared(args.prepared)
    audit = Path(args.audit)
    old_normal = read_json(audit/"historical_normalized.json")
    old_features = read_json(audit/"feature_replay.json")
    old_warmup = read_json(audit/"warmup_exclusions.json")
    new_normal = read_json(prepared/"normalized.json")
    fields = ("season","played_date","home","away","home_goals","away_goals")
    normalize_row = lambda r:tuple(r[k] for k in fields)
    if sorted(map(normalize_row,old_normal))!=sorted(map(normalize_row,new_normal)):
        raise ValueError("Normalized fixtures differ from reference")
    new = read_json(prepared/"development_features.json")+read_json(prepared/"holdout_features.json")
    old = {":".join(r["fixture_key"]):r for r in old_features}
    if len(new)!=len(old) or set(r["fixture_id"] for r in new)!=set(old):
        raise ValueError("Feature fixture coverage differs")
    for row in new:
        reference = old[row["fixture_id"]]
        for field,source in (("issue_date_london","issue_date"),("home_count","home_count"),("away_count","away_count"),
                             ("prior_match_count","prior_match_count"),("prior_latest_date","prior_latest_date")):
            if row[field]!=reference[source]:
                raise ValueError(f"Reference cutoff/count mismatch: {row['fixture_id']}")
        for side in ("home","away"):
            for metric in ("gf","ga","points"):
                if row["features"][side+"_"+metric]!=reference[side][metric]:
                    raise ValueError(f"Feature mismatch: {row['fixture_id']}")
    warmup = read_json(prepared/"warmup_exclusions.json")
    if {r["fixture_id"] for r in warmup}!={":".join(r["fixture_key"]) for r in old_warmup}:
        raise ValueError("Warm-up exclusions differ")
    write_json(prepared/"parity.json",{"status":"PASS","normalized":2280,"feature_rows":2272,"feature_values":2272*6,
        "warmup":8,"exact_float_equality":True,"prepared_manifest_sha256":digest(prepared/"preparation.json"),
        "reference_hashes":{name:digest(audit/name) for name in ("historical_normalized.json","feature_replay.json","warmup_exclusions.json")}})
    print("Parity PASS: all 2,280 fixtures, 13,632 feature values, cutoffs, counts and eight exclusions match.")


def development_inputs(prepared):
    path,manifest = check_prepared(prepared)
    for name in ("development_features.json","development_targets.json"):
        if digest(path/name)!=manifest["files"][name]:
            raise ValueError("Development input hash changed")
    if (path/"parity.json").exists():
        evidence = read_json(path/"parity.json")
        if evidence["status"]!="PASS" or evidence["prepared_manifest_sha256"]!=digest(path/"preparation.json"):
            raise ValueError("Reference parity evidence does not match this preparation")
    return read_json(path/"development_features.json"),read_json(path/"development_targets.json"),manifest


def develop(args):
    output = external_directory(args.output,fresh=True)
    rows,targets,manifest = development_inputs(args.prepared)
    selection,scored = select_development(rows,targets)
    selection.update(code_fingerprint=code_fingerprint(),development_features_sha256=manifest["files"]["development_features.json"],
                     development_targets_sha256=manifest["files"]["development_targets.json"],candidate_policy=CANDIDATES)
    write_json(output/"selection.json",selection)
    write_json(output/"scored_validation.json",scored)
    write_json(output/"validation_predictions.json",[{k:v for k,v in r.items() if k not in {
        "actual_home_goals","actual_away_goals","actual_result","predicted_result","result_correct","log_loss","top_score_correct"}} for r in scored])
    print("Development complete: four expanding folds, 1,520 predictions per model.")
    print("Selected settings:",selection["settings"])


def freeze(args):
    output = external_directory(args.output,fresh=True)
    rows,targets,prepared = development_inputs(args.prepared)
    selection = read_json(Path(args.development)/"selection.json")
    if (selection["code_fingerprint"]!=code_fingerprint() or selection["development_features_sha256"]!=prepared["files"]["development_features.json"]
            or selection["development_targets_sha256"]!=prepared["files"]["development_targets.json"]):
        raise ValueError("Selection does not match this code and development partition")
    fitted = fit_models(rows,targets,selection["settings"])
    joblib.dump(fitted,output/"models.joblib",compress=3)
    def regression_state(regression):
        scaler,model = regression.steps[0][1],regression.steps[1][1]
        return {"training_samples":int(scaler.n_samples_seen_),"scaler_mean":scaler.mean_.tolist(),
                "scaler_variance":scaler.var_.tolist(),"coefficients":model.coef_.tolist(),"intercept":float(model.intercept_)}
    manifest = {"frozen_at_utc":timestamp(),"kind":"new historical experiment","holdout":HOLDOUT,
        "settings":selection["settings"],"forest_common":FOREST_COMMON,"seed":SEED,"feature_contract":FEATURE_CONTRACT,
        "probability_order":ORDER,"scoring":METRIC_RULES,"code_fingerprint":code_fingerprint(),"pins":prepared["pins"],
        "training_rows":len(rows),"training_max_date":max(r["played_date"] for r in rows),
        "training_fixture_ids":fitted.training_fixture_ids,"development_features_sha256":prepared["files"]["development_features.json"],
        "development_targets_sha256":prepared["files"]["development_targets.json"],
        "holdout_target_file_sha256":prepared["files"]["holdout_targets.json"],
        "selection_sha256":digest(Path(args.development)/"selection.json"),"fit_sha256":digest(output/"models.joblib"),
        "home_fit":regression_state(fitted.home_poisson),"away_fit":regression_state(fitted.away_poisson),
        "forest_classes":fitted.forest.classes_.tolist(),"frequencies":fitted.frequencies,
        "python":sys.version,"platform":platform.platform(),
        "packages":{name:importlib.metadata.version(name) for name in ("numpy","pandas","scipy","scikit-learn","matplotlib","joblib")},
        "protocol":"Fit/selection read development files only. Holdout scoring targets may be opened only by the separate score command after saved forecasts."}
    write_json(output/"freeze.json",manifest)
    print("Frozen fit saved from 1,892 development fixtures. Holdout scoring targets were not opened.")


def frozen_manifest(path):
    path = Path(path)
    meta = read_json(path/"freeze.json")
    if meta["code_fingerprint"]!=code_fingerprint() or digest(path/"models.joblib")!=meta["fit_sha256"]:
        raise ValueError("Frozen code/model fingerprint changed")
    return path,meta


def forecast(args):
    output = external_directory(args.output,fresh=True)
    prepared,metadata = check_prepared(args.prepared)
    frozen,freeze_meta = frozen_manifest(args.frozen)
    if digest(prepared/"holdout_features.json")!=metadata["files"]["holdout_features.json"]:
        raise ValueError("Holdout feature file changed")
    if (metadata["files"]["development_features.json"]!=freeze_meta["development_features_sha256"]
            or metadata["files"]["development_targets.json"]!=freeze_meta["development_targets_sha256"]
            or metadata["files"]["holdout_targets.json"]!=freeze_meta["holdout_target_file_sha256"]):
        raise ValueError("Prepared experiment differs from frozen inputs")
    rows = read_json(prepared/"holdout_features.json")
    if len(rows)!=380 or any(r["season"]!=HOLDOUT for r in rows):
        raise ValueError("Expected all 380 holdout rows")
    fitted = joblib.load(frozen/"models.joblib")  # Only the locally fitted artifact whose SHA-256 was verified above.
    predictions = predict(fitted,rows,"frozen-holdout")
    write_json(output/"predictions.json",predictions)
    write_json(output/"forecast_manifest.json",{"saved_at_utc":timestamp(),"kind":"reproducibility replay of a frozen experiment",
        "fixtures_per_model":380,"predictions":len(predictions),"predictions_sha256":digest(output/"predictions.json"),
        "fit_sha256":freeze_meta["fit_sha256"],"freeze_manifest_sha256":digest(frozen/"freeze.json"),
        "code_fingerprint":code_fingerprint(),"holdout_features_sha256":digest(prepared/"holdout_features.json"),
        "expected_targets_sha256":freeze_meta["holdout_target_file_sha256"],"targets_opened":False})
    print("Saved 380 holdout forecasts per model (1,140 total), before opening scoring targets.")


def score(args):
    output = external_directory(args.output,fresh=True)
    forecasts = Path(args.forecasts)
    frozen,frozen_meta = frozen_manifest(args.frozen)
    evidence = read_json(forecasts/"forecast_manifest.json")
    if (evidence["predictions_sha256"]!=digest(forecasts/"predictions.json")
            or evidence["freeze_manifest_sha256"]!=digest(frozen/"freeze.json") or evidence["targets_opened"]):
        raise ValueError("Forecast evidence does not match the saved frozen experiment")
    if digest(args.targets)!=evidence["expected_targets_sha256"]:
        raise ValueError("Scoring targets differ from the prepared holdout")
    # This is the first scoring-stage read of holdout target contents.
    targets = read_json(args.targets)
    scored = score_predictions(read_json(forecasts/"predictions.json"),targets,380)
    summary = metrics(scored)
    development = read_json(Path(args.development)/"selection.json")
    if digest(Path(args.development)/"selection.json")!=frozen_meta["selection_sha256"]:
        raise ValueError("Development selection changed")
    write_json(output/"scored_holdout.json",scored)
    write_json(output/"metrics.json",summary)
    write_json(output/"scoring_manifest.json",{"scored_at_utc":timestamp(),"forecast_saved_at_utc":evidence["saved_at_utc"],
        "forecast_sha256":evidence["predictions_sha256"],"targets_sha256":digest(args.targets),"scoring":METRIC_RULES,
        "counts":{name:summary[name]["fixtures"] for name in summary},"fit_sha256":frozen_meta["fit_sha256"]})
    build_report(output,development,summary,scored,frozen_meta)
    print("Scored all 380 holdout fixtures per model. Metrics and three headless figures saved.")
    for name,values in summary.items():
        print(name,values)


def parser():
    p = argparse.ArgumentParser(description="Premonition-FC historical forecast pipeline")
    sub = p.add_subparsers(dest="command",required=True)
    commands = {
        "prepare":(prepare,("input","manifest","output")),
        "parity":(parity,("prepared","audit")),
        "develop":(develop,("prepared","output")),
        "freeze":(freeze,("prepared","development","output")),
        "forecast":(forecast,("prepared","frozen","output")),
        "score":(score,("forecasts","targets","frozen","development","output")),
    }
    for name,(handler,arguments) in commands.items():
        command = sub.add_parser(name)
        for argument in arguments:
            command.add_argument("--"+argument,type=Path,required=True)
        command.set_defaults(handler=handler)
    return p


def main():
    args = parser().parse_args()
    try:
        args.handler(args)
    except (ValueError,KeyError,FileNotFoundError) as exc:
        raise SystemExit(f"premonition-fc: {exc}") from exc
