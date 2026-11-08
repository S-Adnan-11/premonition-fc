"""Shared-slate, past-only rolling form with exact short-history blends."""
from datetime import date, timedelta
from fractions import Fraction

import numpy as np

FEATURES = tuple(f"{side}_{metric}" for side in ("home", "away") for metric in ("gf", "ga", "points"))
FEATURE_CONTRACT = {
    "columns":FEATURES,"window":5,"slate":"Tuesday-Monday Europe/London calendar dates",
    "issue":"first fixture played date in each slate","eligibility":"confirmed score, played_date < issue date",
    "seasons":"current and immediately previous for team form and league prior",
    "blend":"(team totals + (5-n)*league per-team average)/5",
    "home_advantage":"ordered home/away columns and separate home/away goal regressions",
}


def bucket_start(day):
    day = date.fromisoformat(day)
    return (day-timedelta(days=(day.weekday()-1)%7)).isoformat()


def slates(fixtures):
    grouped = {}
    for m in fixtures:
        grouped.setdefault((m.season,bucket_start(m.played_date)),[]).append(m)
    return [(k[0],k[1],min(m.played_date for m in rows), sorted(rows,key=lambda m:(m.played_date,m.home,m.away)))
            for k,rows in sorted(grouped.items())]


def team_values(match, team):
    gf,ga = (match.home_goals,match.away_goals) if match.home==team else (match.away_goals,match.home_goals)
    return {"gf":gf,"ga":ga,"points":3 if gf>ga else 1 if gf==ga else 0}


def trace(history, target, issue):
    date.fromisoformat(issue)
    if issue > target.played_date:
        raise ValueError("Issue date follows fixture date")
    year = int(target.season[:4])
    previous = f"{year-1}-{str(year)[2:]}"
    eligible = sorted((m for m in history if m.complete and m.season in (previous,target.season) and m.played_date<issue),
                      key=lambda m:(m.played_date,m.season,m.home,m.away))
    if not eligible:
        raise ValueError("warm-up: no past league prior")
    goals = sum(m.home_goals+m.away_goals for m in eligible)
    points = sum(2 if m.home_goals==m.away_goals else 3 for m in eligible)
    prior = {"gf":Fraction(goals,2*len(eligible)),"ga":Fraction(goals,2*len(eligible)),"points":Fraction(points,2*len(eligible))}
    output = dict(target.metadata(), issue_date_london=issue, historical=True, slate_start=bucket_start(target.played_date),
                  prior_match_count=len(eligible),prior_latest_date=eligible[-1].played_date,
                  prior_totals={"goals":goals,"points":points,"team_appearances":2*len(eligible)},
                  prior={k:float(v) for k,v in prior.items()}, features={})
    for side in ("home","away"):
        team = getattr(target,side)
        matches = [m for m in eligible if team in (m.home,m.away)][-5:]
        totals = {k:sum(team_values(m,team)[k] for m in matches) for k in prior}
        blend = {k:(Fraction(totals[k])+(5-len(matches))*prior[k])/5 for k in prior}
        output[side+"_trace"] = {"count":len(matches),"totals":totals,"exact":{k:str(v) for k,v in blend.items()},
            "matches":[dict(m.metadata(),home_goals=m.home_goals,away_goals=m.away_goals,**team_values(m,team)) for m in matches]}
        output["features"].update({side+"_"+k:float(v) for k,v in blend.items()})
    return output


def prepare_features(targets, history):
    """Targets may be fixture-only; history is a distinct confirmed-results input."""
    rows, traces, excluded = [], [], []
    for _,_,issue,fixtures in slates(targets):
        for target in fixtures:
            try:
                detail = trace(history,target,issue)
            except ValueError as exc:
                if str(exc) != "warm-up: no past league prior":
                    raise
                excluded.append(dict(target.metadata(),issue_date_london=issue,reason=str(exc)))
                continue
            traces.append(detail)
            rows.append({k:v for k,v in detail.items() if k not in ("home_trace","away_trace","prior","prior_totals")}
                        | {"home_count":detail["home_trace"]["count"],"away_count":detail["away_trace"]["count"]})
    return rows,traces,excluded


def matrix(rows):
    if any(set(r["features"]) != set(FEATURES) for r in rows):
        raise ValueError("Estimator input must contain exactly the six form features")
    values = np.asarray([[r["features"][key] for key in FEATURES] for r in rows],dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 6 or not np.isfinite(values).all():
        raise ValueError("Non-finite or invalid feature matrix")
    return values
