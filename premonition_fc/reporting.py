"""Headless, shareable figures and a factual historical evaluation report."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLORS = {"frequencies":"#64748b","poisson":"#16856a","forest":"#ae5bce"}


def table(values):
    lines = ["| Model | Fixtures | Log loss | Accuracy | Draw recall | Top score hit |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for model in ("frequencies","poisson","forest"):
        v = values[model]
        hit = f"{v['top_one_score_hit_rate']:.2%}" if v['top_one_score_hit_rate'] is not None else "—"
        recall = f"{v['draw_recall']:.2%}" if v['draw_recall'] is not None else "—"
        lines.append(f"| {model} | {v['fixtures']} | {v['log_loss']:.6f} | {v['accuracy']:.2%} | {recall} | {hit} |")
    return "\n".join(lines)


def build_report(output, development, holdout, scored, frozen):
    output = Path(output)
    plt.rcParams.update({"font.family":"DejaVu Sans","figure.dpi":130,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes = plt.subplots(1,2,figsize=(10,4),layout="constrained")
    for ax,values,title in zip(axes,(development["pooled_metrics"],holdout),("Development validation (used for selection)","Frozen 2025/26 holdout")):
        names = list(COLORS)
        ax.bar(names,[values[n]["log_loss"] for n in names],color=[COLORS[n] for n in names])
        ax.set_ylabel("Multiclass log loss (lower is better)")
        ax.set_title(title,fontsize=11)
    fig.savefig(output/"log_loss.png",metadata={"Software":"Premonition-FC"})
    plt.close(fig)
    fig,ax = plt.subplots(figsize=(8,4),layout="constrained")
    for name,color in COLORS.items():
        rows = sorted((r for r in scored if r["model"]==name),key=lambda r:(r["played_date"],r["fixture_id"]))
        loss = np.asarray([r["log_loss"] for r in rows])
        ax.plot(np.arange(1,len(rows)+1),np.cumsum(loss)/np.arange(1,len(rows)+1),color=color,label=name)
    ax.set(xlabel="Chronological holdout fixture",ylabel="Cumulative mean log loss",title="Historical 2025/26 replay")
    ax.legend()
    fig.savefig(output/"cumulative_log_loss.png",metadata={"Software":"Premonition-FC"})
    plt.close(fig)
    fig,axes = plt.subplots(1,3,figsize=(11,3.6),layout="constrained")
    for idx,(label,ax) in enumerate(zip(("Home win","Draw","Away win"),axes)):
        ax.plot([0,1],[0,1],ls="--",color="#bbb")
        for name,color in COLORS.items():
            rows = [r for r in scored if r["model"]==name]
            bins = [[] for _ in range(5)]
            for row in rows:
                bins[min(int(row["probabilities"][idx]*5),4)].append(row)
            nonempty = [b for b in bins if b]
            x = [np.mean([r["probabilities"][idx] for r in b]) for b in nonempty]
            y = [np.mean([r["actual_result"]==("H","D","A")[idx] for r in b]) for b in nonempty]
            ax.plot(x,y,"o-",color=color,label=name)
        ax.set(xlim=(0,1),ylim=(0,1),xlabel="Mean predicted probability",title=label)
    axes[0].set_ylabel("Observed frequency (five equal-width bins)")
    axes[-1].legend(fontsize=8)
    fig.savefig(output/"reliability.png",metadata={"Software":"Premonition-FC"})
    plt.close(fig)
    best = min(holdout,key=lambda k:holdout[k]["log_loss"])
    delta = holdout["forest"]["log_loss"]-holdout["poisson"]["log_loss"]
    conclusion = ("improved" if delta<0 else "did not improve")
    sections = ["# Premonition-FC historical evaluation",
        "This is a retrospective, date-based replay. It is separate from a real pre-kickoff forecast record.",
        f"The Random Forest {conclusion} holdout log loss over Poisson (forest minus Poisson: {delta:+.6f}). The lowest holdout log loss is from **{best}**. This is a descriptive comparison on one season, not a claim of statistical significance.",
        "## Development validation",table(development["pooled_metrics"]),
        "Four expanding season folds validate 2021/22 through 2024/25. Each model has 1,520 validation predictions. These folds select among two declared configurations per fitted model; the selected development summary is consequently a model-selection result, not another untouched test.",
        "## Frozen holdout",table(holdout),
        "All 380 fixtures in 2025/26 were forecast by each model using fits frozen on 1,892 development rows. Holdout predictions were saved before this scoring join. Earlier holdout matches update later form under the common slate cutoff; they never update the fitted estimators or preprocessing.",
        "## Development fold detail"]
    for season,values in development["fold_metrics"].items():
        sections.extend([f"### {season}",table(values)])
    sections.extend(["## Model and scoring definitions",
        f"Selected settings: `{frozen['settings']}`. Forest: 300 trees, maximum depth 8, all six features considered at splits, seed 1729, one worker; no class weighting or post-hoc calibration. Poisson: separate log-link regressions for home and away goals, training-only standardization and L2 regularization.",
        "Only six blended goals-for, goals-against and points-per-match features enter either fitted model. Ordered home/away roles and separate goal fits represent home advantage. Identifiers, scores, dates, history counts and traces are excluded from the estimator matrix.",
        "Outcome probabilities use the full Skellam goal-difference distribution. The score grid has omitted mass at most 1e-12, reconciles against the outcome probabilities within that bound, and certifies that no unseen cell can displace the third-ranked scoreline. Scoreline probabilities remain unconditional.",
        "Log loss uses unrounded probabilities and natural logarithms, with a 1e-15 scoring floor. Result ties choose H, then D, then A. Score ties sort by probability descending, then home goals and away goals ascending. Draw recall uses actual draws as its denominator. Exact-score accuracy applies only to Poisson's first-ranked scoreline.",
        "## Data and limitations",
        "Pinned OpenFootball JSON contains 2,280 completed fixtures from 2020/21 through 2025/26. The initial slate's eight fixtures are excluded while its scores establish the league prior, leaving 2,272 usable rows. No other fixtures are excluded. Both score objects and plain arrays retain genuine 0-0 results.",
        "Historical slates are Tuesday-Monday UK calendar buckets. Each slate shares its first played date as the simulated issue date; every form input and the league prior must precede that date. Histories use only the current and immediately previous seasons. Missing shares of five matches blend toward past league means. Date-only historical availability approximates when results became known; it does not establish an actual issue-time snapshot.",
        "The goal model assumes conditionally independent Poisson goals. The small feature set omits lineups, injuries and other context. Forest probabilities have not been separately calibrated. One held-out season and four development seasons provide limited evidence about future generalization. Live fixture/result freshness and public-use retention permission remain unresolved separately from this historical evaluation.",
        "## Artifacts and reproducibility",
        "The adjoining metrics, unrounded forecasts, scored fixture joins and PNG plots are generated from the frozen experiment. The fitted artifact, freeze manifest, training fingerprints and source hashes are retained separately. Replays reuse frozen settings and fits; they are not new experiments. Same-runtime forecast and metric JSON must be byte-identical. A new configuration requires a new experiment directory and a clearly separate evaluation record."])
    (output/"REPORT.md").write_text("\n\n".join(sections)+"\n",encoding="utf-8")
