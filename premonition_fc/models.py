"""Three result models with a common class order and exact Poisson outcomes."""
from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson, skellam
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .data import HOLDOUT
from .features import FEATURES, matrix

ORDER = ("H", "D", "A")
SEED = 1729
# Declared before any evaluation; only these four expanding development folds select settings.
CANDIDATES = {
    "poisson": [{"alpha":0.1},{"alpha":1.0}],
    "forest": [{"min_samples_leaf":5},{"min_samples_leaf":15}],
}
FOREST_COMMON = {"n_estimators":300,"max_depth":8,"max_features":1.0,
                 "bootstrap":True,"class_weight":None,"random_state":SEED,"n_jobs":1}


def outcome(hg, ag):
    return "H" if hg>ag else "D" if hg==ag else "A"


def validate_probabilities(values):
    p = np.asarray(values,dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all() or (p<0).any() or (p>1).any():
        raise ValueError("Outcome probabilities must be finite and in [0,1]")
    if not np.allclose(p.sum(axis=1),1,rtol=0,atol=2e-12):
        raise ValueError("Outcome probabilities do not sum to one")
    return p


def poisson_distribution(home_mean, away_mean, tail_tolerance=1e-12):
    """Skellam handles the entire outcome distribution; a bounded grid ranks scores."""
    h,a = float(home_mean),float(away_mean)
    if not np.isfinite([h,a]).all() or min(h,a)<0:
        raise ValueError("Goal means must be finite and non-negative")
    if h==0:
        d = float(np.exp(-a))
        probabilities = np.array([0,d,1-d])
    elif a==0:
        d = float(np.exp(-h))
        probabilities = np.array([1-d,d,0])
    else:
        probabilities = np.array([skellam.sf(0,h,a),skellam.pmf(0,h,a),skellam.cdf(-1,h,a)],dtype=float)
    # Only repair roundoff, never renormalize a truncated score grid into outcome probabilities.
    if abs(probabilities.sum()-1)>2e-12:
        raise ArithmeticError("Skellam outcome mass did not reconcile")
    probabilities /= probabilities.sum()
    validate_probabilities([probabilities])
    limit = max(2,int(max(poisson.isf(tail_tolerance/4,h),poisson.isf(tail_tolerance/4,a))))
    while True:
        if limit>10000:
            raise ValueError("Score grid exceeds supported bound")
        hp,ap = poisson.pmf(np.arange(limit+1),h),poisson.pmf(np.arange(limit+1),a)
        grid = np.outer(hp,ap)
        ranked = sorted(((float(grid[i,j]),i,j) for i in range(limit+1) for j in range(limit+1)),
                        key=lambda v:(-v[0],v[1],v[2]))[:3]
        tail_bound = float(poisson.sf(limit,h)+poisson.sf(limit,a))
        # Every unseen cell is <= total omitted mass. A strict bound proves top-three completeness.
        if tail_bound<=tail_tolerance and (tail_bound<ranked[2][0] or tail_bound==0):
            break
        limit += max(1,limit//4)
    scorelines = [{"home_goals":i,"away_goals":j,"probability":p} for p,i,j in ranked]
    # Independent finite-grid grouping must agree with full outcomes up to the bounded tail.
    grid_outcomes = np.array([np.tril(grid,-1).sum(),np.trace(grid),np.triu(grid,1).sum()])
    if np.max(np.abs(grid_outcomes-probabilities))>tail_bound+2e-12:
        raise ArithmeticError("Score grid and outcome distribution disagree")
    return {"probabilities":probabilities.tolist(),"home_mean":h,"away_mean":a,
            "scorelines":scorelines,"grid_max_goals":limit,"tail_mass_bound":tail_bound,
            "top_three_certified":True}


def aligned_probabilities(estimator, x):
    raw = estimator.predict_proba(x)
    classes = list(estimator.classes_)
    mapped = np.zeros((len(x),3),dtype=float)
    if set(classes)-set(ORDER):
        raise ValueError("Unknown classifier class")
    for i,label in enumerate(ORDER):
        if label in classes:
            mapped[:,i] = raw[:,classes.index(label)]
    return validate_probabilities(mapped)


def joined_targets(rows, targets):
    ids = [r["fixture_id"] for r in rows]
    target_ids = [r["fixture_id"] for r in targets]
    if len(set(ids))!=len(ids) or len(set(target_ids))!=len(target_ids) or set(ids)!=set(target_ids):
        raise ValueError("Targets require a one-to-one, complete fixture ID join")
    lookup = {r["fixture_id"]:r for r in targets}
    return [lookup[key] for key in ids]


@dataclass
class FittedModels:
    home_poisson: object
    away_poisson: object
    forest: object
    frequencies: list
    settings: dict
    training_fixture_ids: list


def fit_models(rows, targets, settings):
    if not rows or any(r["season"]>=HOLDOUT for r in rows):
        raise ValueError("Fitting is restricted to development seasons before the holdout")
    ordered = joined_targets(rows,targets)
    x = matrix(rows)
    hg = np.array([r["home_goals"] for r in ordered])
    ag = np.array([r["away_goals"] for r in ordered])
    labels = np.array([outcome(h,a) for h,a in zip(hg,ag)])
    def regression():
        return make_pipeline(StandardScaler(),PoissonRegressor(alpha=settings["poisson"]["alpha"],
                             max_iter=1000,tol=1e-10,solver="lbfgs"))
    home,away = regression(),regression()
    forest = RandomForestClassifier(**FOREST_COMMON,**settings["forest"])
    with threadpool_limits(limits=1):
        home.fit(x,hg)
        away.fit(x,ag)
        forest.fit(x,labels)
    frequencies = [float(np.mean(labels==label)) for label in ORDER]
    return FittedModels(home,away,forest,frequencies,settings,[r["fixture_id"] for r in rows])


def predict(models, rows, partition):
    x = matrix(rows)
    with threadpool_limits(limits=1):
        hm = models.home_poisson.predict(x)
        am = models.away_poisson.predict(x)
        forest = aligned_probabilities(models.forest,x)
    result = []
    for i,row in enumerate(rows):
        base = {k:row[k] for k in ("fixture_id","season","played_date","home","away","issue_date_london")}
        base.update(historical=True,partition=partition,probability_order=list(ORDER))
        distribution = poisson_distribution(hm[i],am[i])
        result.append(dict(base,model="poisson",**distribution))
        result.append(dict(base,model="forest",probabilities=forest[i].tolist()))
        result.append(dict(base,model="frequencies",probabilities=models.frequencies))
    return result
