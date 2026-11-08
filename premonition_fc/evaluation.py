"""One-to-one scoring and forward-only development model selection."""
import numpy as np
import pandas as pd

from .data import HOLDOUT, SEASONS
from .models import CANDIDATES, ORDER, fit_models, outcome, predict, validate_probabilities

METRIC_RULES = {
    "primary":"mean multiclass negative natural log probability of observed result",
    "log_floor":1e-15,"outcome_tie":"first maximum in H, D, A order",
    "scoreline_tie":"probability descending, then home goals ascending, then away goals ascending",
    "draw_recall":"predicted draw among actual draws; null when no actual draws",
    "score_hit":"Poisson rank-one exact score equals both actual full-time goal counts",
    "selection":"pooled development log loss; exact ties choose first declared candidate",
}


def score_predictions(predictions, targets, expected_per_model=None):
    pred = pd.DataFrame(predictions)
    actual = pd.DataFrame(targets)
    if pred.empty or actual.empty or actual.fixture_id.duplicated().any() or pred.duplicated(["model","fixture_id"]).any():
        raise ValueError("Duplicate or empty prediction/target join")
    models = set(pred.model)
    if models != {"poisson","forest","frequencies"}:
        raise ValueError("All three models must be scored on identical fixtures")
    for model in models:
        ids = set(pred.loc[pred.model==model,"fixture_id"])
        if ids != set(actual.fixture_id) or (expected_per_model is not None and len(ids)!=expected_per_model):
            raise ValueError("Incomplete or extra fixture coverage for scoring")
    joined = pred.merge(actual,on="fixture_id",how="left",validate="many_to_one",indicator=True)
    if not joined["_merge"].eq("both").all():
        raise ValueError("Unmatched fixture targets")
    joined = joined.drop(columns="_merge")
    result = []
    # pandas creates NaN for optional model fields; retain the original prediction schema instead.
    lookup = {t["fixture_id"]:t for t in targets}
    for row in predictions:
        actual_row = lookup[row["fixture_id"]]
        hg,ag = actual_row["home_goals"],actual_row["away_goals"]
        actual_label = outcome(hg,ag)
        p = validate_probabilities([row["probabilities"]])[0]
        label = ORDER[int(np.argmax(p))]
        score_hit = None
        if row["model"]=="poisson":
            top = row["scorelines"][0]
            score_hit = top["home_goals"]==hg and top["away_goals"]==ag
        result.append(dict(row,actual_home_goals=hg,actual_away_goals=ag,actual_result=actual_label,
                           predicted_result=label,result_correct=label==actual_label,
                           log_loss=float(-np.log(max(float(p[ORDER.index(actual_label)]),1e-15))),
                           top_score_correct=score_hit))
    return result


def metrics(scored):
    output = {}
    for model in ("frequencies","poisson","forest"):
        rows = [r for r in scored if r["model"]==model]
        if not rows:
            raise ValueError("Missing model scores")
        draws = [r for r in rows if r["actual_result"]=="D"]
        output[model] = {"log_loss":float(np.mean([r["log_loss"] for r in rows])),
            "accuracy":float(np.mean([r["result_correct"] for r in rows])),
            "draw_recall":float(np.mean([r["predicted_result"]=="D" for r in draws])) if draws else None,
            "fixtures":len(rows),"actual_draws":len(draws),
            "top_one_score_hit_rate":float(np.mean([r["top_score_correct"] for r in rows])) if model=="poisson" else None}
    return output


def development_folds(rows):
    if any(r["season"]>=HOLDOUT for r in rows):
        raise ValueError("Development selection must not receive holdout rows")
    for validation in SEASONS[1:-1]:
        training = [r for r in rows if r["season"]<validation]
        valid = [r for r in rows if r["season"]==validation]
        if not training or len(valid)!=380:
            raise ValueError("Expanding season fold has incomplete coverage")
        yield validation,training,valid


def select_development(rows, targets):
    target_lookup = {t["fixture_id"]:t for t in targets}
    candidates, outputs = [], {}
    # Pair the two candidate lists to avoid redundant fits. Each model is selected independently.
    for index in range(2):
        settings = {name:values[index] for name,values in CANDIDATES.items()}
        scored_all,fold_evidence = [],[]
        for season,training,validation in development_folds(rows):
            train_targets = [target_lookup[r["fixture_id"]] for r in training]
            valid_targets = [target_lookup[r["fixture_id"]] for r in validation]
            fitted = fit_models(training,train_targets,settings)
            preds = predict(fitted,validation,"development-validation")
            for pred in preds:
                pred["validation_season"] = season
            scored = score_predictions(preds,valid_targets,380)
            scored_all.extend(scored)
            fold_evidence.append({"validation_season":season,"training_count":len(training),"validation_count":len(validation),
                                  "training_max_date":max(r["played_date"] for r in training),"metrics":metrics(scored)})
        summary = {"candidate_index":index,"settings":settings,"pooled_metrics":metrics(scored_all),"folds":fold_evidence}
        candidates.append(summary)
        outputs[index] = scored_all
    selected = {model:min(range(2),key=lambda i:candidates[i]["pooled_metrics"][model]["log_loss"]) for model in ("poisson","forest")}
    settings = {model:CANDIDATES[model][index] for model,index in selected.items()}
    chosen = []
    for model in ("poisson","forest","frequencies"):
        index = selected.get(model,0)
        chosen.extend(r for r in outputs[index] if r["model"]==model)
    chosen.sort(key=lambda r:(r["validation_season"],r["played_date"],r["fixture_id"],r["model"]))
    fold_metrics = {season:metrics([r for r in chosen if r["validation_season"]==season]) for season in SEASONS[1:-1]}
    return {"candidates":candidates,"selected_indices":selected,"settings":settings,
            "pooled_metrics":metrics(chosen),"fold_metrics":fold_metrics},chosen
